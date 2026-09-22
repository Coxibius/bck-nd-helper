"""Requirements integration with context building and scans."""

import json
from pathlib import Path

from bck_nd_hlpr.core.requirements import RequirementsParser

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



def test_orchestrator_loads_requirements_when_requested(tmp_path: Path):
    from bck_nd_hlpr.core.orchestrator import OrchestratorConfig, ScannerOrchestrator

    req_dir = tmp_path / ".bck-nd" / "requirements"
    req_dir.mkdir(parents=True)
    story = {
        "story": {
            "id": "US-001",
            "title": "User Registration",
            "role": "visitor",
            "want": "create an account",
            "benefit": "access the application",
            "status": "IN_PROGRESS",
        },
        "acceptance_criteria": [
            {"id": "AC01", "given": "valid data", "when": "submitted", "then": "account created"}
        ],
        "business_rules": [
            {"id": "BR01", "description": "Email must be unique"}
        ],
    }
    (req_dir / "US-001.json").write_text(json.dumps(story), encoding="utf-8")

    result = ScannerOrchestrator.run(
        OrchestratorConfig(path=str(tmp_path), requirements=True, use_cache=False)
    )

    assert result.requirements is not None
    assert [spec.story.id for spec in result.requirements] == ["US-001"]


def test_default_scan_includes_requirements_and_skips_empty_projects(
    tmp_path: Path, monkeypatch
):
    from typer.testing import CliRunner
    from bck_nd_hlpr.cli.cli import app
    from bck_nd_hlpr.core.orchestrator import OrchestratorResult, ScannerOrchestrator

    req_dir = tmp_path / ".bck-nd" / "requirements"
    req_dir.mkdir(parents=True)
    story = {
        "story": {
            "id": "US-001",
            "title": "User Registration",
            "role": "visitor",
            "want": "create an account",
            "benefit": "access the application",
            "status": "DONE",
        },
        "acceptance_criteria": [
            {"id": "AC01", "given": "valid data", "when": "submitted", "then": "account created"}
        ],
        "business_rules": [
            {"id": "BR01", "description": "Email must be unique"}
        ],
    }
    (req_dir / "US-001.json").write_text(json.dumps(story), encoding="utf-8")
    specs = RequirementsParser.load_from_directory(tmp_path)

    def fake_run(config):
        return OrchestratorResult(
            path=str(tmp_path),
            framework="Unknown",
            architecture="",
            features=[],
            summary="",
            todos=[],
            requirements=specs if config.requirements else None,
        )

    monkeypatch.setattr(ScannerOrchestrator, "run", staticmethod(fake_run))

    result = CliRunner().invoke(app, ["scan", str(tmp_path)])
    assert result.exit_code == 0, result.exception
    assert "Requirements: 1 story" in result.stdout
    assert "1 DONE" in result.stdout
    assert "1 criterion" in result.stdout
    assert "1 rule" in result.stdout
    assert f"bck-nd req list {tmp_path}" in result.stdout

    empty_path = tmp_path / "without-requirements"
    empty_path.mkdir()

    def fake_empty_run(config):
        return OrchestratorResult(
            path=str(empty_path),
            framework="Unknown",
            architecture="",
            features=[],
            summary="",
            todos=[],
            requirements=[] if config.requirements else None,
        )

    monkeypatch.setattr(ScannerOrchestrator, "run", staticmethod(fake_empty_run))
    empty_result = CliRunner().invoke(app, ["scan", str(empty_path)])
    assert empty_result.exit_code == 0, empty_result.exception
    assert "Requirements: not initialized" in empty_result.stdout
    assert "bck-nd req init US-001" in empty_result.stdout
