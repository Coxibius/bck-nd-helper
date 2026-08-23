"""Machine-readable output contract tests for ``bck-nd scan --json``."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from bck_nd_hlpr.cli.cli import app


@pytest.fixture
def json_project(tmp_path: Path) -> Path:
    (tmp_path / "main.py").write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "password = 'unsafe-test-value'\n"
        "# TODO: replace temporary repository\n"
        "class UserService:\n"
        "    def get_user(self, user_id: str):\n"
        "        return user_id\n"
        "@app.get('/users')\n"
        "def users():\n"
        "    return []\n",
        encoding="utf-8",
    )
    requirements_dir = tmp_path / ".bck-nd" / "requirements"
    requirements_dir.mkdir(parents=True)
    (requirements_dir / "US-001.json").write_text(
        json.dumps(
            {
                "story": {
                    "id": "US-001",
                    "title": "List users",
                    "role": "operator",
                    "want": "list users",
                    "benefit": "support customers",
                    "status": "IN_PROGRESS",
                },
                "acceptance_criteria": [
                    {
                        "id": "AC01",
                        "given": "users exist",
                        "when": "the endpoint is called",
                        "then": "users are returned",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_scan_json_returns_consolidated_payload(json_project: Path):
    result = CliRunner().invoke(
        app,
        ["scan", str(json_project), "--json", "--no-cache"],
    )

    assert result.exit_code == 0, result.exception
    payload = json.loads(result.stdout)
    assert set(
        (
            "framework",
            "architecture",
            "summary",
            "features",
            "asg",
            "requirements",
            "health",
            "todos",
            "security_risks",
        )
    ).issubset(payload)
    assert payload["framework"] == "FastAPI"
    assert {node["name"] for node in payload["asg"]["nodes"]} >= {"UserService"}
    assert payload["requirements"][0]["story"]["id"] == "US-001"
    assert payload["health"]["score"] < 100
    assert payload["todos"]
    assert payload["security_risks"]
    assert "Analyzing architecture" not in result.stdout


@pytest.mark.parametrize(
    ("flag", "expected_type"),
    [
        ("--health", dict),
        ("--todo", list),
        ("--audit", list),
        ("--contract", list),
        ("--impact", dict),
        ("--req", list),
    ],
)
def test_scan_specific_report_json(
    json_project: Path,
    flag: str,
    expected_type: type,
):
    result = CliRunner().invoke(
        app,
        ["scan", str(json_project), flag, "--json", "--no-cache"],
    )

    assert result.exit_code == 0, result.exception
    assert isinstance(json.loads(result.stdout), expected_type)


def test_scan_json_writes_directly_to_output_file(
    json_project: Path,
    tmp_path: Path,
):
    output = tmp_path / "result.json"
    result = CliRunner().invoke(
        app,
        [
            "scan",
            str(json_project),
            "--todo",
            "--json",
            "--no-cache",
            "-o",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.exception
    assert result.stdout == ""
    assert isinstance(json.loads(output.read_text(encoding="utf-8")), list)


def test_scan_multiple_json_reports_are_keyed(json_project: Path):
    result = CliRunner().invoke(
        app,
        [
            "scan",
            str(json_project),
            "--health",
            "--todo",
            "--json",
            "--no-cache",
        ],
    )

    assert result.exit_code == 0, result.exception
    payload = json.loads(result.stdout)
    assert set(payload) == {"health", "todos"}
    assert isinstance(payload["health"], dict)
    assert isinstance(payload["todos"], list)
