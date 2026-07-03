import pytest
from pathlib import Path
from bck_nd_hlpr.er_parser import parse_project_for_er, generate_mermaid_er

def _create_project(tmp_path, structure: dict):
    for name, content in structure.items():
        if name.endswith("/"):
            dir_path = tmp_path / name.rstrip("/")
            dir_path.mkdir(parents=True, exist_ok=True)
            if isinstance(content, dict):
                _create_project(dir_path, content)
        else:
            file_path = tmp_path / name
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")

def test_er_mongoose_parsing(tmp_path):
    _create_project(tmp_path, {
        "package.json": '{"dependencies": {"mongoose": "^6.0.0"}}',
        "src/": {
            "user.model.js": """
const mongoose = require('mongoose');
const Schema = mongoose.Schema;

const UserSchema = new Schema({
  name: String,
  email: { type: String, required: true },
  posts: [{ type: Schema.Types.ObjectId, ref: 'Post' }]
});

module.exports = mongoose.model('User', UserSchema);
""",
            "post.schema.ts": """
import mongoose, { Schema } from 'mongoose';

const PostSchema = new Schema({
  title: { type: String, required: true },
  author: { type: Schema.Types.ObjectId, ref: 'User' }
});

export default mongoose.model('Post', PostSchema);
"""
        }
    })

    entities = parse_project_for_er(str(tmp_path))
    entity_names = {ent.name for ent in entities}

    # Verify detected collections
    assert "User" in entity_names
    assert "Post" in entity_names

    # Check User entity columns and relationships
    user_entity = next(ent for ent in entities if ent.name == "User")
    cols = {c[0]: c[1] for c in user_entity.columns}
    assert cols["name"] == "String"
    assert cols["email"] == "String"
    
    posts_rel = next(r for r in user_entity.relationships if r[0] == "Post")
    assert posts_rel[1] == "||--o{" # Array of refs -> One-to-Many
    assert posts_rel[3] == "inferred from controller/collection"

    # Check Post entity columns and relationships
    post_entity = next(ent for ent in entities if ent.name == "Post")
    post_cols = {c[0]: c[1] for c in post_entity.columns}
    assert post_cols["title"] == "String"
    
    author_rel = next(r for r in post_entity.relationships if r[0] == "User")
    assert author_rel[1] == "}o--||" # Single ref -> Many-to-One
    assert author_rel[3] == "inferred from controller/collection"

    # Check Mermaid representation
    mermaid = generate_mermaid_er(entities)
    assert 'User ||--o{ Post : "posts" %% -- inferred from controller/collection' in mermaid
    assert 'Post }o--|| User : "author" %% -- inferred from controller/collection' in mermaid
