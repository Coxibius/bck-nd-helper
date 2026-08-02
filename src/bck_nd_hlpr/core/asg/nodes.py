"""
ASG Node Models — Domain representations for entities, classes, endpoints, services, modules.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class NodeKind(str, Enum):
    """Enumeration of standard ASG node types across backend domain concepts."""
    CLASS = "CLASS"
    INTERFACE = "INTERFACE"
    ENTITY = "ENTITY"         # ORM Model
    ENDPOINT = "ENDPOINT"     # API Route / Endpoint
    MODULE = "MODULE"         # Module / Source File
    PACKAGE = "PACKAGE"       # Package / Namespace
    SERVICE = "SERVICE"       # Business Service / Controller


@dataclass
class ASGAttribute:
    """Represents a property or database column on a node."""
    name: str
    type_annotation: str = ""
    is_primary_key: bool = False
    is_nullable: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type_annotation": self.type_annotation,
            "is_primary_key": self.is_primary_key,
            "is_nullable": self.is_nullable,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ASGAttribute":
        return cls(
            name=data.get("name", ""),
            type_annotation=data.get("type_annotation", ""),
            is_primary_key=data.get("is_primary_key", False),
            is_nullable=data.get("is_nullable", True),
        )


@dataclass
class ASGMethod:
    """Represents a method, function, or handler on a node."""
    name: str
    parameters: List[str] = field(default_factory=list)
    return_type: str = "Any"
    visibility: str = "public"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "parameters": list(self.parameters),
            "return_type": self.return_type,
            "visibility": self.visibility,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ASGMethod":
        return cls(
            name=data.get("name", ""),
            parameters=list(data.get("parameters", [])),
            return_type=data.get("return_type", "Any"),
            visibility=data.get("visibility", "public"),
        )


@dataclass
class ASGNode:
    """
    Core vertex in the Abstract Semantic Graph.

    Attributes:
        id: Unique node identifier (e.g. "app.models.User").
        name: Short display name (e.g. "User").
        kind: Categorical NodeKind.
        module: Module path or package location.
        attributes: List of fields/columns/properties.
        methods: List of member functions/methods.
        metadata: Framework-specific parameters, source file, line numbers, etc.
    """
    id: str
    name: str
    kind: NodeKind
    module: str = ""
    attributes: List[ASGAttribute] = field(default_factory=list)
    methods: List[ASGMethod] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        kind_val = self.kind.value if isinstance(self.kind, NodeKind) else str(self.kind)
        return {
            "id": self.id,
            "name": self.name,
            "kind": kind_val,
            "module": self.module,
            "attributes": [attr.to_dict() for attr in self.attributes],
            "methods": [method.to_dict() for method in self.methods],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ASGNode":
        raw_kind = data.get("kind", NodeKind.CLASS.value)
        try:
            kind_enum = NodeKind(raw_kind)
        except ValueError:
            kind_enum = NodeKind.CLASS

        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            kind=kind_enum,
            module=data.get("module", ""),
            attributes=[
                ASGAttribute.from_dict(attr) for attr in data.get("attributes", [])
            ],
            methods=[
                ASGMethod.from_dict(method) for method in data.get("methods", [])
            ],
            metadata=dict(data.get("metadata", {})),
        )
