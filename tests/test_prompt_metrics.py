"""Token estimation and raw-context savings tests for ``bck-nd prompt``."""
from __future__ import annotations

from pathlib import Path

import pytest

from bck_nd_hlpr.core.context_dumper import (
    ContextDumper,
    calculate_context_metrics,
    estimate_token_count,
    format_context_metrics,
)


def test_estimate_token_count_uses_code_xml_ratio():
    assert estimate_token_count("x" * 35) == 10
    assert estimate_token_count("") == 0
    with pytest.raises(ValueError):
        estimate_token_count("content", chars_per_token=0)


def test_calculate_and_format_context_savings():
    metrics = calculate_context_metrics("x" * 1024, raw_size_bytes=4096)

    assert metrics.estimated_tokens == 293
    assert metrics.context_kb == 1.0
    assert metrics.raw_kb == 4.0
    assert metrics.savings_percentage == 75.0
    assert format_context_metrics(metrics) == (
        "📊 AI Context: ~293 tokens (1.0 KB) | "
        "⚡ 75.0% context savings vs raw codebase (4.0 KB)"
    )


def test_raw_source_size_respects_project_exclusions(tmp_path: Path):
    (tmp_path / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    (tmp_path / "app.py").write_bytes(b"a" * 100)
    src = tmp_path / "src"
    src.mkdir()
    (src / "service.go").write_bytes(b"g" * 200)
    (tmp_path / "README.md").write_bytes(b"d" * 500)
    (tmp_path / "ignored.py").write_bytes(b"i" * 700)
    node_modules = tmp_path / "node_modules"
    node_modules.mkdir()
    (node_modules / "noise.js").write_bytes(b"n" * 900)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "bundle.ts").write_bytes(b"b" * 800)

    assert ContextDumper(path=str(tmp_path)).get_raw_source_size() == 300


def test_prompt_prints_token_and_savings_footer(tmp_path: Path):
    from typer.testing import CliRunner
    from bck_nd_hlpr.cli.cli import app

    (tmp_path / "main.py").write_text("value = 1\n" * 3000, encoding="utf-8")
    output = tmp_path / "focused-context.txt"

    result = CliRunner().invoke(
        app,
        ["prompt", str(tmp_path), "--tree", "--output", str(output)],
    )

    assert result.exit_code == 0, result.exception
    assert output.is_file()
    assert "📊 AI Context: ~" in result.stdout
    assert "tokens" in result.stdout
    assert "context savings vs raw codebase" in result.stdout
