"""
ts_base — backward-compatibility shim.

The shared tree-sitter infrastructure now lives in
:mod:`bck_nd_hlpr.base_tree_sitter`. This module simply re-exports it so
existing imports (``from bck_nd_hlpr.core.ts_base import BaseTreeSitterVisitor``)
keep working. Prefer importing from ``base_tree_sitter`` in new code.
"""
# TODO(audit): Centralize TypeScript 5.x decorator extraction helpers (@Injectable, @Controller, @Module,
# TODO(audit): @Entity, etc.) and generic type parameter parsing for NestJS DI metadata and schema generics here,
# TODO(audit): so they can be shared by both js_parser.py (JS/TS visitors) and any future TS-specific parsers.
from __future__ import annotations

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

__all__ = [
    "BaseTreeSitterVisitor",
    "find_all_descendants",
    "find_child_by_type",
    "find_children_by_type",
    "get_node_text",
    "load_grammar",
    "module_name_for",
    "read_source_bytes",
    "walk_source_files",
]
