"""Regression tests for the public CLI help surfaces."""

import pytest
from click.utils import strip_ansi
from typer.testing import CliRunner

import bck_nd_hlpr.cli.cli as cli_module
import bck_nd_hlpr.cli.mcp_server as mcp_server_module
from bck_nd_hlpr.cli.cli import app


runner = CliRunner()


def _visible(text: str) -> str:
    return strip_ansi(text)


def _compact(text: str) -> str:
    return " ".join(_visible(text).replace("│", " ").split())


def test_flow_prints_diagram_once_and_fails_without_internal_details(monkeypatch):
    rendered = runner.invoke(app, ["flow", "A -> B"])

    assert rendered.exit_code == 0, rendered.exception
    assert rendered.stdout.count("GENERATING MANUAL DIAGRAM") == 1
    assert rendered.stdout.count("│  A  │----->│  B  │") == 1

    blank = runner.invoke(app, ["flow", "   "])
    assert blank.exit_code == 1
    assert "Could not render flow diagram safely." in blank.stdout
    assert "Traceback" not in blank.stdout

    def fail_safely(_self, _layout):
        raise RuntimeError("private C:/Users/secret/project")

    monkeypatch.setattr(cli_module.Router, "process", fail_safely)
    failed = runner.invoke(app, ["flow", "A -> B"])
    assert failed.exit_code == 1
    assert "Could not render flow diagram safely." in failed.stdout
    assert "private" not in failed.stdout
    assert "Traceback" not in failed.stdout


def test_scan_help_describes_combinable_views_and_examples():
    result = runner.invoke(app, ["scan", "--help"])
    visible = _visible(result.stdout)
    compact = _compact(result.stdout)

    assert result.exit_code == 0, result.exception
    assert "Exclusive modes" not in visible
    assert "Views may be requested individually or combined" in compact
    assert "bck-nd scan . --uml --er" in compact
    assert "bck-nd scan . --tree --req" in compact


def test_root_help_lists_current_workflows():
    result = runner.invoke(app, ["--help"])
    visible = _visible(result.stdout)
    compact_help = _compact(result.stdout)

    assert result.exit_code == 0, result.exception
    assert "Product intent" in visible
    assert "requirements" in visible
    assert "architecture" in visible
    assert "AI context" in visible
    assert "MCP tooling" in visible
    assert "scan . --json" in visible
    assert "prompt . --copy" in visible
    assert "req init US-001" in visible
    assert "req list ." in visible
    assert "req show HU05 ." in visible
    assert "req validate ." in visible
    assert "req locations ." in visible
    assert "prd init PRD-AUTH" in visible
    assert "AI context with product intent, requirements, and metrics" in compact_help
    assert "bck-nd-mcp --install" in visible
    assert "Antigravity" in visible


def test_prompt_help_describes_requirements_copy_and_metrics():
    result = runner.invoke(app, ["prompt", "--help"])
    visible = _visible(result.stdout)
    compact_help = _compact(result.stdout)

    assert result.exit_code == 0, result.exception
    assert "requirements, diagrams, core files, and metrics" in visible
    assert "--copy" in visible
    assert "--max-core-files" in visible
    assert "--no-prd" in visible
    assert "--max-product-chars" in visible
    assert "--no-req" in visible
    assert "--max-requirements-chars" in visible
    assert "estimated tokens" in visible
    assert "product- and requirements-aware focused context with UML" in compact_help
    assert "product- and requirements-aware focused context with ER" in compact_help
    assert "product- and requirements-aware focused context with project tree" in compact_help
    assert "strictly technical" in compact_help
    assert "UML-only" not in visible
    assert "ER-only" not in visible
    assert "tree-only" not in visible


def test_requirements_help_lists_current_workflow_commands():
    result = runner.invoke(app, ["req", "--help"])
    visible = _visible(result.stdout)

    assert result.exit_code == 0, result.exception
    assert "Scaffold, browse, validate, update, and discover" in visible
    assert "init" in visible
    assert "status" in visible
    assert "set-status" in visible
    assert "discover" in visible
    assert "show" in visible
    assert "validate" in visible
    assert "locations" in visible
    assert "collection locations" in visible


@pytest.mark.parametrize(
    ("arguments", "phrases"),
    [
        (["--help"], ("Product intent", "scan . --json", "prompt . --copy")),
        (["scan", "--help"], ("Views may be requested", "scan . --uml --er")),
        (["prompt", "--help"], ("--max-product-chars", "estimated tokens")),
    ],
)
def test_cli_help_comparisons_handle_real_ansi(monkeypatch, arguments, phrases):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("_TYPER_FORCE_DISABLE_TERMINAL", raising=False)

    result = runner.invoke(app, arguments, color=True)

    assert result.exit_code == 0, result.exception
    assert "\x1b[" in result.stdout
    visible = _visible(result.stdout)
    assert all(phrase in visible for phrase in phrases)


@pytest.mark.parametrize("help_flag", ["--help", "-h"])
def test_mcp_help_does_not_start_stdio(help_flag, monkeypatch, capsys):
    def unexpected_run(*args, **kwargs):
        raise AssertionError("MCP stdio server must not start while rendering help")

    monkeypatch.setattr(mcp_server_module.sys, "argv", ["bck-nd-mcp", help_flag])
    monkeypatch.setattr(mcp_server_module.mcp, "run", unexpected_run)

    assert mcp_server_module.main() is None
    output = capsys.readouterr().out
    compact_help = " ".join(output.split())
    assert "Usage: bck-nd-mcp [OPTIONS]" in output
    assert "product" in output
    assert "requirements" in output
    assert "architecture" in output
    assert "--install" in output
    assert "--allowed-root" in output
    assert "--version" in output
    assert "--help" in output
    assert "Antigravity" in compact_help
    assert "antigravity-ide" in output
    assert "GitHub or other MCP servers" in output


def test_mcp_unknown_option_fails_instead_of_starting_stdio(monkeypatch, capsys):
    def unexpected_run(*args, **kwargs):
        raise AssertionError("MCP stdio server must not start for an invalid option")

    monkeypatch.setattr(mcp_server_module.sys, "argv", ["bck-nd-mcp", "--wat"])
    monkeypatch.setattr(mcp_server_module.mcp, "run", unexpected_run)

    with pytest.raises(SystemExit) as exc_info:
        mcp_server_module.main()

    assert exc_info.value.code == 2
    error_output = capsys.readouterr().err
    assert "unknown option or argument: --wat" in error_output
    assert "Usage: bck-nd-mcp [OPTIONS]" in error_output


def test_mcp_install_without_explicit_roots_fails_before_writing(
    tmp_path,
    monkeypatch,
    capsys,
):
    config_path = tmp_path / "claude.json"
    monkeypatch.delenv("BCK_ND_MCP_ALLOWED_ROOTS", raising=False)
    monkeypatch.setattr(mcp_server_module.sys, "argv", ["bck-nd-mcp", "--install"])
    monkeypatch.setattr(
        mcp_server_module,
        "_get_claude_config_path",
        lambda: config_path,
    )

    with pytest.raises(SystemExit) as error:
        mcp_server_module.main()

    assert error.value.code == 2
    output = capsys.readouterr().err
    assert "--allowed-root" in output
    assert str(tmp_path) not in output
    assert not config_path.exists()
