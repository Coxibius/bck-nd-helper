"""
Module for static analysis of C# code using Tree-Sitter.
Generates structures compatible with UMLClassInfo and EREntity.
"""
from __future__ import annotations

import re
from typing import List, Optional

from tree_sitter import Node

from bck_nd_hlpr.core.base_tree_sitter import BaseTreeSitterVisitor
from bck_nd_hlpr.core.ts_base import (
    load_grammar,
    module_name_for,
    read_source_bytes,
    walk_source_files,
)
from bck_nd_hlpr.core.uml_parser import UMLClassInfo
from bck_nd_hlpr.core.er_parser import EREntity

PARSER = load_grammar("tree_sitter_c_sharp")

_CSHARP_PRIMITIVES = frozenset({
    "int", "string", "bool", "double", "float", "decimal", "DateTime",
    "Guid", "long", "short", "byte", "char", "TimeSpan", "DateTimeOffset",
})

_FOREIGN_KEY_RE = re.compile(
    r'ForeignKey\s*\(\s*["\']?(?:nameof\s*\(\s*)?([^"\')\s]+)(?:\s*\))?["\']?\s*\)'
)


# TODO(audit): Add support for C# 10 file-scoped namespaces (file_scoped_namespace_declaration) and global usings.
# TODO(audit): Add support for C# 9-12 top-level statements in unmanaged files.
class CSharpUMLVisitor(BaseTreeSitterVisitor):
    def __init__(self, source_bytes: bytes, module_name: str) -> None:
        super().__init__(source_bytes)
        self.module_name = module_name
        self.classes: List[UMLClassInfo] = []
        self.current_class: Optional[UMLClassInfo] = None

    def visit_class_declaration(self, node: Node) -> None:
        self._visit_class(node)

    # TODO(audit): Add visit_record_declaration and visit_record_struct_declaration for C# 9-12 records.
    def visit_interface_declaration(self, node: Node) -> None:
        self._visit_class(node)

    def _visit_class(self, node: Node) -> None:
        # TODO(audit): Handle C# 12 Primary Constructors on class header parameter_list.
        name_node = self.child(node, "identifier")
        if not name_node:
            return

        name = self.text(name_node)

        bases: List[str] = []
        base_list_node = self.child(node, "base_list")
        if base_list_node:
            for child in base_list_node.children:
                if child.type in ("identifier", "generic_name"):
                    bases.append(self.text(child))

        cls_info = UMLClassInfo(name, bases, self.module_name)
        self.classes.append(cls_info)

        body_node = self.child(node, "declaration_list")
        if body_node:
            self.current_class = cls_info
            for child in body_node.children:
                if child.type == "property_declaration":
                    self._visit_property(child)
                elif child.type == "method_declaration":
                    self._visit_method(child)
            self.current_class = None

    def _visit_property(self, node: Node) -> None:
        if not self.current_class:
            return

        type_node = node.child_by_field_name("type")
        id_node = node.child_by_field_name("name")

        if type_node and id_node:
            self.current_class.attributes.append(
                f"{self.text(type_node)} {self.text(id_node)}"
            )

    def _visit_method(self, node: Node) -> None:
        if not self.current_class:
            return

        name_node = self.child(node, "identifier")
        params_node = self.child(node, "parameter_list")

        if name_node and params_node:
            self.current_class.methods.append(
                f"{self.text(name_node)}{self.text(params_node)}"
            )


class CSharpERVisitor(BaseTreeSitterVisitor):
    def __init__(self, source_bytes: bytes, is_controller: bool = False) -> None:
        super().__init__(source_bytes)
        self.entities: List[EREntity] = []
        self.current_entity: Optional[EREntity] = None
        self.is_controller = is_controller

    def visit_class_declaration(self, node: Node) -> None:
        self._visit_class(node)

    def _visit_class(self, node: Node) -> None:
        name_node = self.child(node, "identifier")
        if not name_node:
            return

        name = self.text(name_node)
        self.current_entity = EREntity(name)

        body_node = self.child(node, "declaration_list")
        if body_node:
            for child in body_node.children:
                if child.type == "property_declaration":
                    self._visit_property(child)

        if self.current_entity.columns or self.current_entity.relationships:
            self.entities.append(self.current_entity)
        self.current_entity = None

    def _visit_property(self, node: Node) -> None:
        if not self.current_entity:
            return

        is_key = False
        fk_target = None

        for attr_list in self.children(node, "attribute_list"):
            for attr in self.children(attr_list, "attribute"):
                attr_name = self.text(attr).replace("[", "").replace("]", "").strip()
                if attr_name.startswith("Key"):
                    is_key = True
                elif attr_name.startswith("ForeignKey"):
                    fk_target = attr_name

        type_node = node.child_by_field_name("type")
        id_node = node.child_by_field_name("name")

        if type_node and id_node:
            t_str = self.text(type_node).strip()
            n_str = self.text(id_node).strip()

            is_relation = False
            target_class = ""
            rel_type = ""

            if "ICollection<" in t_str or "List<" in t_str or "IEnumerable<" in t_str:
                is_relation = True
                start_idx = t_str.find("<")
                end_idx = t_str.rfind(">")
                if start_idx != -1 and end_idx != -1:
                    target_class = t_str[start_idx + 1:end_idx].strip()
                rel_type = "||--o{"
            else:
                clean_type = t_str.replace("?", "").strip()
                if clean_type not in _CSHARP_PRIMITIVES:
                    is_relation = True
                    target_class = clean_type
                    rel_type = "}o--||"

            if not is_relation and fk_target:
                match = _FOREIGN_KEY_RE.search(fk_target)
                if match:
                    fk_class = match.group(1).strip()
                    is_relation = True
                    target_class = fk_class
                    rel_type = "}o--||"

            if is_relation and target_class:
                label = "FK" if fk_target else n_str
                if self.is_controller:
                    self.current_entity.relationships.append(
                        (target_class, rel_type, label, "inferred from controller/collection")
                    )
                else:
                    self.current_entity.relationships.append((target_class, rel_type, label))
            else:
                col_type = t_str
                if is_key:
                    col_type += " PK"
                self.current_entity.columns.append((n_str, col_type))


def parse_project_for_csharp_uml(root_path: str, max_depth: int = 3) -> List[UMLClassInfo]:
    if not PARSER:
        print("⚠️ Could not load Tree-Sitter parser.")
        return []

    all_classes: List[UMLClassInfo] = []
    for file_path, rel_path in walk_source_files(root_path, (".cs",), max_depth=max_depth):
        try:
            source_bytes = read_source_bytes(file_path)
            tree = PARSER.parse(source_bytes)

            visitor = CSharpUMLVisitor(source_bytes, module_name_for(rel_path))
            visitor.visit(tree.root_node)
            all_classes.extend(visitor.classes)
        except Exception:
            continue
    return all_classes


def parse_project_for_csharp_er(root_path: str, max_depth: int = 3) -> List[EREntity]:
    if not PARSER:
        print("⚠️ Could not load Tree-Sitter parser.")
        return []

    all_entities: List[EREntity] = []
    for file_path, _rel_path in walk_source_files(root_path, (".cs",), max_depth=max_depth):
        file_lower = file_path.name.lower()
        if not any(k in file_lower for k in ("model", "entity", "controller")):
            continue
        if file_lower in ("program.cs", "startup.cs"):
            continue

        is_controller = "controller" in file_lower
        try:
            source_bytes = read_source_bytes(file_path)
            tree = PARSER.parse(source_bytes)

            visitor = CSharpERVisitor(source_bytes, is_controller=is_controller)
            visitor.visit(tree.root_node)
            all_entities.extend(visitor.entities)
        except Exception:
            continue
    return all_entities