"""Requirements status updates and concurrent persistence."""

import json
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

import bck_nd_hlpr.core.requirements.parser as requirements_parser_module
from bck_nd_hlpr.core.requirements import RequirementsParser
from bck_nd_hlpr.core.utils.file_lock import exclusive_file_lock

def test_update_story_status_json_nested_story(tmp_path: Path):
    req_dir = tmp_path / ".bck-nd" / "requirements"
    req_dir.mkdir(parents=True)
    target = req_dir / "US-001.json"
    target.write_text(
        json.dumps(
            {
                "story": {
                    "id": "US-001",
                    "title": "Checkout",
                    "status": "TODO",
                },
                "open_questions": ["Which payment provider?"],
            }
        ),
        encoding="utf-8",
    )

    assert RequirementsParser.update_story_status(
        tmp_path, "us-001", "in_progress"
    ) is True

    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["story"]["status"] == "IN_PROGRESS"
    assert data["open_questions"] == ["Which payment provider?"]
    assert target.read_text(encoding="utf-8").startswith('{\n  "story"')


def test_update_story_status_root_json(tmp_path: Path):
    req_dir = tmp_path / ".bck-nd" / "requirements"
    req_dir.mkdir(parents=True)
    target = req_dir / "REQ-9.json"
    target.write_text(
        json.dumps({"id": "REQ-9", "title": "Audit", "status": "TESTING"}),
        encoding="utf-8",
    )

    assert RequirementsParser.get_story_status(tmp_path, "REQ-9") == "TESTING"
    assert RequirementsParser.update_story_status(tmp_path, "REQ-9", "done") is True
    assert json.loads(target.read_text(encoding="utf-8"))["status"] == "DONE"


def test_update_story_status_markdown_preserves_existing_content(tmp_path: Path):
    req_dir = tmp_path / ".bck-nd" / "requirements"
    req_dir.mkdir(parents=True)
    target = req_dir / "US-001.md"
    target.write_bytes(
        (
            "# US-001 [TODO] - Checkout\r\n\r\n"
            "## Acceptance Criteria\r\n"
            "- AC01: Existing formatting remains unchanged\r\n"
        ).encode("utf-8")
    )

    assert RequirementsParser.update_story_status(tmp_path, "US-001", "DONE") is True

    content = target.read_bytes().decode("utf-8")
    assert content.startswith("# US-001 [DONE] - Checkout\r\n")
    assert "## Acceptance Criteria\r\n- AC01: Existing formatting remains unchanged" in content


def test_update_story_status_markdown_adds_missing_badge(tmp_path: Path):
    req_dir = tmp_path / ".bck-nd" / "requirements"
    req_dir.mkdir(parents=True)
    target = req_dir / "US-002.md"
    target.write_text(
        "# US-002 - Search\n\n## Business Rules\n- Preserve this section\n",
        encoding="utf-8",
    )

    assert RequirementsParser.update_story_status(
        tmp_path, "US-002", "blocked"
    ) is True
    content = target.read_text(encoding="utf-8")
    assert content.startswith("# US-002 [BLOCKED] - Search\n")
    assert "## Business Rules\n- Preserve this section" in content


@pytest.mark.parametrize(
    ("story_id", "new_status"),
    [("MISSING", "DONE"), ("../US-001", "NOT_A_STATUS")],
)
def test_update_story_status_rejects_missing_or_invalid_input(
    tmp_path: Path,
    story_id: str,
    new_status: str,
):
    assert RequirementsParser.update_story_status(
        tmp_path, story_id, new_status
    ) is False



def test_requirement_status_update_preserves_concurrent_content_and_temp_cleanup(
    tmp_path,
    monkeypatch,
):
    req_dir = tmp_path / ".bck-nd" / "requirements"
    req_dir.mkdir(parents=True)
    target = req_dir / "US-RACE.json"
    target.write_text(
        json.dumps({"story": {"id": "US-RACE", "status": "TODO"}}),
        encoding="utf-8",
    )
    concurrent = b'{"story":{"id":"US-RACE","status":"BLOCKED"}}\n'
    real_chmod = requirements_parser_module.os.chmod
    raced = False

    def race_during_temp_chmod(path, mode):
        nonlocal raced
        real_chmod(path, mode)
        if not raced and str(path).endswith(".tmp"):
            raced = True
            target.write_bytes(concurrent)

    monkeypatch.setattr(
        requirements_parser_module.os,
        "chmod",
        race_during_temp_chmod,
    )

    assert RequirementsParser.update_story_status(
        tmp_path,
        "US-RACE",
        "DONE",
    ) is False
    assert raced is True
    assert target.read_bytes() == concurrent
    assert not list(req_dir.glob(".*.tmp"))


@pytest.mark.parametrize("extension", ["md", "json"])
def test_requirement_status_waits_for_lock_and_preserves_latest_content(
    tmp_path,
    monkeypatch,
    extension,
):
    req_dir = tmp_path / ".bck-nd" / "requirements"
    req_dir.mkdir(parents=True)
    target = req_dir / f"US-LOCK.{extension}"
    if extension == "md":
        original = b"\xef\xbb\xbf# US-LOCK [TODO] - Title\r\n\r\nOriginal body\r\n"
        latest = original + b"Concurrent body\r\n"
    else:
        original = (
            b'{"story":{"id":"US-LOCK","status":"TODO"},'
            b'"custom":{"original":true}}\n'
        )
        latest = (
            b'{"story":{"id":"US-LOCK","status":"BLOCKED"},'
            b'"custom":{"concurrent":true}}\n'
        )
    target.write_bytes(original)
    lock_path = requirements_parser_module._requirements_status_lock_path(req_dir)
    attempted = threading.Event()
    results = []
    real_lock = exclusive_file_lock

    @contextmanager
    def observed_lock(path, *, timeout):
        attempted.set()
        with real_lock(path, timeout=timeout) as descriptor:
            yield descriptor

    monkeypatch.setattr(
        requirements_parser_module,
        "exclusive_file_lock",
        observed_lock,
    )

    def update():
        results.append(
            RequirementsParser.update_story_status(tmp_path, "US-LOCK", "DONE")
        )

    with real_lock(lock_path, timeout=0.2):
        thread = threading.Thread(target=update)
        thread.start()
        assert attempted.wait(1.0)
        assert target.read_bytes() == original
        target.write_bytes(latest)

    thread.join(timeout=2.0)
    assert not thread.is_alive()
    assert results == [True]
    final = target.read_bytes()
    if extension == "md":
        assert final.startswith(b"\xef\xbb\xbf")
        assert b"# US-LOCK [DONE] - Title\r\n" in final
        assert b"Concurrent body\r\n" in final
        assert final.replace(b"\r\n", b"").count(b"\n") == 0
    else:
        data = json.loads(final.decode("utf-8"))
        assert data["story"]["status"] == "DONE"
        assert data["custom"] == {"concurrent": True}
    assert not list(req_dir.glob(".*.tmp"))


def test_two_requirement_status_updates_are_serialized(tmp_path):
    req_dir = tmp_path / ".bck-nd" / "requirements"
    req_dir.mkdir(parents=True)
    target = req_dir / "US-TWO.json"
    target.write_text(
        json.dumps(
            {
                "story": {"id": "US-TWO", "status": "TODO"},
                "custom": {"preserve": True},
            }
        ),
        encoding="utf-8",
    )
    start = threading.Event()
    results = []

    def update(status):
        start.wait(1.0)
        results.append(
            RequirementsParser.update_story_status(tmp_path, "US-TWO", status)
        )

    threads = [
        threading.Thread(target=update, args=("TESTING",)),
        threading.Thread(target=update, args=("DONE",)),
    ]
    for thread in threads:
        thread.start()
    start.set()
    for thread in threads:
        thread.join(timeout=2.0)

    assert not any(thread.is_alive() for thread in threads)
    assert results == [True, True]
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["story"]["status"] in {"TESTING", "DONE"}
    assert data["custom"] == {"preserve": True}
    assert not list(req_dir.glob(".*.tmp"))


def test_requirement_status_lock_timeout_returns_false_without_changes(
    tmp_path,
    monkeypatch,
):
    req_dir = tmp_path / ".bck-nd" / "requirements"
    req_dir.mkdir(parents=True)
    target = req_dir / "US-TIMEOUT.md"
    original = b"# US-TIMEOUT [TODO] - Preserve\r\n\r\nBody\r\n"
    target.write_bytes(original)
    lock_path = requirements_parser_module._requirements_status_lock_path(req_dir)
    monkeypatch.setattr(
        requirements_parser_module,
        "REQUIREMENTS_STATUS_LOCK_TIMEOUT",
        0.02,
    )

    with exclusive_file_lock(lock_path, timeout=0.2):
        result = RequirementsParser.update_story_status(
            tmp_path,
            "US-TIMEOUT",
            "DONE",
        )

    assert result is False
    assert target.read_bytes() == original
    assert not list(req_dir.glob(".*.tmp"))
