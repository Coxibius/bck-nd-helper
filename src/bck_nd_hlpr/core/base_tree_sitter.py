"""
base_tree_sitter — shared tree-sitter infrastructure.

Contains the :class:`BaseTreeSitterVisitor` base class (visitor pattern)
and module-level utility functions used by all language-specific parsers.
"""
from __future__ import annotations

import logging
import warnings
import os
from pathlib import Path
from typing import List, Optional, Tuple, Generator

import tree_sitter

_log = logging.getLogger(__name__)

from bck_nd_hlpr.core.constants import GLOBAL_IGNORE_DIRS


# =====================================================================
# Module-level utility functions
# =====================================================================

def get_node_text(node: tree_sitter.Node, source_bytes: bytes) -> str:
    """Extract the source text for a given tree-sitter node."""
    return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")


def load_grammar(module_name: str) -> Optional[tree_sitter.Parser]:
    """
    Import a tree-sitter grammar by its Python package name and return a
    ready-to-use :class:`tree_sitter.Parser`, or *None* on failure.

    Example::

        PARSER = load_grammar("tree_sitter_c_sharp")
        PARSER = load_grammar("tree_sitter_javascript")
    """
    try:
        import importlib
        mod = importlib.import_module(module_name)
        # Modules expose either ``language()`` or ``language_<name>()``.
        lang_fn = getattr(mod, "language", None)
        if lang_fn is None:
            # e.g. tree_sitter_php exposes language_php()
            for attr in dir(mod):
                if attr.startswith("language"):
                    lang_fn = getattr(mod, attr)
                    break
        if lang_fn is None:
            return None
        language = tree_sitter.Language(lang_fn())
        return tree_sitter.Parser(language)
    except Exception:
        return None


def module_name_for(rel_path) -> str:
    """Convert a relative file path to a dotted module name string."""
    p = Path(rel_path)
    module = str(p.parent).replace(os.sep, ".")
    if module == ".":
        module = "Root"
    return module


def read_source_bytes(file_path) -> bytes:
    """Read a source file and return its contents as UTF-8 bytes."""
    from bck_nd_hlpr.core.utils.cache import FileCache
    content = FileCache.read_file(file_path, encoding="utf-8", errors="ignore")
    return content.encode("utf-8")


def walk_source_files(
    root_path: str,
    extensions: Tuple[str, ...],
    *,
    max_depth: int = 4,
) -> Generator[Tuple[Path, Path], None, None]:
    """
    Walk *root_path* yielding ``(absolute_path, relative_path)`` for every
    file whose suffix is in *extensions*, respecting GLOBAL_IGNORE_DIRS and
    *max_depth*.
    """
    root = Path(root_path)
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS]
        try:
            current_depth = len(Path(dirpath).relative_to(root).parts)
        except ValueError:
            current_depth = 0
        if current_depth > max_depth:
            continue
        for fname in files:
            if fname.endswith(extensions):
                abs_path = Path(dirpath) / fname
                rel_path = abs_path.relative_to(root)
                yield abs_path, rel_path


# =====================================================================
# BaseTreeSitterVisitor class
# =====================================================================

# TODO(audit): Implement graceful error degradation logic for unhandled Tree-sitter ERROR nodes.
# TODO(audit): When a node.type == 'ERROR' is encountered during traversal, log a non-fatal warning with
# TODO(audit): the surrounding source context (line numbers, node snippet) and continue traversing the
# TODO(audit): next sibling instead of propagating AttributeError or KeyError crashes up the visitor stack.
class BaseTreeSitterVisitor:
    def __init__(self, source_bytes: bytes):
        self.source_bytes = source_bytes

    def visit(self, node):
        if node is None:
            return None
        # TODO(audit): Add explicit visit_ERROR handler here that records error metrics and
        # TODO(audit): short-circuits problematic subtrees, then falls through to generic_visit siblings.
        if node.type == "ERROR":
            _log.debug(
                "Skipping ERROR node at line %d in %s",
                getattr(node, "start_point", (0,))[0] + 1,
                type(self).__name__,
            )
            return None
        method_name = f"visit_{node.type}"
        visitor = getattr(self, method_name, self.generic_visit)
        return visitor(node)

    def generic_visit(self, node):
        results = []
        for child in getattr(node, "children", []) or []:
            res = self.visit(child)
            if res is not None:
                results.append(res)
        return results

    def text(self, node):
        if node is None:
            return ""
        return self.source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")

    def child(self, node, node_type: str):
        if node is None:
            return None
        for c in getattr(node, "children", []) or []:
            if c.type == node_type:
                return c
        return None

    def children(self, node, node_type: str):
        if node is None:
            return []
        return [c for c in (getattr(node, "children", []) or []) if c.type == node_type]

    def descendants(self, node, node_type: str):
        matches = []

        def _walk(n):
            for c in getattr(n, "children", []) or []:
                if c.type == node_type:
                    matches.append(c)
                _walk(c)

        if node is not None:
            _walk(node)
        return matches

    def _log_syntax_warning(self, node, message: str) -> None:
        """Emit a non-fatal parse warning using :func:`warnings.warn`.

        Reports *message* as a :class:`SyntaxWarning` with the node's start-line
        so callers can filter or suppress it via the standard :mod:`warnings` API.
        Also logs at ``DEBUG`` level for structured log consumers.

        Example usage inside a visitor::

            self._log_syntax_warning(node, "unexpected nullable column type")
        """
        line = 0
        try:
            line = getattr(node, "start_point", (0,))[0] + 1
        except Exception:
            pass
        location = f" (line {line})" if line else ""
        full_msg = f"[{type(self).__name__}]{location}: {message}"
        warnings.warn(full_msg, SyntaxWarning, stacklevel=2)
        _log.debug(full_msg)


# =====================================================================
# Capa de Compatibilidad Global (Fuera de la clase)
# =====================================================================

def find_all_descendants(node, node_type: str):
    matches = []

    def _walk(n):
        for c in getattr(n, "children", []) or []:
            if c.type == node_type:
                matches.append(c)
            _walk(c)

    if node is not None:
        _walk(node)
    return matches


def find_child_by_type(node, node_type: str):
    if node is None:
        return None
    for c in getattr(node, "children", []) or []:
        if c.type == node_type:
            return c
    return None


def find_children_by_type(node, node_type: str):
    if node is None:
        return []
    return [c for c in (getattr(node, "children", []) or []) if c.type == node_type]