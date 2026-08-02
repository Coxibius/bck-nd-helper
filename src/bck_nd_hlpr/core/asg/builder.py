"""
ASG Builder Adapter — Bridges legacy AST extractors and parser outputs to populate ASGGraph instances.
"""

from typing import Any, Dict, List, Optional, Union

from bck_nd_hlpr.core.asg.graph import ASGGraph
from bck_nd_hlpr.core.asg.nodes import ASGNode, NodeKind, ASGAttribute, ASGMethod
from bck_nd_hlpr.core.asg.edges import ASGEdge, EdgeKind


class ASGBuilder:
    """
    Adapter class for building unified ASG graphs from various polyglot parsers
    and legacy extractor results (UML, ER, Routes).
    """

    @staticmethod
    def from_uml_classes(
        classes_info: List[Any],
        graph: Optional[ASGGraph] = None,
    ) -> ASGGraph:
        """
        Populate ASGGraph from UML class descriptors (UMLClassInfo dataclasses or dicts).
        """
        if graph is None:
            graph = ASGGraph()

        for item in classes_info:
            # Handle dataclass or dict
            if hasattr(item, "__dict__"):
                c_name = getattr(item, "name", "")
                c_module = getattr(item, "module", "") or ""
                c_is_interface = getattr(item, "is_interface", False)
                c_attrs = getattr(item, "attributes", []) or []
                c_methods = getattr(item, "methods", []) or []
                c_parents = getattr(item, "parents", []) or []
                c_deps = getattr(item, "dependencies", []) or []
                c_meta = getattr(item, "metadata", {}) or {}
            elif isinstance(item, dict):
                c_name = item.get("name", "")
                c_module = item.get("module", "")
                c_is_interface = item.get("is_interface", False)
                c_attrs = item.get("attributes", [])
                c_methods = item.get("methods", [])
                c_parents = item.get("parents", [])
                c_deps = item.get("dependencies", [])
                c_meta = item.get("metadata", {})
            else:
                continue

            if not c_name:
                continue

            node_id = f"{c_module}.{c_name}" if c_module else c_name
            kind = NodeKind.INTERFACE if c_is_interface else NodeKind.CLASS

            # Attributes conversion
            asg_attributes = []
            for attr in c_attrs:
                if isinstance(attr, ASGAttribute):
                    asg_attributes.append(attr)
                elif isinstance(attr, dict):
                    asg_attributes.append(ASGAttribute.from_dict(attr))
                elif isinstance(attr, str):
                    asg_attributes.append(ASGAttribute(name=attr))

            # Methods conversion
            asg_methods = []
            for method in c_methods:
                if isinstance(method, ASGMethod):
                    asg_methods.append(method)
                elif isinstance(method, dict):
                    asg_methods.append(ASGMethod.from_dict(method))
                elif isinstance(method, str):
                    asg_methods.append(ASGMethod(name=method))

            node = ASGNode(
                id=node_id,
                name=c_name,
                kind=kind,
                module=c_module,
                attributes=asg_attributes,
                methods=asg_methods,
                metadata=dict(c_meta),
            )
            graph.add_node(node)

            # Parents / Inheritance
            for parent in c_parents:
                parent_id = str(parent)
                edge_kind = EdgeKind.IMPLEMENTS if c_is_interface else EdgeKind.INHERITS
                graph.add_edge(
                    ASGEdge(
                        source_id=node_id,
                        target_id=parent_id,
                        kind=edge_kind,
                    )
                )

            # Dependencies
            for dep in c_deps:
                dep_id = str(dep)
                graph.add_edge(
                    ASGEdge(
                        source_id=node_id,
                        target_id=dep_id,
                        kind=EdgeKind.DEPENDS_ON,
                    )
                )

        return graph

    @staticmethod
    def from_er_entities(
        entities_info: List[Any],
        relationships_info: Optional[List[Any]] = None,
        graph: Optional[ASGGraph] = None,
    ) -> ASGGraph:
        """
        Populate ASGGraph from ER entity descriptors and relationships.
        """
        if graph is None:
            graph = ASGGraph()

        for entity in entities_info:
            if hasattr(entity, "__dict__"):
                e_name = getattr(entity, "name", "")
                e_cols = getattr(entity, "columns", []) or getattr(entity, "attributes", [])
                e_meta = getattr(entity, "metadata", {}) or {}
            elif isinstance(entity, dict):
                e_name = entity.get("name", "")
                e_cols = entity.get("columns", []) or entity.get("attributes", [])
                e_meta = entity.get("metadata", {})
            else:
                continue

            if not e_name:
                continue

            node_id = e_name
            asg_attrs = []
            for col in e_cols:
                if isinstance(col, ASGAttribute):
                    asg_attrs.append(col)
                elif isinstance(col, dict):
                    asg_attrs.append(ASGAttribute.from_dict(col))
                elif hasattr(col, "__dict__"):
                    col_name = getattr(col, "name", str(col))
                    col_type = getattr(col, "type_annotation", "") or getattr(col, "type", "")
                    col_pk = getattr(col, "is_primary_key", False) or getattr(col, "primary_key", False)
                    col_nullable = getattr(col, "is_nullable", True) or getattr(col, "nullable", True)
                    asg_attrs.append(
                        ASGAttribute(
                            name=col_name,
                            type_annotation=str(col_type),
                            is_primary_key=bool(col_pk),
                            is_nullable=bool(col_nullable),
                        )
                    )
                elif isinstance(col, str):
                    asg_attrs.append(ASGAttribute(name=col))

            node = ASGNode(
                id=node_id,
                name=e_name,
                kind=NodeKind.ENTITY,
                attributes=asg_attrs,
                metadata=dict(e_meta),
            )
            graph.add_node(node)

        # Relationships
        if relationships_info:
            for rel in relationships_info:
                if isinstance(rel, dict):
                    src = rel.get("source", rel.get("source_id", ""))
                    tgt = rel.get("target", rel.get("target_id", ""))
                    rel_kind_raw = rel.get("kind", EdgeKind.HAS_MANY.value)
                    label = rel.get("label")
                elif hasattr(rel, "__dict__"):
                    src = getattr(rel, "source", getattr(rel, "source_id", ""))
                    tgt = getattr(rel, "target", getattr(rel, "target_id", ""))
                    rel_kind_raw = getattr(rel, "kind", EdgeKind.HAS_MANY.value)
                    label = getattr(rel, "label", None)
                else:
                    continue

                if src and tgt:
                    try:
                        edge_kind = EdgeKind(rel_kind_raw)
                    except ValueError:
                        edge_kind = EdgeKind.HAS_MANY

                    graph.add_edge(
                        ASGEdge(
                            source_id=str(src),
                            target_id=str(tgt),
                            kind=edge_kind,
                            label=label,
                        )
                    )

        return graph

    @staticmethod
    def from_routes(
        routes_info: List[Any],
        graph: Optional[ASGGraph] = None,
    ) -> ASGGraph:
        """
        Populate ASGGraph from API route definitions.
        """
        if graph is None:
            graph = ASGGraph()

        for route in routes_info:
            if isinstance(route, dict):
                r_path = route.get("path", route.get("route", ""))
                r_method = route.get("method", route.get("http_method", "GET"))
                r_handler = route.get("handler", route.get("function", ""))
                r_file = route.get("file", "")
            elif hasattr(route, "__dict__"):
                r_path = getattr(route, "path", getattr(route, "route", ""))
                r_method = getattr(route, "method", getattr(route, "http_method", "GET"))
                r_handler = getattr(route, "handler", getattr(route, "function", ""))
                r_file = getattr(route, "file", "")
            else:
                continue

            if not r_path:
                continue

            node_id = f"{r_method} {r_path}"
            node = ASGNode(
                id=node_id,
                name=f"{r_method} {r_path}",
                kind=NodeKind.ENDPOINT,
                metadata={"handler": r_handler, "file": r_file, "method": r_method, "path": r_path},
            )
            graph.add_node(node)

        return graph
