"""
Tests básicos para los 6 ORM parser stubs.
Cada test crea un mini-proyecto mock en tmp_path y verifica:
  - detect() retorna True
  - extract() retorna entidades con nombres correctos
  - Relaciones básicas presentes
"""
import pytest
from pathlib import Path
from bck_nd_hlpr.er_parser import (
    SQLAlchemyParser, DjangoORMParser, PrismaParser,
    TypeORMParser, SequelizeParser, EFCoreParser,
    run_orm_parsers, generate_mermaid_er,
)


def _create_project(tmp_path, structure: dict):
    """Crea estructura de archivos recursivamente."""
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


# ── 1. SQLAlchemy ────────────────────────────────────────────────────────────

class TestSQLAlchemyParser:
    def test_detect_and_extract(self, tmp_path):
        _create_project(tmp_path, {
            "models.py": '''
from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    posts = relationship("Post")

class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True)
    title = Column(String)
    user_id = Column(Integer, ForeignKey("users.id"))
'''
        })

        parser = SQLAlchemyParser()
        assert parser.detect(str(tmp_path)) is True

        entities = parser.extract(str(tmp_path))
        names = {e.name for e in entities}
        assert "User" in names
        assert "Post" in names

        # Verificar relaciones
        user = next(e for e in entities if e.name == "User")
        rel_targets = [r[0] for r in user.relationships]
        assert "Post" in rel_targets

        post = next(e for e in entities if e.name == "Post")
        fk_targets = [r[0] for r in post.relationships]
        assert "users" in fk_targets

    def test_detect_false(self, tmp_path):
        _create_project(tmp_path, {
            "models.py": "# No SQLAlchemy here\nclass Foo:\n    pass\n"
        })
        parser = SQLAlchemyParser()
        assert parser.detect(str(tmp_path)) is False


# ── 2. Django ORM ────────────────────────────────────────────────────────────

class TestDjangoORMParser:
    def test_detect_and_extract_with_m2m(self, tmp_path):
        _create_project(tmp_path, {
            "models.py": '''
from django.db import models

class Article(models.Model):
    title = models.CharField(max_length=200)
    body = models.TextField()
    tags = models.ManyToManyField(Tag)

class Tag(models.Model):
    name = models.CharField(max_length=50)
    articles = models.ManyToManyField(Article)
'''
        })

        parser = DjangoORMParser()
        assert parser.detect(str(tmp_path)) is True

        entities = parser.extract(str(tmp_path))
        names = {e.name for e in entities}
        assert "Article" in names
        assert "Tag" in names

        # Verificar ManyToManyField
        article = next(e for e in entities if e.name == "Article")
        m2m_rels = [r for r in article.relationships if r[1] == "}o--o{"]
        assert len(m2m_rels) >= 1
        assert m2m_rels[0][0] == "Tag"

    def test_detect_false(self, tmp_path):
        _create_project(tmp_path, {
            "models.py": "# Plain Python\nclass Foo:\n    pass\n"
        })
        parser = DjangoORMParser()
        assert parser.detect(str(tmp_path)) is False


# ── 3. Prisma ────────────────────────────────────────────────────────────────

class TestPrismaParser:
    def test_detect_and_extract(self, tmp_path):
        _create_project(tmp_path, {
            "prisma/": {
                "schema.prisma": '''
generator client {
  provider = "prisma-client-js"
}

model User {
  id    Int     @id @default(autoincrement())
  email String  @unique
  name  String?
  posts Post[]
}

model Post {
  id       Int    @id @default(autoincrement())
  title    String
  author   User   @relation(fields: [authorId], references: [id])
  authorId Int
}
'''
            }
        })

        parser = PrismaParser()
        assert parser.detect(str(tmp_path)) is True

        entities = parser.extract(str(tmp_path))
        names = {e.name for e in entities}
        assert "User" in names
        assert "Post" in names

        # User should have relationship to Post (Post[])
        user = next(e for e in entities if e.name == "User")
        rel_targets = [r[0] for r in user.relationships]
        assert "Post" in rel_targets

    def test_detect_false(self, tmp_path):
        _create_project(tmp_path, {
            "src/": {"index.ts": "console.log('hello');"}
        })
        parser = PrismaParser()
        assert parser.detect(str(tmp_path)) is False


# ── 4. TypeORM ───────────────────────────────────────────────────────────────

class TestTypeORMParser:
    def test_detect_and_extract(self, tmp_path):
        _create_project(tmp_path, {
            "src/": {
                "user.entity.ts": '''
import { Entity, PrimaryGeneratedColumn, Column, OneToMany } from "typeorm";
import { Post } from "./post.entity";

@Entity()
export class User {
    @PrimaryGeneratedColumn()
    id: number;

    @Column()
    name: string;

    @OneToMany(() => Post, post => post.author)
    posts: Post[];
}
''',
                "post.entity.ts": '''
import { Entity, PrimaryGeneratedColumn, Column, ManyToOne } from "typeorm";
import { User } from "./user.entity";

@Entity()
export class Post {
    @PrimaryGeneratedColumn()
    id: number;

    @Column()
    title: string;

    @ManyToOne(() => User, user => user.posts)
    author: User;
}
'''
            }
        })

        parser = TypeORMParser()
        assert parser.detect(str(tmp_path)) is True

        entities = parser.extract(str(tmp_path))
        names = {e.name for e in entities}
        assert "User" in names
        assert "Post" in names

        # Verify User -> Post relationship (OneToMany)
        user = next(e for e in entities if e.name == "User")
        one_to_many = [r for r in user.relationships if r[1] == "||--o{"]
        assert len(one_to_many) >= 1
        assert one_to_many[0][0] == "Post"

        # Verify Post -> User relationship (ManyToOne) with target captured
        post = next(e for e in entities if e.name == "Post")
        many_to_one = [r for r in post.relationships if r[1] == "}o--||"]
        assert len(many_to_one) >= 1
        assert many_to_one[0][0] == "User"

    def test_typeorm_captures_target(self, tmp_path):
        """Verifica que el regex captura el target del arrow function."""
        _create_project(tmp_path, {
            "src/": {
                "comment.entity.ts": '''
import { Entity, ManyToOne, Column, PrimaryGeneratedColumn } from "typeorm";

@Entity()
export class Comment {
    @PrimaryGeneratedColumn()
    id: number;

    @Column()
    body: string;

    @ManyToOne(() => Post, post => post.comments)
    post: Post;

    @ManyToOne(() => User, user => user.comments)
    author: User;
}
'''
            }
        })
        parser = TypeORMParser()
        entities = parser.extract(str(tmp_path))
        comment = next(e for e in entities if e.name == "Comment")

        targets = {r[0] for r in comment.relationships}
        assert "Post" in targets, "Should capture Post from @ManyToOne(() => Post, ...)"
        assert "User" in targets, "Should capture User from @ManyToOne(() => User, ...)"

    def test_detect_false(self, tmp_path):
        _create_project(tmp_path, {
            "src/": {"user.entity.ts": "// No decorators\nexport class User {}\n"}
        })
        parser = TypeORMParser()
        assert parser.detect(str(tmp_path)) is False


# ── 5. Sequelize ─────────────────────────────────────────────────────────────

class TestSequelizeParser:
    def test_detect_and_extract(self, tmp_path):
        _create_project(tmp_path, {
            "src/": {
                "user.model.js": '''
const { Model, DataTypes } = require('sequelize');

class User extends Model {}

User.init({
    name: DataTypes.STRING,
    email: DataTypes.STRING,
}, { sequelize, modelName: 'User' });

User.hasMany(Post);

module.exports = User;
''',
                "post.model.js": '''
const { Model, DataTypes } = require('sequelize');

class Post extends Model {}

Post.init({
    title: DataTypes.STRING,
    content: DataTypes.TEXT,
}, { sequelize, modelName: 'Post' });

Post.belongsTo(User);

module.exports = Post;
'''
            }
        })

        parser = SequelizeParser()
        assert parser.detect(str(tmp_path)) is True

        entities = parser.extract(str(tmp_path))
        names = {e.name for e in entities}
        assert "User" in names
        assert "Post" in names

        # Verify User.hasMany(Post)
        user = next(e for e in entities if e.name == "User")
        has_many = [r for r in user.relationships if r[1] == "||--o{"]
        assert len(has_many) >= 1
        assert has_many[0][0] == "Post"

        # Verify Post.belongsTo(User)
        post = next(e for e in entities if e.name == "Post")
        belongs_to = [r for r in post.relationships if r[1] == "}o--||"]
        assert len(belongs_to) >= 1
        assert belongs_to[0][0] == "User"

    def test_detect_false(self, tmp_path):
        _create_project(tmp_path, {
            "src/": {"user.model.js": "// No Sequelize\nclass User {}\n"}
        })
        parser = SequelizeParser()
        assert parser.detect(str(tmp_path)) is False


# ── 6. Entity Framework Core ─────────────────────────────────────────────────

class TestEFCoreParser:
    def test_detect_and_extract(self, tmp_path):
        _create_project(tmp_path, {
            "Data/": {
                "AppDbContext.cs": '''
using Microsoft.EntityFrameworkCore;

public class AppDbContext : DbContext
{
    public DbSet<User> Users { get; set; }
    public DbSet<Post> Posts { get; set; }
}
'''
            },
            "Models/": {
                "UserModel.cs": '''
public class User
{
    public int Id { get; set; }
    public string Name { get; set; }
    public ICollection<Post> Posts { get; set; }
}
''',
                "PostModel.cs": '''
public class Post
{
    public int Id { get; set; }
    public string Title { get; set; }
    public User Author { get; set; }
}
'''
            }
        })

        parser = EFCoreParser()
        assert parser.detect(str(tmp_path)) is True

        entities = parser.extract(str(tmp_path))
        names = {e.name for e in entities}
        assert "User" in names
        assert "Post" in names

        # Verify User has ICollection<Post> -> relationship
        user = next(e for e in entities if e.name == "User")
        collection_rels = [r for r in user.relationships if r[1] == "||--o{"]
        assert len(collection_rels) >= 1
        assert collection_rels[0][0] == "Post"

        # Verify Post has User Author -> navigation property
        post = next(e for e in entities if e.name == "Post")
        nav_rels = [r for r in post.relationships if r[1] == "}o--||"]
        assert len(nav_rels) >= 1
        assert nav_rels[0][0] == "User"

    def test_detect_false(self, tmp_path):
        _create_project(tmp_path, {
            "Models/": {"UserModel.cs": "// No DbContext\npublic class User {}\n"}
        })
        parser = EFCoreParser()
        assert parser.detect(str(tmp_path)) is False


# ── 7. Integración: run_orm_parsers ──────────────────────────────────────────

class TestRunORMParsers:
    def test_multi_orm_merge(self, tmp_path):
        """Verifica que run_orm_parsers detecta y combina múltiples ORMs."""
        _create_project(tmp_path, {
            "models.py": '''
from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True)
    name = Column(String)
''',
            "prisma/": {
                "schema.prisma": '''
model Product {
  id    Int    @id
  name  String
  price Float
}
'''
            }
        })

        entities = run_orm_parsers(str(tmp_path))
        names = {e.name for e in entities}
        assert "Customer" in names, "SQLAlchemy entity should be detected"
        assert "Product" in names, "Prisma entity should be detected"

    def test_mermaid_generation(self, tmp_path):
        """Verifica que las entidades de los stubs generan Mermaid válido."""
        _create_project(tmp_path, {
            "prisma/": {
                "schema.prisma": '''
model User {
  id    Int     @id
  email String
  posts Post[]
}

model Post {
  id     Int  @id
  title  String
  author User @relation(fields: [authorId], references: [id])
}
'''
            }
        })

        entities = run_orm_parsers(str(tmp_path))
        mermaid = generate_mermaid_er(entities)
        assert "erDiagram" in mermaid
        assert "User" in mermaid
        assert "Post" in mermaid
