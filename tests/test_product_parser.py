"""Tests for safe PRD Markdown parsing and deterministic discovery."""

import os
from pathlib import Path

import pytest

import bck_nd_hlpr.core.product.parser as parser_module

from bck_nd_hlpr.core.product import (
    DiagnosticSeverity,
    ProductDiagnosticCode,
    ProductParser,
    ProductStatus,
)


def complete_prd(
    prd_id: str = "PRD-250",
    *,
    status: str = "DRAFT",
    newline: str = "\n",
    open_questions: str = "None",
) -> str:
    content = f"""---
schema_version: 1
id: {prd_id}
title: PRD Intelligence — Atención
status: {status}
owner: Product Architect
target_release: 2.5.0
applies_to:
  - .
requirement_ids:
  - US-001
custom_flag: true
---

# {prd_id} — PRD Intelligence

## Problem Statement
Agents lack durable product intent.

## Target Users
Students and educators.

## Goals
- Preserve product intent.

### Secondary Goal
Keep subsections as Markdown.

## Non-Goals
- Do not become a project manager.

## Success Metrics
- Users complete the workflow.

## Scope
Local PRD files only.

## Risks
- Added complexity.

## Rollout Plan
Ship in three sprints.

## Open Questions
- {open_questions}

## Dependencies
### Internal
Requirements Intelligence.
"""
    return content.replace("\n", newline)


def diagnostic_codes(result):
    return [
        item.code.value if isinstance(item.code, ProductDiagnosticCode) else item.code
        for item in result.diagnostics
    ]


def create_symlink_or_skip(link: Path, target: Path, *, directory: bool = False):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"Symbolic links are not supported in this environment: {exc}")


def test_parse_complete_prd_preserves_domain_content_and_extras():
    result = ProductParser.parse_markdown(
        complete_prd(),
        source_path=".bck-nd/product/PRD-250.md",
    )

    assert result.diagnostics == []
    assert result.document is not None
    document = result.document
    assert document.schema_version == 1
    assert document.id == "PRD-250"
    assert document.title == "PRD Intelligence — Atención"
    assert document.status is ProductStatus.DRAFT
    assert document.applies_to == ["."]
    assert document.requirement_ids == ["US-001"]
    assert "### Secondary Goal" in document.goals
    assert document.open_questions == []
    assert document.extra_metadata == {"custom_flag": True}
    assert document.extra_sections["Dependencies"].startswith("### Internal")


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_parse_supports_lf_and_crlf(newline):
    result = ProductParser.parse_markdown(complete_prd(newline=newline))

    assert result.document is not None
    assert "Students and educators." in result.document.target_users


def test_parse_supports_unicode_utf8_file(tmp_path):
    path = tmp_path / "PRD-Ñ.md"
    path.write_text(complete_prd("PRD-Ñ").replace("id: PRD-Ñ", "id: PRD-N"), encoding="utf-8")

    result = ProductParser.parse_file(path)

    assert result.document is not None
    assert "Atención" in result.document.title
    assert result.document.source_path.endswith("PRD-Ñ.md")


def test_parse_headers_case_insensitively():
    content = complete_prd()
    replacements = {
        "## Problem Statement": "## problem statement",
        "## Target Users": "## TARGET USERS",
        "## Non-Goals": "## nOn-GoAlS",
        "## Success Metrics": "## SUCCESS METRICS",
        "## Rollout Plan": "## rollout plan",
        "## Open Questions": "## OPEN QUESTIONS",
    }
    for original, replacement in replacements.items():
        content = content.replace(original, replacement)

    result = ProductParser.parse_markdown(content)

    assert result.document is not None
    assert result.document.problem_statement.startswith("Agents lack")
    assert result.document.rollout_plan == "Ship in three sprints."


def test_level_three_subsections_do_not_start_new_main_sections():
    result = ProductParser.parse_markdown(complete_prd())

    assert result.document is not None
    assert "### Secondary Goal\nKeep subsections" in result.document.goals
    assert "Secondary Goal" not in result.document.extra_sections


def test_unknown_sections_are_preserved():
    result = ProductParser.parse_markdown(complete_prd())

    assert result.document is not None
    assert result.document.extra_sections == {
        "Preamble": "# PRD-250 — PRD Intelligence",
        "Dependencies": "### Internal\nRequirements Intelligence.",
    }


def test_missing_front_matter_returns_explicit_diagnostic():
    result = ProductParser.parse_markdown("# PRD\n\n## Goals\nSomething")

    assert result.document is None
    assert diagnostic_codes(result) == ["PRD_PARSE_ERROR"]
    assert result.diagnostics[0].field == "front_matter"


def test_unclosed_front_matter_returns_explicit_diagnostic():
    result = ProductParser.parse_markdown("---\nid: PRD-1\n# Body")

    assert result.document is None
    assert "not closed" in result.diagnostics[0].message


def test_invalid_yaml_returns_explicit_diagnostic():
    result = ProductParser.parse_markdown("---\ntitle: [broken\n---\n## Goals\nText")

    assert result.document is None
    assert result.diagnostics[0].severity is DiagnosticSeverity.ERROR
    assert "Invalid YAML" in result.diagnostics[0].message


def test_yaml_front_matter_must_be_mapping():
    result = ProductParser.parse_markdown("---\n- one\n- two\n---\n## Goals\nText")

    assert result.document is None
    assert "object/mapping" in result.diagnostics[0].message


def test_partial_document_is_returned_with_field_diagnostics():
    content = complete_prd().replace("applies_to:\n  - .", "applies_to:\n  nested: value")

    result = ProductParser.parse_markdown(content)

    assert result.document is not None
    assert result.document.applies_to == []
    assert diagnostic_codes(result) == ["PRD_PARSE_ERROR"]
    assert result.diagnostics[0].field == "applies_to"


@pytest.mark.parametrize("empty_value", ["None", "N/A", "No open questions"])
def test_explicit_no_open_questions_values_become_empty_list(empty_value):
    result = ProductParser.parse_markdown(complete_prd(open_questions=empty_value))

    assert result.document is not None
    assert result.document.open_questions == []
    assert "open_questions" in result.document._present_sections


def test_actual_open_questions_are_extracted():
    result = ProductParser.parse_markdown(
        complete_prd(open_questions="Should drafts be included?")
    )

    assert result.document is not None
    assert result.document.open_questions == ["Should drafts be included?"]


def test_yaml_unsafe_constructor_is_rejected_without_execution(monkeypatch):
    calls = []
    monkeypatch.setattr(os, "system", lambda command: calls.append(command))
    content = """---
schema_version: 1
id: PRD-EVIL
title: !!python/object/apply:os.system ["echo unsafe"]
---
## Goals
Text
"""

    result = ProductParser.parse_markdown(content)

    assert result.document is None
    assert calls == []
    assert diagnostic_codes(result) == ["PRD_PARSE_ERROR"]


@pytest.mark.parametrize(
    "yaml_fragment",
    [
        "owner: &team Backend\nreviewer: *team",
        "custom: &cycle\n  - *cycle",
        "base: &base [one, two]\ncopy: [*base, *base, *base]",
    ],
    ids=["simple", "recursive", "shared-amplified"],
)
def test_yaml_aliases_are_rejected_without_recursion_error(yaml_fragment):
    content = f"---\nschema_version: 1\nid: PRD-ALIAS\n{yaml_fragment}\n---\n"

    result = ProductParser.parse_markdown(
        content,
        source_path=".bck-nd/product/PRD-ALIAS.md",
    )

    assert result.document is None
    assert diagnostic_codes(result) == ["PRD_YAML_ALIAS_UNSUPPORTED"]
    assert result.diagnostics[0].severity is DiagnosticSeverity.ERROR


@pytest.mark.parametrize(
    ("yaml_fragment", "conflicting_key"),
    [
        ("title: First\ntitle: Second", "title"),
        ("title: First\nTitle: Second", "Title"),
        ('title: First\n" title ": Second', " title "),
        ("custom:\n  Name: First\n  name: Second", "name"),
        ("schema-version: 1\nschema_version: 2", "schema_version"),
        ("applies-to: [. ]\napplies_to: [apps/api]", "applies_to"),
        ("Schema Version: 1\nSCHEMA_VERSION: 2", "SCHEMA_VERSION"),
        (
            "custom:\n  applies-to: first\n  applies_to: second",
            "applies_to",
        ),
    ],
    ids=[
        "exact",
        "case-insensitive",
        "outer-space",
        "nested",
        "hyphen-underscore",
        "applies-hyphen-underscore",
        "case-space-underscore",
        "nested-canonical",
    ],
)
def test_yaml_duplicate_and_ambiguous_keys_are_rejected(
    yaml_fragment,
    conflicting_key,
):
    content = f"---\nid: PRD-DUP\n{yaml_fragment}\n---\n"

    result = ProductParser.parse_markdown(
        content,
        source_path=".bck-nd/product/PRD-DUP.md",
    )

    assert result.document is None
    assert diagnostic_codes(result) == ["PRD_YAML_DUPLICATE_KEY"]
    diagnostic = result.diagnostics[0]
    assert diagnostic.severity is DiagnosticSeverity.ERROR
    assert diagnostic.reference == conflicting_key
    assert "PRD-DUP.md" in diagnostic.source_path


def test_invalid_utf8_file_returns_diagnostic(tmp_path):
    path = tmp_path / "invalid.md"
    path.write_bytes(b"---\xff---")

    result = ProductParser.parse_file(path)

    assert result.document is None
    assert "not valid UTF-8" in result.diagnostics[0].message


def test_parse_file_discards_content_when_inode_changes_before_open(
    tmp_path,
    monkeypatch,
):
    project_root = tmp_path / "workspace"
    product_dir = project_root / ".bck-nd" / "product"
    product_dir.mkdir(parents=True)
    target = product_dir / "PRD.md"
    target.write_text(complete_prd("PRD-SAFE"), encoding="utf-8")
    external = tmp_path / "external-secret.md"
    external.write_text(
        complete_prd("PRD-SECRET") + "\nEXTERNAL-RACE-SECRET",
        encoding="utf-8",
    )
    original_resolve = Path.resolve
    raced = False

    def resolve_then_replace(path, strict=False):
        nonlocal raced
        resolved = original_resolve(path, strict=strict)
        if path == target and not raced:
            raced = True
            os.replace(external, target)
        return resolved

    monkeypatch.setattr(Path, "resolve", resolve_then_replace)

    result = ProductParser.parse_file(
        target,
        source_path=".bck-nd/product/PRD.md",
        product_directory=product_dir,
        project_root=project_root,
    )

    assert raced is True
    assert result.document is None
    assert diagnostic_codes(result) == ["PRD_SOURCE_OUTSIDE_ROOT"]
    serialized = repr(result.to_dict())
    assert "PRD-SECRET" not in serialized
    assert "EXTERNAL-RACE-SECRET" not in serialized
    assert str(external) not in serialized


def test_missing_product_directory_returns_empty_collection(tmp_path):
    result = ProductParser.load_from_directory(tmp_path)

    assert result.documents == []
    assert result.diagnostics == []
    assert result.source_directory.endswith(".bck-nd/product")


def test_empty_product_directory_returns_empty_collection(tmp_path):
    product_dir = tmp_path / ".bck-nd" / "product"
    product_dir.mkdir(parents=True)

    result = ProductParser.load_from_directory(tmp_path)

    assert result.documents == []
    assert result.diagnostics == []


def test_loader_uses_direct_product_directory_without_duplicating_path(tmp_path):
    product_dir = tmp_path / ".bck-nd" / "product"
    product_dir.mkdir(parents=True)
    (product_dir / "PRD.md").write_text(complete_prd(), encoding="utf-8")

    result = ProductParser.load_from_directory(product_dir)

    assert len(result.documents) == 1
    assert result.source_directory == product_dir.as_posix()
    assert result.documents[0].source_path == ".bck-nd/product/PRD.md"


def test_loader_order_is_stable_and_non_recursive(tmp_path):
    product_dir = tmp_path / ".bck-nd" / "product"
    nested = product_dir / "nested"
    nested.mkdir(parents=True)
    (product_dir / "b.markdown").write_text(complete_prd("PRD-B"), encoding="utf-8")
    (product_dir / "A.md").write_text(complete_prd("PRD-A"), encoding="utf-8")
    (product_dir / "ignored.txt").write_text(complete_prd("PRD-TXT"), encoding="utf-8")
    (nested / "nested.md").write_text(complete_prd("PRD-NESTED"), encoding="utf-8")

    result = ProductParser.load_from_directory(tmp_path)

    assert [document.id for document in result.documents] == ["PRD-A", "PRD-B"]


def test_loader_detects_duplicate_ids_case_insensitively(tmp_path):
    product_dir = tmp_path / ".bck-nd" / "product"
    product_dir.mkdir(parents=True)
    (product_dir / "first.md").write_text(complete_prd("PRD-AUTH"), encoding="utf-8")
    (product_dir / "second.md").write_text(complete_prd("prd-auth"), encoding="utf-8")

    result = ProductParser.load_from_directory(tmp_path)

    assert len(result.documents) == 2
    duplicates = [
        item for item in result.diagnostics
        if item.code == ProductDiagnosticCode.ID_DUPLICATE
    ]
    assert len(duplicates) == 1
    assert duplicates[0].severity is DiagnosticSeverity.ERROR
    assert duplicates[0].reference == ".bck-nd/product/first.md"


def test_loader_keeps_valid_documents_and_invalid_file_diagnostics(tmp_path):
    product_dir = tmp_path / ".bck-nd" / "product"
    product_dir.mkdir(parents=True)
    (product_dir / "good.md").write_text(complete_prd("PRD-GOOD"), encoding="utf-8")
    (product_dir / "bad.md").write_text("No front matter", encoding="utf-8")

    result = ProductParser.load_from_directory(tmp_path)

    assert [document.id for document in result.documents] == ["PRD-GOOD"]
    assert diagnostic_codes(result) == ["PRD_PARSE_ERROR"]
    assert result.diagnostics[0].source_path == ".bck-nd/product/bad.md"


def test_loader_rejects_external_file_symlink_without_reading_secret(
    tmp_path,
    monkeypatch,
):
    project_root = tmp_path / "workspace"
    product_dir = project_root / ".bck-nd" / "product"
    product_dir.mkdir(parents=True)
    (product_dir / "safe.md").write_text(
        complete_prd("PRD-SAFE"),
        encoding="utf-8",
    )
    external = tmp_path / "external-secret.md"
    external.write_text(
        complete_prd("PRD-SECRET") + "\nTOP-SECRET-MARKER",
        encoding="utf-8",
    )
    create_symlink_or_skip(product_dir / "unsafe.md", external)

    result = ProductParser.load_from_directory(project_root)

    assert [document.id for document in result.documents] == ["PRD-SAFE"]
    assert diagnostic_codes(result) == ["PRD_SOURCE_SYMLINK"]
    assert "TOP-SECRET-MARKER" not in repr(result.to_dict())

    unsafe = product_dir / "unsafe.md"
    unsafe.unlink()
    unsafe.write_text(complete_prd("PRD-RACE-SAFE"), encoding="utf-8")
    original_resolve = Path.resolve
    raced = False

    def resolve_then_link(path, strict=False):
        nonlocal raced
        resolved = original_resolve(path, strict=strict)
        if path == unsafe and not raced:
            raced = True
            unsafe.unlink()
            unsafe.symlink_to(external)
        return resolved

    monkeypatch.setattr(Path, "resolve", resolve_then_link)

    raced_result = ProductParser.load_from_directory(project_root)

    assert raced is True
    assert [document.id for document in raced_result.documents] == ["PRD-SAFE"]
    assert diagnostic_codes(raced_result) == ["PRD_SOURCE_SYMLINK"]
    raced_serialized = repr(raced_result.to_dict())
    assert "PRD-SECRET" not in raced_serialized
    assert "TOP-SECRET-MARKER" not in raced_serialized
    assert str(external) not in raced_serialized


def test_loader_rejects_symlinked_product_directory_without_reading_secret(tmp_path):
    project_root = tmp_path / "workspace"
    metadata_dir = project_root / ".bck-nd"
    metadata_dir.mkdir(parents=True)
    external_product = tmp_path / "external-product"
    external_product.mkdir()
    (external_product / "secret.md").write_text(
        complete_prd("PRD-SECRET") + "\nDIRECTORY-SECRET-MARKER",
        encoding="utf-8",
    )
    create_symlink_or_skip(
        metadata_dir / "product",
        external_product,
        directory=True,
    )

    result = ProductParser.load_from_directory(project_root)

    assert result.documents == []
    assert diagnostic_codes(result) == ["PRD_SOURCE_SYMLINK"]
    assert "DIRECTORY-SECRET-MARKER" not in repr(result.to_dict())


def test_loader_rejects_resolved_product_directory_outside_root(
    tmp_path,
    monkeypatch,
):
    project_root = tmp_path / "workspace"
    project_root.mkdir()
    outside_product = tmp_path / "outside-product"
    outside_product.mkdir()
    (outside_product / "outside.md").write_text(
        complete_prd("PRD-OUTSIDE"),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        ProductParser,
        "_resolve_product_directory",
        staticmethod(lambda _path: (outside_product, project_root)),
    )

    result = ProductParser.load_from_directory(project_root)

    assert result.documents == []
    assert diagnostic_codes(result) == ["PRD_SOURCE_OUTSIDE_ROOT"]


def test_path_containment_logic_is_cross_platform(tmp_path):
    project_root = tmp_path / "workspace"
    inside = project_root / ".bck-nd" / "product" / "PRD.md"
    outside = tmp_path / "outside" / "PRD.md"

    assert ProductParser._is_path_within(inside, project_root) is True
    assert ProductParser._is_path_within(outside, project_root) is False
