"""Dependency-free domain models for Product Requirements Documents."""

from dataclasses import dataclass, field
from enum import Enum
import math
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Union


class ProductStatus(str, Enum):
    """Supported PRD lifecycle states."""

    DRAFT = "DRAFT"
    REVIEW = "REVIEW"
    APPROVED = "APPROVED"
    SHIPPED = "SHIPPED"
    ARCHIVED = "ARCHIVED"


class DiagnosticSeverity(str, Enum):
    """Stable severity levels exposed by the product domain."""

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class ProductDiagnosticCode(str, Enum):
    """Public, machine-readable product diagnostic codes."""

    PARSE_ERROR = "PRD_PARSE_ERROR"
    SOURCE_SYMLINK = "PRD_SOURCE_SYMLINK"
    SOURCE_OUTSIDE_ROOT = "PRD_SOURCE_OUTSIDE_ROOT"
    YAML_ALIAS_UNSUPPORTED = "PRD_YAML_ALIAS_UNSUPPORTED"
    YAML_DUPLICATE_KEY = "PRD_YAML_DUPLICATE_KEY"
    ID_MISSING = "PRD_ID_MISSING"
    ID_INVALID = "PRD_ID_INVALID"
    ID_DUPLICATE = "PRD_ID_DUPLICATE"
    SCHEMA_UNSUPPORTED = "PRD_SCHEMA_UNSUPPORTED"
    STATUS_INVALID = "PRD_STATUS_INVALID"
    METADATA_MISSING = "PRD_METADATA_MISSING"
    SECTION_MISSING = "PRD_SECTION_MISSING"
    SECTION_PLACEHOLDER = "PRD_SECTION_PLACEHOLDER"
    REQUIREMENT_MISSING = "PRD_REQUIREMENT_MISSING"
    REQUIREMENT_ORPHAN = "PRD_REQUIREMENT_ORPHAN"
    APPLIES_TO_INVALID = "PRD_APPLIES_TO_INVALID"
    APPLIES_TO_MISSING = "PRD_APPLIES_TO_MISSING"
    OPEN_QUESTIONS_PRESENT = "PRD_OPEN_QUESTIONS_PRESENT"
    OPEN_QUESTIONS_BLOCKING = "PRD_OPEN_QUESTIONS_BLOCKING"


class ProductSerializationError(ValueError):
    """Raised when domain data cannot be serialized safely."""


_MAX_SERIALIZATION_DEPTH = 64


def _enum_value(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def _serialize(value: Any) -> Any:
    """Convert domain values without allowing cycles or unbounded recursion."""
    try:
        return _serialize_value(value, active_containers=set(), depth=0)
    except RecursionError as exc:
        raise ProductSerializationError(
            "Product data exceeds the safe serialization recursion limit."
        ) from exc


def _contains_set(value: Any) -> bool:
    """Detect unsupported sets nested inside otherwise hashable mapping keys."""
    if isinstance(value, (set, frozenset)):
        return True
    if isinstance(value, tuple):
        return any(_contains_set(item) for item in value)
    return False


def _contains_non_finite_number(value: Any) -> bool:
    """Detect non-finite floats before mapping keys are stringified or sorted."""
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, tuple):
        return any(_contains_non_finite_number(item) for item in value)
    return False


def _serialize_value(value: Any, active_containers: set, depth: int) -> Any:
    if depth > _MAX_SERIALIZATION_DEPTH:
        raise ProductSerializationError(
            "Product data exceeds the maximum serialization depth "
            f"({_MAX_SERIALIZATION_DEPTH})."
        )
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, (set, frozenset)):
        raise ProductSerializationError(
            "Product data contains a set or frozenset, which is not JSON-native."
        )
    if isinstance(value, float) and not math.isfinite(value):
        raise ProductSerializationError(
            "Product data contains a non-finite number, which is not valid JSON."
        )
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in active_containers:
            raise ProductSerializationError(
                "Product data contains a cyclic mapping or collection."
            )
        active_containers.add(identity)
        try:
            keys = list(value)
            if any(_contains_set(key) for key in keys):
                raise ProductSerializationError(
                    "Product data contains a set or frozenset mapping key, "
                    "which cannot be serialized deterministically."
                )
            if any(_contains_non_finite_number(key) for key in keys):
                raise ProductSerializationError(
                    "Product data contains a non-finite mapping key, "
                    "which is not valid JSON."
                )
            return {
                str(key): _serialize_value(
                    value[key], active_containers, depth + 1
                )
                for key in sorted(keys, key=lambda item: str(item))
            }
        finally:
            active_containers.remove(identity)
    if isinstance(value, (list, tuple)):
        identity = id(value)
        if identity in active_containers:
            raise ProductSerializationError(
                "Product data contains a cyclic mapping or collection."
            )
        active_containers.add(identity)
        try:
            return [
                _serialize_value(item, active_containers, depth + 1)
                for item in value
            ]
        finally:
            active_containers.remove(identity)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _normalized_source_path(value: Union[str, Path, None]) -> str:
    if value is None:
        return ""
    return str(value).replace("\\", "/")


@dataclass
class ProductDiagnostic:
    """One structured parsing or validation finding."""

    code: Union[ProductDiagnosticCode, str]
    severity: DiagnosticSeverity
    message: str
    source_path: Union[str, Path] = ""
    field: Optional[str] = None
    section: Optional[str] = None
    reference: Optional[str] = None

    def __post_init__(self) -> None:
        self.source_path = _normalized_source_path(self.source_path)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": _serialize(_enum_value(self.code)),
            "severity": _serialize(self.severity.value),
            "message": _serialize(self.message),
            "source_path": _serialize(self.source_path),
            "field": _serialize(self.field),
            "section": _serialize(self.section),
            "reference": _serialize(self.reference),
        }


@dataclass
class ProductRequirementDocument:
    """Normalized product intent parsed from one Markdown PRD."""

    schema_version: Optional[int] = None
    id: str = ""
    title: str = ""
    status: Union[ProductStatus, str, None] = None
    owner: str = ""
    target_release: str = ""
    applies_to: List[str] = field(default_factory=list)
    requirement_ids: List[str] = field(default_factory=list)
    problem_statement: str = ""
    target_users: str = ""
    goals: str = ""
    non_goals: str = ""
    success_metrics: str = ""
    scope: str = ""
    risks: str = ""
    rollout_plan: str = ""
    open_questions: List[str] = field(default_factory=list)
    source_path: Union[str, Path] = ""
    extra_metadata: Dict[str, Any] = field(default_factory=dict)
    extra_sections: Dict[str, str] = field(default_factory=dict)
    _present_metadata: Optional[List[str]] = field(
        default=None,
        repr=False,
        compare=False,
    )
    _present_sections: Optional[List[str]] = field(
        default=None,
        repr=False,
        compare=False,
    )
    _section_markdown: Dict[str, str] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        self.source_path = _normalized_source_path(self.source_path)

    @property
    def status_value(self) -> str:
        value = _enum_value(self.status)
        if isinstance(value, float) and not math.isfinite(value):
            raise ProductSerializationError(
                "Product data contains a non-finite number, which is not valid JSON."
            )
        return "" if value is None else str(value).strip().upper()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": _serialize(self.schema_version),
            "id": _serialize(self.id),
            "title": _serialize(self.title),
            "status": _serialize(self.status_value),
            "owner": _serialize(self.owner),
            "target_release": _serialize(self.target_release),
            "applies_to": _serialize(list(self.applies_to)),
            "requirement_ids": _serialize(list(self.requirement_ids)),
            "problem_statement": _serialize(self.problem_statement),
            "target_users": _serialize(self.target_users),
            "goals": _serialize(self.goals),
            "non_goals": _serialize(self.non_goals),
            "success_metrics": _serialize(self.success_metrics),
            "scope": _serialize(self.scope),
            "risks": _serialize(self.risks),
            "rollout_plan": _serialize(self.rollout_plan),
            "open_questions": _serialize(list(self.open_questions)),
            "source_path": _serialize(self.source_path),
            "extra_metadata": _serialize(self.extra_metadata),
            "extra_sections": _serialize(self.extra_sections),
        }


@dataclass
class ProductParseResult:
    """Result of parsing one source; failures are explicit diagnostics."""

    document: Optional[ProductRequirementDocument] = None
    diagnostics: List[ProductDiagnostic] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(item.severity is DiagnosticSeverity.ERROR for item in self.diagnostics)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document": self.document.to_dict() if self.document is not None else None,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


@dataclass
class ProductCollectionResult:
    """Deterministic aggregate of all directly discovered product documents."""

    documents: List[ProductRequirementDocument] = field(default_factory=list)
    diagnostics: List[ProductDiagnostic] = field(default_factory=list)
    source_directory: Union[str, Path] = ""

    def __post_init__(self) -> None:
        self.source_directory = _normalized_source_path(self.source_directory)

    @property
    def has_errors(self) -> bool:
        return any(item.severity is DiagnosticSeverity.ERROR for item in self.diagnostics)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "documents": [document.to_dict() for document in self.documents],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "source_directory": self.source_directory,
        }
