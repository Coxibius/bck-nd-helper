"""Run the repository test suite once and keep readable, structured reports."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_console(stream, text: str, *, end: str = "\n", flush: bool = False) -> None:
    """Write without letting a limited terminal encoding abort report creation."""
    payload = text + end
    try:
        stream.write(payload)
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "ascii"
        safe_payload = payload.encode(encoding, errors="backslashreplace").decode(encoding)
        stream.write(safe_payload)
    if flush:
        stream.flush()


def _outside_project(path: Path) -> bool:
    resolved = path.resolve()
    return resolved != PROJECT_ROOT and PROJECT_ROOT not in resolved.parents


def _create_report_dir(requested: Optional[str]) -> Path:
    if requested is None:
        temporary_root = Path(tempfile.gettempdir()).resolve()
        if not _outside_project(temporary_root):
            raise ValueError("The system temporary directory is inside the repository.")
        return Path(tempfile.mkdtemp(prefix="bck-nd-qa-", dir=temporary_root))

    destination = Path(requested).expanduser().resolve()
    if not _outside_project(destination):
        raise ValueError("QA reports must be outside the repository.")
    destination.mkdir(parents=True, exist_ok=False)
    return destination


def _junit_counts(report: Path) -> dict[str, int]:
    root = ET.parse(report).getroot()
    if root.tag == "testsuite":
        suites = [root]
    elif root.tag == "testsuites":
        suites = list(root.findall("testsuite"))
    else:
        raise ValueError("JUnit report has an unsupported root element.")
    if not suites:
        raise ValueError("JUnit report has no test suite.")

    totals = {"tests": 0, "failed": 0, "errors": 0, "skipped": 0}
    attributes = (
        ("tests", "tests"),
        ("failed", "failures"),
        ("errors", "errors"),
        ("skipped", "skipped"),
    )
    for suite in suites:
        for key, attribute in attributes:
            value = int(suite.attrib[attribute])
            if value < 0:
                raise ValueError("JUnit report has negative counts.")
            totals[key] += value
    totals["passed"] = (
        totals["tests"] - totals["failed"] - totals["errors"] - totals["skipped"]
    )
    if totals["passed"] < 0:
        raise ValueError("JUnit report has inconsistent counts.")
    return totals


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run Backend Helper QA once and save reports.")
    parser.add_argument(
        "--report-dir",
        help="New, unused results directory outside the repository (default: system temp).",
    )
    args = parser.parse_args(argv)

    try:
        report_dir = _create_report_dir(args.report_dir)
    except (OSError, ValueError) as exc:
        _write_console(sys.stderr, f"Cannot create QA report directory: {exc}")
        return 2

    log_path = report_dir / "qa.log"
    junit_path = report_dir / "junit.xml"
    summary_path = report_dir / "summary.json"
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--basetemp",
        str(report_dir / "basetemp"),
        "-o",
        f"cache_dir={report_dir / 'pytest-cache'}",
        f"--junitxml={junit_path}",
    ]
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    environment.pop("PYTEST_ADDOPTS", None)
    _write_console(sys.stdout, f"QA results: {report_dir}", flush=True)

    pytest_exit_code: Optional[int] = None
    launch_error: Optional[str] = None
    with log_path.open("w", encoding="utf-8", newline="\n") as log:
        log.write(f"Interpreter: {sys.executable}\nProject: {PROJECT_ROOT}\n\n")
        try:
            completed = subprocess.run(
                command,
                cwd=PROJECT_ROOT,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            pytest_exit_code = completed.returncode
            output = completed.stdout or ""
        except OSError as exc:
            launch_error = f"pytest could not start: {exc}"
            output = launch_error + "\n"
        log.write(output)
        _write_console(
            sys.stdout,
            output,
            end="" if output.endswith("\n") else "\n",
        )

    counts: Optional[dict[str, int]] = None
    report_error: Optional[str] = None
    try:
        counts = _junit_counts(junit_path)
    except (OSError, ValueError, KeyError, ET.ParseError) as exc:
        report_error = f"JUnit report unavailable or invalid: {exc}"
        with log_path.open("a", encoding="utf-8", newline="\n") as log:
            log.write(report_error + "\n")
        _write_console(sys.stderr, report_error)

    if pytest_exit_code is None:
        exit_code = 2
        status = "error"
    elif pytest_exit_code != 0:
        exit_code = pytest_exit_code
        status = "failed" if counts is not None and counts["failed"] else "error"
    elif counts is None or counts["failed"] or counts["errors"]:
        exit_code = 2
        status = "error"
    else:
        exit_code = 0
        status = "passed"

    summary = {
        "status": status,
        "exit_code": exit_code,
        "pytest_exit_code": pytest_exit_code,
        "counts": counts,
        "diagnostic": launch_error or report_error,
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_console(sys.stdout, f"QA {status}; reports: {report_dir}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
