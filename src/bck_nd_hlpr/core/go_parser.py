"""Go UML extraction with an optional Tree-sitter visitor and safe fallback."""
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

GO_EXTENSIONS = (".go",)
PARSER = load_grammar("tree_sitter_go")

_GO_TYPE_BLOCK = re.compile(
    r"\btype\s+(?P<name>[A-Za-z_]\w*)\s+(?P<kind>struct|interface)\s*\{",
    re.MULTILINE,
)
_GO_RECEIVER_METHOD = re.compile(
    r"\bfunc\s*\(\s*[A-Za-z_]\w*\s+\*?(?P<receiver>[A-Za-z_]\w*)"
    r"(?:\s*\[[^\]]+\])?\s*\)\s*(?P<name>[A-Za-z_]\w*)\s*\(",
    re.MULTILINE,
)


def _new_class(name: str, module: str, stereotype: Optional[str] = None) -> UMLClassInfo:
    info = UMLClassInfo(name, [], module)
    info.stereotypes = [stereotype] if stereotype else []
    info.is_interface = stereotype == "interface"
    info.metadata = {"language": "go"}
    return info


def _merge_classes(*groups: Iterable[UMLClassInfo]) -> list[UMLClassInfo]:
    """Merge visitor and fallback results without duplicating declarations."""
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
    for raw_field in split_top_level(body, ";\n"):
        field = compact(mask_non_code(raw_field))
        if not field:
            continue
        match = re.match(
            r"^(?P<names>[A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s+(?P<type>.+)$",
            field,
        )
        if not match:
            # Embedded fields have no explicit field name.
            attributes.append(field)
            continue
        field_type = compact(match.group("type"))
        for name in re.split(r"\s*,\s*", match.group("names")):
            attribute = f"{field_type} {name}"
            if attribute not in attributes:
                attributes.append(attribute)
    return attributes


def _parse_interface_methods(body: str) -> list[str]:
    methods: list[str] = []
    for raw_member in split_top_level(body, ";\n"):
        member = compact(mask_non_code(raw_member))
        if not member:
            continue
        match = re.match(
            r"^(?P<name>[A-Za-z_]\w*)\s*\((?P<params>.*)\)\s*(?P<result>.*)$",
            member,
        )
        if match:
            signature = f"{match.group('name')}({compact(match.group('params'))})"
            result = compact(match.group("result"))
            if result:
                signature += f" {result}"
            methods.append(signature)
        else:
            # Embedded interface names are represented as UML bases.
            methods.append(member)
    return methods


def _parse_go_types(source: str, module: str) -> list[UMLClassInfo]:
    classes: list[UMLClassInfo] = []
    for match, body in iter_balanced_blocks(source, _GO_TYPE_BLOCK):
        kind = match.group("kind")
        info = _new_class(
            match.group("name"),
            module,
            "interface" if kind == "interface" else "struct",
        )
        if kind == "struct":
            info.attributes.extend(_parse_struct_fields(body))
        else:
            info.methods.extend(_parse_interface_methods(body))
        classes.append(info)
    return classes


def _parse_receiver_methods(source: str) -> dict[str, list[str]]:
    methods: dict[str, list[str]] = {}
    masked = mask_non_code(source)
    for match in _GO_RECEIVER_METHOD.finditer(masked):
        params_open = match.end() - 1
        params_close = find_matching(masked, params_open, "(", ")")
        if params_close < 0:
            continue
        body_open = masked.find("{", params_close + 1)
        if body_open < 0:
            continue
        params = compact(mask_non_code(source[params_open + 1:params_close]))
        result = compact(mask_non_code(source[params_close + 1:body_open]))
        signature = f"{match.group('name')}({params})"
        if result:
            signature += f" {result}"
        methods.setdefault(match.group("receiver"), []).append(signature)
    return methods


def _parse_go_fallback(source: str, module: str) -> list[UMLClassInfo]:
    classes = _parse_go_types(source, module)
    by_name = {item.name: item for item in classes}
    for receiver, signatures in _parse_receiver_methods(source).items():
        target = by_name.get(receiver)
        if target is None:
            # Go permits a type and its receiver methods to live in separate
            # files of the same package.  A lightweight descriptor lets the
            # project-level merge attach those methods to the declaration.
            target = _new_class(receiver, module, "struct")
            by_name[receiver] = target
            classes.append(target)
        for signature in signatures:
            if signature not in target.methods:
                target.methods.append(signature)
    return classes


class GoUMLVisitor(BaseTreeSitterVisitor):
    """Tree-sitter visitor that emits the same model as the fallback parser."""

    def __init__(self, source_bytes: bytes, module: str):
        super().__init__(source_bytes)
        self.module = module
        self.classes: list[UMLClassInfo] = []
        self.receiver_methods: dict[str, list[str]] = {}

    def visit_type_spec(self, node):
        declaration = self.text(node)
        # In tree-sitter-go the ``type_spec`` node normally starts at the type
        # name; the parent ``type_declaration`` owns the ``type`` keyword.
        if not re.match(r"^\s*type\b", declaration):
            declaration = f"type {declaration}"
        self.classes = _merge_classes(
            self.classes,
            _parse_go_types(declaration, self.module),
        )
        return None

    def visit_method_declaration(self, node):
        for receiver, signatures in _parse_receiver_methods(self.text(node)).items():
            bucket = self.receiver_methods.setdefault(receiver, [])
            for signature in signatures:
                if signature not in bucket:
                    bucket.append(signature)
        return None

    def finish(self) -> list[UMLClassInfo]:
        by_name = {item.name: item for item in self.classes}
        for receiver, signatures in self.receiver_methods.items():
            target = by_name.get(receiver)
            if target is None:
                target = _new_class(receiver, self.module, "struct")
                by_name[receiver] = target
                self.classes.append(target)
            for signature in signatures:
                if signature not in target.methods:
                    target.methods.append(signature)
        return self.classes


def parse_go_content(source: str, module: str = "Root") -> list[UMLClassInfo]:
    """Extract UML declarations from Go source without propagating parser errors."""
    fallback = _parse_go_fallback(source, module)
    visitor_classes: list[UMLClassInfo] = []
    if PARSER is not None:
        try:
            source_bytes = source.encode("utf-8", errors="ignore")
            tree = PARSER.parse(source_bytes)
            visitor = GoUMLVisitor(source_bytes, module)
            visitor.visit(tree.root_node)
            visitor_classes = visitor.finish()
        except Exception:
            visitor_classes = []
    return _merge_classes(visitor_classes, fallback)


def parse_file_for_go_uml(
    file_path: Path,
    root_path: Optional[Path] = None,
) -> list[UMLClassInfo]:
    """Parse one ``.go`` file and return an empty list on any I/O failure."""
    try:
        path = Path(file_path)
        source = read_source_bytes(path).decode("utf-8", errors="ignore")
        relative = path.relative_to(root_path) if root_path is not None else Path(path.name)
        return parse_go_content(source, module_name_for(relative))
    except Exception:
        return []


def parse_project_for_go_uml(
    root_path: str,
    max_depth: Optional[int] = 4,
) -> list[UMLClassInfo]:
    """Parse every Go source file under a project root."""
    classes: list[UMLClassInfo] = []
    root = Path(root_path).resolve()
    for file_path, _ in walk_source_files(
        root_path,
        GO_EXTENSIONS,
        max_depth=max_depth,
    ):
        classes.extend(parse_file_for_go_uml(file_path, root))
    return _merge_classes(classes)


__all__ = [
    "GO_EXTENSIONS",
    "GoUMLVisitor",
    "parse_file_for_go_uml",
    "parse_go_content",
    "parse_project_for_go_uml",
]
