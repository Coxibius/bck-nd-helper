"""Tests for deterministic PRD lifecycle, reference, and path validation."""

from pathlib import Path

import pytest

from bck_nd_hlpr.core.product import (
    DiagnosticSeverity,
    ProductCollectionResult,
    ProductDiagnostic,
    ProductDiagnosticCode,
    ProductRequirementDocument,
    ProductStatus,
    ProductValidator,
)


METADATA_FIELDS = [
    "schema_version",
    "id",
    "title",
    "status",
    "owner",
    "target_release",
    "applies_to",
    "requirement_ids",
]

SECTION_FIELDS = [
    "problem_statement",
    "target_users",
    "goals",
    "non_goals",
    "success_metrics",
    "scope",
    "risks",
    "rollout_plan",
    "open_questions",
]


def valid_document(
    *,
    prd_id="PRD-250",
    status=ProductStatus.DRAFT,
    applies_to=None,
    requirement_ids=None,
    source_path=".bck-nd/product/PRD-250.md",
):
    section_markdown = {
        "problem_statement": "A real product problem.",
        "target_users": "Students and educators.",
        "goals": "Preserve product intent.",
        "non_goals": "Do not replace project management.",
        "success_metrics": "Users complete the documented workflow.",
        "scope": "Local files and deterministic validation.",
        "risks": "The template may become too large.",
        "rollout_plan": "Release through three reviewed sprints.",
        "open_questions": "None",
    }
    return ProductRequirementDocument(
        schema_version=1,
        id=prd_id,
        title="PRD Intelligence",
        status=status,
        owner="Product Architect",
        target_release="2.5.0",
        applies_to=list(applies_to if applies_to is not None else ["."]),
        requirement_ids=list(requirement_ids if requirement_ids is not None else []),
        problem_statement=section_markdown["problem_statement"],
        target_users=section_markdown["target_users"],
        goals=section_markdown["goals"],
        non_goals=section_markdown["non_goals"],
        success_metrics=section_markdown["success_metrics"],
        scope=section_markdown["scope"],
        risks=section_markdown["risks"],
        rollout_plan=section_markdown["rollout_plan"],
        open_questions=[],
        source_path=source_path,
        _present_metadata=list(METADATA_FIELDS),
        _present_sections=list(SECTION_FIELDS),
        _section_markdown=section_markdown,
    )


def findings(diagnostics, code):
    return [item for item in diagnostics if item.code == code]


def test_complete_document_is_valid(tmp_path):
    diagnostics = ProductValidator.validate_document(
        valid_document(),
        project_root=tmp_path,
        available_requirement_ids=set(),
    )

    assert diagnostics == []


@pytest.mark.parametrize(
    ("status", "expected_severity"),
    [
        (ProductStatus.DRAFT, DiagnosticSeverity.WARNING),
        (ProductStatus.REVIEW, DiagnosticSeverity.ERROR),
        (ProductStatus.APPROVED, DiagnosticSeverity.ERROR),
        (ProductStatus.SHIPPED, DiagnosticSeverity.ERROR),
        (ProductStatus.ARCHIVED, DiagnosticSeverity.WARNING),
    ],
)
def test_missing_section_severity_follows_lifecycle(status, expected_severity):
    document = valid_document(status=status)
    document.goals = ""
    document._present_sections.remove("goals")
    document._section_markdown.pop("goals")

    diagnostics = ProductValidator.validate_document(document)
    missing = findings(diagnostics, ProductDiagnosticCode.SECTION_MISSING)

    assert len(missing) == 1
    assert missing[0].section == "Goals"
    assert missing[0].severity is expected_severity


def test_unsupported_schema_is_error():
    document = valid_document()
    document.schema_version = 99

    diagnostics = ProductValidator.validate_document(document)

    assert findings(diagnostics, ProductDiagnosticCode.SCHEMA_UNSUPPORTED)[0].severity is DiagnosticSeverity.ERROR


def test_missing_schema_uses_required_metadata_diagnostic():
    document = valid_document()
    document.schema_version = None
    document._present_metadata.remove("schema_version")

    diagnostics = ProductValidator.validate_document(document)

    missing = findings(diagnostics, ProductDiagnosticCode.METADATA_MISSING)
    assert any(item.field == "schema_version" for item in missing)


@pytest.mark.parametrize("prd_id", ["bad id", "../PRD", "_PRD", "PRD/ONE"])
def test_invalid_id_format_is_error(prd_id):
    diagnostics = ProductValidator.validate_document(valid_document(prd_id=prd_id))

    assert findings(diagnostics, ProductDiagnosticCode.ID_INVALID)[0].severity is DiagnosticSeverity.ERROR


def test_missing_id_has_dedicated_error():
    diagnostics = ProductValidator.validate_document(valid_document(prd_id=""))

    assert len(findings(diagnostics, ProductDiagnosticCode.ID_MISSING)) == 1


def test_invalid_status_is_error():
    diagnostics = ProductValidator.validate_document(valid_document(status="ready"))

    assert len(findings(diagnostics, ProductDiagnosticCode.STATUS_INVALID)) == 1


@pytest.mark.parametrize("field_name", ["title", "status", "applies_to", "requirement_ids"])
def test_required_metadata_missing_is_error(field_name):
    document = valid_document()
    document._present_metadata.remove(field_name)
    if field_name == "title":
        document.title = ""
    elif field_name == "status":
        document.status = None
    elif field_name == "applies_to":
        document.applies_to = []

    diagnostics = ProductValidator.validate_document(document)

    assert any(
        item.field == field_name and item.severity is DiagnosticSeverity.ERROR
        for item in findings(diagnostics, ProductDiagnosticCode.METADATA_MISSING)
    )


@pytest.mark.parametrize(
    ("status", "expected_severity"),
    [
        (ProductStatus.DRAFT, DiagnosticSeverity.WARNING),
        (ProductStatus.REVIEW, DiagnosticSeverity.ERROR),
        (ProductStatus.APPROVED, DiagnosticSeverity.ERROR),
        (ProductStatus.SHIPPED, DiagnosticSeverity.ERROR),
        (ProductStatus.ARCHIVED, DiagnosticSeverity.WARNING),
    ],
)
def test_placeholder_section_severity_follows_lifecycle(status, expected_severity):
    document = valid_document(status=status)
    document.success_metrics = "TBD"
    document._section_markdown["success_metrics"] = "TBD"

    diagnostics = ProductValidator.validate_document(document)
    placeholders = findings(diagnostics, ProductDiagnosticCode.SECTION_PLACEHOLDER)

    assert len(placeholders) == 1
    assert placeholders[0].section == "Success Metrics"
    assert placeholders[0].severity is expected_severity


def test_describe_template_line_is_placeholder_without_metric_heuristics():
    document = valid_document()
    document.success_metrics = "Describe how success will be evaluated"
    document._section_markdown["success_metrics"] = document.success_metrics

    diagnostics = ProductValidator.validate_document(document)

    assert len(findings(diagnostics, ProductDiagnosticCode.SECTION_PLACEHOLDER)) == 1

    document.success_metrics = "Customer satisfaction improves after release."
    document._section_markdown["success_metrics"] = document.success_metrics
    assert findings(
        ProductValidator.validate_document(document),
        ProductDiagnosticCode.SECTION_PLACEHOLDER,
    ) == []


def test_requirement_reference_matching_is_case_insensitive():
    document = valid_document(requirement_ids=["us-001"])

    diagnostics = ProductValidator.validate_document(
        document,
        available_requirement_ids={"US-001"},
    )

    assert findings(diagnostics, ProductDiagnosticCode.REQUIREMENT_MISSING) == []


def test_missing_requirement_reference_is_error():
    document = valid_document(requirement_ids=["US-404"])

    diagnostics = ProductValidator.validate_document(
        document,
        available_requirement_ids={"US-001"},
    )
    missing = findings(diagnostics, ProductDiagnosticCode.REQUIREMENT_MISSING)

    assert len(missing) == 1
    assert missing[0].reference == "US-404"
    assert missing[0].severity is DiagnosticSeverity.ERROR


def test_orphan_requirement_is_collection_warning():
    document = valid_document(requirement_ids=["US-001"])

    diagnostics = ProductValidator.validate_collection(
        [document],
        available_requirement_ids={"US-001", "US-002"},
    )
    orphan = findings(diagnostics, ProductDiagnosticCode.REQUIREMENT_ORPHAN)

    assert len(orphan) == 1
    assert orphan[0].reference == "US-002"
    assert orphan[0].severity is DiagnosticSeverity.WARNING


def test_empty_product_collection_does_not_report_orphan_requirements():
    diagnostics = ProductValidator.validate_collection(
        [],
        available_requirement_ids={"US-001"},
    )

    assert diagnostics == []


def test_project_root_dot_path_is_valid(tmp_path):
    diagnostics = ProductValidator.validate_document(
        valid_document(applies_to=["."]),
        project_root=tmp_path,
    )

    assert findings(diagnostics, ProductDiagnosticCode.APPLIES_TO_INVALID) == []
    assert findings(diagnostics, ProductDiagnosticCode.APPLIES_TO_MISSING) == []


@pytest.mark.parametrize("absolute_path", ["/etc/passwd", "C:/Windows/System32", "C:\\Windows"])
def test_absolute_applies_to_path_is_error(absolute_path, tmp_path):
    diagnostics = ProductValidator.validate_document(
        valid_document(applies_to=[absolute_path]),
        project_root=tmp_path,
    )

    invalid = findings(diagnostics, ProductDiagnosticCode.APPLIES_TO_INVALID)
    assert len(invalid) == 1
    assert invalid[0].severity is DiagnosticSeverity.ERROR


@pytest.mark.parametrize(
    "external_uri",
    [
        "file:///C:/Users/Private/secret",
        "file:///etc/passwd",
        "FiLe:///C:/Users/Private/secret",
    ],
    ids=["windows-file-uri", "posix-file-uri", "mixed-case-scheme"],
)
def test_uri_applies_to_path_is_rejected_without_exposure(external_uri, tmp_path):
    diagnostics = ProductValidator.validate_document(
        valid_document(applies_to=[external_uri]),
        project_root=tmp_path,
    )

    invalid = findings(diagnostics, ProductDiagnosticCode.APPLIES_TO_INVALID)
    assert len(invalid) == 1
    payload = invalid[0].to_dict()
    assert payload["reference"] == "<outside-project>"
    assert external_uri not in repr(payload)


@pytest.mark.parametrize("escape_path", ["../outside", "apps/../../outside"])
def test_parent_escape_is_error(escape_path, tmp_path):
    diagnostics = ProductValidator.validate_document(
        valid_document(applies_to=[escape_path]),
        project_root=tmp_path,
    )

    assert len(findings(diagnostics, ProductDiagnosticCode.APPLIES_TO_INVALID)) == 1


def test_safe_missing_applies_to_path_is_warning(tmp_path):
    diagnostics = ProductValidator.validate_document(
        valid_document(applies_to=["apps/api"]),
        project_root=tmp_path,
    )
    missing = findings(diagnostics, ProductDiagnosticCode.APPLIES_TO_MISSING)

    assert len(missing) == 1
    assert missing[0].reference == "apps/api"
    assert missing[0].severity is DiagnosticSeverity.WARNING


def test_safe_existing_applies_to_path_is_valid(tmp_path):
    (tmp_path / "apps" / "api").mkdir(parents=True)

    diagnostics = ProductValidator.validate_document(
        valid_document(applies_to=["apps/api"]),
        project_root=tmp_path,
    )

    assert findings(diagnostics, ProductDiagnosticCode.APPLIES_TO_INVALID) == []
    assert findings(diagnostics, ProductDiagnosticCode.APPLIES_TO_MISSING) == []


@pytest.mark.parametrize(
    ("status", "expected_code", "expected_severity"),
    [
        (ProductStatus.DRAFT, ProductDiagnosticCode.OPEN_QUESTIONS_PRESENT, DiagnosticSeverity.WARNING),
        (ProductStatus.REVIEW, ProductDiagnosticCode.OPEN_QUESTIONS_PRESENT, DiagnosticSeverity.WARNING),
        (ProductStatus.APPROVED, ProductDiagnosticCode.OPEN_QUESTIONS_BLOCKING, DiagnosticSeverity.ERROR),
        (ProductStatus.SHIPPED, ProductDiagnosticCode.OPEN_QUESTIONS_BLOCKING, DiagnosticSeverity.ERROR),
        (ProductStatus.ARCHIVED, None, None),
    ],
)
def test_open_question_policy_for_every_status(status, expected_code, expected_severity):
    document = valid_document(status=status)
    document.open_questions = ["Which draft policy should ship?"]
    document._section_markdown["open_questions"] = "- Which draft policy should ship?"

    diagnostics = ProductValidator.validate_document(document)

    question_findings = [
        item
        for item in diagnostics
        if item.code in {
            ProductDiagnosticCode.OPEN_QUESTIONS_PRESENT,
            ProductDiagnosticCode.OPEN_QUESTIONS_BLOCKING,
        }
    ]
    if expected_code is None:
        assert question_findings == []
    else:
        assert len(question_findings) == 1
        assert question_findings[0].code is expected_code
        assert question_findings[0].severity is expected_severity


def test_collection_detects_duplicate_ids_case_insensitively():
    first = valid_document(prd_id="PRD-AUTH", source_path="first.md")
    second = valid_document(prd_id="prd-auth", source_path="second.md")

    diagnostics = ProductValidator.validate_collection([first, second])
    duplicates = findings(diagnostics, ProductDiagnosticCode.ID_DUPLICATE)

    assert len(duplicates) == 1
    assert duplicates[0].source_path == "second.md"
    assert duplicates[0].reference == "first.md"


def test_collection_preserves_existing_parse_diagnostics_without_duplicates():
    parse_error = ProductDiagnostic(
        code=ProductDiagnosticCode.PARSE_ERROR,
        severity=DiagnosticSeverity.ERROR,
        message="Broken YAML.",
        source_path="broken.md",
        field="front_matter",
    )
    collection = ProductCollectionResult(
        documents=[valid_document()],
        diagnostics=[parse_error, parse_error],
    )

    diagnostics = ProductValidator.validate_collection(collection)

    assert findings(diagnostics, ProductDiagnosticCode.PARSE_ERROR) == [parse_error]
