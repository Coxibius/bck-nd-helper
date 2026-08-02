"""
Tests for Laravel Eloquent relationship parsing, namespace sanitization,
fallback casing matching, Unknown node elimination, and Factory UML heuristics.
"""
import pytest
from bck_nd_hlpr.core.php_parser import (
    sanitize_php_class_name,
    parse_project_for_php_er,
    parse_project_for_php_uml,
)
from bck_nd_hlpr.core.er_parser import (
    resolve_relationship_target,
    generate_mermaid_er,
    EREntity,
)
from bck_nd_hlpr.core.uml_parser import (
    UMLClassInfo,
    generate_mermaid_class_diagram,
)


def _create_mock_project(tmp_path, structure: dict):
    for name, content in structure.items():
        file_path = tmp_path / name
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")


def test_sanitize_php_class_name():
    assert sanitize_php_class_name("\\App\\Models\\Solicitud") == "Solicitud"
    assert sanitize_php_class_name("App\\Models\\Solicitud::class") == "Solicitud"
    assert sanitize_php_class_name("Solicitud::class") == "Solicitud"
    assert sanitize_php_class_name("'App\\Models\\Solicitud'") == "Solicitud"
    assert sanitize_php_class_name("\"\\App\\Models\\User\"") == "User"
    assert sanitize_php_class_name("User") == "User"
    assert sanitize_php_class_name("") == "Unknown"
    assert sanitize_php_class_name(None) == "Unknown"


def test_resolve_relationship_target_matching():
    entity_names = {"User", "Solicitud", "Justificativo"}

    # Direct match with namespace
    res1 = resolve_relationship_target("\\App\\Models\\Solicitud::class", "solicitud", entity_names)
    assert res1 == "Solicitud"

    # Fallback to method label singularization matching
    res2 = resolve_relationship_target("Unknown", "solicitudes", entity_names)
    assert res2 == "Solicitud"

    res3 = resolve_relationship_target("Unknown", "justificativo", entity_names)
    assert res3 == "Justificativo"

    # Custom method name (e.g. revisor) returning known model User
    res4 = resolve_relationship_target("User", "revisor", entity_names)
    assert res4 == "User"

    # Completely unknown target and method label
    res5 = resolve_relationship_target("Unknown", "customUnknownMethod", entity_names)
    assert res5 is None


def test_php_eloquent_er_parsing(tmp_path):
    _create_mock_project(tmp_path, {
        "app/Models/User.php": """<?php
namespace App\\Models;
use Illuminate\\Database\\Eloquent\\Model;

class User extends Model {
    protected $fillable = ['name', 'email'];

    public function solicitudes() {
        return $this->hasMany(\\App\\Models\\Solicitud::class);
    }
}
""",
        "app/Models/Solicitud.php": """<?php
namespace App\\Models;
use Illuminate\\Database\\Eloquent\\Model;

class Solicitud extends Model {
    protected $fillable = ['titulo', 'user_id'];

    public function revisor() {
        return $this->belongsTo(\\App\\Models\\User::class, 'revisor_id');
    }

    public function justificativo() {
        return $this->hasMany(Justificativo::class);
    }
}
""",
        "app/Models/Justificativo.php": """<?php
namespace App\\Models;
use Illuminate\\Database\\Eloquent\\Model;

class Justificativo extends Model {
    protected $fillable = ['motivo'];

    public function solicitud() {
        return $this->belongsTo(Solicitud::class);
    }
}
"""
    })

    entities = parse_project_for_php_er(str(tmp_path))
    names = {e.name for e in entities}
    assert "User" in names
    assert "Solicitud" in names
    assert "Justificativo" in names

    diagram = generate_mermaid_er(entities)
    assert "erDiagram" in diagram
    assert "Unknown" not in diagram

    # Solicitud -- User (revisor) relationship resolved to User
    assert "Solicitud }o--|| User : \"revisor\"" in diagram
    # Solicitud -- Justificativo relationship
    assert "Solicitud ||--o{ Justificativo : \"justificativo\"" in diagram
    # User -- Solicitud relationship
    assert "User ||--o{ Solicitud : \"solicitudes\"" in diagram


def test_factory_to_model_uml_heuristic():
    classes = [
        UMLClassInfo("User", ["Model"], "App.Models"),
        UMLClassInfo("UserFactory", ["Factory"], "Database.Factories"),
        UMLClassInfo("Solicitud", ["Model"], "App.Models"),
        UMLClassInfo("SolicitudFactory", ["Factory"], "Database.Factories"),
    ]

    diagram = generate_mermaid_class_diagram(classes)
    assert "UserFactory ..> User : \"generates\"" in diagram
    assert "SolicitudFactory ..> Solicitud : \"generates\"" in diagram
