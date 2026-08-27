"""CLI coverage for the Sprint 2 local PRD workflow."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from bck_nd_hlpr.cli.cli import app
from bck_nd_hlpr.core.product import (
    ProductParser,
    ProductRequirementDocument,
    ProductService,
    ProductValidationReport,
)


runner = CliRunner()


def complete_prd(
    product_id="PRD-TEST",
    *,
    status="DRAFT",
    requirements=None,
    open_questions="None",
    newline="\n",
):
    requirement_lines = "requirement_ids: []"
    if requirements:
        requirement_lines = "requirement_ids:\n" + "\n".join(
            f"  - {item}" for item in requirements
        )
    content = f"""---
schema_version: 1
id: {product_id}
title: Product intent — Salud
status: {status} # keep lifecycle note
owner: Equipo Ñ
target_release: 2.5.0
applies_to:
  - .
{requirement_lines}
custom_flag: keep-me
---

# {product_id} — Product intent

## Problem Statement
Agents need confirmed product context.

## Target Users
Students and educators.

## Goals
Preserve reviewed product intent.

## Non-Goals
Do not invent business decisions.

## Success Metrics
Users complete the documented workflow.

## Scope
Local product documents.

## Risks
Incorrect assumptions may be propagated.

## Rollout Plan
Release after deterministic verification.

## Open Questions
- {open_questions}
"""
    return content.replace("\n", newline)


def write_prd(project: Path, filename: str, content: str) -> Path:
    directory = project / ".bck-nd" / "product"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_text(content, encoding="utf-8", newline="")
    return path


def write_requirement(project: Path, story_id: str) -> None:
    directory = project / ".bck-nd" / "requirements"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{story_id}.md").write_text(
        f"# {story_id} [TODO] - Story\n\n- **Role**: User\n",
        encoding="utf-8",
    )


def invoke(*arguments):
    return runner.invoke(app, ["prd", *map(str, arguments)])


def test_prd_group_and_init_help_expose_local_workflow():
    group = invoke("--help")
    command = invoke("init", "--help")

    assert group.exit_code == 0
    assert all(name in group.stdout for name in ("init", "list", "validate", "status"))
    assert command.exit_code == 0
    assert "--path" in command.stdout
    assert "-p" in command.stdout
    assert "Defaults to PRD" in command.stdout


@pytest.mark.parametrize("path_flag", ["--path", "-p"])
def test_prd_init_creates_default_template_with_path_alias(tmp_path, path_flag):
    result = invoke("init", path_flag, tmp_path)
    target = tmp_path / ".bck-nd" / "product" / "PRD.md"

    assert result.exit_code == 0, result.output
    assert ".bck-nd/product/PRD.md" in result.stdout
    assert target.is_file()
    parsed = ProductParser.load_from_directory(tmp_path)
    assert [document.id for document in parsed.documents] == ["PRD"]
    assert parsed.diagnostics == []


def test_prd_init_creates_explicit_uppercase_id(tmp_path):
    result = invoke("init", "prd-auth", "--path", tmp_path)

    assert result.exit_code == 0, result.output
    assert (tmp_path / ".bck-nd" / "product" / "PRD-AUTH.md").is_file()


def test_prd_init_invalid_id_returns_usage_error_without_creating_storage(tmp_path):
    result = invoke("init", "../unsafe", "--path", tmp_path)

    assert result.exit_code == 2
    assert "PRD_ID" in result.stdout
    assert not (tmp_path / ".bck-nd").exists()


def test_prd_init_second_attempt_does_not_overwrite(tmp_path):
    first = invoke("init", "PRD-AUTH", "--path", tmp_path)
    target = tmp_path / ".bck-nd" / "product" / "PRD-AUTH.md"
    target.write_text(target.read_text(encoding="utf-8") + "human edit\n", encoding="utf-8")
    edited = target.read_bytes()
    second = invoke("init", "prd-auth", "-p", tmp_path)

    assert first.exit_code == 0
    assert second.exit_code == 1
    assert target.read_bytes() == edited


def test_prd_init_template_is_parseable_and_has_expected_warnings(tmp_path):
    assert invoke("init", "--path", tmp_path).exit_code == 0

    result = invoke("validate", "--path", tmp_path)

    assert result.exit_code == 0
    assert "warning(s)" in result.stdout
    assert "0 error(s)" in result.stdout


@pytest.mark.parametrize("with_empty_directory", [False, True])
def test_prd_list_handles_absent_or_empty_directory(tmp_path, with_empty_directory):
    if with_empty_directory:
        (tmp_path / ".bck-nd" / "product").mkdir(parents=True)

    result = invoke("list", "--path", tmp_path)

    assert result.exit_code == 0
    assert "No product requirements documents found" in result.stdout


def test_prd_list_shows_one_document_and_diagnostic_summary(tmp_path):
    write_prd(tmp_path, "PRD-A.md", complete_prd("PRD-A"))

    result = invoke("list", "-p", tmp_path)

    assert result.exit_code == 0, result.output
    for heading in ("ID", "Title", "Status", "Applies To", "Requirements", "Diagnostics"):
        assert heading in result.stdout
    assert "PRD-A" in result.stdout
    assert "0E / 0W" in result.stdout


def test_prd_list_orders_multiple_documents_deterministically(tmp_path):
    write_prd(tmp_path, "b.md", complete_prd("PRD-B"))
    write_prd(tmp_path, "A.md", complete_prd("PRD-A"))

    result = invoke("list", "--path", tmp_path)

    assert result.exit_code == 0
    assert result.stdout.index("PRD-A") < result.stdout.index("PRD-B")


def test_prd_list_keeps_partial_document_and_summarizes_error(tmp_path):
    content = complete_prd("PRD-PARTIAL").replace(
        "applies_to:\n  - .",
        "applies_to:\n  nested: invalid",
    )
    write_prd(tmp_path, "partial.md", content)

    result = invoke("list", "--path", tmp_path)

    assert result.exit_code == 0
    assert "PRD-PARTIAL" in result.stdout
    assert "2E / 0W" in result.stdout


def test_prd_validate_valid_document_returns_zero(tmp_path):
    write_prd(tmp_path, "PRD.md", complete_prd("PRD"))

    result = invoke("validate", "--path", tmp_path)

    assert result.exit_code == 0, result.output
    assert "0 error(s)" in result.stdout


def test_prd_validate_warning_only_document_returns_zero(tmp_path):
    assert invoke("init", "--path", tmp_path).exit_code == 0

    result = invoke("validate", "PRD", "--path", tmp_path)

    assert result.exit_code == 0
    assert "WARNING" in result.stdout


def test_prd_validate_document_with_errors_returns_one(tmp_path):
    content = complete_prd("PRD-BAD").replace(
        "title: Product intent — Salud",
        "title:",
    )
    write_prd(tmp_path, "bad.md", content)

    result = invoke("validate", "--path", tmp_path)

    assert result.exit_code == 1
    assert "PRD_METADATA_MISSING" in result.stdout
    assert "1 error(s)" in result.stdout


def test_prd_validate_selects_id_case_insensitively(tmp_path):
    write_prd(tmp_path, "one.md", complete_prd("PRD-ONE"))
    write_prd(
        tmp_path,
        "two.md",
        complete_prd("PRD-TWO").replace("title: Product intent — Salud", "title:"),
    )

    result = invoke("validate", "prd-one", "--path", tmp_path)

    assert result.exit_code == 0
    assert "0 error(s)" in result.stdout
    assert "PRD-TWO" not in result.stdout


def test_prd_validate_missing_id_returns_one(tmp_path):
    write_prd(tmp_path, "PRD.md", complete_prd("PRD"))

    result = invoke("validate", "PRD-404", "--path", tmp_path)

    assert result.exit_code == 1
    assert "not found" in result.stdout


def test_prd_validate_without_documents_returns_zero_in_human_and_json(tmp_path):
    human = invoke("validate", "--path", tmp_path)
    machine = invoke("validate", "--json", "--path", tmp_path)
    payload = json.loads(machine.stdout)

    assert human.exit_code == 0
    assert "No product requirements documents found" in human.stdout
    assert machine.exit_code == 0
    assert payload["valid"] is True
    assert payload["summary"] == {
        "documents": 0,
        "errors": 0,
        "warnings": 0,
        "info": 0,
    }


def test_prd_validate_integrates_existing_and_missing_requirements(tmp_path):
    write_prd(
        tmp_path,
        "PRD.md",
        complete_prd("PRD", requirements=["US-001", "US-404"]),
    )
    write_requirement(tmp_path, "US-001")

    result = invoke("validate", "--path", tmp_path)

    assert result.exit_code == 1
    assert "US-404" in result.stdout
    assert "US-001" not in result.stdout


def test_prd_validate_reports_orphan_requirement_for_full_collection(tmp_path):
    write_prd(tmp_path, "PRD.md", complete_prd("PRD"))
    write_requirement(tmp_path, "US-ORPHAN")

    result = invoke("validate", "--path", tmp_path)

    assert result.exit_code == 0
    assert "PRD_REQUIREMENT_ORPHAN" in result.stdout
    assert "US-ORPHAN" in result.stdout


def test_prd_validate_json_is_pure_valid_deterministic_and_relative(tmp_path):
    write_prd(tmp_path, "b.md", complete_prd("PRD-B"))
    write_prd(tmp_path, "A.md", complete_prd("PRD-A"))

    first = invoke("validate", "--json", "--path", tmp_path)
    second = invoke("validate", "--json", "--path", tmp_path)
    payload = json.loads(first.stdout)

    assert first.exit_code == 0
    assert first.stdout == second.stdout
    assert first.stdout.lstrip().startswith("{")
    assert first.stdout.rstrip().endswith("}")
    assert payload["schema_version"] == 1
    assert payload["valid"] is True
    assert [document["id"] for document in payload["documents"]] == ["PRD-A", "PRD-B"]
    assert all(
        document["source_path"].startswith(".bck-nd/product/")
        and not Path(document["source_path"]).is_absolute()
        for document in payload["documents"]
    )


def test_prd_validate_json_error_contains_no_additional_text(tmp_path):
    content = complete_prd("PRD-BAD").replace(
        "title: Product intent — Salud",
        "title:",
    )
    write_prd(tmp_path, "bad.md", content)

    result = invoke("validate", "--json", "--path", tmp_path)
    payload = json.loads(result.stdout)

    assert result.exit_code == 1
    assert payload["valid"] is False
    assert payload["summary"]["errors"] == 1
    assert "Summary:" not in result.stdout


@pytest.mark.parametrize(
    "external_uri",
    [
        "file:///C:/Users/Private/secret",
        "file:///etc/passwd",
        "FiLe:///C:/Users/Private/secret",
    ],
)
def test_prd_validate_json_redacts_uri_paths_as_strict_json(tmp_path, external_uri):
    content = complete_prd("PRD-URI").replace(
        "applies_to:\n  - .",
        f"applies_to:\n  - {external_uri}",
    )
    write_prd(tmp_path, "PRD-URI.md", content)

    result = invoke("validate", "--json", "--path", tmp_path)
    payload = json.loads(result.stdout)

    assert result.exit_code == 1
    assert external_uri not in result.stdout
    assert payload["documents"][0]["applies_to"] == ["<outside-project>"]
    assert payload["diagnostics"][0]["reference"] == "<outside-project>"


def test_prd_validate_controls_serialization_error(tmp_path, monkeypatch):
    document = ProductRequirementDocument(id="PRD-CYCLE")
    cyclic = {}
    cyclic["self"] = cyclic
    document.extra_metadata = cyclic
    report = ProductValidationReport(documents=[document])
    monkeypatch.setattr(
        ProductService,
        "validate_documents",
        lambda self, product_id=None: report,
    )

    result = invoke("validate", "--json", "--path", tmp_path)
    payload = json.loads(result.stdout)

    assert result.exit_code == 1
    assert payload["valid"] is False
    assert payload["diagnostics"][0]["code"] == "PRD_OPERATION_ERROR"


@pytest.mark.parametrize("yaml_number", [".nan", ".inf", "-.inf"])
def test_prd_validate_json_rejects_non_finite_yaml_as_strict_json(
    tmp_path,
    yaml_number,
):
    content = complete_prd("PRD-NUMBER").replace(
        "custom_flag: keep-me",
        f"custom_number: {yaml_number}",
    )
    write_prd(tmp_path, "PRD-NUMBER.md", content)

    result = invoke("validate", "--json", "--path", tmp_path)
    payload = json.loads(result.stdout)

    assert result.exit_code == 1
    assert payload["valid"] is False
    assert payload["diagnostics"][0]["code"] == "PRD_OPERATION_ERROR"
    json.dumps(payload, allow_nan=False)
    assert "NaN" not in result.stdout
    assert "Infinity" not in result.stdout


@pytest.mark.parametrize("new_status", ["DRAFT", "REVIEW", "APPROVED", "SHIPPED", "ARCHIVED"])
def test_prd_status_accepts_every_lifecycle_state(tmp_path, new_status):
    starting_status = "REVIEW" if new_status == "DRAFT" else "DRAFT"
    write_prd(tmp_path, "feature.md", complete_prd("PRD-FEATURE", status=starting_status))

    result = invoke("status", "prd-feature", new_status.lower(), "--path", tmp_path)

    assert result.exit_code == 0, result.output
    assert f"status: {new_status}" in (
        tmp_path / ".bck-nd" / "product" / "feature.md"
    ).read_text(encoding="utf-8")


def test_prd_status_invalid_status_returns_usage_error(tmp_path):
    write_prd(tmp_path, "PRD.md", complete_prd("PRD"))

    result = invoke("status", "PRD", "READY", "--path", tmp_path)

    assert result.exit_code == 2
    assert "STATUS" in result.stdout


def test_prd_status_missing_id_returns_one(tmp_path):
    result = invoke("status", "PRD-404", "REVIEW", "--path", tmp_path)

    assert result.exit_code == 1
    assert "not found" in result.stdout


def test_prd_status_same_state_is_successful_noop(tmp_path):
    target = write_prd(tmp_path, "custom.md", complete_prd("PRD-AUTH"))
    original = target.read_bytes()

    result = invoke("status", "prd-auth", "draft", "-p", tmp_path)

    assert result.exit_code == 0
    assert "already DRAFT" in result.stdout
    assert target.read_bytes() == original


def test_prd_status_blocked_transition_preserves_source(tmp_path):
    target = write_prd(
        tmp_path,
        "PRD.md",
        complete_prd("PRD", open_questions="Who approves launch?"),
    )
    original = target.read_bytes()

    result = invoke("status", "PRD", "APPROVED", "--path", tmp_path)

    assert result.exit_code == 1
    assert "blocked" in result.stdout
    assert "PRD_OPEN_QUESTIONS_BLOCKING" in result.stdout
    assert target.read_bytes() == original


def test_prd_status_missing_requirement_blocks_review(tmp_path):
    target = write_prd(
        tmp_path,
        "PRD.md",
        complete_prd("PRD", requirements=["US-404"]),
    )

    result = invoke("status", "PRD", "REVIEW", "--path", tmp_path)

    assert result.exit_code == 1
    assert "PRD_REQUIREMENT_MISSING" in result.stdout
    assert "status: DRAFT" in target.read_text(encoding="utf-8")


def test_prd_status_archives_incomplete_document(tmp_path):
    write_prd(
        tmp_path,
        "history.md",
        """---
schema_version: 1
id: PRD-HISTORY
title:
status: DRAFT
applies_to:
  - .
requirement_ids: []
---
# Historical notes
""",
    )

    result = invoke("status", "PRD-HISTORY", "ARCHIVED", "--path", tmp_path)

    assert result.exit_code == 0
    assert "status: ARCHIVED" in (
        tmp_path / ".bck-nd" / "product" / "history.md"
    ).read_text(encoding="utf-8")


def test_prd_status_preserves_unicode_comments_metadata_body_bom_and_crlf(tmp_path):
    text = complete_prd("PRD-PRESERVE", newline="\r\n")
    target = write_prd(tmp_path, "preserve.md", text)
    target.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
    original_body = text.split("---\r\n", 2)[2]

    result = invoke("status", "prd-preserve", "REVIEW", "--path", tmp_path)
    updated = target.read_bytes()
    decoded = updated[3:].decode("utf-8")

    assert result.exit_code == 0, result.output
    assert updated.startswith(b"\xef\xbb\xbf")
    assert "status: REVIEW # keep lifecycle note\r\n" in decoded
    assert "custom_flag: keep-me\r\n" in decoded
    assert "Equipo Ñ" in decoded
    assert decoded.split("---\r\n", 2)[2] == original_body
    assert "\n" not in decoded.replace("\r\n", "")
    assert list(target.parent.glob("*.tmp")) == []
