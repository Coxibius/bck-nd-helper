"""
ts_base — backward-compatibility shim.

The shared tree-sitter infrastructure now lives in
:mod:`bck_nd_hlpr.base_tree_sitter`. This module simply re-exports it so
existing imports (``from bck_nd_hlpr.core.ts_base import BaseTreeSitterVisitor``)
keep working. Prefer importing from ``base_tree_sitter`` in new code.
"""
from __future__ import annotations

from typing import List, Optional

from tree_sitter import Node

from bck_nd_hlpr.core.base_tree_sitter import (  # noqa: F401
    BaseTreeSitterVisitor,
    find_all_descendants,
    find_child_by_type,
    find_children_by_type,
    get_node_text,
    load_grammar,
    module_name_for,
    read_source_bytes,
    walk_source_files,
)

_DECORATOR_NODE_TYPES = frozenset({"decorator", "decorator_declaration"})


def is_decorator_node(node) -> bool:
    """Return *True* if *node* represents a Tree-sitter decorator node.

    Checks the node ``type`` against known decorator grammar node-type names
    (``'decorator'`` in JavaScript/TypeScript, ``'decorator_declaration'`` in
    some other grammars) and falls back to inspecting whether the raw node text
    starts with ``'@'``.
    """
    if node is None:
        return False
    if getattr(node, "type", None) in _DECORATOR_NODE_TYPES:
        return True
    try:
        raw = node.text  # bytes on some tree-sitter versions
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="ignore")
        return str(raw).lstrip().startswith("@")
    except Exception:
        return False


def _node_text(node, source_bytes: Optional[bytes] = None) -> str:
    """Extract raw text from a tree-sitter *node*."""
    try:
        if source_bytes is not None:
            return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")
        raw = getattr(node, "text", None)
        if isinstance(raw, (bytes, bytearray)):
            return raw.decode("utf-8", errors="ignore")
        if isinstance(raw, str):
            return raw
    except Exception:
        pass
    return ""


def extract_decorator_name(node) -> Optional[str]:
    """Return the clean decorator identifier name (no ``@``, no call parens).

    Handles the common Tree-sitter decorator shapes produced by
    JavaScript/TypeScript grammars::

        @Controller           →  "Controller"
        @Controller('api')    →  "Controller"
        @Entity()             →  "Entity"
        @SomeNs.Decorator     →  "Decorator"

    Returns ``None`` if *node* is not recognisable as a decorator.
    """
    if node is None:
        return None
    if not is_decorator_node(node):
        return None

    try:
        call = None
        for child in getattr(node, "children", []) or []:
            if child.type == "call_expression":
                call = child
                break
        if call is not None:
            func = call.child_by_field_name("function")
            if func is not None:
                ident = None
                for fchild in getattr(func, "children", []) or []:
                    if fchild.type in ("identifier", "member_expression"):
                        ident = fchild
                        break
                if ident is None:
                    ident = func
                if ident is not None:
                    name = _node_text(ident)
                    if "." in name:
                        name = name.rsplit(".", 1)[-1]
                    return name if name else None
        for child in getattr(node, "children", []) or []:
            if child.type == "identifier":
                name = _node_text(child)
                return name if name else None
        raw = _node_text(node).lstrip()
        if raw.startswith("@"):
            body = raw[1:].strip()
            if "(" in body:
                body = body.split("(", 1)[0].strip()
            if "." in body:
                body = body.rsplit(".", 1)[-1]
            return body or None
    except Exception:
        pass
    return None


def extract_decorator_args(node) -> List[str]:
    """Return the stringified arguments passed to a decorator call.

    Each argument is captured as its raw source text.  For string literals the
    surrounding quotes are stripped so callers receive clean values::

        @Controller('users')            →  ["users"]
        @Entity({ name: "posts" })      →  ['{ name: "posts" }']
        @JoinColumn()                   →  []
        @Injectable                     →  []
    """
    result: List[str] = []
    if node is None or not is_decorator_node(node):
        return result

    try:
        call = None
        for child in getattr(node, "children", []) or []:
            if child.type == "call_expression":
                call = child
                break
        if call is None:
            return result
        args_node = call.child_by_field_name("arguments")
        if args_node is None:
            return result
        children = getattr(args_node, "children", []) or []
        for child in children:
            if child.type in ("(", ")", "[", "]", "{", "}", ",", ";"):
                continue
            raw = _node_text(child).strip()
            if not raw:
                continue
            if len(raw) >= 2 and raw[0] in ("'", '"', "`") and raw[-1] == raw[0]:
                raw = raw[1:-1]
            result.append(raw)
    except Exception:
        pass
    return result


__all__ = [
    "BaseTreeSitterVisitor",
    "extract_decorator_args",
    "extract_decorator_name",
    "find_all_descendants",
    "find_child_by_type",
    "find_children_by_type",
    "get_node_text",
    "is_decorator_node",
    "load_grammar",
    "module_name_for",
    "read_source_bytes",
    "walk_source_files",
]
