"""Small simulations of the QA runner; these never start another pytest suite."""

import json
import subprocess
import sys
from pathlib import Path

from scripts import run_qa


def _junit_path(command):
    return Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junitxml=")))


def test_qa_runner_uses_its_interpreter_repo_root_and_structured_success(
    tmp_path, monkeypatch
):
    foreign_cwd = tmp_path / "another directory"
    foreign_cwd.mkdir()
    monkeypatch.chdir(foreign_cwd)
    report_dir = tmp_path / "qa success"
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        _junit_path(command).write_text(
            '<testsuites><testsuite tests="3" failures="0" errors="0" skipped="1"/>'
            '</testsuites>',
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="2 passed, 1 skipped\n")

    monkeypatch.setattr(run_qa.subprocess, "run", fake_run)

    assert run_qa.main(["--report-dir", str(report_dir)]) == 0
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command[:3] == [sys.executable, "-m", "pytest"]
    assert kwargs["cwd"] == run_qa.PROJECT_ROOT
    assert command[command.index("--basetemp") + 1] == str(report_dir / "basetemp")
    assert f"cache_dir={report_dir / 'pytest-cache'}" in command
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["env"]["PYTHONIOENCODING"] == "utf-8"
    assert "2 passed, 1 skipped" in (report_dir / "qa.log").read_text(encoding="utf-8")
    assert json.loads((report_dir / "summary.json").read_text(encoding="utf-8")) == {
        "status": "passed",
        "exit_code": 0,
        "pytest_exit_code": 0,
        "counts": {"tests": 3, "failed": 0, "errors": 0, "skipped": 1, "passed": 2},
        "diagnostic": None,
    }


def test_qa_runner_preserves_pytest_failure_without_retry(tmp_path, monkeypatch):
    report_dir = tmp_path / "qa failed"
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        _junit_path(command).write_text(
            '<testsuites><testsuite tests="2" failures="1" errors="0" skipped="0"/>'
            '</testsuites>',
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 1, stdout="one assertion failed\n")

    monkeypatch.setattr(run_qa.subprocess, "run", fake_run)

    assert run_qa.main(["--report-dir", str(report_dir)]) == 1
    assert len(calls) == 1
    summary = json.loads((report_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "failed"
    assert summary["exit_code"] == summary["pytest_exit_code"] == 1
    assert summary["counts"] == {
        "tests": 2, "failed": 1, "errors": 0, "skipped": 0, "passed": 1
    }
    assert "one assertion failed" in (report_dir / "qa.log").read_text(encoding="utf-8")


def test_qa_runner_keeps_collection_error_without_invented_counts(tmp_path, monkeypatch):
    report_dir = tmp_path / "qa collection error"
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 5, stdout="no tests collected\n")

    monkeypatch.setattr(run_qa.subprocess, "run", fake_run)

    assert run_qa.main(["--report-dir", str(report_dir)]) == 5
    assert len(calls) == 1
    summary = json.loads((report_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "error"
    assert summary["counts"] is None
    assert summary["pytest_exit_code"] == summary["exit_code"] == 5
    assert "no tests collected" in (report_dir / "qa.log").read_text(encoding="utf-8")


def test_qa_runner_reports_subprocess_launch_error(tmp_path, monkeypatch):
    report_dir = tmp_path / "qa launch error"

    def unavailable(_command, **_kwargs):
        raise OSError("simulated pytest launch failure")

    monkeypatch.setattr(run_qa.subprocess, "run", unavailable)

    assert run_qa.main(["--report-dir", str(report_dir)]) == 2
    summary = json.loads((report_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "error"
    assert summary["pytest_exit_code"] is None
    assert summary["counts"] is None
    assert "simulated pytest launch failure" in (
        report_dir / "qa.log"
    ).read_text(encoding="utf-8")


def test_qa_runner_never_overwrites_existing_report_directory(tmp_path, monkeypatch):
    report_dir = tmp_path / "existing"
    report_dir.mkdir()
    sentinel = report_dir / "keep.txt"
    sentinel.write_text("original", encoding="utf-8")

    def unexpected_run(_command, **_kwargs):
        raise AssertionError("pytest must not run for an existing report directory")

    monkeypatch.setattr(run_qa.subprocess, "run", unexpected_run)

    assert run_qa.main(["--report-dir", str(report_dir)]) == 2
    assert sentinel.read_text(encoding="utf-8") == "original"
