"""
ASG Renderers — Exporters to convert ASGGraph into Mermaid string diagrams and JSON format.
"""

import json
from typing import Any, Dict, List

from bck_nd_hlpr.core.asg.graph import ASGGraph
from bck_nd_hlpr.core.asg.nodes import NodeKind, ASGNode
from bck_nd_hlpr.core.asg.edges import EdgeKind, ASGEdge


class ASGToMermaidRenderer:
    """Renders ASGGraph into standard Mermaid classDiagram and erDiagram strings."""

    @staticmethod
    def render_uml(graph: ASGGraph) -> str:
        """
        Converts CLASS and INTERFACE nodes + structural/dependency edges into a valid Mermaid classDiagram.
        """
        lines: List[str] = ["classDiagram"]

        uml_kinds = {NodeKind.CLASS, NodeKind.INTERFACE, NodeKind.SERVICE}
        uml_nodes = [node for node in graph.nodes.values() if node.kind in uml_kinds]

        if not uml_nodes and not graph.edges:
            return "classDiagram\n"

        # 1. Render Nodes
        for node in uml_nodes:
            clean_name = _clean_identifier(node.name or node.id)
            lines.append(f"    class {clean_name} {{")

            if node.kind == NodeKind.INTERFACE:
                lines.append("        <<interface>>")

            for attr in node.attributes:
                vis = _format_visibility(getattr(attr, "visibility", "public"))
                type_str = f" {attr.type_annotation}" if attr.type_annotation else ""
                lines.append(f"        {vis}{clean_name_type(type_str)} {attr.name}".strip())

            for method in node.methods:
                vis = _format_visibility(method.visibility)
                params_str = ", ".join(method.parameters)
                ret_str = f" {method.return_type}" if method.return_type and method.return_type != "Any" else ""
                lines.append(f"        {vis}{method.name}({params_str}){ret_str}".strip())

            lines.append("    }")

        # 2. Render Edges
        uml_edge_kinds = {EdgeKind.INHERITS, EdgeKind.IMPLEMENTS, EdgeKind.DEPENDS_ON}
        rendered_edges = set()

        for edge in graph.edges:
            if edge.kind not in uml_edge_kinds:
                continue

            src_node = graph.get_node(edge.source_id)
            tgt_node = graph.get_node(edge.target_id)

            src_name = _clean_identifier(src_node.name if src_node else edge.source_id)
            tgt_name = _clean_identifier(tgt_node.name if tgt_node else edge.target_id)

            edge_key = (src_name, tgt_name, edge.kind.value, edge.label)
            if edge_key in rendered_edges:
                continue
            rendered_edges.add(edge_key)

            label_str = f" : {edge.label}" if edge.label else ""

            if edge.kind == EdgeKind.INHERITS:
                # Inheritance: Target <|-- Source
                lines.append(f"    {tgt_name} <|-- {src_name}{label_str}")
            elif edge.kind == EdgeKind.IMPLEMENTS:
                # Realization: Target <|.. Source
                lines.append(f"    {tgt_name} <|.. {src_name}{label_str}")
            elif edge.kind == EdgeKind.DEPENDS_ON:
                # Dependency: Source ..> Target
                lines.append(f"    {src_name} ..> {tgt_name}{label_str}")

        return "\n".join(lines)

    @staticmethod
    def render_er(graph: ASGGraph) -> str:
        """
        Converts ENTITY nodes + ORM edges (HAS_ONE, HAS_MANY, etc.) into a valid Mermaid erDiagram.
        """
        lines: List[str] = ["erDiagram"]

        er_nodes = [node for node in graph.nodes.values() if node.kind == NodeKind.ENTITY]

        if not er_nodes and not graph.edges:
            return "erDiagram\n"

        # 1. Render Entities
        for node in er_nodes:
            clean_name = _clean_identifier(node.name or node.id).upper()
            lines.append(f"    {clean_name} {{")

            for attr in node.attributes:
                type_name = attr.type_annotation or "string"
                attr_name = attr.name
                key_marker = ""
                if attr.is_primary_key:
                    key_marker = " PK"
                elif "FK" in attr.name.upper() or attr.name.endswith("_id"):
                    key_marker = " FK"

                lines.append(f"        {type_name} {attr_name}{key_marker}")

            lines.append("    }")

        # 2. Render ER Edges
        er_edge_kinds = {
            EdgeKind.HAS_ONE,
            EdgeKind.HAS_MANY,
            EdgeKind.BELONGS_TO,
            EdgeKind.MANY_TO_MANY,
        }
        rendered_edges = set()

        for edge in graph.edges:
            if edge.kind not in er_edge_kinds:
                continue

            src_node = graph.get_node(edge.source_id)
            tgt_node = graph.get_node(edge.target_id)

            src_name = _clean_identifier(src_node.name if src_node else edge.source_id).upper()
            tgt_name = _clean_identifier(tgt_node.name if tgt_node else edge.target_id).upper()

            edge_key = (src_name, tgt_name, edge.kind.value, edge.label)
            if edge_key in rendered_edges:
                continue
            rendered_edges.add(edge_key)

            label_text = f'"{edge.label}"' if edge.label else '"relates to"'

            if edge.kind == EdgeKind.HAS_ONE:
                lines.append(f"    {src_name} ||--|| {tgt_name} : {label_text}")
            elif edge.kind == EdgeKind.HAS_MANY:
                lines.append(f"    {src_name} ||--|{{ {tgt_name} : {label_text}")
            elif edge.kind == EdgeKind.BELONGS_TO:
                lines.append(f"    {src_name} }}|--|| {tgt_name} : {label_text}")
            elif edge.kind == EdgeKind.MANY_TO_MANY:
                lines.append(f"    {src_name} }}|--|{{ {tgt_name} : {label_text}")

        return "\n".join(lines)


class ASGToJsonExporter:
    """Exporter for serializing ASGGraph into JSON for MCP server or AI context dumping."""

    @staticmethod
    def export_json(graph: ASGGraph, indent: int = 2) -> str:
        """Serializes ASGGraph into a formatted JSON string."""
        return json.dumps(graph.to_dict(), indent=indent)

    @staticmethod
    def to_dict(graph: ASGGraph) -> Dict[str, Any]:
        """Returns the dictionary representation of ASGGraph."""
        return graph.to_dict()


def _clean_identifier(name: str) -> str:
    """Strips non-alphanumeric characters for valid Mermaid syntax identifiers."""
    cleaned = "".join(c if c.isalnum() or c == "_" else "_" for c in name)
    return cleaned or "Unnamed"


def clean_name_type(type_str: str) -> str:
    return type_str.replace("<", "~").replace(">", "~").strip()


def _format_visibility(vis: str) -> str:
    vis_map = {
        "public": "+",
        "private": "-",
        "protected": "#",
        "internal": "~",
        "package": "~",
    }
    return vis_map.get(str(vis).lower(), "+")
