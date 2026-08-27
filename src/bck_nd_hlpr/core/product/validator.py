"""Pure, deterministic validation policy for Product Requirements Documents."""

import os
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple, Union

from .models import (
    DiagnosticSeverity,
    ProductCollectionResult,
    ProductDiagnostic,
    ProductDiagnosticCode,
    ProductRequirementDocument,
    ProductStatus,
)


SUPPORTED_SCHEMA_VERSION = 1
VALID_PRODUCT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

REQUIRED_SECTIONS: Tuple[Tuple[str, str], ...] = (
    ("problem_statement", "Problem Statement"),
    ("target_users", "Target Users"),
    ("goals", "Goals"),
    ("non_goals", "Non-Goals"),
    ("success_metrics", "Success Metrics"),
    ("scope", "Scope"),
    ("risks", "Risks"),
    ("rollout_plan", "Rollout Plan"),
    ("open_questions", "Open Questions"),
)

_PLACEHOLDER_TOKEN = re.compile(r"\b(?:TODO|TBD)\b")
_DESCRIBE_LINE = re.compile(
    r"^\s*(?:[-*+]\s+)?describe(?:\s+.*|\s*\.{3})\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _source(document: ProductRequirementDocument) -> str:
    return str(document.source_path).replace("\\", "/")


def classify_product_path(value: Union[str, Path]) -> Tuple[str, bool, bool]:
    """Classify path syntax portably for validation and public sanitization."""
    raw = str(value).strip()
    normalized = raw.replace("\\", "/")
    posix_path = PurePosixPath(normalized)
    windows_path = PureWindowsPath(raw)
    has_uri_scheme = re.match(
        r"^[A-Za-z][A-Za-z0-9+.-]*:",
        normalized,
    ) is not None
    has_external_syntax = (
        "\x00" in normalized
        or posix_path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or normalized.startswith("//")
        or has_uri_scheme
    )
    has_parent_reference = ".." in posix_path.parts
    return normalized, has_external_syntax, has_parent_reference


def _diagnostic(
    code: ProductDiagnosticCode,
    severity: DiagnosticSeverity,
    message: str,
    source_path: str,
    *,
    field: Optional[str] = None,
    section: Optional[str] = None,
    reference: Optional[str] = None,
) -> ProductDiagnostic:
    return ProductDiagnostic(
        code=code,
        severity=severity,
        message=message,
        source_path=source_path,
        field=field,
        section=section,
        reference=reference,
    )


class ProductValidator:
    """Validate product documents without loading requirements or invoking adapters."""

    @classmethod
    def validate_document(
        cls,
        document: ProductRequirementDocument,
        project_root: Optional[Union[str, Path]] = None,
        available_requirement_ids: Optional[Iterable[str]] = None,
    ) -> List[ProductDiagnostic]:
        diagnostics: List[ProductDiagnostic] = []
        source_path = _source(document)
        status = document.status_value
        metadata_present = (
            set(document._present_metadata)
            if document._present_metadata is not None
            else None
        )

        if not document.id.strip():
            diagnostics.append(
                _diagnostic(
                    ProductDiagnosticCode.ID_MISSING,
                    DiagnosticSeverity.ERROR,
                    "PRD ID is required.",
                    source_path,
                    field="id",
                )
            )
        elif VALID_PRODUCT_ID.fullmatch(document.id.strip()) is None:
            diagnostics.append(
                _diagnostic(
                    ProductDiagnosticCode.ID_INVALID,
                    DiagnosticSeverity.ERROR,
                    f"PRD ID '{document.id}' has an invalid format.",
                    source_path,
                    field="id",
                    reference=document.id,
                )
            )

        if document.schema_version is None:
            diagnostics.append(
                cls._missing_metadata(document, "schema_version", source_path)
            )
        elif document.schema_version != SUPPORTED_SCHEMA_VERSION:
            diagnostics.append(
                _diagnostic(
                    ProductDiagnosticCode.SCHEMA_UNSUPPORTED,
                    DiagnosticSeverity.ERROR,
                    (
                        f"Unsupported schema_version '{document.schema_version}'; "
                        f"expected {SUPPORTED_SCHEMA_VERSION}."
                    ),
                    source_path,
                    field="schema_version",
                    reference=str(document.schema_version),
                )
            )

        if not document.title.strip():
            diagnostics.append(cls._missing_metadata(document, "title", source_path))

        if not status:
            diagnostics.append(cls._missing_metadata(document, "status", source_path))
        elif status not in {item.value for item in ProductStatus}:
            diagnostics.append(
                _diagnostic(
                    ProductDiagnosticCode.STATUS_INVALID,
                    DiagnosticSeverity.ERROR,
                    f"Unsupported PRD status '{status}'.",
                    source_path,
                    field="status",
                    reference=status,
                )
            )

        if not document.applies_to:
            diagnostics.append(
                cls._missing_metadata(document, "applies_to", source_path)
            )

        if metadata_present is not None and "requirement_ids" not in metadata_present:
            diagnostics.append(
                cls._missing_metadata(document, "requirement_ids", source_path)
            )

        diagnostics.extend(cls._validate_sections(document, status))
        diagnostics.extend(cls._validate_open_questions(document, status))
        diagnostics.extend(
            cls._validate_requirement_references(
                document,
                available_requirement_ids,
            )
        )
        diagnostics.extend(cls._validate_paths(document, project_root))
        return diagnostics

    @classmethod
    def validate_collection(
        cls,
        collection: Union[
            ProductCollectionResult,
            Sequence[ProductRequirementDocument],
            Iterable[ProductRequirementDocument],
        ],
        project_root: Optional[Union[str, Path]] = None,
        available_requirement_ids: Optional[Iterable[str]] = None,
    ) -> List[ProductDiagnostic]:
        if isinstance(collection, ProductCollectionResult):
            documents = list(collection.documents)
            diagnostics = list(collection.diagnostics)
            collection_source = str(collection.source_directory)
        else:
            documents = list(collection)
            diagnostics = []
            collection_source = ""

        available = cls._canonical_ids(available_requirement_ids)
        available_values = list(available.values()) if available is not None else None
        for document in documents:
            diagnostics.extend(
                cls.validate_document(
                    document,
                    project_root=project_root,
                    available_requirement_ids=available_values,
                )
            )

        diagnostics.extend(cls._duplicate_id_diagnostics(documents))

        # A project without PRDs remains silent and backward-compatible.
        if documents and available is not None:
            referenced = {
                requirement_id.strip().casefold()
                for document in documents
                for requirement_id in document.requirement_ids
                if requirement_id.strip()
            }
            for normalized_id, original_id in available.items():
                if normalized_id in referenced:
                    continue
                diagnostics.append(
                    _diagnostic(
                        ProductDiagnosticCode.REQUIREMENT_ORPHAN,
                        DiagnosticSeverity.WARNING,
                        f"Requirement '{original_id}' is not referenced by any PRD.",
                        collection_source,
                        field="requirement_ids",
                        reference=original_id,
                    )
                )

        return cls._deduplicate(diagnostics)

    @staticmethod
    def _missing_metadata(
        document: ProductRequirementDocument,
        field_name: str,
        source_path: str,
    ) -> ProductDiagnostic:
        return _diagnostic(
            ProductDiagnosticCode.METADATA_MISSING,
            DiagnosticSeverity.ERROR,
            f"Required metadata field '{field_name}' is missing or empty.",
            source_path,
            field=field_name,
        )

    @classmethod
    def _validate_sections(
        cls,
        document: ProductRequirementDocument,
        status: str,
    ) -> List[ProductDiagnostic]:
        diagnostics: List[ProductDiagnostic] = []
        source_path = _source(document)
        present = (
            set(document._present_sections)
            if document._present_sections is not None
            else None
        )
        severity = cls._incomplete_section_severity(status)

        for field_name, section_name in REQUIRED_SECTIONS:
            if present is None:
                if field_name == "open_questions":
                    is_present = bool(document.open_questions)
                else:
                    is_present = bool(str(getattr(document, field_name)).strip())
            else:
                is_present = field_name in present

            if not is_present:
                diagnostics.append(
                    _diagnostic(
                        ProductDiagnosticCode.SECTION_MISSING,
                        severity,
                        f"Required section '{section_name}' is missing.",
                        source_path,
                        section=section_name,
                    )
                )
                continue

            raw_content = document._section_markdown.get(field_name)
            if raw_content is None:
                if field_name == "open_questions":
                    raw_content = "\n".join(document.open_questions)
                else:
                    raw_content = str(getattr(document, field_name))

            # An explicitly present Open Questions section may be empty or say N/A.
            if field_name == "open_questions" and not document.open_questions:
                continue
            if not raw_content.strip() or cls._contains_placeholder(raw_content):
                diagnostics.append(
                    _diagnostic(
                        ProductDiagnosticCode.SECTION_PLACEHOLDER,
                        severity,
                        (
                            f"Required section '{section_name}' is empty or still "
                            "contains placeholder content."
                        ),
                        source_path,
                        section=section_name,
                    )
                )
        return diagnostics

    @staticmethod
    def _validate_open_questions(
        document: ProductRequirementDocument,
        status: str,
    ) -> List[ProductDiagnostic]:
        if not document.open_questions or status == ProductStatus.ARCHIVED.value:
            return []

        source_path = _source(document)
        if status in {ProductStatus.APPROVED.value, ProductStatus.SHIPPED.value}:
            return [
                _diagnostic(
                    ProductDiagnosticCode.OPEN_QUESTIONS_BLOCKING,
                    DiagnosticSeverity.ERROR,
                    (
                        f"PRD status {status} cannot retain unresolved open questions."
                    ),
                    source_path,
                    section="Open Questions",
                )
            ]
        if status in {ProductStatus.DRAFT.value, ProductStatus.REVIEW.value}:
            return [
                _diagnostic(
                    ProductDiagnosticCode.OPEN_QUESTIONS_PRESENT,
                    DiagnosticSeverity.WARNING,
                    "PRD contains unresolved open questions.",
                    source_path,
                    section="Open Questions",
                )
            ]
        return []

    @staticmethod
    def _validate_requirement_references(
        document: ProductRequirementDocument,
        available_requirement_ids: Optional[Iterable[str]],
    ) -> List[ProductDiagnostic]:
        available = ProductValidator._canonical_ids(available_requirement_ids)
        if available is None:
            return []

        diagnostics: List[ProductDiagnostic] = []
        for requirement_id in document.requirement_ids:
            reference = requirement_id.strip()
            if not reference or reference.casefold() in available:
                continue
            diagnostics.append(
                _diagnostic(
                    ProductDiagnosticCode.REQUIREMENT_MISSING,
                    DiagnosticSeverity.ERROR,
                    f"Referenced requirement '{reference}' does not exist.",
                    _source(document),
                    field="requirement_ids",
                    reference=reference,
                )
            )
        return diagnostics

    @classmethod
    def _validate_paths(
        cls,
        document: ProductRequirementDocument,
        project_root: Optional[Union[str, Path]],
    ) -> List[ProductDiagnostic]:
        diagnostics: List[ProductDiagnostic] = []
        source_path = _source(document)
        root = Path(project_root).resolve(strict=False) if project_root is not None else None

        for applies_path in document.applies_to:
            normalized, has_external_syntax, _ = classify_product_path(
                applies_path
            )
            if not normalized:
                diagnostics.append(
                    cls._invalid_path(source_path, applies_path, "Path cannot be empty.")
                )
                continue
            if has_external_syntax:
                diagnostics.append(
                    cls._invalid_path(
                        source_path,
                        "<outside-project>",
                        "External paths and URI schemes are not allowed in applies_to.",
                    )
                )
                continue
            if cls._escapes_root(normalized):
                diagnostics.append(
                    cls._invalid_path(
                        source_path,
                        normalized,
                        "Path escapes the selected project root.",
                    )
                )
                continue
            if root is None:
                continue

            parts = [part for part in normalized.split("/") if part not in {"", "."}]
            candidate = root.joinpath(*parts)
            try:
                resolved_candidate = candidate.resolve(strict=False)
                if os.path.commonpath([str(root), str(resolved_candidate)]) != str(root):
                    diagnostics.append(
                        cls._invalid_path(
                            source_path,
                            normalized,
                            "Resolved path leaves the selected project root.",
                        )
                    )
                    continue
            except (OSError, ValueError):
                diagnostics.append(
                    cls._invalid_path(
                        source_path,
                        normalized,
                        "Path cannot be safely resolved inside the project root.",
                    )
                )
                continue

            if not candidate.exists():
                diagnostics.append(
                    _diagnostic(
                        ProductDiagnosticCode.APPLIES_TO_MISSING,
                        DiagnosticSeverity.WARNING,
                        f"Applicable path '{normalized}' does not exist.",
                        source_path,
                        field="applies_to",
                        reference=normalized,
                    )
                )
        return diagnostics

    @staticmethod
    def _invalid_path(
        source_path: str,
        reference: str,
        detail: str,
    ) -> ProductDiagnostic:
        return _diagnostic(
            ProductDiagnosticCode.APPLIES_TO_INVALID,
            DiagnosticSeverity.ERROR,
            f"Invalid applies_to path '{reference}': {detail}",
            source_path,
            field="applies_to",
            reference=reference,
        )

    @staticmethod
    def _escapes_root(value: str) -> bool:
        depth = 0
        for part in value.split("/"):
            if part in {"", "."}:
                continue
            if part == "..":
                if depth == 0:
                    return True
                depth -= 1
            else:
                depth += 1
        return False

    @staticmethod
    def _contains_placeholder(content: str) -> bool:
        return bool(
            _PLACEHOLDER_TOKEN.search(content) or _DESCRIBE_LINE.search(content)
        )

    @staticmethod
    def _incomplete_section_severity(status: str) -> DiagnosticSeverity:
        if status in {
            ProductStatus.REVIEW.value,
            ProductStatus.APPROVED.value,
            ProductStatus.SHIPPED.value,
        }:
            return DiagnosticSeverity.ERROR
        return DiagnosticSeverity.WARNING

    @staticmethod
    def _canonical_ids(
        values: Optional[Iterable[str]],
    ) -> Optional[Dict[str, str]]:
        if values is None:
            return None
        unique: Dict[str, str] = {}
        ordered = sorted(
            (str(value).strip() for value in values if str(value).strip()),
            key=lambda item: (item.casefold(), item),
        )
        for value in ordered:
            unique.setdefault(value.casefold(), value)
        return unique

    @staticmethod
    def _duplicate_id_diagnostics(
        documents: Sequence[ProductRequirementDocument],
    ) -> List[ProductDiagnostic]:
        diagnostics: List[ProductDiagnostic] = []
        seen: Dict[str, ProductRequirementDocument] = {}
        for document in documents:
            normalized = document.id.strip().casefold()
            if not normalized:
                continue
            first = seen.get(normalized)
            if first is None:
                seen[normalized] = document
                continue
            diagnostics.append(
                _diagnostic(
                    ProductDiagnosticCode.ID_DUPLICATE,
                    DiagnosticSeverity.ERROR,
                    (
                        f"Duplicate PRD ID '{document.id}' conflicts with "
                        f"'{first.source_path}'."
                    ),
                    _source(document),
                    field="id",
                    reference=str(first.source_path),
                )
            )
        return diagnostics

    @staticmethod
    def _deduplicate(
        diagnostics: Iterable[ProductDiagnostic],
    ) -> List[ProductDiagnostic]:
        result: List[ProductDiagnostic] = []
        seen: Set[Tuple[object, ...]] = set()
        for item in diagnostics:
            key = (
                item.code.value if isinstance(item.code, ProductDiagnosticCode) else item.code,
                item.severity.value,
                item.source_path,
                item.field,
                item.section,
                item.reference,
            )
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result
