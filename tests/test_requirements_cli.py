"""Requirements command-line behavior."""

import json
from pathlib import Path

import pytest

from bck_nd_hlpr.core.requirements import RequirementsParser

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


def test_cli_req_init_markdown_template(tmp_path: Path):
    from typer.testing import CliRunner
    from bck_nd_hlpr.cli.cli import app

    result = CliRunner().invoke(
        app,
        ["req", "init", "us-001", "--path", str(tmp_path)],
    )

    assert result.exit_code == 0, result.exception
    target = tmp_path / ".bck-nd" / "requirements" / "US-001.md"
    assert target.is_file()
    content = target.read_text(encoding="utf-8")
    for section in (
        "**Role**",
        "**Want**",
        "**Benefit**",
        "## Business Rules",
        "## Acceptance Criteria",
        "## Required Data",
        "## Validations",
        "## Exceptions",
        "## Open Questions",
    ):
        assert section in content

    spec = RequirementsParser.parse_file(target)
    assert spec is not None
    assert spec.story.id == "US-001"


def test_cli_req_init_json_and_refuses_overwrite(tmp_path: Path):
    from typer.testing import CliRunner
    from bck_nd_hlpr.cli.cli import app

    runner = CliRunner()
    args = ["req", "init", "HU02", "--format", "json", "--path", str(tmp_path)]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.exception

    target = tmp_path / ".bck-nd" / "requirements" / "HU02.json"
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["story"]["id"] == "HU02"
    assert data["business_rules"]
    assert data["acceptance_criteria"]
    assert data["required_data"]
    assert data["validations"]
    assert data["exceptions"]
    assert data["open_questions"]

    duplicate = runner.invoke(app, args)
    assert duplicate.exit_code == 1
    assert "already exists" in duplicate.stdout


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



@pytest.mark.parametrize("command", ["status", "set-status"])
def test_cli_req_status_and_alias(tmp_path: Path, command: str):
    from typer.testing import CliRunner
    from bck_nd_hlpr.cli.cli import app

    req_dir = tmp_path / ".bck-nd" / "requirements"
    req_dir.mkdir(parents=True)
    target = req_dir / "US-001.json"
    target.write_text(
        json.dumps({"story": {"id": "US-001", "status": "TODO"}}),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        ["req", command, "us-001", "in_progress", "--path", str(tmp_path)],
    )

    assert result.exit_code == 0, result.exception
    assert "Story US-001 status updated" in result.stdout
    assert "TODO" in result.stdout
    assert "IN_PROGRESS" in result.stdout
    assert json.loads(target.read_text(encoding="utf-8"))["story"]["status"] == "IN_PROGRESS"


@pytest.mark.parametrize(
    ("story_id", "new_status", "expected", "exit_code"),
    [
        ("US-001", "INVALID", "Invalid status", 2),
        ("MISSING", "DONE", "not found", 1),
    ],
)
def test_cli_req_status_reports_invalid_or_missing_story(
    tmp_path: Path,
    story_id: str,
    new_status: str,
    expected: str,
    exit_code: int,
):
    from typer.testing import CliRunner
    from bck_nd_hlpr.cli.cli import app

    req_dir = tmp_path / ".bck-nd" / "requirements"
    req_dir.mkdir(parents=True)
    (req_dir / "US-001.json").write_text(
        json.dumps({"story": {"id": "US-001", "status": "TODO"}}),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        ["req", "status", story_id, new_status, "--path", str(tmp_path)],
    )

    assert result.exit_code == exit_code
    assert expected in result.stdout
