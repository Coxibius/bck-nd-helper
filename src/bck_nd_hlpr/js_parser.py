"""
Módulo para el análisis estático de código JavaScript/TypeScript utilizando tree-sitter.
Genera estructuras compatibles con UMLClassInfo y EREntity para Node/Express (Mongoose/Sequelize).

Los visitors heredan de :class:`~bck_nd_hlpr.ts_base.BaseTreeSitterVisitor`,
que centraliza el recorrido del árbol y los helpers de extracción.
"""
from __future__ import annotations

from typing import List, Optional

from tree_sitter import Node

from bck_nd_hlpr.ts_base import (
    BaseTreeSitterVisitor,
    find_child_by_type,     # re-exported for backward compatibility
    get_node_text,          # re-exported for backward compatibility
    load_grammar,
    module_name_for,
    read_source_bytes,
    walk_source_files,
)
from bck_nd_hlpr.uml_parser import UMLClassInfo
from bck_nd_hlpr.er_parser import EREntity

PARSER = load_grammar("tree_sitter_javascript")

_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"})


class JSUMLVisitor(BaseTreeSitterVisitor):
    """Extrae clases, componentes React y route handlers como UMLClassInfo."""

    def __init__(self, source_bytes: bytes, module_name: str) -> None:
        super().__init__(source_bytes)
        self.module_name = module_name
        self.classes: List[UMLClassInfo] = []
        self.current_class: Optional[UMLClassInfo] = None

    # -- dispatch handlers (convención visit_<node_type>) ---------------

    def visit_class_declaration(self, node: Node) -> None:
        self._visit_class(node)

    def visit_function_declaration(self, node: Node) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = self.text(name_node)

        is_component = bool(name) and name[0].isupper()
        is_http_method = name in _HTTP_METHODS

        if is_component or is_http_method:
            cls_info = UMLClassInfo(name, [], self.module_name)
            params = node.child_by_field_name("parameters")
            p_text = self.text(params) if params else "()"

            if is_component:
                cls_info.methods.append(f"render{p_text}")
            else:
                cls_info.methods.append(f"handler{p_text}")

            self.classes.append(cls_info)

    def visit_lexical_declaration(self, node: Node) -> None:
        for child in node.children:
            if child.type != "variable_declarator":
                continue
            name_node = child.child_by_field_name("name")
            value_node = child.child_by_field_name("value")
            if not (name_node and value_node):
                continue

            name = self.text(name_node)
            if name and name[0].isupper() and value_node.type in ("arrow_function", "function_expression"):
                cls_info = UMLClassInfo(name, [], self.module_name)
                params = value_node.child_by_field_name("parameters")
                p_text = self.text(params) if params else "()"
                cls_info.methods.append(f"render{p_text}")
                self.classes.append(cls_info)

    # -- extraction ------------------------------------------------------

    def _visit_class(self, node: Node) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return

        name = self.text(name_node)
        bases: List[str] = []

        heritage = self.child(node, "class_heritage")
        if heritage:
            for child in heritage.children:
                if child.type == "identifier":
                    bases.append(self.text(child))

        cls_info = UMLClassInfo(name, bases, self.module_name)
        self.classes.append(cls_info)

        body_node = node.child_by_field_name("body")
        if body_node:
            self.current_class = cls_info
            for child in body_node.children:
                if child.type == "public_field_definition":
                    n = child.child_by_field_name("name")
                    if n:
                        self.current_class.attributes.append(self.text(n))
                elif child.type == "method_definition":
                    n = child.child_by_field_name("name")
                    params = child.child_by_field_name("parameters")
                    if n:
                        p_text = self.text(params) if params else "()"
                        self.current_class.methods.append(f"{self.text(n)}{p_text}")
            self.current_class = None


class JSERVisitor(BaseTreeSitterVisitor):
    """Detecta modelos Mongoose (`.model`) y Sequelize (`.define`) como EREntity."""

    def __init__(self, source_bytes: bytes) -> None:
        super().__init__(source_bytes)
        self.entities: List[EREntity] = []

    # -- dispatch handlers ------------------------------------------------

    def visit_call_expression(self, node: Node) -> bool:
        # Look for mongoose.model('Name', schema) or sequelize.define('Name', schema)
        self._check_model_definition(node)
        return True  # seguir recorriendo: pueden existir llamadas anidadas

    # -- extraction ---------------------------------------------------------

    def _check_model_definition(self, node: Node) -> None:
        func = node.child_by_field_name("function")
        args = node.child_by_field_name("arguments")
        if not func or not args:
            return

        func_text = self.text(func)

        if func_text.endswith(".model") or func_text == "model":
            # Mongoose
            if args.named_child_count >= 1:
                name_arg = args.named_child(0)
                if name_arg.type == "string":
                    name = self.text(name_arg).strip("'\"")
                    entity = EREntity(name)
                    # For mongoose, field extraction is complex because it's usually defined in a previous Schema
                    # For simplicity, we just extract the model name.
                    # If the schema is passed inline, we could parse it:
                    if args.named_child_count >= 2:
                        schema_arg = args.named_child(1)
                        self._parse_mongoose_schema(schema_arg, entity)
                    self.entities.append(entity)

        elif func_text.endswith(".define"):
            # Sequelize
            if args.named_child_count >= 2:
                name_arg = args.named_child(0)
                schema_arg = args.named_child(1)
                if name_arg.type == "string":
                    name = self.text(name_arg).strip("'\"")
                    entity = EREntity(name)
                    if schema_arg.type == "object":
                        self._parse_sequelize_schema(schema_arg, entity)
                    self.entities.append(entity)

    def _parse_mongoose_schema(self, node: Node, entity: EREntity) -> None:
        # Very basic extraction if new Schema({ ... }) is passed inline
        if node.type == "new_expression":
            args = node.child_by_field_name("arguments")
            if args and args.named_child_count > 0:
                obj = args.named_child(0)
                if obj.type == "object":
                    for pair in self.descendants(obj, "pair"):
                        key = pair.child_by_field_name("key")
                        if key:
                            entity.columns.append((self.text(key), "Field"))

    def _parse_sequelize_schema(self, node: Node, entity: EREntity) -> None:
        for pair in self.descendants(node, "pair"):
            key = pair.child_by_field_name("key")
            if key:
                # Usually depth is important to avoid nested objects, but this is a heuristic
                entity.columns.append((self.text(key), "Field"))


def parse_project_for_js_uml(root_path: str, max_depth: int = 4) -> List[UMLClassInfo]:
    if not PARSER:
        print("⚠️ No se pudo cargar tree-sitter-javascript.")
        return []

    all_classes: List[UMLClassInfo] = []
    for file_path, rel_path in walk_source_files(
        root_path, (".js", ".ts", ".jsx", ".tsx"), max_depth=max_depth
    ):
        try:
            source_bytes = read_source_bytes(file_path)
            tree = PARSER.parse(source_bytes)

            visitor = JSUMLVisitor(source_bytes, module_name_for(rel_path))
            visitor.visit(tree.root_node)
            all_classes.extend(visitor.classes)
        except Exception:
            continue
    return all_classes


def parse_project_for_js_er(root_path: str, max_depth: int = 4) -> List[EREntity]:
    if not PARSER:
        return []

    all_entities: List[EREntity] = []
    for file_path, _rel_path in walk_source_files(root_path, (".js", ".ts"), max_depth=max_depth):
        try:
            source_bytes = read_source_bytes(file_path)
            tree = PARSER.parse(source_bytes)

            visitor = JSERVisitor(source_bytes)
            visitor.visit(tree.root_node)
            all_entities.extend(visitor.entities)
        except Exception:
            continue
    return all_entities