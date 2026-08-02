"""
ASG Graph Container — The in-memory graph representing nodes and edges with querying, merging, and serialization.
"""

from dataclasses import dataclass, field
import threading
from typing import Any, Dict, List, Optional, Set, Tuple

from bck_nd_hlpr.core.asg.nodes import ASGNode, NodeKind, ASGAttribute, ASGMethod
from bck_nd_hlpr.core.asg.edges import ASGEdge, EdgeKind


class ASGGraph:
    """
    Unified Abstract Semantic Graph (ASG) IR.

    Provides a thread-safe in-memory graph store for program topology, models, routes,
    and architectural elements, with support for JSON serialization.
    """

    def __init__(
        self,
        nodes: Optional[Dict[str, ASGNode]] = None,
        edges: Optional[List[ASGEdge]] = None,
    ):
        self._nodes: Dict[str, ASGNode] = nodes if nodes is not None else {}
        self._edges: List[ASGEdge] = edges if edges is not None else []
        self._lock = threading.RLock()

    @property
    def nodes(self) -> Dict[str, ASGNode]:
        """Returns a shallow copy of nodes dict."""
        with self._lock:
            return dict(self._nodes)

    @property
    def edges(self) -> List[ASGEdge]:
        """Returns a copy of edges list."""
        with self._lock:
            return list(self._edges)

    def add_node(self, node: ASGNode) -> ASGNode:
        """
        Add or update a node in the graph.

        If a node with the same ID already exists, merges attributes, methods, and metadata.
        """
        with self._lock:
            if node.id in self._nodes:
                existing = self._nodes[node.id]
                # Merge attributes (dedup by name)
                attr_names = {a.name for a in existing.attributes}
                for new_attr in node.attributes:
                    if new_attr.name not in attr_names:
                        existing.attributes.append(new_attr)
                        attr_names.add(new_attr.name)

                # Merge methods (dedup by name)
                method_names = {m.name for m in existing.methods}
                for new_method in node.methods:
                    if new_method.name not in method_names:
                        existing.methods.append(new_method)
                        method_names.add(new_method.name)

                # Merge metadata
                existing.metadata.update(node.metadata)
                return existing
            else:
                self._nodes[node.id] = node
                return node

    def add_edge(self, edge: ASGEdge) -> None:
        """Add an edge if an identical directed edge does not already exist."""
        with self._lock:
            # Check for existing duplicate edge
            for existing in self._edges:
                if (
                    existing.source_id == edge.source_id
                    and existing.target_id == edge.target_id
                    and existing.kind == edge.kind
                    and existing.label == edge.label
                ):
                    return
            self._edges.append(edge)

    def get_node(self, node_id: str) -> Optional[ASGNode]:
        """Retrieve node by unique ID."""
        with self._lock:
            return self._nodes.get(node_id)

    def get_nodes_by_kind(self, kind: NodeKind) -> List[ASGNode]:
        """Retrieve all nodes matching the given NodeKind."""
        with self._lock:
            return [node for node in self._nodes.values() if node.kind == kind]

    def get_outgoing_edges(self, source_id: str) -> List[ASGEdge]:
        """Retrieve all outgoing edges from source_id."""
        with self._lock:
            return [edge for edge in self._edges if edge.source_id == source_id]

    def get_incoming_edges(self, target_id: str) -> List[ASGEdge]:
        """Retrieve all incoming edges to target_id."""
        with self._lock:
            return [edge for edge in self._edges if edge.target_id == target_id]

    def merge(self, other_graph: "ASGGraph") -> None:
        """
        Merge another ASGGraph into this graph in a thread-safe manner.

        Nodes with matching IDs are merged, and non-duplicate edges are added.
        """
        if not other_graph:
            return

        with self._lock, other_graph._lock:
            for node in other_graph._nodes.values():
                self.add_node(node)
            for edge in other_graph._edges:
                self.add_edge(edge)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize graph to a Python dictionary."""
        with self._lock:
            return {
                "nodes": [node.to_dict() for node in self._nodes.values()],
                "edges": [edge.to_dict() for edge in self._edges],
            }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ASGGraph":
        """Deserialize a dictionary representation into an ASGGraph instance."""
        graph = cls()
        raw_nodes = data.get("nodes", [])
        if isinstance(raw_nodes, dict):
            raw_nodes = list(raw_nodes.values())

        for raw_node in raw_nodes:
            node = ASGNode.from_dict(raw_node)
            graph.add_node(node)

        raw_edges = data.get("edges", [])
        for raw_edge in raw_edges:
            edge = ASGEdge.from_dict(raw_edge)
            graph.add_edge(edge)

        return graph
