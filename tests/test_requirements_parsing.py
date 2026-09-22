"""Requirements parsing, verified reading, and collection loading."""

import json
import stat
from pathlib import Path

import bck_nd_hlpr.core.requirements.parser as requirements_parser_module
from bck_nd_hlpr.core.requirements import RequirementsParser

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



def test_requirement_verified_reader_accepts_normal_json_and_markdown(tmp_path):
    req_dir = tmp_path / ".bck-nd" / "requirements"
    req_dir.mkdir(parents=True)
    (req_dir / "US-JSON.json").write_text(
        json.dumps({"story": {"id": "US-JSON", "status": "TODO"}}),
        encoding="utf-8",
    )
    (req_dir / "US-MD.md").write_text(
        "# US-MD [DONE] - Safe story\n",
        encoding="utf-8",
    )

    specs = RequirementsParser.load_from_directory(tmp_path)

    assert [spec.story.id for spec in specs] == ["US-JSON", "US-MD"]


def test_requirement_link_or_reparse_source_is_not_loaded(tmp_path, monkeypatch):
    req_dir = tmp_path / ".bck-nd" / "requirements"
    req_dir.mkdir(parents=True)
    safe = req_dir / "US-SAFE.md"
    unsafe = req_dir / "US-UNSAFE.md"
    safe.write_text("# US-SAFE [TODO] - Safe\n", encoding="utf-8")
    unsafe.write_text(
        "# US-UNSAFE [DONE] - EXTERNAL-REQUIREMENT-SECRET\n",
        encoding="utf-8",
    )
    unsafe_size = unsafe.stat().st_size
    original = RequirementsParser._is_link_or_reparse

    monkeypatch.setattr(
        RequirementsParser,
        "_is_link_or_reparse",
        staticmethod(
            lambda path_stat: (
                path_stat.st_size == unsafe_size
                and stat.S_ISREG(path_stat.st_mode)
            )
            or original(path_stat)
        ),
    )

    result = RequirementsParser.load_collection(tmp_path)

    assert result.rejected is True
    assert result.specifications == ()
    assert [item.code for item in result.diagnostics] == [
        "REQUIREMENT_SOURCE_UNSAFE"
    ]
    assert RequirementsParser.load_from_directory(tmp_path) == []
    assert "EXTERNAL-REQUIREMENT-SECRET" not in repr(result)


def test_requirement_replacement_during_read_returns_no_content(
    tmp_path,
    monkeypatch,
):
    req_dir = tmp_path / ".bck-nd" / "requirements"
    req_dir.mkdir(parents=True)
    target = req_dir / "US-RACE.md"
    target.write_text("# US-RACE [TODO] - Original\n", encoding="utf-8")
    secret = b"# US-RACE [DONE] - CONCURRENT-SECRET-CONTENT\n"
    real_read = requirements_parser_module.os.read
    raced = False

    def replace_after_read(descriptor, amount):
        nonlocal raced
        chunk = real_read(descriptor, amount)
        if not raced:
            raced = True
            target.write_bytes(secret)
        return chunk

    monkeypatch.setattr(requirements_parser_module.os, "read", replace_after_read)

    assert RequirementsParser.parse_file(target) is None
    assert raced is True
    assert target.read_bytes() == secret


def test_requirement_growth_above_limit_is_rejected(tmp_path, monkeypatch):
    req_dir = tmp_path / ".bck-nd" / "requirements"
    req_dir.mkdir(parents=True)
    target = req_dir / "US-GROW.md"
    target.write_text("# US-GROW [TODO] - Original\n", encoding="utf-8")

    monkeypatch.setattr(
        requirements_parser_module.os,
        "read",
        lambda _descriptor, _amount: b"x"
        * (requirements_parser_module.MAX_REQUIREMENT_SOURCE_BYTES + 1),
    )

    assert RequirementsParser.parse_file(target) is None
