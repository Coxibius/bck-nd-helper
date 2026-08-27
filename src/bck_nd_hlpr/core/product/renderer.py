"""Canonical, deterministic product context for prompts and MCP consumers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Sequence, Tuple, Union

from .models import (
    DiagnosticSeverity,
    ProductDiagnostic,
    ProductDiagnosticCode,
    ProductRequirementDocument,
    ProductStatus,
)
from .service import ProductService
from .validator import classify_product_path


DEFAULT_PRODUCT_CONTEXT_CHARS = 6000
MIN_PRODUCT_CONTEXT_CHARS = 256

_OPENING_TAG = '<product_context schema_version="1">'
_CLOSING_TAG = "</product_context>"
_TRUNCATION_MARKER = "… [TRUNCATED]"

_ACTIVE_STATUSES = frozenset(
    {
        ProductStatus.DRAFT.value,
        ProductStatus.REVIEW.value,
        ProductStatus.APPROVED.value,
        ProductStatus.SHIPPED.value,
    }
)
_APPROVED_STATUSES = frozenset(
    {ProductStatus.APPROVED.value, ProductStatus.SHIPPED.value}
)
_TRUST_NOTICES = {
    ProductStatus.DRAFT.value: "DRAFT — product intent is not approved",
    ProductStatus.REVIEW.value: "REVIEW — product intent is pending approval",
    ProductStatus.APPROVED.value: "APPROVED — product intent is approved",
    ProductStatus.SHIPPED.value: (
        "SHIPPED — product intent was approved and shipped"
    ),
}
_SECTION_PRIORITY = (
    "problem_statement",
    "target_users",
    "goals",
    "non_goals",
    "success_metrics",
    "open_questions",
    "scope",
    "risks",
    "rollout_plan",
)
_GLOBAL_DIAGNOSTIC_CODES = frozenset(
    {
        ProductDiagnosticCode.PARSE_ERROR.value,
        ProductDiagnosticCode.SOURCE_SYMLINK.value,
        ProductDiagnosticCode.SOURCE_OUTSIDE_ROOT.value,
        ProductDiagnosticCode.ID_DUPLICATE.value,
        ProductDiagnosticCode.REQUIREMENT_ORPHAN.value,
        ProductDiagnosticCode.APPLIES_TO_INVALID.value,
    }
)


class ProductContextError(ValueError):
    """Base class for controlled product-context rendering failures."""


class ProductContextBudgetError(ProductContextError):
    """The requested budget cannot hold a valid canonical envelope."""


class ProductContextPathError(ProductContextError):
    """The requested target scope is not safely project-relative."""


@dataclass(frozen=True)
class _NarrativeSection:
    key: str
    value: str


@dataclass(frozen=True)
class _DocumentCandidate:
    identifier: str
    provenance: Dict[str, object]
    narrative: Tuple[_NarrativeSection, ...]

    @property
    def omitted_section_labels(self) -> List[str]:
        return [f"{self.identifier}:{item.key}" for item in self.narrative]


@dataclass(frozen=True)
class _SelectionResult:
    candidates: Tuple[_DocumentCandidate, ...]
    out_of_scope_sources: FrozenSet[str]


@dataclass(frozen=True)
class _SectionFit:
    value: Optional[str]
    complete: bool


def build_product_context(
    project_path: Union[str, Path] = ".",
    *,
    target_path: str = ".",
    max_chars: int = DEFAULT_PRODUCT_CONTEXT_CHARS,
) -> Optional[str]:
    """Build the one canonical product block shared by prompt and MCP adapters."""
    _validate_budget(max_chars)
    target_components = _safe_components(target_path, target=True)

    service = ProductService(project_path)
    collection = service.load_documents()
    if not collection.documents and not collection.diagnostics:
        return None
    report = service.validate_documents(collection=collection)

    selection = _select_documents(
        report.documents,
        report.diagnostics,
        service,
        target_components,
    )
    diagnostics = _prioritize_diagnostics([
        _diagnostic_payload(item)
        for item in _filter_diagnostics_for_scope(
            report.diagnostics,
            selection,
            target_components,
        )
    ])
    candidates = selection.candidates

    complete_documents = []
    for candidate in candidates:
        rendered = _copy_document(candidate.provenance)
        rendered["sections"] = {
            section.key: section.value for section in candidate.narrative
        }
        complete_documents.append(rendered)
    complete_payload = _payload(
        truncated=False,
        documents=complete_documents,
        diagnostics=diagnostics,
        omitted_sections=[],
        omitted_document_ids=[],
        omitted_diagnostics=0,
    )
    complete = _render(complete_payload)
    if len(complete) <= max_chars:
        return complete

    return _render_with_budget(candidates, diagnostics, max_chars)


def _validate_budget(max_chars: int) -> None:
    if (
        isinstance(max_chars, bool)
        or not isinstance(max_chars, int)
        or max_chars < MIN_PRODUCT_CONTEXT_CHARS
    ):
        raise ProductContextBudgetError(
            f"Product context max_chars must be at least {MIN_PRODUCT_CONTEXT_CHARS}."
        )


def _safe_components(value: Union[str, Path], *, target: bool = False) -> Tuple[str, ...]:
    normalized, external, traversal = classify_product_path(value)
    if not normalized or external or traversal:
        if target:
            raise ProductContextPathError(
                "target_path must be a safe project-relative path."
            )
        return ()
    return tuple(
        part for part in normalized.split("/") if part not in {"", "."}
    )


def _paths_overlap(first: Tuple[str, ...], second: Tuple[str, ...]) -> bool:
    if not first or not second:
        return True
    shared = min(len(first), len(second))
    return first[:shared] == second[:shared]


def _select_documents(
    documents: Sequence[ProductRequirementDocument],
    diagnostics: Sequence[ProductDiagnostic],
    service: ProductService,
    target_components: Tuple[str, ...],
) -> _SelectionResult:
    ordered = sorted(
        documents,
        key=lambda item: (
            str(item.source_path).replace("\\", "/").casefold(),
            str(item.source_path).replace("\\", "/"),
            item.id.casefold(),
            item.id,
        ),
    )
    error_sources = {
        str(item.source_path).replace("\\", "/").casefold()
        for item in diagnostics
        if item.severity is DiagnosticSeverity.ERROR
    }
    duplicate_ids = {
        document.id.casefold()
        for document in documents
        if sum(
            other.id.casefold() == document.id.casefold()
            for other in documents
        )
        > 1
    }

    selected: List[_DocumentCandidate] = []
    out_of_scope_sources = set()
    for document in ordered:
        safe_applies: List[str] = []
        applies_components: List[Tuple[str, ...]] = []
        scope_is_valid = bool(document.applies_to)
        for declared_path in document.applies_to:
            normalized, external, traversal = classify_product_path(declared_path)
            if not normalized or external or traversal:
                scope_is_valid = False
                continue
            components = _safe_components(normalized)
            safe_applies.append(normalized)
            applies_components.append(components)
        is_applicable = bool(applies_components) and any(
            _paths_overlap(item, target_components) for item in applies_components
        )

        source_path = service._exposed_path(document.source_path)
        source_key = source_path.casefold()
        if scope_is_valid and not is_applicable:
            out_of_scope_sources.add(source_key)

        status = document.status_value
        if status not in _ACTIVE_STATUSES or not is_applicable:
            continue

        invalid = source_key in error_sources or document.id.casefold() in duplicate_ids
        missing_ids = {
            str(item.reference).casefold()
            for item in diagnostics
            if item.code == ProductDiagnosticCode.REQUIREMENT_MISSING
            and str(item.source_path).replace("\\", "/").casefold() == source_key
            and item.reference
        }
        requirements = [
            {
                "id": requirement_id,
                "resolution": (
                    "MISSING"
                    if requirement_id.casefold() in missing_ids
                    else "RESOLVED"
                ),
            }
            for requirement_id in document.requirement_ids
        ]
        validation = "INVALID" if invalid else "VALID"
        approved = status in _APPROVED_STATUSES and validation == "VALID"
        trust_notice = (
            f"INVALID — declared status {status}; "
            "do not treat product intent as approved"
            if invalid
            else _TRUST_NOTICES[status]
        )
        provenance: Dict[str, object] = {
            "id": document.id,
            "source_path": source_path,
            "status": status,
            "approved": approved,
            "trust_notice": trust_notice,
            "applies_to": safe_applies,
            "requirement_ids": requirements,
            "validation": validation,
            "sections": {},
        }
        narrative = () if invalid else _document_narrative(document)
        selected.append(
            _DocumentCandidate(
                identifier=document.id,
                provenance=provenance,
                narrative=narrative,
            )
        )
    return _SelectionResult(
        candidates=tuple(selected),
        out_of_scope_sources=frozenset(out_of_scope_sources),
    )


def _filter_diagnostics_for_scope(
    diagnostics: Sequence[ProductDiagnostic],
    selection: _SelectionResult,
    target_components: Tuple[str, ...],
) -> List[ProductDiagnostic]:
    """Drop only source-local findings proven to belong outside target scope."""
    if not target_components:
        return list(diagnostics)

    filtered: List[ProductDiagnostic] = []
    for diagnostic in diagnostics:
        code = (
            diagnostic.code.value
            if isinstance(diagnostic.code, ProductDiagnosticCode)
            else str(diagnostic.code)
        )
        source_key = str(diagnostic.source_path).replace("\\", "/").casefold()
        if (
            code not in _GLOBAL_DIAGNOSTIC_CODES
            and source_key in selection.out_of_scope_sources
        ):
            continue
        filtered.append(diagnostic)
    return filtered


def _document_narrative(
    document: ProductRequirementDocument,
) -> Tuple[_NarrativeSection, ...]:
    values = {
        "problem_statement": document.problem_statement,
        "target_users": document.target_users,
        "goals": document.goals,
        "non_goals": document.non_goals,
        "success_metrics": document.success_metrics,
        "open_questions": "\n".join(
            f"- {question}" for question in document.open_questions
        ),
        "scope": document.scope,
        "risks": document.risks,
        "rollout_plan": document.rollout_plan,
    }
    result = [
        _NarrativeSection(key, str(values[key]).strip())
        for key in _SECTION_PRIORITY
        if str(values[key]).strip()
    ]
    for section_name, content in sorted(
        document.extra_sections.items(),
        key=lambda item: (item[0].casefold(), item[0]),
    ):
        text = str(content).strip()
        if text:
            result.append(_NarrativeSection(f"extra:{section_name}", text))
    return tuple(result)


def _diagnostic_payload(diagnostic: ProductDiagnostic) -> Dict[str, object]:
    code = (
        diagnostic.code.value
        if isinstance(diagnostic.code, ProductDiagnosticCode)
        else str(diagnostic.code)
    )
    return {
        "code": code,
        "severity": diagnostic.severity.value,
        "message": diagnostic.message,
        "source_path": str(diagnostic.source_path).replace("\\", "/"),
        "field": diagnostic.field,
        "section": diagnostic.section,
        "reference": diagnostic.reference,
    }


def _prioritize_diagnostics(
    diagnostics: Sequence[Dict[str, object]],
) -> List[Dict[str, object]]:
    """Keep stable source order inside trust-first severity groups."""
    priorities = ("ERROR", "WARNING", "INFO")
    ordered: List[Dict[str, object]] = []
    for severity in priorities:
        ordered.extend(
            item for item in diagnostics if item.get("severity") == severity
        )
    ordered.extend(
        item for item in diagnostics if item.get("severity") not in priorities
    )
    return ordered


def _payload(
    *,
    truncated: bool,
    documents: List[Dict[str, object]],
    diagnostics: List[Dict[str, object]],
    omitted_sections: List[str],
    omitted_document_ids: List[str],
    omitted_diagnostics: int,
) -> Dict[str, object]:
    return {
        "truncated": truncated,
        "documents": documents,
        "diagnostics": diagnostics,
        "omitted_sections": omitted_sections,
        "omitted_document_ids": omitted_document_ids,
        "omitted_diagnostics": omitted_diagnostics,
    }


def _copy_document(document: Dict[str, object]) -> Dict[str, object]:
    copied = dict(document)
    copied["sections"] = dict(document.get("sections", {}))
    return copied


def _copy_documents(
    documents: Sequence[Dict[str, object]],
) -> List[Dict[str, object]]:
    return [_copy_document(item) for item in documents]


def _render(payload: Dict[str, object]) -> str:
    interior = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    interior = (
        interior.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    return f"{_OPENING_TAG}\n{interior}\n{_CLOSING_TAG}"


def _render_with_budget(
    candidates: Sequence[_DocumentCandidate],
    diagnostics: Sequence[Dict[str, object]],
    max_chars: int,
) -> str:
    included_candidates: List[_DocumentCandidate] = []
    documents: List[Dict[str, object]] = []
    omitted_document_ids = [item.identifier for item in candidates]
    omitted_sections: List[str] = []
    included_diagnostics: List[Dict[str, object]] = []
    omitted_diagnostics = len(diagnostics)

    def current_payload() -> Dict[str, object]:
        return _payload(
            truncated=True,
            documents=documents,
            diagnostics=included_diagnostics,
            omitted_sections=omitted_sections,
            omitted_document_ids=omitted_document_ids,
            omitted_diagnostics=omitted_diagnostics,
        )

    def finish() -> str:
        rendered = _render(current_payload())
        if len(rendered) > max_chars:
            raise ProductContextBudgetError(
                "Product context budget cannot hold the minimum valid envelope."
            )
        return rendered

    def include_diagnostic_group(
        severity: str,
    ) -> bool:
        nonlocal included_diagnostics, omitted_diagnostics
        group = [
            item for item in diagnostics if item.get("severity") == severity
        ]
        for diagnostic in group:
            trial_diagnostics = included_diagnostics + [dict(diagnostic)]
            trial = _payload(
                truncated=True,
                documents=documents,
                diagnostics=trial_diagnostics,
                omitted_sections=omitted_sections,
                omitted_document_ids=omitted_document_ids,
                omitted_diagnostics=omitted_diagnostics - 1,
            )
            if len(_render(trial)) > max_chars:
                return False
            included_diagnostics = trial_diagnostics
            omitted_diagnostics -= 1
        return True

    if len(_render(current_payload())) > max_chars:
        raise ProductContextBudgetError(
            "Product context budget cannot hold the minimum valid envelope."
        )

    for candidate in candidates:
        trial_documents = documents + [_copy_document(candidate.provenance)]
        trial_omitted_ids = list(omitted_document_ids)
        trial_omitted_ids.remove(candidate.identifier)
        trial_omitted_sections = (
            omitted_sections + candidate.omitted_section_labels
        )
        trial = _payload(
            truncated=True,
            documents=trial_documents,
            diagnostics=included_diagnostics,
            omitted_sections=trial_omitted_sections,
            omitted_document_ids=trial_omitted_ids,
            omitted_diagnostics=omitted_diagnostics,
        )
        if len(_render(trial)) <= max_chars:
            documents = trial_documents
            omitted_document_ids = trial_omitted_ids
            omitted_sections = trial_omitted_sections
            included_candidates.append(candidate)
        else:
            break

    # Narrative and diagnostics remain disabled until the selected provenance
    # prefix is stable. Otherwise a larger budget could add a document and
    # evict content that was emitted at a smaller budget.
    if omitted_document_ids:
        return finish()

    # Validation errors are trust metadata. They must be represented before
    # any narrative is allowed to consume the shared budget.
    if not include_diagnostic_group("ERROR"):
        return finish()

    narrative_by_priority: Dict[str, List[Tuple[_DocumentCandidate, _NarrativeSection]]] = {}
    for candidate in included_candidates:
        for section in candidate.narrative:
            narrative_by_priority.setdefault(section.key, []).append(
                (candidate, section)
            )

    priority_keys = list(_SECTION_PRIORITY)
    extra_keys = sorted(
        (key for key in narrative_by_priority if key not in _SECTION_PRIORITY),
        key=lambda item: (item.casefold(), item),
    )
    for key in priority_keys + extra_keys:
        entries = narrative_by_priority.get(key, [])
        if not entries:
            continue

        trial_documents = _copy_documents(documents)
        trial_by_id = {str(item["id"]): item for item in trial_documents}
        labels_to_remove = []
        for candidate, section in entries:
            trial_by_id[candidate.identifier]["sections"][section.key] = section.value
            labels_to_remove.append(f"{candidate.identifier}:{section.key}")
        trial_omitted = [
            label for label in omitted_sections if label not in labels_to_remove
        ]
        trial = _payload(
            truncated=True,
            documents=trial_documents,
            diagnostics=included_diagnostics,
            omitted_sections=trial_omitted,
            omitted_document_ids=omitted_document_ids,
            omitted_diagnostics=omitted_diagnostics,
        )
        if len(_render(trial)) <= max_chars:
            documents = trial_documents
            omitted_sections = trial_omitted
            continue

        for index, (candidate, section) in enumerate(entries):
            remaining_entries = len(entries) - index
            available = max_chars - len(_render(current_payload()))
            fair_share = max(0, available // max(1, remaining_entries))
            fit = _largest_fitting_section(
                current_payload,
                documents,
                candidate.identifier,
                section,
                fair_share,
                max_chars,
            )
            if fit.complete:
                label = f"{candidate.identifier}:{section.key}"
                omitted_sections = [
                    item for item in omitted_sections if item != label
                ]

        # Do not advance to lower-priority prose or non-error diagnostics
        # while any section in the current priority group remains pending.
        labels_for_group = {
            f"{candidate.identifier}:{section.key}"
            for candidate, section in entries
        }
        if any(label in labels_for_group for label in omitted_sections):
            return finish()

    # Lower-severity diagnostics are useful context, but may only consume
    # space after every selected narrative section is complete.
    if omitted_sections:
        return finish()
    if not include_diagnostic_group("WARNING"):
        return finish()
    include_diagnostic_group("INFO")
    return finish()


def _largest_fitting_section(
    payload_factory,
    documents: List[Dict[str, object]],
    document_id: str,
    section: _NarrativeSection,
    fair_share: int,
    max_chars: int,
) -> _SectionFit:
    if fair_share <= len(_TRUNCATION_MARKER):
        return _SectionFit(None, False)
    upper = min(len(section.value), fair_share)
    lower = 0
    best: Optional[str] = None
    target = next(item for item in documents if str(item["id"]) == document_id)
    sections = target["sections"]
    while lower <= upper:
        midpoint = (lower + upper) // 2
        if midpoint >= len(section.value):
            candidate_text = section.value
        else:
            prefix = section.value[:midpoint].rstrip()
            candidate_text = (
                f"{prefix}\n{_TRUNCATION_MARKER}"
                if prefix
                else _TRUNCATION_MARKER
            )
        sections[section.key] = candidate_text
        if len(_render(payload_factory())) <= max_chars:
            best = candidate_text
            lower = midpoint + 1
        else:
            upper = midpoint - 1
    if best is None:
        sections.pop(section.key, None)
    else:
        sections[section.key] = best
    return _SectionFit(best, best == section.value)


__all__ = [
    "DEFAULT_PRODUCT_CONTEXT_CHARS",
    "MIN_PRODUCT_CONTEXT_CHARS",
    "ProductContextBudgetError",
    "ProductContextError",
    "ProductContextPathError",
    "build_product_context",
]
