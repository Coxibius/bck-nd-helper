"""Focused public regressions for the Requirements UX hotfix."""

import json
import os
import shlex
from pathlib import Path

from typer.testing import CliRunner

import bck_nd_hlpr.cli.cli as cli_module
from bck_nd_hlpr.cli.cli import app
from bck_nd_hlpr.core.orchestrator import OrchestratorResult, ScannerOrchestrator
from bck_nd_hlpr.core.requirements import RequirementsParser
from bck_nd_hlpr.core.requirements.locations import discover_requirements_locations


runner = CliRunner()


def _write_story(
    project: Path,
    story_id: str,
    *,
    status: str = "TODO",
    title: str = "Iniciar sesión de forma simulada",
) -> Path:
    requirements = project / ".bck-nd" / "requirements"
    requirements.mkdir(parents=True, exist_ok=True)
    target = requirements / f"{story_id}.json"
    target.write_text(
        json.dumps(
            {
                "story": {
                    "id": story_id,
                    "status": status,
                    "title": title,
                    "role": "usuario de VidaSalud",
                    "want": "iniciar sesión de forma simulada",
                    "benefit": "acceder a las funciones del sistema",
                },
                "business_rules": [
                    {"id": "BR01", "description": "Descripción privada de la regla"},
                    {"id": "BR02", "description": "Segunda regla privada"},
                ],
                "acceptance_criteria": [
                    {
                        "id": "AC01",
                        "given": "credenciales válidas",
                        "when": "se envía el formulario",
                        "then": "la sesión comienza",
                    }
                ],
                "required_data": [
                    {
                        "field": "usuario",
                        "type": "string",
                        "required": True,
                        "format": "email",
                    }
                ],
                "validations": [
                    {"field": "usuario", "rule": "obligatorio", "severity": "alta"}
                ],
                "exceptions": [
                    {
                        "code": "INVALID_CREDENTIALS",
                        "description": "Usuario incorrecto.",
                        "retryable": False,
                    }
                ],
                "open_questions": ["¿Se necesita recuperación de contraseña?"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return target


def _lightweight_orchestrator(config):
    return OrchestratorResult(
        path=config.path,
        framework="Unknown",
        architecture="",
        features=[],
        summary="",
        todos=[],
    )


def test_req_list_renders_all_story_briefs_and_dynamic_show_hint(tmp_path):
    _write_story(tmp_path, "HU05")
    _write_story(tmp_path, "HU06", status="DONE", title="Consultar agenda")
    nested = tmp_path / "Sistemas1-Equipo321-VidaSalud"
    _write_story(nested, "HU01", status="DONE", title="Nested only")
    _write_story(nested, "HU05", status="DONE", title="Nested conflict")
    _write_story(nested, "HU06", status="DONE", title="Nested conflict")

    result = runner.invoke(app, ["req", "list", str(tmp_path)])
    shown = runner.invoke(app, ["req", "show", "HU05", str(tmp_path)])
    validated = runner.invoke(app, ["req", "validate", str(tmp_path)])
    discovered = runner.invoke(app, ["req", "discover", "HU05", str(tmp_path)])

    assert result.exit_code == 0, result.exception
    for expected in (
        "HU05",
        "HU06",
        "Iniciar sesión de forma simulada",
        "Consultar agenda",
        "usuario de VidaSalud",
        "iniciar sesión de forma simulada",
        "acceder a las funciones del sistema",
        "1 criterio",
        "2 reglas",
        f"bck-nd req show HU05 {tmp_path}",
        "Requirements scope: .",
        "Source: .bck-nd/requirements",
        "WARNING: 1 nested Requirements collection was omitted.",
        "Conflicting IDs: HU05, HU06",
        f"bck-nd req locations {tmp_path}",
    ):
        assert expected in result.stdout
    assert "HU01" not in result.stdout
    assert "Descripción privada de la regla" not in result.stdout
    assert "credenciales válidas" not in result.stdout
    for scoped in (shown, validated, discovered):
        assert scoped.exit_code == 0, scoped.exception
        assert "Requirements scope: ." in scoped.stdout
        assert "WARNING: 1 nested Requirements collection was omitted." in scoped.stdout
        assert "Conflicting IDs: HU05, HU06" in scoped.stdout
    assert "Displayed from current scope only." in shown.stdout
    assert "HU05 also exists in:" in shown.stdout
    assert "Sistemas1-Equipo321-VidaSalud" in shown.stdout


def test_req_show_is_complete_case_insensitive_and_reports_missing(tmp_path):
    _write_story(tmp_path, "HU05", title="Historia [segura]")

    shown = runner.invoke(app, ["req", "show", "hu05", str(tmp_path)])
    missing = runner.invoke(app, ["req", "show", "HU99", str(tmp_path)])

    assert shown.exit_code == 0, shown.exception
    for expected in (
        "HU05",
        "Historia [segura]",
        "usuario de VidaSalud",
        "BR01",
        "Descripción privada de la regla",
        "AC01",
        "Given",
        "When",
        "Then",
        "Required Data",
        "Validations",
        "Exceptions",
        "Open Questions",
        "recuperación de contraseña",
        "usuario — string",
        "format: email",
        "required: true",
        "usuario — obligatorio",
        "severity: alta",
        "INVALID_CREDENTIALS — Usuario incorrecto.",
        "retryable: false",
    ):
        assert expected in shown.stdout
    assert '{"field"' not in shown.stdout
    assert '{"code"' not in shown.stdout
    assert missing.exit_code == 1
    assert "Requirement not found: HU99" in missing.stdout
    assert "HU05" in missing.stdout


def test_req_validate_distinguishes_valid_uninitialized_and_rejected(tmp_path):
    valid_project = tmp_path / "valid"
    missing_project = tmp_path / "missing"
    invalid_project = tmp_path / "invalid"
    missing_project.mkdir()
    _write_story(valid_project, "HU05")
    invalid_dir = invalid_project / ".bck-nd" / "requirements"
    invalid_dir.mkdir(parents=True)
    (invalid_dir / "HU-BAD.json").write_text("{invalid", encoding="utf-8")

    valid = runner.invoke(app, ["req", "validate", str(valid_project)])
    missing = runner.invoke(app, ["req", "validate", str(missing_project)])
    invalid = runner.invoke(app, ["req", "validate", str(invalid_project)])

    assert valid.exit_code == 0, valid.exception
    assert "Requirements: VALID" in valid.stdout
    assert "Stories: 1" in valid.stdout
    assert "Acceptance criteria: 1" in valid.stdout
    assert "Business rules: 2" in valid.stdout
    assert "Open questions: 1" in valid.stdout
    assert missing.exit_code == 1
    assert "Requirements are not initialized" in missing.stdout
    assert "bck-nd req init US-001 --path" in missing.stdout
    assert invalid.exit_code == 1
    assert "Requirements: INVALID" in invalid.stdout
    assert "REQUIREMENT_" in invalid.stdout
    assert f"bck-nd req validate {invalid_project}" in invalid.stdout
    assert "Traceback" not in invalid.stdout


def test_rejected_list_and_discover_direct_users_to_validate(tmp_path):
    requirements = tmp_path / ".bck-nd" / "requirements"
    requirements.mkdir(parents=True)
    (requirements / "bad.json").write_text("[]", encoding="utf-8")

    listed = runner.invoke(app, ["req", "list", str(tmp_path)])
    discovered = runner.invoke(app, ["req", "discover", str(tmp_path)])

    for result in (listed, discovered):
        assert result.exit_code == 1
        assert "Requirements: INVALID" in result.stdout
        assert f"bck-nd req validate {tmp_path}" in result.stdout
        assert "No requirements found" not in result.stdout


def test_scan_general_metrics_and_req_mode_share_briefs(tmp_path, monkeypatch):
    project = tmp_path / "Vida Salud"
    _write_story(project, "HU05")
    nested = project / "Sistemas1-Equipo321-VidaSalud"
    _write_story(nested, "HU01", status="DONE", title="Nested only")
    _write_story(nested, "HU05", status="DONE", title="Nested conflict")
    monkeypatch.setattr(ScannerOrchestrator, "run", staticmethod(_lightweight_orchestrator))

    listed = runner.invoke(app, ["req", "list", str(project)])
    general = runner.invoke(app, ["scan", str(project), "--no-graph"])
    briefs = runner.invoke(app, ["scan", str(project), "--req"])
    quoted_project = (
        f'"{project}"' if os.name == "nt" else shlex.quote(str(project))
    )

    assert listed.exit_code == 0, listed.exception
    assert f"bck-nd req show HU05 {quoted_project}" in listed.stdout
    assert general.exit_code == 0, general.exception
    assert "Requirements: 1 story" in general.stdout
    assert "1 TODO" in general.stdout
    assert "1 criterion" in general.stdout
    assert "2 rules" in general.stdout
    assert "Scope: ." in general.stdout
    assert "Nested Requirements collections omitted: 1" in general.stdout
    assert f"bck-nd req locations {quoted_project}" in general.stdout
    assert f"bck-nd req list {quoted_project}" in general.stdout
    assert f"AI context: bck-nd prompt {quoted_project} --copy" in general.stdout
    assert briefs.exit_code == 0, briefs.exception
    assert "Scope: ." in briefs.stdout
    assert "HU05" in briefs.stdout
    assert "HU01" not in briefs.stdout
    assert "usuario de VidaSalud" in briefs.stdout
    assert "Descripción privada de la regla" not in briefs.stdout
    assert "WARNING: 1 nested Requirements collection was omitted." in briefs.stdout
    assert "Conflicting IDs: HU05" in briefs.stdout


def test_requirements_locations_respect_hierarchical_gitignore(tmp_path, monkeypatch):
    _write_story(tmp_path, "HU-SHARED")
    (tmp_path / ".gitignore").write_text("pytest_*/\n", encoding="utf-8")
    ignored = tmp_path / "pytest_temp" / "fixture"
    _write_story(ignored, "HU-SHARED", title="Ignored fixture")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".gitignore").write_text(
        "*\n!visible/\n!blocked/\n",
        encoding="utf-8",
    )
    visible = workspace / "visible"
    _write_story(visible, "HU-VISIBLE", title="Visible nested story")
    generated = workspace / "generated"
    _write_story(generated, "HU-SHARED", title="Ignored generated story")
    blocked = workspace / "blocked"
    _write_story(blocked, "HU-BLOCKED", title="Unsafe policy story")
    (blocked / ".gitignore").write_text("x" * 4097 + "\n", encoding="utf-8")

    real_load = RequirementsParser.load_collection
    loaded_roots = []

    def counted_load(*args):
        project_path = args[-1]
        loaded_roots.append(Path(project_path))
        return real_load(project_path)

    monkeypatch.setattr(RequirementsParser, "load_collection", counted_load)
    report = discover_requirements_locations(tmp_path, max_locations=2)

    assert tuple(item.relative_root for item in report.nested_locations) == (
        "workspace/visible",
    )
    assert report.conflicting_ids == ()
    assert report.truncated is False
    fixture_root = tmp_path.resolve()
    relative_loaded = tuple(
        Path(path).resolve().relative_to(fixture_root)
        for path in loaded_roots
    )
    assert Path(".") in relative_loaded
    assert Path("workspace/visible") in relative_loaded
    assert all(
        not relative.parts or relative.parts[0] != "pytest_temp"
        for relative in relative_loaded
    )
    assert all("generated" not in relative.parts for relative in relative_loaded)
    assert all("blocked" not in relative.parts for relative in relative_loaded)
    assert any(
        item.code == "REQUIREMENTS_IGNORE_POLICY_UNAVAILABLE"
        for item in report.diagnostics
    )
    assert all(str(tmp_path) not in item.message for item in report.diagnostics)

    root_blocked = tmp_path / "root-blocked"
    root_blocked.mkdir()
    (root_blocked / ".gitignore").write_text("y" * 4097 + "\n", encoding="utf-8")
    _write_story(root_blocked / "nested", "HU-HIDDEN")
    blocked_report = discover_requirements_locations(root_blocked)
    assert blocked_report.nested_locations == ()
    assert any(
        item.code == "REQUIREMENTS_IGNORE_POLICY_UNAVAILABLE"
        for item in blocked_report.diagnostics
    )

    depth_limited = tmp_path / "depth-limited"
    depth_limited.mkdir()
    (depth_limited / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    _write_story(depth_limited / "ignored", "HU-IGNORED")
    depth_report = discover_requirements_locations(depth_limited, max_depth=0)
    assert depth_report.nested_locations == ()
    assert depth_report.truncated is False


def test_prompt_full_focused_disable_and_budget_requirements(tmp_path, monkeypatch):
    import bck_nd_hlpr.core.context_dumper as context_dumper_module

    _write_story(tmp_path, "HU05")
    _write_story(tmp_path, "HU06", title="Outer HU06")
    (tmp_path / "main.py").write_text("print('ok')\n", encoding="utf-8")
    nested = tmp_path / "Sistemas1-Equipo321-VidaSalud"
    for story_id in ("HU01", "HU02", "HU03", "HU04", "HU05", "HU06", "HU07"):
        _write_story(nested, story_id, status="DONE", title=f"Inner {story_id}")
    (nested / "main.py").write_text("print('inner')\n", encoding="utf-8")
    focused_file = tmp_path / "focused.txt"
    inner_file = tmp_path / "inner.txt"
    disabled_file = tmp_path / "disabled.txt"
    real_discover = context_dumper_module.discover_requirements_locations
    discovery_calls = []

    def counted_discovery(project_path, current_result=None, **kwargs):
        discovery_calls.append(Path(project_path))
        return real_discover(project_path, current_result=current_result, **kwargs)

    monkeypatch.setattr(
        context_dumper_module,
        "discover_requirements_locations",
        counted_discovery,
    )

    focused = runner.invoke(
        app,
        [
            "prompt",
            str(tmp_path),
            "--tree",
            "--max-requirements-chars",
            "256",
            "--output",
            str(focused_file),
        ],
    )
    disabled = runner.invoke(
        app,
        [
            "prompt",
            str(tmp_path),
            "--tree",
            "--no-req",
            "--output",
            str(disabled_file),
        ],
    )
    inner_result = runner.invoke(
        app,
        [
            "prompt",
            str(nested),
            "--tree",
            "--output",
            str(inner_file),
        ],
    )

    assert focused.exit_code == 0, focused.exception
    focused_context = focused_file.read_text(encoding="utf-8")
    assert "<requirements_scope>" in focused_context
    assert focused_context.index("<requirements_scope>") < focused_context.index(
        "<requirements_context>"
    )
    assert "nested_locations_omitted: 1" in focused_context
    assert "Sistemas1-Equipo321-VidaSalud" in focused_context
    assert "  - HU05" in focused_context
    assert "  - HU06" in focused_context
    assert "<requirements_context>" in focused_context
    inner_requirements = focused_context.split("<requirements_context>", 1)[1].split(
        "</requirements_context>", 1
    )[0].strip()
    assert len(inner_requirements) <= 256
    assert "HU05" in inner_requirements
    assert "HU06" in inner_requirements
    assert "HU01" not in inner_requirements
    assert "HU07" not in inner_requirements
    assert "Requirements:" in focused.stdout
    assert "Included with truncation" in focused.stdout
    assert "1 nested collection omitted" in focused.stdout
    assert disabled.exit_code == 0, disabled.exception
    disabled_context = disabled_file.read_text(encoding="utf-8")
    assert "<requirements_scope>" not in disabled_context
    assert "<requirements_context>" not in disabled_context
    assert "Disabled with --no-req" in disabled.stdout
    assert inner_result.exit_code == 0, inner_result.exception
    inner_context = inner_file.read_text(encoding="utf-8")
    assert "<requirements_scope>" not in inner_context
    assert "<requirements_context>" in inner_context
    for story_id in ("HU01", "HU02", "HU03", "HU04", "HU05", "HU06", "HU07"):
        assert story_id in inner_context
    assert "Outer HU06" not in inner_context
    assert len(discovery_calls) == 2


def test_context_dumper_caches_one_requirements_load(tmp_path, monkeypatch):
    from bck_nd_hlpr.core.context_dumper import ContextDumper

    _write_story(tmp_path, "HU05")
    real_load = RequirementsParser.load_collection
    calls = []

    def counted_load(project_path):
        calls.append(project_path)
        return real_load(project_path)

    monkeypatch.setattr(RequirementsParser, "load_collection", counted_load)
    dumper = ContextDumper(path=str(tmp_path), include_prd=False)

    rendered = dumper.build_focused(include_tree=True)
    assert dumper.get_requirements_context() is not None
    assert dumper.get_requirements_result().specifications
    assert "<requirements_context>" in rendered
    assert len(calls) == 1


def test_req_init_prints_real_next_steps(tmp_path):
    result = runner.invoke(
        app, ["req", "init", "us-007", "--path", str(tmp_path)]
    )

    assert result.exit_code == 0, result.exception
    assert f"bck-nd req show US-007 {tmp_path}" in result.stdout
    assert f"bck-nd req list {tmp_path}" in result.stdout
    assert f"bck-nd prompt {tmp_path} -c" in result.stdout
