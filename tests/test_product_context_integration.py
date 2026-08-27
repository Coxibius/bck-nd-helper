"""Sprint 3 integration tests for ContextDumper, prompt CLI, and MCP."""

from pathlib import Path
from typer.testing import CliRunner

import bck_nd_hlpr.cli.cli as cli_module
import bck_nd_hlpr.cli.mcp_server as mcp_module
import bck_nd_hlpr.core.context_dumper as context_dumper_module
from bck_nd_hlpr.core.context_dumper import ContextDumper
from bck_nd_hlpr.core.product import ProductContextBudgetError, build_product_context


runner = CliRunner()


def complete_product(product_id="PRD-INTEGRATION", applies_to=".", padding=""):
    return f"""---
schema_version: 1
id: {product_id}
title: Integration product
status: DRAFT
owner: Team
target_release: 2.5.0
applies_to:
  - {applies_to}
requirement_ids: []
---

## Problem Statement
Agents need product context.{padding}

## Target Users
Developers.

## Goals
Preserve intent.

## Non-Goals
No invented scope.

## Success Metrics
Context is deterministic.

## Scope
Local files.

## Risks
Token growth.

## Rollout Plan
Test first.

## Open Questions
- None
"""


def write_product(project: Path, filename="PRD-INTEGRATION.md", **kwargs) -> Path:
    directory = project / ".bck-nd" / "product"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / filename
    target.write_text(complete_product(**kwargs), encoding="utf-8")
    return target


def stabilize_dumper(dumper: ContextDumper, monkeypatch) -> None:
    monkeypatch.setattr(dumper, "get_project_tree", lambda: "TREE")
    monkeypatch.setattr(dumper, "get_uml_diagram", lambda: "classDiagram")
    monkeypatch.setattr(dumper, "get_er_diagram", lambda: "erDiagram")
    monkeypatch.setattr(dumper, "get_core_files", lambda: [])
    monkeypatch.setattr(dumper, "get_requirements_context", lambda: "REQS")


def test_context_dumper_orders_product_before_existing_sections(tmp_path, monkeypatch):
    write_product(tmp_path)
    dumper = ContextDumper(path=str(tmp_path))
    stabilize_dumper(dumper, monkeypatch)

    content = dumper.build()

    assert content.index("<product_context") < content.index("<requirements_context>")
    assert content.index("<requirements_context>") < content.index("<project_tree>")
    assert content.index("<project_tree>") < content.index("<architecture_uml>")


def test_focused_context_uses_same_contractual_order(tmp_path, monkeypatch):
    write_product(tmp_path)
    dumper = ContextDumper(path=str(tmp_path))
    stabilize_dumper(dumper, monkeypatch)

    content = dumper.build_focused(
        include_tree=True,
        include_uml=True,
        include_requirements=True,
    )

    assert content.index("<product_context") < content.index("<requirements_context>")
    assert content.index("<requirements_context>") < content.index("<project_tree>")
    assert content.index("<project_tree>") < content.index("<architecture_uml>")


def test_absent_product_keeps_previous_output_byte_for_byte(tmp_path, monkeypatch):
    enabled = ContextDumper(path=str(tmp_path))
    disabled = ContextDumper(path=str(tmp_path), include_prd=False)
    stabilize_dumper(enabled, monkeypatch)
    stabilize_dumper(disabled, monkeypatch)

    assert enabled.build() == disabled.build()


def test_include_prd_false_never_calls_renderer(tmp_path, monkeypatch):
    def unexpected_renderer(*args, **kwargs):
        raise AssertionError("product renderer must not be called")

    monkeypatch.setattr(
        context_dumper_module,
        "build_product_context",
        unexpected_renderer,
    )
    dumper = ContextDumper(path=str(tmp_path), include_prd=False)
    stabilize_dumper(dumper, monkeypatch)

    assert "<product_context" not in dumper.build()
    assert dumper.get_product_context() is None


def test_controlled_product_error_does_not_break_context_build(
    tmp_path,
    monkeypatch,
    capsys,
):
    def unavailable_renderer(*args, **kwargs):
        raise ProductContextBudgetError("minimum envelope is too large")

    monkeypatch.setattr(
        context_dumper_module,
        "build_product_context",
        unavailable_renderer,
    )
    dumper = ContextDumper(path=str(tmp_path))
    stabilize_dumper(dumper, monkeypatch)

    content = dumper.build()

    assert "<project_tree>" in content
    assert "<product_context" not in content
    assert "Product context unavailable" in capsys.readouterr().err


def test_context_dumper_delegates_budget_to_canonical_renderer(tmp_path):
    write_product(tmp_path, padding="\n" + ("Long narrative.\n" * 100))
    dumper = ContextDumper(path=str(tmp_path), max_product_chars=700)

    product_context = dumper.get_product_context()

    assert product_context == build_product_context(tmp_path, max_chars=700)
    assert len(product_context) <= 700


def test_prompt_default_includes_product_and_custom_budget(tmp_path):
    write_product(tmp_path, padding="\n" + ("Long narrative.\n" * 80))
    (tmp_path / "main.py").write_text("value = 1\n", encoding="utf-8")
    output = tmp_path / "context.txt"

    result = runner.invoke(
        cli_module.app,
        [
            "prompt",
            str(tmp_path),
            "--tree",
            "--max-product-chars",
            "700",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.exception
    context = output.read_text(encoding="utf-8")
    start = context.index('<product_context schema_version="1">')
    end = context.index("</product_context>", start) + len("</product_context>")
    assert end - start <= 700


def test_prompt_without_focus_flags_includes_product_context(
    tmp_path,
    monkeypatch,
):
    write_product(tmp_path)
    output = tmp_path / "full-context.txt"
    monkeypatch.setattr(ContextDumper, "get_project_tree", lambda self: "TREE")
    monkeypatch.setattr(ContextDumper, "get_uml_diagram", lambda self: None)
    monkeypatch.setattr(ContextDumper, "get_er_diagram", lambda self: None)
    monkeypatch.setattr(ContextDumper, "get_core_files", lambda self: [])

    result = runner.invoke(
        cli_module.app,
        ["prompt", str(tmp_path), "--output", str(output)],
    )

    assert result.exit_code == 0, result.exception
    assert '<product_context schema_version="1">' in output.read_text(
        encoding="utf-8"
    )


def test_prompt_no_prd_skips_loading_even_with_budget(tmp_path, monkeypatch):
    write_product(tmp_path)
    output = tmp_path / "context.txt"

    def unexpected_renderer(*args, **kwargs):
        raise AssertionError("--no-prd must not load product context")

    monkeypatch.setattr(
        context_dumper_module,
        "build_product_context",
        unexpected_renderer,
    )
    result = runner.invoke(
        cli_module.app,
        [
            "prompt",
            str(tmp_path),
            "--tree",
            "--no-prd",
            "--max-product-chars",
            "700",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.exception
    assert "<product_context" not in output.read_text(encoding="utf-8")


def test_prompt_rejects_product_budget_below_minimum(tmp_path):
    result = runner.invoke(
        cli_module.app,
        ["prompt", str(tmp_path), "--max-product-chars", "255"],
    )

    assert result.exit_code == 2
    assert "256" in (result.stdout + result.stderr)


def test_mcp_product_tool_matches_renderer_and_does_not_modify_sources(tmp_path):
    source = write_product(tmp_path)
    before = source.read_bytes()

    expected = build_product_context(tmp_path, target_path=".", max_chars=900)
    actual = mcp_module.get_product_context(
        project_path=str(tmp_path),
        target_path=".",
        max_chars=900,
    )

    assert actual == expected
    assert source.read_bytes() == before


def test_mcp_product_tool_handles_absence_scope_and_budget(tmp_path):
    assert mcp_module.get_product_context(str(tmp_path)) == ""

    (tmp_path / "frontend").mkdir()
    (tmp_path / "backend").mkdir()
    write_product(
        tmp_path,
        filename="frontend.md",
        product_id="PRD-FRONTEND",
        applies_to="frontend",
        padding="\n" + ("Frontend intent.\n" * 80),
    )
    write_product(
        tmp_path,
        filename="backend.md",
        product_id="PRD-BACKEND",
        applies_to="backend",
    )

    context = mcp_module.get_product_context(
        project_path=str(tmp_path),
        target_path="frontend/src",
        max_chars=800,
    )

    assert len(context) <= 800
    assert "PRD-FRONTEND" in context
    assert "PRD-BACKEND" not in context


def test_mcp_product_tool_rejects_unsafe_target_without_leaking_it(tmp_path):
    unsafe = "file:///C:/Users/Private/secret"

    result = mcp_module.get_product_context(
        project_path=str(tmp_path),
        target_path=unsafe,
    )

    assert result.startswith("Error building product context:")
    assert unsafe not in result


def test_mcp_registers_exactly_one_new_read_only_product_tool():
    tools = mcp_module.mcp._tool_manager._tools

    assert len(tools) == 24
    assert "get_product_context" in tools
    assert "consult" in mcp_module.get_product_context.__doc__.lower()
