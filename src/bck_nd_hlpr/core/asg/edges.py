"""
ASG Edge Models — Directed edge representations for structural, ORM, and architectural relationships.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class EdgeKind(str, Enum):
    """Enumeration of standard ASG edge relationship kinds."""
    # Structural
    INHERITS = "INHERITS"
    IMPLEMENTS = "IMPLEMENTS"

    # ORM / Database
    HAS_ONE = "HAS_ONE"
    HAS_MANY = "HAS_MANY"
    BELONGS_TO = "BELONGS_TO"
    MANY_TO_MANY = "MANY_TO_MANY"

    # Architectural
    DEPENDS_ON = "DEPENDS_ON"
    CALLS = "CALLS"
    ROUTES_TO = "ROUTES_TO"


@dataclass
class ASGEdge:
    """
    Directed edge in the Abstract Semantic Graph.

    Attributes:
        source_id: Origin node ID.
        target_id: Destination node ID.
        kind: Categorical EdgeKind.
        label: Optional descriptive text or cardinal string.
        metadata: Framework-specific details, source file, line numbers, etc.
    """
    source_id: str
    target_id: str
    kind: EdgeKind
    label: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        kind_val = self.kind.value if isinstance(self.kind, EdgeKind) else str(self.kind)
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "kind": kind_val,
            "label": self.label,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ASGEdge":
        raw_kind = data.get("kind", EdgeKind.DEPENDS_ON.value)
        try:
            kind_enum = EdgeKind(raw_kind)
        except ValueError:
            kind_enum = EdgeKind.DEPENDS_ON

        return cls(
            source_id=data.get("source_id", ""),
            target_id=data.get("target_id", ""),
            kind=kind_enum,
            label=data.get("label"),
            metadata=dict(data.get("metadata", {})),
        )
