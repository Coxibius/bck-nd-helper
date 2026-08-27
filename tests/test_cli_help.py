"""Regression tests for the public CLI help surfaces."""

import pytest
from typer.testing import CliRunner

import bck_nd_hlpr.cli.mcp_server as mcp_server_module
from bck_nd_hlpr.cli.cli import app


runner = CliRunner()


def test_root_help_lists_current_workflows():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0, result.exception
    assert "Architecture, requirements, AI context, and MCP tooling" in result.stdout
    assert "scan . --json" in result.stdout
    assert "prompt . --copy" in result.stdout
    assert "req init US-001" in result.stdout
    assert "bck-nd-mcp --install" in result.stdout
    assert "Antigravity" in result.stdout


def test_prompt_help_describes_requirements_copy_and_metrics():
    result = runner.invoke(app, ["prompt", "--help"])
    compact_help = " ".join(result.stdout.replace("│", " ").split())

    assert result.exit_code == 0, result.exception
    assert "requirements, diagrams, core files, and metrics" in result.stdout
    assert "--copy" in result.stdout
    assert "--max-core-files" in result.stdout
    assert "--no-prd" in result.stdout
    assert "--max-product-chars" in result.stdout
    assert "estimated tokens" in result.stdout
    assert "product-aware focused context with UML" in compact_help
    assert "product-aware focused context with ER" in compact_help
    assert "product-aware focused context with project tree" in compact_help
    assert "strictly technical" in compact_help
    assert "UML-only" not in result.stdout
    assert "ER-only" not in result.stdout
    assert "tree-only" not in result.stdout


def test_requirements_help_lists_current_workflow_commands():
    result = runner.invoke(app, ["req", "--help"])

    assert result.exit_code == 0, result.exception
    assert "Scaffold, list, update, and discover" in result.stdout
    assert "init" in result.stdout
    assert "status" in result.stdout
    assert "set-status" in result.stdout
    assert "discover" in result.stdout


@pytest.mark.parametrize("help_flag", ["--help", "-h"])
def test_mcp_help_does_not_start_stdio(help_flag, monkeypatch, capsys):
    def unexpected_run(*args, **kwargs):
        raise AssertionError("MCP stdio server must not start while rendering help")

    monkeypatch.setattr(mcp_server_module.sys, "argv", ["bck-nd-mcp", help_flag])
    monkeypatch.setattr(mcp_server_module.mcp, "run", unexpected_run)

    assert mcp_server_module.main() is None
    output = capsys.readouterr().out
    assert "Usage: bck-nd-mcp [OPTIONS]" in output
    assert "--install" in output
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
