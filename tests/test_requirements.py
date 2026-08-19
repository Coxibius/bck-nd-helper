"""
Unit tests for Requirements Layer (models and parser).
"""

import json
from pathlib import Path
import pytest

from bck_nd_hlpr.core.requirements import (
    AcceptanceCriteria,
    BusinessRule,
    RequirementSpecification,
    RequirementsParser,
    UserStory,
)


def test_user_story_model():
    story = UserStory(
        id="HU01",
        title="Registrar cliente",
        role="Agente de campo",
        want="Registrar un nuevo cliente",
        benefit="Contar con información centralizada",
        status="IN_PROGRESS",
    )
    data = story.to_dict()
    assert data["id"] == "HU01"
    assert data["title"] == "Registrar cliente"
    assert data["role"] == "Agente de campo"
    assert data["want"] == "Registrar un nuevo cliente"
    assert data["benefit"] == "Contar con información centralizada"
    assert data["status"] == "IN_PROGRESS"

    restored = UserStory.from_dict(data)
    assert restored.id == "HU01"
    assert restored.title == "Registrar cliente"
    assert restored.role == "Agente de campo"
    assert restored.want == "Registrar un nuevo cliente"
    assert restored.benefit == "Contar con información centralizada"
    assert restored.status == "IN_PROGRESS"


def test_user_story_defaults():
    story = UserStory(
        id="HU02",
        title="Consultar cliente",
        role="Usuario",
        want="Ver perfil",
        benefit="Visualizar datos",
    )
    assert story.status == "TODO"

    story_from_empty = UserStory.from_dict({})
    assert story_from_empty.id == ""
    assert story_from_empty.status == "TODO"


def test_acceptance_criteria_model():
    ac = AcceptanceCriteria(
        id="AC01",
        given="un cliente no registrado",
        when="se envían datos válidos",
        then="se crea el registro en la base de datos",
    )
    data = ac.to_dict()
    assert data == {
        "id": "AC01",
        "given": "un cliente no registrado",
        "when": "se envían datos válidos",
        "then": "se crea el registro en la base de datos",
    }
    restored = AcceptanceCriteria.from_dict(data)
    assert restored.id == "AC01"
    assert restored.given == "un cliente no registrado"
    assert restored.when == "se envían datos válidos"
    assert restored.then == "se crea el registro en la base de datos"


def test_business_rule_model():
    br = BusinessRule(
        id="BR01",
        description="El documento de identidad debe ser único y obligatorio.",
    )
    data = br.to_dict()
    assert data == {
        "id": "BR01",
        "description": "El documento de identidad debe ser único y obligatorio.",
    }
    restored = BusinessRule.from_dict(data)
    assert restored.id == "BR01"
    assert restored.description == "El documento de identidad debe ser único y obligatorio."


def test_requirement_specification_roundtrip():
    spec = RequirementSpecification(
        story=UserStory(
            id="HU01",
            title="Registrar cliente",
            role="Agente de campo",
            want="Registrar un nuevo cliente",
            benefit="Contar con información centralizada",
            status="TODO",
        ),
        business_rules=[
            BusinessRule(id="BR01", description="Documento obligatorio"),
            BusinessRule(id="BR02", description="Email válido"),
        ],
        acceptance_criteria=[
            AcceptanceCriteria(
                id="AC01",
                given="formulario completo",
                when="se hace submit",
                then="retorna HTTP 201",
            )
        ],
        required_data=[{"name": "dni", "type": "string", "required": True}],
        validations=[{"field": "email", "rule": "regex"}],
        exceptions=[{"code": 409, "condition": "DNI ya existente"}],
        open_questions=["¿Se permite registro sin correo electrónico?"],
    )

    data = spec.to_dict()
    assert data["story"]["id"] == "HU01"
    assert len(data["business_rules"]) == 2
    assert len(data["acceptance_criteria"]) == 1
    assert data["required_data"][0]["name"] == "dni"
    assert data["validations"][0]["field"] == "email"
    assert data["exceptions"][0]["code"] == 409
    assert data["open_questions"] == ["¿Se permite registro sin correo electrónico?"]

    restored = RequirementSpecification.from_dict(data)
    assert restored.story.id == "HU01"
    assert restored.story.title == "Registrar cliente"
    assert len(restored.business_rules) == 2
    assert restored.business_rules[0].id == "BR01"
    assert restored.business_rules[1].id == "BR02"
    assert len(restored.acceptance_criteria) == 1
    assert restored.acceptance_criteria[0].id == "AC01"
    assert restored.required_data == [{"name": "dni", "type": "string", "required": True}]
    assert restored.validations == [{"field": "email", "rule": "regex"}]
    assert restored.exceptions == [{"code": 409, "condition": "DNI ya existente"}]
    assert restored.open_questions == ["¿Se permite registro sin correo electrónico?"]


def test_requirements_parser_load_from_directory(tmp_path: Path):
    req_dir = tmp_path / ".bck-nd" / "requirements"
    req_dir.mkdir(parents=True)

    hu01_content = {
        "story": {
            "id": "HU01",
            "title": "Registrar cliente",
            "role": "Agente de campo",
            "want": "Registrar un nuevo cliente",
            "benefit": "Contar con información centralizada",
            "status": "TODO",
        },
        "business_rules": [
            {"id": "BR01", "description": "El documento de identidad debe ser único."},
            {"id": "BR02", "description": "La edad mínima es 18 años."},
        ],
        "acceptance_criteria": [
            {
                "id": "AC01",
                "given": "El agente ingresa datos válidos",
                "when": "Presiona Guardar",
                "then": "El cliente queda registrado en estado activo",
            }
        ],
        "required_data": [
            {"field": "dni", "type": "string"},
            {"field": "nombre", "type": "string"},
        ],
        "validations": [
            {"field": "dni", "rule": "8_digits"},
        ],
        "exceptions": [
            {"code": "ERR_DUPLICATE", "description": "DNI duplicado"},
        ],
        "open_questions": [
            "¿Se requiere validación biométrica?",
        ],
    }

    hu02_content = {
        "id": "HU02",
        "title": "Actualizar cliente",
        "role": "Supervisor",
        "want": "Modificar los datos de un cliente",
        "benefit": "Mantener información actualizada",
        "status": "IN_PROGRESS",
        "business_rules": [
            {"id": "BR03", "description": "Solo supervisores pueden editar el DNI."},
        ],
        "acceptance_criteria": [
            {
                "id": "AC02",
                "given": "Un cliente existente",
                "when": "Se actualiza el teléfono",
                "then": "Se guardan los cambios y se registra auditoría",
            }
        ],
    }

    (req_dir / "HU01.json").write_text(json.dumps(hu01_content, indent=2), encoding="utf-8")
    (req_dir / "HU02.json").write_text(json.dumps(hu02_content, indent=2), encoding="utf-8")

    specs = RequirementsParser.load_from_directory(tmp_path)
    assert len(specs) == 2

    # Ordered alphabetically by file name
    spec1, spec2 = specs[0], specs[1]
    assert spec1.story.id == "HU01"
    assert spec1.story.title == "Registrar cliente"
    assert len(spec1.business_rules) == 2
    assert spec1.business_rules[0].id == "BR01"
    assert len(spec1.acceptance_criteria) == 1
    assert spec1.acceptance_criteria[0].id == "AC01"
    assert len(spec1.required_data) == 2
    assert spec1.open_questions == ["¿Se requiere validación biométrica?"]

    assert spec2.story.id == "HU02"
    assert spec2.story.title == "Actualizar cliente"
    assert spec2.story.status == "IN_PROGRESS"
    assert len(spec2.business_rules) == 1
    assert spec2.business_rules[0].id == "BR03"


def test_requirements_parser_missing_directory(tmp_path: Path):
    # No .bck-nd directory exists
    specs = RequirementsParser.load_from_directory(tmp_path)
    assert specs == []


def test_requirements_parser_nonexistent_path():
    specs = RequirementsParser.load_from_directory("C:/non/existent/path/for/sure/12345")
    assert specs == []


def test_requirements_parser_malformed_json(tmp_path: Path):
    req_dir = tmp_path / ".bck-nd" / "requirements"
    req_dir.mkdir(parents=True)

    (req_dir / "broken.json").write_text("{ this is not valid JSON }", encoding="utf-8")
    (req_dir / "array.json").write_text("[\"not\", \"a\", \"dict\"]", encoding="utf-8")

    specs = RequirementsParser.load_from_directory(tmp_path)
    assert specs == []


def test_requirements_parser_direct_requirements_folder(tmp_path: Path):
    req_dir = tmp_path / "requirements"
    req_dir.mkdir()

    hu_data = {
        "story": {
            "id": "HU10",
            "title": "Reportes",
            "role": "Admin",
            "want": "Ver reportes",
            "benefit": "Tomar decisiones",
            "status": "DONE",
        }
    }
    (req_dir / "HU10.json").write_text(json.dumps(hu_data), encoding="utf-8")

    specs = RequirementsParser.load_from_directory(req_dir)
    assert len(specs) == 1
    assert specs[0].story.id == "HU10"
    assert specs[0].story.status == "DONE"


def test_requirements_parser_parse_file_invalid():
    assert RequirementsParser.parse_file("non_existent_file.json") is None


def test_context_dumper_with_requirements(tmp_path: Path):
    from bck_nd_hlpr.core.context_dumper import ContextDumper

    # Setup dummy project files
    (tmp_path / "main.py").write_text("print('hello')", encoding="utf-8")

    req_dir = tmp_path / ".bck-nd" / "requirements"
    req_dir.mkdir(parents=True)

    hu01_content = {
        "story": {
            "id": "HU01",
            "title": "Registrar cliente",
            "role": "Agente de campo",
            "want": "Registrar un nuevo cliente",
            "benefit": "Contar con información centralizada",
            "status": "TODO",
        },
        "business_rules": [
            {"id": "BR01", "description": "El documento de identidad debe ser único."},
        ],
        "acceptance_criteria": [
            {
                "id": "AC01",
                "given": "datos válidos",
                "when": "presiona guardar",
                "then": "cliente guardado",
            }
        ],
    }
    (req_dir / "HU01.json").write_text(json.dumps(hu01_content), encoding="utf-8")

    dumper = ContextDumper(path=str(tmp_path))
    content = dumper.build()

    assert "<project_tree>" in content
    assert "<requirements_context>" in content
    assert "<!-- User Stories & Acceptance Criteria -->" in content
    assert "HU01 [TODO] - Registrar cliente" in content
    assert "As a: Agente de campo" in content
    assert "I want: Registrar un nuevo cliente" in content
    assert "So that: Contar con información centralizada" in content
    assert "- BR01: El documento de identidad debe ser único." in content
    assert "- AC01: Given datos válidos When presiona guardar Then cliente guardado" in content
    assert "</requirements_context>" in content
    assert "<core_files>" in content


def test_context_dumper_without_requirements(tmp_path: Path):
    from bck_nd_hlpr.core.context_dumper import ContextDumper

    (tmp_path / "main.py").write_text("print('hello')", encoding="utf-8")

    dumper = ContextDumper(path=str(tmp_path))
    content = dumper.build()

    assert "<project_tree>" in content
    assert "<requirements_context>" not in content
    assert "<core_files>" in content


def test_context_dumper_build_focused_with_requirements(tmp_path: Path):
    from bck_nd_hlpr.core.context_dumper import ContextDumper

    req_dir = tmp_path / ".bck-nd" / "requirements"
    req_dir.mkdir(parents=True)

    hu01 = {
        "story": {
            "id": "HU01",
            "title": "Registrar cliente",
            "role": "Agente",
            "want": "Registrar cliente",
            "benefit": "Centralizar",
            "status": "TODO",
        }
    }
    (req_dir / "HU01.json").write_text(json.dumps(hu01), encoding="utf-8")

    dumper = ContextDumper(path=str(tmp_path))
    content = dumper.build_focused(include_requirements=True)

    assert "<requirements_context>" in content
    assert "HU01 [TODO] - Registrar cliente" in content
    assert "</requirements_context>" in content


def test_cli_req_list_with_stories(tmp_path: Path):
    from typer.testing import CliRunner
    from bck_nd_hlpr.cli.cli import app

    runner = CliRunner()
    req_dir = tmp_path / ".bck-nd" / "requirements"
    req_dir.mkdir(parents=True)

    hu01_content = {
        "story": {
            "id": "HU01",
            "title": "Registrar cliente",
            "role": "Agente de campo",
            "want": "Registrar un nuevo cliente",
            "benefit": "Contar con información centralizada",
            "status": "TODO",
        },
        "business_rules": [
            {"id": "BR01", "description": "El documento de identidad debe ser único."},
        ],
        "acceptance_criteria": [
            {
                "id": "AC01",
                "given": "datos válidos",
                "when": "submit",
                "then": "creado",
            }
        ],
    }
    (req_dir / "HU01.json").write_text(json.dumps(hu01_content), encoding="utf-8")

    result = runner.invoke(app, ["req", "list", str(tmp_path)])
    assert result.exit_code == 0
    assert "HU01" in result.stdout
    assert "Registrar cliente" in result.stdout
    assert "Agente de campo" in result.stdout


def test_cli_req_list_empty(tmp_path: Path):
    from typer.testing import CliRunner
    from bck_nd_hlpr.cli.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["req", "list", str(tmp_path)])
    assert result.exit_code == 0
    assert "No requirements found" in result.stdout


def test_cli_req_discover_story(tmp_path: Path):
    from typer.testing import CliRunner
    from bck_nd_hlpr.cli.cli import app

    runner = CliRunner()
    req_dir = tmp_path / ".bck-nd" / "requirements"
    req_dir.mkdir(parents=True)

    hu01_content = {
        "story": {
            "id": "HU01",
            "title": "Registrar cliente",
            "role": "Agente de campo",
            "want": "Registrar un nuevo cliente",
            "benefit": "Contar con información centralizada",
            "status": "TODO",
        },
        "business_rules": [
            {"id": "BR01", "description": "El documento debe ser único."},
        ],
        "acceptance_criteria": [
            {
                "id": "AC01",
                "given": "datos válidos",
                "when": "submit",
                "then": "registrado",
            }
        ],
        "required_data": [{"field": "dni", "type": "string"}],
        "validations": [{"field": "dni", "rule": "8_digits"}],
        "exceptions": [{"code": "ERR_DUPLICATE", "description": "DNI repetido"}],
        "open_questions": ["¿Validación biométrica?"],
    }
    (req_dir / "HU01.json").write_text(json.dumps(hu01_content), encoding="utf-8")

    result = runner.invoke(app, ["req", "discover", "HU01", str(tmp_path)])
    assert result.exit_code == 0
    assert "DISCOVERY & STAKEHOLDER INTERVIEW GUIDE" in result.stdout
    assert "HU01" in result.stdout
    assert "1. Mandatory Data & Field Specifications" in result.stdout
    assert "2. Business Rules & Domain Validations" in result.stdout
    assert "3. Exception Handling & Edge Cases" in result.stdout
    assert "4. Acceptance Criteria Verification Scenarios" in result.stdout
    assert "5. Open Stakeholder Questions" in result.stdout
    assert "BR01" in result.stdout
    assert "AC01" in result.stdout


def test_cli_req_discover_list_mode(tmp_path: Path):
    from typer.testing import CliRunner
    from bck_nd_hlpr.cli.cli import app

    runner = CliRunner()
    req_dir = tmp_path / ".bck-nd" / "requirements"
    req_dir.mkdir(parents=True)

    hu01 = {"story": {"id": "HU01", "title": "Registrar cliente", "role": "Agente", "want": "x", "benefit": "y"}}
    (req_dir / "HU01.json").write_text(json.dumps(hu01), encoding="utf-8")

    result = runner.invoke(app, ["req", "discover", str(tmp_path)])
    assert result.exit_code == 0
    assert "Available User Stories for Discovery" in result.stdout
    assert "HU01" in result.stdout


def test_cli_req_discover_not_found(tmp_path: Path):
    from typer.testing import CliRunner
    from bck_nd_hlpr.cli.cli import app

    runner = CliRunner()
    req_dir = tmp_path / ".bck-nd" / "requirements"
    req_dir.mkdir(parents=True)

    hu01 = {"story": {"id": "HU01", "title": "Registrar cliente", "role": "Agente", "want": "x", "benefit": "y"}}
    (req_dir / "HU01.json").write_text(json.dumps(hu01), encoding="utf-8")

    result = runner.invoke(app, ["req", "discover", "HU99", str(tmp_path)])
    assert result.exit_code == 1
    assert "Story ID 'HU99' not found" in result.stdout


def test_parse_markdown_story_full():
    md_content = """# HU01 [IN_PROGRESS] - Registrar cliente

- **Role**: Agente de campo
- **Want**: Registrar un nuevo cliente en el sistema
- **Benefit**: Centralizar la información del cliente
- **Status**: IN_PROGRESS

## Business Rules
- BR01: El documento de identidad debe ser único y obligatorio.
- BR02: La edad mínima del cliente debe ser 18 años.

## Acceptance Criteria
- AC01: Given datos válidos When presiona Guardar Then el cliente queda registrado en estado activo
- AC02: Given un documento duplicado When se intenta registrar Then retorna error de validación 409

## Required Data
- `dni`: string (8 dígitos)
- `nombre`: string

## Validations
- `dni`: 8_digits_numeric
- `email`: valid_email_format

## Exceptions
- `ERR_DUPLICATE`: Documento ya registrado
- `ERR_AGE`: Cliente menor de edad

## Open Questions
- ¿Se permite registro con pasaporte extranjero?
"""
    spec = RequirementsParser.parse_markdown(md_content, default_id="HU01")
    assert spec is not None
    assert spec.story.id == "HU01"
    assert spec.story.title == "Registrar cliente"
    assert spec.story.role == "Agente de campo"
    assert spec.story.want == "Registrar un nuevo cliente en el sistema"
    assert spec.story.benefit == "Centralizar la información del cliente"
    assert spec.story.status == "IN_PROGRESS"

    assert len(spec.business_rules) == 2
    assert spec.business_rules[0].id == "BR01"
    assert "único y obligatorio" in spec.business_rules[0].description
    assert spec.business_rules[1].id == "BR02"

    assert len(spec.acceptance_criteria) == 2
    assert spec.acceptance_criteria[0].id == "AC01"
    assert spec.acceptance_criteria[0].given == "datos válidos"
    assert spec.acceptance_criteria[0].when == "presiona Guardar"
    assert spec.acceptance_criteria[0].then == "el cliente queda registrado en estado activo"

    assert spec.acceptance_criteria[1].id == "AC02"
    assert spec.acceptance_criteria[1].given == "un documento duplicado"
    assert spec.acceptance_criteria[1].when == "se intenta registrar"
    assert "409" in spec.acceptance_criteria[1].then

    assert len(spec.required_data) == 2
    assert len(spec.validations) == 2
    assert len(spec.exceptions) == 2
    assert spec.open_questions == ["¿Se permite registro con pasaporte extranjero?"]


def test_parse_markdown_story_minimal():
    md_content = """# HU05 - Autenticación

- **As a**: Usuario registrado
- **I want**: Iniciar sesión con email y contraseña
- **So that**: Acceder a mi panel de control
"""
    spec = RequirementsParser.parse_markdown(md_content, default_id="HU05")
    assert spec is not None
    assert spec.story.id == "HU05"
    assert spec.story.title == "Autenticación"
    assert spec.story.role == "Usuario registrado"
    assert spec.story.want == "Iniciar sesión con email y contraseña"
    assert spec.story.benefit == "Acceder a mi panel de control"
    assert spec.story.status == "TODO"


def test_requirements_parser_load_from_directory_mixed(tmp_path: Path):
    req_dir = tmp_path / ".bck-nd" / "requirements"
    req_dir.mkdir(parents=True)

    # JSON story
    hu01_json = {
        "story": {
            "id": "HU01",
            "title": "Registrar cliente",
            "role": "Agente",
            "want": "Registrar",
            "benefit": "Centralizar",
            "status": "TODO",
        }
    }
    (req_dir / "HU01.json").write_text(json.dumps(hu01_json), encoding="utf-8")

    # Markdown story
    hu02_md = """# HU02 - Consultar cliente

- **Role**: Supervisor
- **Want**: Ver datos del cliente
- **Benefit**: Supervisar operaciones

## Business Rules
- BR01: Solo clientes activos son visibles
"""
    (req_dir / "HU02.md").write_text(hu02_md, encoding="utf-8")

    specs = RequirementsParser.load_from_directory(tmp_path)
    assert len(specs) == 2
    assert specs[0].story.id == "HU01"
    assert specs[1].story.id == "HU02"
    assert specs[1].story.role == "Supervisor"
    assert len(specs[1].business_rules) == 1



