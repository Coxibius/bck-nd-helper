"""
ASG — Abstract Semantic Graph package.

Unified intermediate representation for backend topology: classes, entities,
endpoints, and their structural/ORM/architectural relationships.
"""

from bck_nd_hlpr.core.asg.nodes import (
    NodeKind,
    ASGAttribute,
    ASGMethod,
    ASGNode,
)
from bck_nd_hlpr.core.asg.edges import (
    EdgeKind,
    ASGEdge,
)
from bck_nd_hlpr.core.asg.graph import ASGGraph
from bck_nd_hlpr.core.asg.renderers import ASGToMermaidRenderer, ASGToJsonExporter
from bck_nd_hlpr.core.asg.builder import ASGBuilder

__all__ = [
    "NodeKind",
    "EdgeKind",
    "ASGNode",
    "ASGEdge",
    "ASGAttribute",
    "ASGMethod",
    "ASGGraph",
    "ASGToMermaidRenderer",
    "ASGToJsonExporter",
    "ASGBuilder",
]
