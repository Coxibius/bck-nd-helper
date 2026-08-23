"""Rust UML extraction with an optional Tree-sitter visitor and safe fallback."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Optional

from bck_nd_hlpr.core.compiled_parser_utils import (
    compact,
    find_matching,
    iter_balanced_blocks,
    mask_non_code,
    split_top_level,
)
from bck_nd_hlpr.core.ts_base import (
    BaseTreeSitterVisitor,
    load_grammar,
    module_name_for,
    read_source_bytes,
    walk_source_files,
)
from bck_nd_hlpr.core.uml_parser import UMLClassInfo

RUST_EXTENSIONS = (".rs",)
PARSER = load_grammar("tree_sitter_rust")

_RUST_TYPE_BLOCK = re.compile(
    r"\b(?:pub(?:\s*\([^)]*\))?\s+)?(?P<kind>struct|enum|trait)\s+"
    r"(?P<name>[A-Za-z_]\w*)(?:\s*<[^{};]*>)?(?:\s*:[^{]+)?\s*\{",
    re.MULTILINE,
)
_RUST_IMPL_BLOCK = re.compile(
    r"\bimpl(?:\s*<[^{};]*>)?\s+"
    r"(?:(?:[A-Za-z_]\w*(?:::\w+)*(?:\s*<[^{};]*>)?)\s+for\s+)?"
    r"(?P<name>[A-Za-z_]\w*)(?:\s*<[^{};]*>)?(?:\s+where\s+[^{]+)?\s*\{",
    re.MULTILINE,
)
_RUST_FUNCTION = re.compile(
    r"\b(?:pub(?:\s*\([^)]*\))?\s+)?(?:async\s+)?(?:unsafe\s+)?"
    r"fn\s+(?P<name>[A-Za-z_]\w*)\s*(?:<[^{};()]*>)?\s*\(",
    re.MULTILINE,
)


def _new_class(name: str, module: str, stereotype: str) -> UMLClassInfo:
    info = UMLClassInfo(name, [], module)
    info.stereotypes = [stereotype]
    if stereotype == "trait":
        info.stereotypes.append("interface")
    info.is_interface = stereotype == "trait"
    info.metadata = {"language": "rust", "kind": stereotype}
    return info


def _merge_classes(*groups: Iterable[UMLClassInfo]) -> list[UMLClassInfo]:
    merged: dict[tuple[str, str], UMLClassInfo] = {}
    for group in groups:
        for item in group:
            key = (item.module, item.name)
            current = merged.get(key)
            if current is None:
                merged[key] = item
                continue
            for attr in item.attributes:
                if attr not in current.attributes:
                    current.attributes.append(attr)
            for method in item.methods:
                if method not in current.methods:
                    current.methods.append(method)
            for base in item.bases:
                if base not in current.bases:
                    current.bases.append(base)
            current.is_interface = bool(
                getattr(current, "is_interface", False)
                or getattr(item, "is_interface", False)
            )
            stereotypes = list(getattr(current, "stereotypes", []) or [])
            for stereotype in getattr(item, "stereotypes", []) or []:
                if stereotype not in stereotypes:
                    stereotypes.append(stereotype)
            current.stereotypes = stereotypes
            metadata = dict(getattr(current, "metadata", {}) or {})
            metadata.update(getattr(item, "metadata", {}) or {})
            current.metadata = metadata
    return list(merged.values())


def _parse_struct_fields(body: str) -> list[str]:
    attributes: list[str] = []
    for raw_field in split_top_level(body, ","):
        field = re.sub(r"#\s*\[[^\]]*\]", " ", raw_field)
        field = compact(mask_non_code(field))
        if not field:
            continue
        match = re.match(
            r"^(?:pub(?:\s*\([^)]*\))?\s+)?(?P<name>[A-Za-z_]\w*)\s*:\s*(?P<type>.+)$",
            field,
        )
        if match:
            attribute = f"{match.group('name')}: {compact(match.group('type'))}"
            if attribute not in attributes:
                attributes.append(attribute)
    return attributes


def _parse_enum_variants(body: str) -> list[str]:
    variants: list[str] = []
    for raw_variant in split_top_level(body, ","):
        variant = compact(mask_non_code(raw_variant))
        if not variant:
            continue
        match = re.match(r"^(?P<name>[A-Za-z_]\w*)", variant)
        if match:
            value = f"variant {match.group('name')}"
            if value not in variants:
                variants.append(value)
    return variants


def _extract_functions(body: str) -> list[str]:
    methods: list[str] = []
    masked = mask_non_code(body)
    for match in _RUST_FUNCTION.finditer(masked):
        params_open = match.end() - 1
        params_close = find_matching(masked, params_open, "(", ")")
        if params_close < 0:
            continue
        block_index = masked.find("{", params_close + 1)
        semicolon_index = masked.find(";", params_close + 1)
        candidates = [index for index in (block_index, semicolon_index) if index >= 0]
        end_index = min(candidates) if candidates else len(body)
        params = compact(mask_non_code(body[params_open + 1:params_close]))
        suffix = compact(mask_non_code(body[params_close + 1:end_index]))
        signature = f"{match.group('name')}({params})"
        if suffix:
            signature += f" {suffix}"
        if signature not in methods:
            methods.append(signature)
    return methods


def _parse_rust_types(source: str, module: str) -> list[UMLClassInfo]:
    classes: list[UMLClassInfo] = []
    for match, body in iter_balanced_blocks(source, _RUST_TYPE_BLOCK):
        kind = match.group("kind")
        info = _new_class(match.group("name"), module, kind)
        if kind == "struct":
            info.attributes.extend(_parse_struct_fields(body))
        elif kind == "enum":
            info.attributes.extend(_parse_enum_variants(body))
        else:
            info.methods.extend(_extract_functions(body))
        classes.append(info)
    return classes


def _parse_impl_methods(source: str) -> dict[str, list[str]]:
    methods: dict[str, list[str]] = {}
    for match, body in iter_balanced_blocks(source, _RUST_IMPL_BLOCK):
        methods.setdefault(match.group("name"), []).extend(_extract_functions(body))
    return methods


def _parse_rust_fallback(source: str, module: str) -> list[UMLClassInfo]:
    classes = _parse_rust_types(source, module)
    by_name = {item.name: item for item in classes}
    for target_name, signatures in _parse_impl_methods(source).items():
        target = by_name.get(target_name)
        if target is None:
            # An impl can be stored separately from its type declaration.  A
            # descriptor with the same module/name is merged at project level.
            target = _new_class(target_name, module, "struct")
            by_name[target_name] = target
            classes.append(target)
        for signature in signatures:
            if signature not in target.methods:
                target.methods.append(signature)
    return classes


class RustUMLVisitor(BaseTreeSitterVisitor):
    """Tree-sitter visitor for structs, enums, traits, and impl methods."""

    def __init__(self, source_bytes: bytes, module: str):
        super().__init__(source_bytes)
        self.module = module
        self.classes: list[UMLClassInfo] = []
        self.impl_methods: dict[str, list[str]] = {}

    def _visit_type_item(self, node) -> None:
        self.classes = _merge_classes(
            self.classes,
            _parse_rust_types(self.text(node), self.module),
        )

    def visit_struct_item(self, node):
        self._visit_type_item(node)
        return None

    def visit_enum_item(self, node):
        self._visit_type_item(node)
        return None

    def visit_trait_item(self, node):
        self._visit_type_item(node)
        return None

    def visit_impl_item(self, node):
        for target, signatures in _parse_impl_methods(self.text(node)).items():
            bucket = self.impl_methods.setdefault(target, [])
            for signature in signatures:
                if signature not in bucket:
                    bucket.append(signature)
        return None

    def finish(self) -> list[UMLClassInfo]:
        by_name = {item.name: item for item in self.classes}
        for target_name, signatures in self.impl_methods.items():
            target = by_name.get(target_name)
            if target is None:
                target = _new_class(target_name, self.module, "struct")
                by_name[target_name] = target
                self.classes.append(target)
            for signature in signatures:
                if signature not in target.methods:
                    target.methods.append(signature)
        return self.classes


def parse_rust_content(source: str, module: str = "Root") -> list[UMLClassInfo]:
    """Extract UML declarations from Rust source without propagating errors."""
    fallback = _parse_rust_fallback(source, module)
    visitor_classes: list[UMLClassInfo] = []
    if PARSER is not None:
        try:
            source_bytes = source.encode("utf-8", errors="ignore")
            tree = PARSER.parse(source_bytes)
            visitor = RustUMLVisitor(source_bytes, module)
            visitor.visit(tree.root_node)
            visitor_classes = visitor.finish()
        except Exception:
            visitor_classes = []
    return _merge_classes(visitor_classes, fallback)


def parse_file_for_rust_uml(
    file_path: Path,
    root_path: Optional[Path] = None,
) -> list[UMLClassInfo]:
    """Parse one ``.rs`` file and return an empty list on any I/O failure."""
    try:
        path = Path(file_path)
        source = read_source_bytes(path).decode("utf-8", errors="ignore")
        relative = path.relative_to(root_path) if root_path is not None else Path(path.name)
        return parse_rust_content(source, module_name_for(relative))
    except Exception:
        return []


def parse_project_for_rust_uml(
    root_path: str,
    max_depth: Optional[int] = 4,
) -> list[UMLClassInfo]:
    """Parse every Rust source file under a project root."""
    classes: list[UMLClassInfo] = []
    root = Path(root_path).resolve()
    for file_path, _ in walk_source_files(
        root_path,
        RUST_EXTENSIONS,
        max_depth=max_depth,
    ):
        classes.extend(parse_file_for_rust_uml(file_path, root))
    return _merge_classes(classes)


__all__ = [
    "RUST_EXTENSIONS",
    "RustUMLVisitor",
    "parse_file_for_rust_uml",
    "parse_project_for_rust_uml",
    "parse_rust_content",
]
