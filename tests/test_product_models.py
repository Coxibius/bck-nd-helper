"""Tests for PRD Intelligence domain models."""

from pathlib import Path

import pytest

from bck_nd_hlpr.core.product import (
    DiagnosticSeverity,
    ProductCollectionResult,
    ProductDiagnostic,
    ProductDiagnosticCode,
    ProductParseResult,
    ProductRequirementDocument,
    ProductSerializationError,
    ProductStatus,
)


def test_product_enums_expose_stable_values():
    assert [status.value for status in ProductStatus] == [
        "DRAFT",
        "REVIEW",
        "APPROVED",
        "SHIPPED",
        "ARCHIVED",
    ]
    assert [severity.value for severity in DiagnosticSeverity] == [
        "INFO",
        "WARNING",
        "ERROR",
    ]
    assert ProductDiagnosticCode.PARSE_ERROR.value == "PRD_PARSE_ERROR"


def test_product_document_defaults_are_independent_and_serializable():
    first = ProductRequirementDocument()
    second = ProductRequirementDocument()
    first.applies_to.append(".")

    assert second.applies_to == []
    assert first.to_dict()["status"] == ""
    assert first.to_dict()["source_path"] == ""
    assert first.to_dict()["open_questions"] == []


def test_product_document_to_dict_preserves_fields_and_extra_data_deterministically():
    document = ProductRequirementDocument(
        schema_version=1,
        id="PRD-UNICODE",
        title="Salud y atención",
        status=ProductStatus.REVIEW,
        owner="Equipo ñ",
        target_release="2.5.0",
        applies_to=[".", "apps/api"],
        requirement_ids=["US-002", "US-001"],
        problem_statement="Problema",
        target_users="Usuarios",
        goals="Metas",
        non_goals="No metas",
        success_metrics="Métricas",
        scope="Alcance",
        risks="Riesgos",
        rollout_plan="Despliegue",
        open_questions=["¿Pregunta?"],
        source_path=Path(".bck-nd/product/PRD-UNICODE.md"),
        extra_metadata={"zeta": 2, "alpha": {"b": 2, "a": 1}},
        extra_sections={"Dependencies": "### Internal\nKeep Markdown"},
    )

    serialized = document.to_dict()

    assert serialized["status"] == "REVIEW"
    assert serialized["source_path"] == ".bck-nd/product/PRD-UNICODE.md"
    assert list(serialized["extra_metadata"]) == ["alpha", "zeta"]
    assert list(serialized["extra_metadata"]["alpha"]) == ["a", "b"]
    assert serialized["extra_sections"]["Dependencies"].startswith("### Internal")


def test_diagnostic_to_dict_has_stable_optional_shape():
    diagnostic = ProductDiagnostic(
        code=ProductDiagnosticCode.REQUIREMENT_MISSING,
        severity=DiagnosticSeverity.ERROR,
        message="Missing reference.",
        source_path=Path(".bck-nd/product/PRD.md"),
        field="requirement_ids",
        reference="US-404",
    )

    assert diagnostic.to_dict() == {
        "code": "PRD_REQUIREMENT_MISSING",
        "severity": "ERROR",
        "message": "Missing reference.",
        "source_path": ".bck-nd/product/PRD.md",
        "field": "requirement_ids",
        "section": None,
        "reference": "US-404",
    }


def test_parse_and_collection_results_preserve_order_and_diagnostics():
    first = ProductRequirementDocument(id="PRD-B")
    second = ProductRequirementDocument(id="PRD-A")
    warning = ProductDiagnostic(
        code=ProductDiagnosticCode.OPEN_QUESTIONS_PRESENT,
        severity=DiagnosticSeverity.WARNING,
        message="Questions remain.",
    )

    parse_result = ProductParseResult(document=first, diagnostics=[warning])
    collection = ProductCollectionResult(
        documents=[first, second],
        diagnostics=[warning],
        source_directory=Path(".bck-nd/product"),
    )

    assert parse_result.has_errors is False
    assert [item["id"] for item in collection.to_dict()["documents"]] == [
        "PRD-B",
        "PRD-A",
    ]
    assert collection.to_dict()["source_directory"] == ".bck-nd/product"


@pytest.mark.parametrize("container_kind", ["mapping", "list"])
def test_product_serialization_rejects_cycles_without_recursion_error(container_kind):
    document = ProductRequirementDocument()
    if container_kind == "mapping":
        cyclic = {}
        cyclic["self"] = cyclic
    else:
        cyclic = []
        cyclic.append(cyclic)
    document.extra_metadata = {"cyclic": cyclic}

    with pytest.raises(ProductSerializationError, match="cyclic"):
        document.to_dict()


def test_product_serialization_rejects_excessive_depth_deterministically():
    nested = {}
    cursor = nested
    for _ in range(70):
        child = {}
        cursor["child"] = child
        cursor = child
    document = ProductRequirementDocument(extra_metadata=nested)

    with pytest.raises(ProductSerializationError, match="maximum serialization depth"):
        document.to_dict()


def test_product_serialization_allows_shared_non_cyclic_values():
    shared = {"value": [1, 2]}
    document = ProductRequirementDocument(
        extra_metadata={"second": shared, "first": shared}
    )

    assert document.to_dict()["extra_metadata"] == {
        "first": {"value": [1, 2]},
        "second": {"value": [1, 2]},
    }


@pytest.mark.parametrize(
    "unsupported_value",
    [
        {"alpha", "beta"},
        frozenset({"alpha", "beta"}),
        {frozenset({"alpha", "beta"}): "value"},
        {("nested", frozenset({"alpha", "beta"})): "value"},
    ],
    ids=[
        "set",
        "frozenset",
        "frozenset-mapping-key",
        "nested-frozenset-mapping-key",
    ],
)
def test_product_serialization_rejects_sets_deterministically(unsupported_value):
    document = ProductRequirementDocument(extra_metadata={"value": unsupported_value})

    with pytest.raises(ProductSerializationError, match="set|frozenset") as captured:
        document.to_dict()

    assert "alpha" not in str(captured.value)
    assert "beta" not in str(captured.value)


@pytest.mark.parametrize(
    "unsupported_value",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
        {"nested": [float("nan")]},
        {float("inf"): "mapping-key"},
        {("nested", float("-inf")): "compound-mapping-key"},
    ],
    ids=[
        "nan",
        "positive-infinity",
        "negative-infinity",
        "nested-nan",
        "infinite-mapping-key",
        "nested-infinite-mapping-key",
    ],
)
def test_product_serialization_rejects_non_finite_numbers(unsupported_value):
    document = ProductRequirementDocument(extra_metadata={"value": unsupported_value})

    with pytest.raises(ProductSerializationError, match="non-finite") as first:
        document.to_dict()
    with pytest.raises(ProductSerializationError) as second:
        document.to_dict()

    assert str(first.value) == str(second.value)
    assert "nan" not in str(first.value).casefold()
    assert "inf" not in str(first.value).casefold()
