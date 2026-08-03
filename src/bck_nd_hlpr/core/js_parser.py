"""
Module for static analysis of JavaScript/TypeScript code using Tree-Sitter.
Generates structures compatible with UMLClassInfo and EREntity for Node/Express (Mongoose/Sequelize).

Visitors inherit from :class:`~bck_nd_hlpr.ts_base.BaseTreeSitterVisitor`,
which centralizes tree traversal and extraction helpers.
"""
from __future__ import annotations

from typing import List, Optional

from tree_sitter import Node

from bck_nd_hlpr.core.ts_base import (
    BaseTreeSitterVisitor,
    load_grammar,
    module_name_for,
    read_source_bytes,
    walk_source_files,
)
from bck_nd_hlpr.core.uml_parser import UMLClassInfo
from bck_nd_hlpr.core.er_parser import EREntity

PARSER = load_grammar("tree_sitter_javascript")

_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"})


# TODO(audit): Implement support for TypeScript 5.x decorators (@Controller, @Injectable, @Module, etc.)
# TODO(audit): to detect NestJS dependency injection patterns and extract module/provider/controller metadata.
# TODO(audit): Add generic schema type parsing for Zod, class-validator, and TypeBox generic type inference.
class JSUMLVisitor(BaseTreeSitterVisitor):
    """Extracts classes, React components, and route handlers as UMLClassInfo."""

    def __init__(self, source_bytes: bytes, module_name: str) -> None:
        super().__init__(source_bytes)
        self.module_name = module_name
        self.classes: List[UMLClassInfo] = []
        self.current_class: Optional[UMLClassInfo] = None

    # -- dispatch handlers (convention: visit_<node_type>) ---------------

    # TODO(audit): Add a decorator_list / decorator pre-processing pass for TypeScript 5.x decorator nodes
    # TODO(audit): on class_declaration and method_definition to detect NestJS @Injectable/@Controller patterns.
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


# TODO(audit): Add support for parsing generic schema type definitions (z.object<T>, TypeBox.Type.Object<T>,
# TODO(audit): NestJS DTOs with class-validator decorators) to extract strongly-typed column definitions.
class JSERVisitor(BaseTreeSitterVisitor):
    """Detects Mongoose (`.model`) and Sequelize (`.define`) models as EREntity."""

    def __init__(self, source_bytes: bytes) -> None:
        super().__init__(source_bytes)
        self.entities: List[EREntity] = []
        self._pending_entity_name: Optional[str] = None

    # -- dispatch handlers ------------------------------------------------

    def visit_call_expression(self, node: Node) -> bool:
        # TODO(audit): Extend model detection to parse NestJS @Entity() decorators + TypeORM Repository<T>
        # TODO(audit): generic injection patterns for ER entity extraction alongside mongoose/sequelize calls.
        # Look for mongoose.model('Name', schema) or sequelize.define('Name', schema)
        self._check_model_definition(node)
        return True  # continue traversal: nested calls may exist

    def visit_decorator(self, node: Node) -> None:
        """Detect TypeORM ``@Entity()`` decorators on TypeScript classes."""
        # TODO(audit): Extend model detection to parse NestJS @Entity() decorators + TypeORM Repository<T>
        # TODO(audit): generic injection patterns for ER entity extraction alongside mongoose/sequelize calls.
        call = self.child(node, "call_expression")
        if call is None:
            # Plain @Entity without parens
            ident = self.child(node, "identifier")
            if ident and self.text(ident) == "Entity":
                self._pending_entity_name = "_entity_pending_"
            return
        func = call.child_by_field_name("function")
        if func and self.text(func) == "Entity":
            self._pending_entity_name = "_entity_pending_"

    def visit_class_declaration(self, node: Node) -> None:
        """If a preceding ``@Entity()`` decorator was found, emit an EREntity.

        Also inspects DTO-named classes for typed public field definitions.
        """
        if self._pending_entity_name is not None:
            name_node = node.child_by_field_name("name")
            if name_node:
                name = self.text(name_node)
                entity = EREntity(name)
                self.entities.append(entity)
            self._pending_entity_name = None
        else:
            # Parse generic type annotations in DTO classes (MappedType<User>, etc.)
            # TODO(audit): Add support for parsing generic schema type definitions (z.object<T>, TypeBox.Type.Object<T>,
            # TODO(audit): NestJS DTOs with class-validator decorators) to extract strongly-typed column definitions.
            name_node = node.child_by_field_name("name")
            if name_node:
                class_name = self.text(name_node)
                _dto_suffixes = ("Dto", "DTO", "Response", "Request")
                if any(class_name.endswith(s) for s in _dto_suffixes):
                    entity = EREntity(class_name)
                    self._parse_generic_dto_class(node, entity)
                    if entity.columns:
                        self.entities.append(entity)
        # Continue into the class body so nested call_expressions are visited.
        self.generic_visit(node)


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

    def _parse_generic_dto_class(self, node: Node, entity: EREntity) -> None:
        """Extract typed public fields from TypeScript DTO class bodies.

        Handles generic type annotations such as ``MappedType<User>`` by
        capturing the raw type text of ``public_field_definition`` nodes.
        This supports DTO classes decorated or named with Dto/DTO/Response/Request
        suffixes that carry strong TypeScript type information.
        """
        # TODO(audit): Add support for parsing generic schema type definitions (z.object<T>, TypeBox.Type.Object<T>,
        # TODO(audit): NestJS DTOs with class-validator decorators) to extract strongly-typed column definitions.
        body = node.child_by_field_name("body")
        if body is None:
            return
        for child in body.children:
            if child.type == "public_field_definition":
                name_node = child.child_by_field_name("name")
                type_node = child.child_by_field_name("type")
                if name_node:
                    field_name = self.text(name_node)
                    field_type = self.text(type_node).lstrip(": ").strip() if type_node else "any"
                    entity.columns.append((field_name, field_type))


def parse_project_for_js_uml(root_path: str, max_depth: int = 4) -> List[UMLClassInfo]:
    if not PARSER:
        print("⚠️ Could not load Tree-Sitter parser (tree-sitter-javascript).")
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