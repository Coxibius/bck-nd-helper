"""Real installed-entry-point smoke tests on a small synthetic project."""

from __future__ import annotations

import json
import os
import subprocess
import sysconfig
from pathlib import Path

import pytest
from bck_nd_hlpr import __version__


def _entry_point(name: str) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    entry = Path(sysconfig.get_path("scripts")) / f"{name}{suffix}"
    assert entry.is_file(), f"Missing {name} in the selected Python environment"
    return entry


def _run(entry: Path, project: Path, *arguments: str) -> str:
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["BCK_ND_MCP_ALLOWED_ROOTS"] = str(project)
    result = subprocess.run(
        [str(entry), *arguments],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, (
        f"{entry.name} {arguments} exited {result.returncode}:\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return result.stdout


@pytest.fixture
def smoke_project(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "QA proyecto con espacios"
    project.mkdir()
    (project / "main.py").write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "class CatalogService:\n"
        "    def list_items(self):\n"
        "        return []\n"
        "@app.get('/items')\n"
        "def list_items():\n"
        "    return []\n",
        encoding="utf-8",
    )
    requirements = project / ".bck-nd" / "requirements"
    requirements.mkdir(parents=True)
    story = requirements / "US-101.json"
    story.write_text(
        json.dumps(
            {
                "story": {
                    "id": "US-101",
                    "title": "List catalog items",
                    "role": "inventory clerk",
                    "want": "view the catalog",
                    "benefit": "prepare orders",
                    "status": "IN_PROGRESS",
                },
                "business_rules": [
                    {"id": "BR-101", "description": "Only active items are listed."}
                ],
                "acceptance_criteria": [
                    {
                        "id": "AC-101",
                        "given": "active items exist",
                        "when": "the catalog is requested",
                        "then": "active items are returned",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return project, story


def test_entry_points_report_version_and_help_without_starting_mcp(smoke_project):
    project, _story = smoke_project
    for name in ("bck-nd", "bck-nd-mcp"):
        entry = _entry_point(name)
        assert __version__ in _run(entry, project, "--version")
        help_text = _run(entry, project, "--help")
        assert "Usage:" in help_text
        assert name in help_text


def test_scan_prompt_and_requirements_agree_on_known_project(smoke_project, tmp_path):
    project, story = smoke_project
    original_story = story.read_bytes()
    cli = _entry_point("bck-nd")

    scan = json.loads(_run(cli, project, "scan", str(project), "--json", "--no-cache"))
    assert scan["framework"] == "FastAPI"
    assert {node["name"] for node in scan["asg"]["nodes"]} >= {"CatalogService"}
    assert {item["story"]["id"] for item in scan["requirements"]} >= {"US-101"}

    output = tmp_path / "QA context with spaces.txt"
    _run(cli, project, "prompt", str(project), "--output", str(output))
    context = output.read_text(encoding="utf-8")
    assert "<architecture_uml>" in context
    assert "CatalogService" in context
    assert "<requirements_context>" in context
    assert "US-101" in context
    assert "<core_files>" in context

    listed = _run(cli, project, "req", "list", str(project))
    shown = _run(cli, project, "req", "show", "US-101", str(project))
    assert "US-101" in listed and "List catalog items" in listed
    for expected in (
        "US-101",
        "inventory clerk",
        "view the catalog",
        "prepare orders",
        "BR-101",
        "Only active items are listed.",
        "AC-101",
        "active items are returned",
    ):
        assert expected in shown
    assert story.read_bytes() == original_story
