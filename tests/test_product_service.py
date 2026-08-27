"""Tests for the reusable local PRD application service."""

import os
from pathlib import Path

import pytest

import bck_nd_hlpr.core.product.service as service_module
from bck_nd_hlpr.core.product import (
    DiagnosticSeverity,
    ProductCollectionResult,
    ProductCollisionError,
    ProductDiagnostic,
    ProductDiagnosticCode,
    ProductInvalidIdError,
    ProductParser,
    ProductPathError,
    ProductReadError,
    ProductRequirementDocument,
    ProductSerializationError,
    ProductService,
    ProductTransitionBlockedError,
    ProductWriteError,
    ProductValidator,
)


def complete_prd(
    product_id="PRD-TEST",
    *,
    status="DRAFT",
    requirements=None,
    open_questions="None",
    newline="\n",
    extra_metadata="custom_flag: keep-me\n",
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
status: {status} # lifecycle comment
owner: Equipo Ñ
target_release: 2.5.0
applies_to:
  - .
{requirement_lines}
{extra_metadata}---

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
    product_dir = project / ".bck-nd" / "product"
    product_dir.mkdir(parents=True, exist_ok=True)
    target = product_dir / filename
    target.write_text(content, encoding="utf-8", newline="")
    return target


def write_requirement(project: Path, story_id: str) -> None:
    requirements_dir = project / ".bck-nd" / "requirements"
    requirements_dir.mkdir(parents=True, exist_ok=True)
    (requirements_dir / f"{story_id}.md").write_text(
        f"# {story_id} [TODO] - Story\n\n- **Role**: User\n",
        encoding="utf-8",
    )


def test_create_document_uses_default_id_and_creates_missing_directories(tmp_path):
    result = ProductService(tmp_path).create_document()

    assert result.path == tmp_path / ".bck-nd" / "product" / "PRD.md"
    assert result.document.id == "PRD"
    assert result.path.read_text(encoding="utf-8").endswith("\n")
    parsed = ProductParser.load_from_directory(tmp_path)
    assert [document.id for document in parsed.documents] == ["PRD"]
    assert parsed.diagnostics == []
    validation = ProductValidator.validate_document(parsed.documents[0], tmp_path)
    assert validation
    assert all(item.severity is DiagnosticSeverity.WARNING for item in validation)


def test_create_document_normalizes_explicit_id(tmp_path):
    result = ProductService(tmp_path).create_document("  prd-auth  ")

    assert result.document.id == "PRD-AUTH"
    assert result.path.name == "PRD-AUTH.md"


@pytest.mark.parametrize("invalid_id", ["../PRD", "PRD/AUTH", "C:\\PRD", ".", " "])
def test_create_document_rejects_invalid_id_before_creating_directories(
    tmp_path,
    invalid_id,
):
    with pytest.raises(ProductInvalidIdError):
        ProductService(tmp_path).create_document(invalid_id)

    assert not (tmp_path / ".bck-nd").exists()


def test_create_document_never_overwrites_exact_collision(tmp_path):
    service = ProductService(tmp_path)
    result = service.create_document("PRD-AUTH")
    original = result.path.read_bytes()

    with pytest.raises(ProductCollisionError):
        service.create_document("PRD-AUTH")

    assert result.path.read_bytes() == original


def test_create_document_rejects_case_insensitive_filename_collision(tmp_path):
    existing = write_prd(tmp_path, "prd-auth.md", complete_prd("PRD-OTHER"))
    original = existing.read_bytes()

    with pytest.raises(ProductCollisionError):
        ProductService(tmp_path).create_document("PRD-AUTH")

    assert existing.read_bytes() == original


def test_create_document_rejects_collision_by_parsed_id(tmp_path):
    write_prd(tmp_path, "feature.md", complete_prd("PRD-AUTH"))

    with pytest.raises(ProductCollisionError):
        ProductService(tmp_path).create_document("prd-auth")


def test_atomic_create_publishes_complete_file_without_temporary_artifacts(tmp_path):
    result = ProductService(tmp_path).create_document("PRD-ATOMIC")

    assert result.path.read_text(encoding="utf-8").startswith("---\nschema_version: 1")
    assert list(result.path.parent.glob("*.tmp")) == []


def test_failed_atomic_create_removes_temporary_file(tmp_path, monkeypatch):
    def fail_link(_source, _target):
        raise OSError("simulated publish failure")

    monkeypatch.setattr(service_module.os, "link", fail_link)

    with pytest.raises(ProductWriteError):
        ProductService(tmp_path).create_document("PRD-FAIL")

    product_dir = tmp_path / ".bck-nd" / "product"
    assert not (product_dir / "PRD-FAIL.md").exists()
    assert list(product_dir.glob("*.tmp")) == []


def test_get_document_searches_parsed_id_case_insensitively(tmp_path):
    write_prd(tmp_path, "feature-name.md", complete_prd("PRD-AUTH"))

    document = ProductService(tmp_path).get_document("prd-auth")

    assert document.id == "PRD-AUTH"
    assert document.source_path.endswith("feature-name.md")


def test_validation_links_available_and_missing_requirements(tmp_path):
    write_prd(
        tmp_path,
        "PRD-REQ.md",
        complete_prd("PRD-REQ", requirements=["US-001", "US-404"]),
    )
    write_requirement(tmp_path, "US-001")

    report = ProductService(tmp_path).validate_documents()

    missing = [
        item
        for item in report.diagnostics
        if item.code == ProductDiagnosticCode.REQUIREMENT_MISSING
    ]
    assert [item.reference for item in missing] == ["US-404"]


def test_full_validation_reports_orphan_requirement(tmp_path):
    write_prd(tmp_path, "PRD.md", complete_prd("PRD"))
    write_requirement(tmp_path, "US-ORPHAN")

    report = ProductService(tmp_path).validate_documents()

    orphan = [
        item
        for item in report.diagnostics
        if item.code == ProductDiagnosticCode.REQUIREMENT_ORPHAN
    ]
    assert [item.reference for item in orphan] == ["US-ORPHAN"]


def test_validation_report_is_deterministic_and_exposes_relative_paths(tmp_path):
    write_prd(tmp_path, "b.md", complete_prd("PRD-B"))
    write_prd(tmp_path, "A.md", complete_prd("PRD-A"))
    service = ProductService(tmp_path)

    first = service.validate_documents().to_dict()
    second = service.validate_documents().to_dict()

    assert first == second
    assert [item["id"] for item in first["documents"]] == ["PRD-A", "PRD-B"]
    assert all(
        not Path(item["source_path"]).is_absolute()
        for item in first["documents"]
    )


@pytest.mark.parametrize(
    "external_path",
    [
        "/outside/secret",
        "C:\\outside\\secret",
        "\\\\server\\share\\secret",
        "../outside/secret",
        "..\\outside\\secret",
    ],
    ids=["posix", "windows-drive", "unc", "posix-traversal", "windows-traversal"],
)
def test_validation_json_does_not_expose_absolute_applies_to_path(
    tmp_path,
    external_path,
):
    content = complete_prd("PRD-PATH").replace(
        "applies_to:\n  - .",
        f"applies_to:\n  - {external_path}",
    )
    write_prd(tmp_path, "PRD-PATH.md", content)

    report = ProductService(tmp_path).validate_documents()
    original_applies_to = list(report.documents[0].applies_to)
    payload = report.to_dict()

    serialized = repr(payload)
    assert external_path not in serialized
    assert external_path.replace("\\", "/") not in serialized
    assert payload["documents"][0]["applies_to"] == ["<outside-project>"]
    assert payload["diagnostics"][0]["reference"] == "<outside-project>"
    assert report.documents[0].applies_to == original_applies_to
    assert "<outside-project>" not in report.documents[0].applies_to


@pytest.mark.parametrize(
    "external_uri",
    [
        "file:///C:/Users/Private/secret",
        "file:///etc/passwd",
        "FiLe:///C:/Users/Private/secret",
    ],
    ids=["windows-file-uri", "posix-file-uri", "mixed-case-scheme"],
)
def test_validation_json_redacts_uri_applies_to_everywhere(tmp_path, external_uri):
    content = complete_prd("PRD-URI").replace(
        "applies_to:\n  - .",
        f"applies_to:\n  - {external_uri}",
    )
    write_prd(tmp_path, "PRD-URI.md", content)

    payload = ProductService(tmp_path).validate_documents().to_dict()
    serialized = repr(payload)

    assert external_uri not in serialized
    assert payload["documents"][0]["applies_to"] == ["<outside-project>"]
    assert payload["diagnostics"][0]["reference"] == "<outside-project>"
    assert external_uri not in payload["diagnostics"][0]["message"]


def test_validation_json_keeps_legitimate_internal_reference_relative(tmp_path):
    content = complete_prd("PRD-INTERNAL").replace(
        "applies_to:\n  - .",
        "applies_to:\n  - apps/api",
    )
    write_prd(tmp_path, "PRD-INTERNAL.md", content)

    payload = ProductService(tmp_path).validate_documents().to_dict()

    missing = [
        item
        for item in payload["diagnostics"]
        if item["code"] == "PRD_APPLIES_TO_MISSING"
    ]
    assert payload["documents"][0]["applies_to"] == ["apps/api"]
    assert missing[0]["reference"] == "apps/api"
    assert missing[0]["source_path"] == ".bck-nd/product/PRD-INTERNAL.md"


def test_validation_propagates_security_diagnostic_without_external_path(
    tmp_path,
    monkeypatch,
):
    external = tmp_path.parent / "external-product"
    diagnostic = ProductDiagnostic(
        code=ProductDiagnosticCode.SOURCE_OUTSIDE_ROOT,
        severity=DiagnosticSeverity.ERROR,
        message=f"Unsafe source: {external}",
        source_path=external,
        reference=str(external),
    )
    collection = ProductCollectionResult(
        diagnostics=[diagnostic],
        source_directory=external,
    )
    monkeypatch.setattr(
        ProductParser,
        "load_from_directory",
        classmethod(lambda cls, _path: collection),
    )

    payload = ProductService(tmp_path).validate_documents().to_dict()

    assert payload["valid"] is False
    assert payload["diagnostics"][0]["source_path"] == "<outside-project>"
    assert payload["diagnostics"][0]["reference"] == "<outside-project>"
    assert str(external) not in repr(payload)


@pytest.mark.parametrize(
    "external_path",
    [
        "/outside/secret",
        "C:\\outside\\secret",
        "\\\\server\\share\\secret",
        "../outside/secret",
        "..\\outside\\secret",
    ],
    ids=["posix", "windows-drive", "unc", "posix-traversal", "windows-traversal"],
)
def test_safe_diagnostics_sanitizes_portable_external_source_paths(
    tmp_path,
    external_path,
):
    diagnostic = ProductDiagnostic(
        code=ProductDiagnosticCode.PARSE_ERROR,
        severity=DiagnosticSeverity.ERROR,
        message=f"Could not parse {external_path}",
        source_path=external_path,
    )

    sanitized = ProductService(tmp_path)._safe_diagnostics([diagnostic])[0].to_dict()

    serialized = repr(sanitized)
    assert sanitized["source_path"] == "<outside-project>"
    assert external_path not in sanitized["message"]
    assert external_path.replace("\\", "/") not in sanitized["message"]
    assert external_path not in serialized
    assert external_path.replace("\\", "/") not in serialized


def test_safe_diagnostics_keeps_native_internal_source_relative(tmp_path):
    internal_path = tmp_path / ".bck-nd" / "product" / "PRD.md"
    diagnostic = ProductDiagnostic(
        code=ProductDiagnosticCode.PARSE_ERROR,
        severity=DiagnosticSeverity.ERROR,
        message="Could not parse internal PRD.",
        source_path=internal_path,
    )

    sanitized = ProductService(tmp_path)._safe_diagnostics([diagnostic])[0]

    assert sanitized.source_path == ".bck-nd/product/PRD.md"


def test_get_document_sanitizes_diagnostics_for_ambiguous_id(tmp_path):
    external_path = tmp_path.parent / "private" / "secret-prd.md"
    unsafe = ProductDiagnostic(
        code=ProductDiagnosticCode.SOURCE_OUTSIDE_ROOT,
        severity=DiagnosticSeverity.ERROR,
        message=f"Unsafe source: {external_path}",
        source_path=external_path,
        reference=str(external_path),
    )
    collection = ProductCollectionResult(
        documents=[
            ProductRequirementDocument(
                id="PRD-DUPLICATE",
                source_path=Path(".bck-nd/product/first.md"),
            ),
            ProductRequirementDocument(
                id="prd-duplicate",
                source_path=Path(".bck-nd/product/second.md"),
            ),
        ],
        diagnostics=[unsafe],
    )

    with pytest.raises(ProductCollisionError) as captured:
        ProductService(tmp_path).get_document(
            "PRD-DUPLICATE",
            collection=collection,
        )

    serialized = repr(
        [diagnostic.to_dict() for diagnostic in captured.value.diagnostics]
    )
    assert "<outside-project>" in serialized
    assert str(external_path) not in serialized
    assert str(external_path).replace("\\", "/") not in serialized


def test_update_status_preserves_bom_crlf_unicode_comments_metadata_and_body(tmp_path):
    text = complete_prd("PRD-PRESERVE", newline="\r\n")
    target = write_prd(tmp_path, "custom.md", text)
    target.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
    original_body = text.split("---\r\n", 2)[2]

    result = ProductService(tmp_path).update_status("prd-preserve", "review")
    updated = target.read_bytes()
    decoded = updated[3:].decode("utf-8")

    assert result.changed is True
    assert updated.startswith(b"\xef\xbb\xbf")
    assert "status: REVIEW # lifecycle comment\r\n" in decoded
    assert "custom_flag: keep-me\r\n" in decoded
    assert "Equipo Ñ" in decoded
    assert decoded.split("---\r\n", 2)[2] == original_body
    assert "\n" not in decoded.replace("\r\n", "")


@pytest.mark.parametrize("status_key", ["status", '"status"', "'status'"])
def test_update_status_preserves_quoted_yaml_status_key_and_formatting(
    tmp_path,
    status_key,
):
    text = complete_prd("PRD-QUOTED", newline="\r\n").replace(
        "status: DRAFT # lifecycle comment",
        f"{status_key}: DRAFT # lifecycle comment",
    )
    target = write_prd(tmp_path, "quoted.md", text)
    target.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
    original_body = text.split("---\r\n", 2)[2]

    ProductService(tmp_path).update_status("PRD-QUOTED", "REVIEW")

    updated = target.read_bytes()
    decoded = updated[3:].decode("utf-8")
    front_matter = decoded.split("---\r\n", 2)[1]
    assert updated.startswith(b"\xef\xbb\xbf")
    assert f"{status_key}: REVIEW # lifecycle comment\r\n" in front_matter
    assert front_matter.count("status") == 1
    assert decoded.split("---\r\n", 2)[2] == original_body
    assert "\n" not in decoded.replace("\r\n", "")


def test_update_status_edits_flow_style_yaml_without_reformatting(tmp_path):
    body = complete_prd("PRD-FLOW").split("---\n", 2)[2]
    content = (
        "---\n"
        "{schema_version: 1, id: PRD-FLOW, title: Product intent, "
        "status: DRAFT, owner: Team, target_release: 2.5.0, "
        "applies_to: [.], requirement_ids: [], custom_flag: keep-me} "
        "# preserve flow comment\n"
        "---\n"
        f"{body}"
    )
    target = write_prd(tmp_path, "flow.md", content)
    original_body = content.split("---\n", 2)[2]

    result = ProductService(tmp_path).update_status("PRD-FLOW", "REVIEW")

    updated = target.read_text(encoding="utf-8")
    front_matter = updated.split("---\n", 2)[1]
    reparsed = ProductParser.parse_file(target)
    assert result.changed is True
    assert reparsed.document is not None
    assert reparsed.document.status_value == "REVIEW"
    assert front_matter.count("status:") == 1
    assert "status: REVIEW" in front_matter
    assert "# preserve flow comment" in front_matter
    assert updated.split("---\n", 2)[2] == original_body


@pytest.mark.parametrize("scalar_style", [">-", "|"])
def test_update_status_edits_multiline_scalar_by_structural_span(
    tmp_path,
    scalar_style,
):
    text = complete_prd("PRD-BLOCK", newline="\r\n").replace(
        "status: DRAFT # lifecycle comment",
        f"# preserve status comment\r\nstatus: {scalar_style}\r\n  DRAFT",
    )
    content = b"\xef\xbb\xbf" + text.encode("utf-8")
    target = write_prd(tmp_path, "block.md", text)
    target.write_bytes(content)
    original_body = text.split("---\r\n", 2)[2]

    result = ProductService(tmp_path).update_status("PRD-BLOCK", "REVIEW")

    updated = target.read_bytes()
    decoded = updated[3:].decode("utf-8")
    front_matter = decoded.split("---\r\n", 2)[1]
    reparsed = ProductParser.parse_file(target)
    assert result.changed is True
    assert updated.startswith(b"\xef\xbb\xbf")
    assert front_matter.count("status:") == 1
    assert "status: REVIEW\r\n" in front_matter
    assert "# preserve status comment\r\n" in front_matter
    assert "custom_flag: keep-me\r\n" in front_matter
    assert decoded.split("---\r\n", 2)[2] == original_body
    assert reparsed.document is not None
    assert reparsed.document.status_value == "REVIEW"


def test_update_status_rejects_inconsistent_yaml_span_without_writing(
    tmp_path,
    monkeypatch,
):
    target = write_prd(tmp_path, "unsafe-span.md", complete_prd("PRD-SPAN"))
    original = target.read_bytes()
    original_compose = service_module.yaml.compose

    def compose_with_invalid_span(*args, **kwargs):
        root = original_compose(*args, **kwargs)
        for key_node, value_node in root.value:
            if key_node.value == "status":
                value_node.start_mark.index = -1
        return root

    monkeypatch.setattr(service_module.yaml, "compose", compose_with_invalid_span)

    with pytest.raises(ProductReadError):
        ProductService(tmp_path).update_status("PRD-SPAN", "REVIEW")

    assert target.read_bytes() == original


def test_update_status_noop_keeps_original_bytes(tmp_path):
    target = write_prd(tmp_path, "PRD.md", complete_prd("PRD", status="DRAFT"))
    original = target.read_bytes()

    result = ProductService(tmp_path).update_status("PRD", "draft")

    assert result.changed is False
    assert target.read_bytes() == original


def test_update_status_inserts_missing_status_minimally(tmp_path):
    content = complete_prd("PRD-NOSTATUS").replace(
        "status: DRAFT # lifecycle comment\n",
        "",
    )
    target = write_prd(tmp_path, "missing-status.md", content)

    ProductService(tmp_path).update_status("PRD-NOSTATUS", "REVIEW")
    updated = target.read_text(encoding="utf-8")

    assert updated.count("status: REVIEW") == 1
    assert updated.endswith("- None\n")


def test_update_status_blocks_invalid_candidate_without_writing(tmp_path):
    target = write_prd(
        tmp_path,
        "PRD-BLOCKED.md",
        complete_prd("PRD-BLOCKED").replace(
            "Users complete the documented workflow.",
            "TODO: Define success.",
        ),
    )
    original = target.read_bytes()

    with pytest.raises(ProductTransitionBlockedError) as captured:
        ProductService(tmp_path).update_status("PRD-BLOCKED", "APPROVED")

    assert captured.value.diagnostics
    assert target.read_bytes() == original


def test_update_status_blocks_missing_requirement(tmp_path):
    target = write_prd(
        tmp_path,
        "PRD-REQ.md",
        complete_prd("PRD-REQ", requirements=["US-404"]),
    )
    original = target.read_bytes()

    with pytest.raises(ProductTransitionBlockedError) as captured:
        ProductService(tmp_path).update_status("PRD-REQ", "REVIEW")

    assert any(
        item.code == ProductDiagnosticCode.REQUIREMENT_MISSING
        for item in captured.value.diagnostics
    )
    assert target.read_bytes() == original


def test_update_status_blocks_open_questions_for_approved(tmp_path):
    target = write_prd(
        tmp_path,
        "PRD-QUESTION.md",
        complete_prd("PRD-QUESTION", open_questions="Who approves launch?"),
    )

    with pytest.raises(ProductTransitionBlockedError):
        ProductService(tmp_path).update_status("PRD-QUESTION", "APPROVED")

    assert "status: DRAFT" in target.read_text(encoding="utf-8")


def test_update_status_allows_archiving_incomplete_document(tmp_path):
    incomplete = """---
schema_version: 1
id: PRD-HISTORY
title:
status: DRAFT
applies_to:
  - .
requirement_ids: []
---

# Historical notes
"""
    target = write_prd(tmp_path, "history.md", incomplete)

    result = ProductService(tmp_path).update_status("PRD-HISTORY", "ARCHIVED")

    assert result.changed is True
    assert "status: ARCHIVED" in target.read_text(encoding="utf-8")


def test_update_status_allows_return_to_draft_with_validation_errors(tmp_path):
    content = complete_prd("PRD-RETURN", status="REVIEW").replace(
        "title: Product intent — Salud",
        "title:",
    )
    target = write_prd(tmp_path, "return.md", content)

    result = ProductService(tmp_path).update_status("PRD-RETURN", "DRAFT")

    assert result.changed is True
    assert result.new_status == "DRAFT"
    assert any(
        item.severity is DiagnosticSeverity.ERROR for item in result.diagnostics
    )
    assert "status: DRAFT # lifecycle comment" in target.read_text(encoding="utf-8")


def test_update_status_blocks_incomplete_document_for_review(tmp_path):
    content = complete_prd("PRD-REVIEW").replace(
        "title: Product intent — Salud",
        "title:",
    )
    target = write_prd(tmp_path, "review.md", content)
    original = target.read_bytes()

    with pytest.raises(ProductTransitionBlockedError):
        ProductService(tmp_path).update_status("PRD-REVIEW", "REVIEW")

    assert target.read_bytes() == original


def test_failed_atomic_status_update_keeps_original_and_removes_temp(
    tmp_path,
    monkeypatch,
):
    target = write_prd(tmp_path, "PRD.md", complete_prd("PRD"))
    original = target.read_bytes()

    def fail_replace(_source, _target):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(service_module.os, "replace", fail_replace)

    with pytest.raises(ProductWriteError):
        ProductService(tmp_path).update_status("PRD", "REVIEW")

    assert target.read_bytes() == original
    assert list(target.parent.glob("*.tmp")) == []


def test_atomic_status_update_rejects_same_inode_concurrent_write(
    tmp_path,
    monkeypatch,
):
    target = write_prd(tmp_path, "PRD.md", complete_prd("PRD"))
    original_inode = target.stat().st_ino
    concurrent_content = b"concurrent writer content\r\n"
    original_write_temp = ProductService._write_temp_file

    def write_temp_then_modify_target(target_path, content):
        temp_path = original_write_temp(target_path, content)
        target_path.write_bytes(concurrent_content)
        assert target_path.stat().st_ino == original_inode
        return temp_path

    monkeypatch.setattr(
        ProductService,
        "_write_temp_file",
        staticmethod(write_temp_then_modify_target),
    )

    with pytest.raises(ProductPathError, match="changed during the update"):
        ProductService(tmp_path).update_status("PRD", "REVIEW")

    assert target.stat().st_ino == original_inode
    assert target.read_bytes() == concurrent_content
    assert list(target.parent.glob("*.tmp")) == []


def test_atomic_status_update_detects_concurrent_write_during_temp_chmod(
    tmp_path,
    monkeypatch,
):
    target = write_prd(tmp_path, "PRD.md", complete_prd("PRD"))
    concurrent_content = b"human concurrent edit during chmod\r\n"
    original_chmod = service_module.os.chmod
    raced = False

    def chmod_then_edit(path, mode):
        nonlocal raced
        original_chmod(path, mode)
        if Path(path).suffix == ".tmp" and not raced:
            raced = True
            target.write_bytes(concurrent_content)

    monkeypatch.setattr(service_module.os, "chmod", chmod_then_edit)

    with pytest.raises(ProductPathError, match="changed during the update"):
        ProductService(tmp_path).update_status("PRD", "REVIEW")

    assert raced is True
    assert target.read_bytes() == concurrent_content
    assert list(target.parent.glob("*.tmp")) == []


def test_two_normal_status_updates_remain_atomic(tmp_path):
    target = write_prd(tmp_path, "PRD.md", complete_prd("PRD"))
    service = ProductService(tmp_path)

    first = service.update_status("PRD", "REVIEW")
    second = service.update_status("PRD", "DRAFT")

    assert first.changed is True
    assert second.changed is True
    assert ProductParser.parse_file(target).document.status_value == "DRAFT"
    assert list(target.parent.glob("*.tmp")) == []


def test_parser_and_service_share_one_verified_source_reader(tmp_path, monkeypatch):
    target = write_prd(tmp_path, "PRD.md", complete_prd("PRD"))
    product_dir = target.parent
    original_reader = ProductParser.read_verified_source.__func__
    calls = []

    def tracked_reader(cls, file_path, *, product_directory, project_root):
        calls.append(Path(file_path))
        return original_reader(
            cls,
            file_path,
            product_directory=product_directory,
            project_root=project_root,
        )

    monkeypatch.setattr(
        ProductParser,
        "read_verified_source",
        classmethod(tracked_reader),
    )

    parsed = ProductParser.parse_file(
        target,
        source_path=".bck-nd/product/PRD.md",
        product_directory=product_dir,
        project_root=tmp_path,
    )
    assert parsed.document is not None
    ProductService(tmp_path)._read_document_source(parsed.document)

    assert calls == [target, target]


def test_service_secure_reader_rejects_aba_replacement_without_leaking(
    tmp_path,
    monkeypatch,
):
    target = write_prd(tmp_path, "PRD.md", complete_prd("PRD-SAFE"))
    service = ProductService(tmp_path)
    document = service.get_document("PRD-SAFE")
    external = tmp_path / "external-secret.md"
    marker = "EXTERNAL-ABA-CONTENT"
    external.write_text(complete_prd("PRD-EXTERNAL") + marker, encoding="utf-8")
    backup = target.parent / ".original-backup.tmp"
    returned_external = tmp_path / "returned-external.md"
    original_resolve = Path.resolve
    original_lstat = Path.lstat
    phase = 0

    def resolve_then_swap(path, strict=False):
        nonlocal phase
        resolved = original_resolve(path, strict=strict)
        if path == target and phase == 0:
            os.replace(target, backup)
            os.replace(external, target)
            phase = 1
        return resolved

    def lstat_then_restore(path):
        nonlocal phase
        if path == target and phase == 1:
            os.replace(target, returned_external)
            os.replace(backup, target)
            phase = 2
        return original_lstat(path)

    monkeypatch.setattr(Path, "resolve", resolve_then_swap)
    monkeypatch.setattr(Path, "lstat", lstat_then_restore)

    try:
        with pytest.raises((ProductPathError, ProductReadError)) as captured:
            service._read_document_source(document)
    finally:
        if phase == 1:
            os.replace(target, returned_external)
            os.replace(backup, target)
            phase = 2

    assert phase == 2
    serialized_error = repr(captured.value)
    assert marker not in serialized_error
    assert str(external) not in serialized_error
    payload = service.validate_documents().to_dict()
    assert marker not in repr(payload)
    assert target.read_text(encoding="utf-8").startswith("---")


def test_validation_report_rejects_yaml_set_metadata(tmp_path):
    content = complete_prd(
        "PRD-SET",
        extra_metadata="custom_values: !!set\n  ? alpha\n  ? beta\n",
    )
    write_prd(tmp_path, "PRD-SET.md", content)
    report = ProductService(tmp_path).validate_documents()

    assert isinstance(report.documents[0].extra_metadata["custom_values"], set)
    with pytest.raises(ProductSerializationError, match="set|frozenset"):
        report.to_dict()


@pytest.mark.parametrize(
    "yaml_number",
    [".nan", ".inf", "-.inf"],
    ids=["nan", "positive-infinity", "negative-infinity"],
)
def test_validation_report_rejects_yaml_non_finite_metadata(tmp_path, yaml_number):
    content = complete_prd(
        "PRD-NUMBER",
        extra_metadata=f"custom_number: {yaml_number}\n",
    )
    write_prd(tmp_path, "PRD-NUMBER.md", content)
    report = ProductService(tmp_path).validate_documents()

    with pytest.raises(ProductSerializationError, match="non-finite"):
        report.to_dict()


@pytest.mark.parametrize(
    "extra_metadata",
    [
        ".nan: top-level-key\n",
        "custom_map:\n  .inf: nested-key\n",
    ],
    ids=["top-level-key", "nested-key"],
)
def test_validation_report_rejects_yaml_non_finite_mapping_keys(
    tmp_path,
    extra_metadata,
):
    content = complete_prd("PRD-NUMBER-KEY", extra_metadata=extra_metadata)
    write_prd(tmp_path, "PRD-NUMBER-KEY.md", content)
    report = ProductService(tmp_path).validate_documents()

    assert report.documents
    with pytest.raises(ProductSerializationError, match="non-finite"):
        report.to_dict()


def test_update_status_rejects_security_diagnostic_without_reading(
    tmp_path,
    monkeypatch,
):
    diagnostic = ProductDiagnostic(
        code=ProductDiagnosticCode.SOURCE_SYMLINK,
        severity=DiagnosticSeverity.ERROR,
        message="Unsafe linked source.",
        source_path=".bck-nd/product/PRD-LINK.md",
    )
    collection = ProductCollectionResult(diagnostics=[diagnostic])
    monkeypatch.setattr(
        ProductParser,
        "load_from_directory",
        classmethod(lambda cls, _path: collection),
    )

    with pytest.raises(ProductPathError):
        ProductService(tmp_path).update_status("PRD-LINK", "REVIEW")
