"""Focused regressions for explicit Requirements collection scopes."""

import json
import os
from pathlib import Path
import shlex

from typer.testing import CliRunner

import bck_nd_hlpr.core.requirements.locations as locations_module
from bck_nd_hlpr.cli.cli import app
from bck_nd_hlpr.core.requirements import discover_requirements_locations


runner = CliRunner()


def _story(project: Path, story_id: str, *, status: str = "TODO") -> None:
    directory = project / ".bck-nd" / "requirements"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{story_id}.json").write_text(
        json.dumps(
            {
                "story": {
                    "id": story_id,
                    "status": status,
                    "title": f"Story {story_id}",
                    "role": "user",
                    "want": f"complete {story_id}",
                    "benefit": "receive value",
                }
            }
        ),
        encoding="utf-8",
    )


def test_discovery_keeps_current_and_nested_collections_independent(tmp_path):
    _story(tmp_path, "HU05")
    _story(tmp_path, "HU06")

    current_only = discover_requirements_locations(tmp_path)

    assert current_only.selected_location is not None
    assert current_only.selected_location.relative_root == "."
    assert current_only.selected_location.ids == ("HU05", "HU06")
    assert current_only.nested_locations == ()
    assert current_only.conflicting_ids == ()

    nested = tmp_path / "Sistemas1-Equipo321-VidaSalud"
    for story_id in ("HU01", "HU02", "HU03", "HU04", "HU05", "HU06", "HU07"):
        _story(nested, story_id, status="DONE")

    report = discover_requirements_locations(tmp_path)

    assert report.selected_location is not None
    assert report.selected_location.ids == ("HU05", "HU06")
    assert len(report.nested_locations) == 1
    assert report.nested_locations[0].ids == (
        "HU01", "HU02", "HU03", "HU04", "HU05", "HU06", "HU07"
    )
    assert report.conflicting_ids == ("HU05", "HU06")
    assert report.selected_location.result is not report.nested_locations[0].result


def test_locations_cli_reports_conflicts_and_copyable_nested_command(tmp_path):
    project = tmp_path / "Vida Salud"
    nested = project / "Sistemas1-Equipo321-VidaSalud"
    _story(project, "HU05")
    _story(project, "HU06")
    for story_id in ("HU01", "HU05", "HU06", "HU07"):
        _story(nested, story_id, status="DONE")
    quoted_nested = (
        f'"{nested}"' if os.name == "nt" else shlex.quote(str(nested))
    )

    result = runner.invoke(app, ["req", "locations", str(project)])

    assert result.exit_code == 0, result.exception
    for expected in (
        "Requirements Locations (2)",
        "CURRENT",
        "Root: .",
        "Source: .bck-nd/requirements",
        "Stories: 2",
        "NESTED",
        "Root: Sistemas1-Equipo321-VidaSalud",
        "Stories: 4",
        "Conflicting IDs: HU05, HU06",
        "Collections were not merged.",
        f"bck-nd req list {quoted_nested}",
    ):
        assert expected in result.stdout


def test_discovery_is_bounded_and_skips_reparse_directories(tmp_path, monkeypatch):
    _story(tmp_path, "HU05")
    unsafe = tmp_path / "linked-project"
    _story(unsafe, "HU-SECRET")
    (tmp_path / "ordinary" / "child").mkdir(parents=True)
    unsafe_state = (unsafe.lstat().st_dev, unsafe.lstat().st_ino)
    original = locations_module._is_link_or_reparse

    monkeypatch.setattr(
        locations_module,
        "_is_link_or_reparse",
        lambda value: (value.st_dev, value.st_ino) == unsafe_state or original(value),
    )

    safe_report = discover_requirements_locations(tmp_path)
    bounded_report = discover_requirements_locations(tmp_path, max_directories=1)

    assert safe_report.nested_locations == ()
    assert "HU-SECRET" not in safe_report.conflicting_ids
    assert bounded_report.selected_location is not None
    assert bounded_report.truncated is True
