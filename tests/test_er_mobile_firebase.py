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

def test_er_firestore_inference(tmp_path):
    _create_project(tmp_path, {
        "firebaseConfig.ts": "export const db = {};",
        "src/": {
            "users_service.ts": """
import { collection, doc, getDocs } from "firebase/firestore";
// Some comment
const usersCol = collection(db, "users");
const postsCol = collection(doc(collection(db, "users"), "userId"), "posts");
""",
            "comments_service.ts": """
import { collection, doc } from "firebase/firestore";
// Chained method collection doc collection
const commCol = collection(db, "posts").doc("postId").collection("comments");
""",
            "direct_arg_service.ts": """
import { collection } from 'firebase/firestore';
const subCol = collection(db, 'users', 'userId', 'history');
""",
            "generic_file.ts": """
// No firestore import, so collection() here should NOT be parsed
const collection = (a, b) => b;
const myCol = collection("dummy", "should_ignore");
"""
        }
    })

    entities = parse_project_for_er(str(tmp_path))
    entity_names = {ent.name for ent in entities}

    # Verify detected collections
    assert "Users" in entity_names
    assert "Posts" in entity_names
    assert "Comments" in entity_names
    assert "History" in entity_names
    assert "Should_ignore" not in entity_names

    # Check relationships
    # Users should have a relationship with Posts
    users_entity = next(ent for ent in entities if ent.name == "Users")
    posts_rel = next(r for r in users_entity.relationships if r[0] == "Posts")
    assert posts_rel[1] == "||--o{"
    assert posts_rel[3] == "inferred from controller/collection"

    # Posts should have relationship with Comments
    posts_entity = next(ent for ent in entities if ent.name == "Posts")
    comments_rel = next(r for r in posts_entity.relationships if r[0] == "Comments")
    assert comments_rel[1] == "||--o{"
    assert comments_rel[3] == "inferred from controller/collection"

    # Check Mermaid representation
    mermaid = generate_mermaid_er(entities)
    assert 'Users ||--o{ Posts : "posts" %% -- inferred from controller/collection' in mermaid
    assert 'Posts ||--o{ Comments : "comments" %% -- inferred from controller/collection' in mermaid
