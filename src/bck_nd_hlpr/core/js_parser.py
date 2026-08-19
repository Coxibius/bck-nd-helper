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
    extract_decorator_args,
    extract_decorator_name,
    is_decorator_node,
    load_grammar,
    module_name_for,
    read_source_bytes,
    walk_source_files,
)
from bck_nd_hlpr.core.uml_parser import UMLClassInfo
from bck_nd_hlpr.core.er_parser import EREntity

PARSER = load_grammar("tree_sitter_javascript")

_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"})

_ZOD_TYPE_KEYS = frozenset({
    "string", "number", "boolean", "integer", "date", "array", "object",
    "bigint", "null", "undefined", "nan", "any", "unknown", "never",
    "literal", "enum", "union", "discriminatedUnion", "intersection",
    "optional", "nullable", "default", "transform", "refine",
})

_TYPEBOX_TYPE_KEYS = frozenset({
    "String", "Number", "Boolean", "Integer", "Literal", "Array", "Object",
    "Union", "Intersect", "Optional", "Nullable", "ReadonlyOptional",
    "Readonly", "Null", "Undefined", "Any", "Unknown", "Never", "BigInt",
    "Date", "Uint8Array", "RegEx", "TemplateLiteral", "Enum", "Dict",
    "Record", "KeyOf", "Index", "Tuple",
})


def infer_schema_dto_fields(root_node) -> List[tuple[str, str]]:
    """Best-effort Zod/TypeBox schema → ``(field_name, field_type)`` inference.

    Inspects a Tree-sitter *root_node* (typically an ``object`` node) for
    Zod-style field descriptors::

        { name: z.string(), age: z.number().int().min(0) }

    and TypeBox-style declarations::

        { name: Type.String(), age: Type.Integer({ minimum: 0 }) }

    Returns a list of ``(field_name, inferred_type)`` pairs.  If the schema
    shape cannot be recognised an empty list is returned — the helper is
    intentionally defensive and never raises on malformed input.
    """
    fields: List[tuple[str, str]] = []
    if root_node is None:
        return fields
    try:
        node_type = getattr(root_node, "type", "")
        candidate_objects: List = []
        if node_type == "object":
            candidate_objects.append(root_node)
        else:
            # Fallback: look for any object node under the provided root
            def _walk(n):
                if getattr(n, "type", "") == "object":
                    candidate_objects.append(n)
                    return
                for c in getattr(n, "children", []) or []:
                    _walk(c)
            _walk(root_node)
        for obj in candidate_objects:
            for pair in (getattr(obj, "children", []) or []):
                if getattr(pair, "type", "") != "pair":
                    continue
                key_node = pair.child_by_field_name("key")
                value_node = pair.child_by_field_name("value")
                if key_node is None:
                    continue
                name = _node_text_js(key_node).strip("'\"` ")
                if not name:
                    continue
                inferred = "any"
                if value_node is not None:
                    inferred = _infer_zod_or_typebox_type(value_node)
                fields.append((name, inferred))
            if fields:
                break
    except Exception:
        return fields
    return fields


def _node_text_js(node) -> str:
    if node is None:
        return ""
    try:
        raw = getattr(node, "text", None)
        if isinstance(raw, (bytes, bytearray)):
            return raw.decode("utf-8", errors="ignore")
        if isinstance(raw, str):
            return raw
    except Exception:
        pass
    return ""


def _infer_zod_or_typebox_type(value_node) -> str:
    """Try to classify a schema call-expression as a type string."""
    if value_node is None:
        return "any"
    vt = getattr(value_node, "type", "")
    if vt in ("string", "template_string", "template_literal", "regex"):
        return "string"
    if vt in ("number",):
        return "number"
    if vt in ("true", "false"):
        return "boolean"
    if vt in ("null",):
        return "null"
    if vt in ("undefined",):
        return "undefined"
    if vt in ("array",):
        return "array"
    if vt in ("object",):
        return "object"
    # Walk the value text & child chain looking for z.<key> or Type.<Key>
    candidates_to_check: List = [value_node]
    seen: set = set()
    while candidates_to_check:
        n = candidates_to_check.pop(0)
        if n is None:
            continue
        nid = id(n)
        if nid in seen:
            continue
        seen.add(nid)
        ntype = getattr(n, "type", "")
        if ntype == "member_expression":
            prop_node = n.child_by_field_name("property") if hasattr(n, "child_by_field_name") else None
            if prop_node is not None:
                pname = _node_text_js(prop_node)
                if pname in _ZOD_TYPE_KEYS:
                    return pname
                if pname in _TYPEBOX_TYPE_KEYS:
                    return pname.lower()
            raw = _node_text_js(n)
            tail = raw.rsplit(".", 1)[-1] if "." in raw else raw
            tail_clean = tail.split("(", 1)[0].strip()
            if tail_clean in _ZOD_TYPE_KEYS:
                return tail_clean
            if tail_clean in _TYPEBOX_TYPE_KEYS:
                return tail_clean.lower()
        elif ntype in ("call_expression",):
            fn = n.child_by_field_name("function") if hasattr(n, "child_by_field_name") else None
            if fn is not None:
                candidates_to_check.append(fn)
        else:
            for c in (getattr(n, "children", []) or []):
                candidates_to_check.append(c)
    raw = _node_text_js(value_node)
    if not raw:
        return "any"
    for key in sorted(_ZOD_TYPE_KEYS, key=len, reverse=True):
        needle = f".{key}("
        if needle in raw or raw.startswith(key + "("):
            return key
    for key in sorted(_TYPEBOX_TYPE_KEYS, key=len, reverse=True):
        needle = f".{key}("
        if needle in raw or raw.startswith(key + "("):
            return key.lower()
    return "any"


class JSUMLVisitor(BaseTreeSitterVisitor):
    """Extracts classes, React components, and route handlers as UMLClassInfo."""

    def __init__(self, source_bytes: bytes, module_name: str) -> None:
        super().__init__(source_bytes)
        self.module_name = module_name
        self.classes: List[UMLClassInfo] = []
        self.current_class: Optional[UMLClassInfo] = None

    def visit_decorator(self, node: Node) -> None:
        self.generic_visit(node)

    def visit_class_declaration(self, node: Node) -> None:
        self._visit_class(node)

    def visit_interface_declaration(self, node: Node) -> None:
        self._visit_interface(node)

    def visit_type_alias_declaration(self, node: Node) -> None:
        self._visit_type_alias(node)

    def visit_export_statement(self, node: Node) -> None:
        decl = node.child_by_field_name("declaration") if hasattr(node, "child_by_field_name") else None
        if decl is not None:
            self.visit(decl)
        else:
            self.generic_visit(node)

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

    def _gather_decorator_lists(self, node: Node) -> List[List[Node]]:
        """Return decorator groups that precede *node* within its parent.

        TypeScript 5 decorators can be supplied as either a single ``@Foo``
        node before the target declaration or grouped inside a
        ``decorator_list`` grammar node.  This helper walks the parent's
        children looking for decorator nodes immediately before *node* and
        returns them grouped so callers can later merge
        ``extract_decorator_name`` / ``extract_decorator_args`` results.
        """
        groups: List[List[Node]] = []
        try:
            parent = getattr(node, "parent", None)
            if parent is None:
                return groups
            siblings = list(getattr(parent, "children", []) or [])
            try:
                idx = siblings.index(node)
            except ValueError:
                return groups
            current: List[Node] = []
            for prev in siblings[:idx]:
                if is_decorator_node(prev):
                    current.append(prev)
                elif prev.type in ("decorator_list",):
                    if current:
                        groups.append(current)
                        current = []
                    inner = [c for c in prev.children if is_decorator_node(c)]
                    if inner:
                        groups.append(inner)
                elif getattr(prev, "type", "") not in ("\n", "\r\n", "comment", "decorator"):
                    current = []
            if current:
                groups.append(current)
        except Exception:
            pass
        return groups

    def _flatten_decorators(self, node: Node) -> List[Node]:
        groups = self._gather_decorator_lists(node)
        flat: List[Node] = []
        for g in groups:
            flat.extend(g)
        return flat

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

        decorators = self._flatten_decorators(node)
        decorator_names: List[str] = []
        controller_base_path: Optional[str] = None
        for dec in decorators:
            dname = extract_decorator_name(dec)
            if dname:
                decorator_names.append(dname)
            if dname == "Controller":
                args = extract_decorator_args(dec)
                if args:
                    controller_base_path = args[0]
        if decorator_names:
            cls_info.metadata = getattr(cls_info, "metadata", {}) or {}
            cls_info.metadata["decorators"] = decorator_names
        if controller_base_path is not None:
            cls_info.metadata = getattr(cls_info, "metadata", {}) or {}
            cls_info.metadata["controller_base_path"] = controller_base_path
            cls_info.stereotypes = getattr(cls_info, "stereotypes", []) or []
            cls_info.stereotypes.append(f"controller: {controller_base_path}")

        self.classes.append(cls_info)

        body_node = node.child_by_field_name("body")
        if body_node:
            self.current_class = cls_info
            for child in body_node.children:
                if child.type == "public_field_definition":
                    field_decorators = self._flatten_decorators(child)
                    n = child.child_by_field_name("name")
                    type_node = child.child_by_field_name("type") if hasattr(child, 'child_by_field_name') else None
                    if n:
                        attr_text = self.text(n)
                        full_type = ""
                        if type_node is not None:
                            raw_t = self.text(type_node).lstrip(": ").strip()
                            if raw_t:
                                full_type = raw_t
                        prefix = ""
                        if field_decorators:
                            dn = [extract_decorator_name(d) for d in field_decorators if extract_decorator_name(d)]
                            if dn:
                                prefix = f"[{' '.join(dn)}] "
                        if full_type:
                            self.current_class.attributes.append(f"{prefix}{full_type} {attr_text}")
                        else:
                            self.current_class.attributes.append(f"{prefix}{attr_text}")
                elif child.type == "method_definition":
                    method_decorators = self._flatten_decorators(child)
                    mname = child.child_by_field_name("name")
                    params = child.child_by_field_name("parameters")
                    if mname:
                        label = self.text(mname)
                        if method_decorators:
                            names = [extract_decorator_name(d) for d in method_decorators if extract_decorator_name(d)]
                            if names:
                                label = f"[{' '.join(names)}] {label}"
                        p_text = self._render_method_params_with_decorators(params) if params else "()"
                        self.current_class.methods.append(f"{label}{p_text}")
            self.current_class = None

    def _visit_interface(self, node: Node) -> None:
        name_node = node.child_by_field_name("name") if hasattr(node, "child_by_field_name") else None
        if not name_node:
            for child in (getattr(node, "children", []) or []):
                if child.type in ("type_identifier", "identifier"):
                    name_node = child
                    break
        if not name_node:
            return

        name = self.text(name_node)
        if not name:
            return

        bases: List[str] = []
        for child in (getattr(node, "children", []) or []):
            if child.type in ("extends_type_clause", "extends_clause", "class_heritage", "heritage_clause"):
                for sub in self.descendants(child, "type_identifier") + self.descendants(child, "identifier"):
                    bname = self.text(sub)
                    if bname and bname not in bases and bname != "extends":
                        bases.append(bname)

        cls_info = UMLClassInfo(name, bases, self.module_name)
        cls_info.stereotypes = getattr(cls_info, "stereotypes", []) or []
        cls_info.stereotypes.append("interface")

        body_node = node.child_by_field_name("body") if hasattr(node, "child_by_field_name") else None
        if body_node is None:
            for child in (getattr(node, "children", []) or []):
                if child.type in ("interface_body", "object_type", "statement_block"):
                    body_node = child
                    break

        if body_node:
            for child in (getattr(body_node, "children", []) or []):
                ct = getattr(child, "type", "")
                if ct in ("property_signature", "public_field_definition", "field_definition", "pair"):
                    pname_node = child.child_by_field_name("name") or child.child_by_field_name("key") or self.child(child, "property_identifier") or self.child(child, "identifier")
                    ptype_node = child.child_by_field_name("type") or child.child_by_field_name("value") or self.child(child, "type_annotation")
                    if pname_node:
                        pname = self.text(pname_node).strip()
                        ptype = self.text(ptype_node).lstrip(": ").strip() if ptype_node else "any"
                        if ptype and ptype != "any":
                            cls_info.attributes.append(f"{ptype} {pname}")
                        else:
                            cls_info.attributes.append(pname)
                elif ct in ("method_signature", "method_definition", "call_signature"):
                    mname_node = child.child_by_field_name("name") or self.child(child, "property_identifier") or self.child(child, "identifier")
                    params_node = child.child_by_field_name("parameters") or self.child(child, "formal_parameters")
                    if mname_node:
                        mname = self.text(mname_node).strip()
                        p_text = self.text(params_node) if params_node else "()"
                        cls_info.methods.append(f"{mname}{p_text}")

        self.classes.append(cls_info)

    def _visit_type_alias(self, node: Node) -> None:
        name_node = node.child_by_field_name("name") if hasattr(node, "child_by_field_name") else None
        if not name_node:
            for child in (getattr(node, "children", []) or []):
                if child.type in ("type_identifier", "identifier"):
                    name_node = child
                    break
        if not name_node:
            return

        name = self.text(name_node)
        if not name:
            return

        cls_info = UMLClassInfo(name, [], self.module_name)
        cls_info.stereotypes = getattr(cls_info, "stereotypes", []) or []
        cls_info.stereotypes.append("type")

        value_node = node.child_by_field_name("value") if hasattr(node, "child_by_field_name") else None
        if value_node is None:
            for child in (getattr(node, "children", []) or []):
                if child.type in ("object_type", "type_literal", "object"):
                    value_node = child
                    break

        if value_node:
            for child in (getattr(value_node, "children", []) or []):
                ct = getattr(child, "type", "")
                if ct in ("property_signature", "public_field_definition", "pair", "field_definition"):
                    pname_node = child.child_by_field_name("name") or child.child_by_field_name("key") or self.child(child, "property_identifier") or self.child(child, "identifier")
                    ptype_node = child.child_by_field_name("type") or child.child_by_field_name("value") or self.child(child, "type_annotation")
                    if pname_node:
                        pname = self.text(pname_node).strip()
                        ptype = self.text(ptype_node).lstrip(": ").strip() if ptype_node else "any"
                        if ptype and ptype != "any":
                            cls_info.attributes.append(f"{ptype} {pname}")
                        else:
                            cls_info.attributes.append(pname)

        self.classes.append(cls_info)

    def _extract_ts_interfaces_and_types_from_source(self) -> None:
        """Extract TypeScript interfaces and type aliases from source bytes when tree-sitter AST misses them."""
        import re

        try:
            source_text = self.source_bytes.decode("utf-8", errors="ignore")
        except Exception:
            return

        existing_names = {c.name for c in self.classes}

        # 1. Interface regex: (export\s+)?interface Name (extends Base1, Base2)? { body }
        interface_pattern = re.compile(
            r'(?:^|\n)\s*(?:export\s+)?interface\s+([A-Za-z0-9_$]+)(?:\s+extends\s+([^{]+))?\s*\{([^}]*)\}',
            re.MULTILINE
        )
        for match in interface_pattern.finditer(source_text):
            iface_name = match.group(1).strip()
            if not iface_name or iface_name in existing_names:
                continue

            bases_str = match.group(2)
            bases: List[str] = []
            if bases_str:
                for b in bases_str.split(","):
                    b_clean = b.strip()
                    if b_clean and b_clean not in bases:
                        bases.append(b_clean)

            body_str = match.group(3)
            cls_info = UMLClassInfo(iface_name, bases, self.module_name)
            cls_info.stereotypes = getattr(cls_info, "stereotypes", []) or []
            cls_info.stereotypes.append("interface")

            for line in body_str.split(";"):
                for subline in line.split("\n"):
                    trimmed = subline.strip().rstrip(",")
                    if not trimmed or trimmed.startswith("//") or trimmed.startswith("/*"):
                        continue
                    method_match = re.match(r'^([A-Za-z0-9_$]+)\s*\(([^)]*)\)(?:\s*:\s*([^;,\n]+))?', trimmed)
                    if method_match:
                        mname = method_match.group(1)
                        margs = method_match.group(2)
                        cls_info.methods.append(f"{mname}({margs})")
                        continue
                    prop_match = re.match(r'^([A-Za-z0-9_$]+)\s*\??\s*:\s*(.+)$', trimmed)
                    if prop_match:
                        pname = prop_match.group(1)
                        ptype = prop_match.group(2).strip()
                        if ptype:
                            cls_info.attributes.append(f"{ptype} {pname}")
                        else:
                            cls_info.attributes.append(pname)

            self.classes.append(cls_info)
            existing_names.add(iface_name)

        # 2. Type alias regex: (export\s+)?type Name = { body }
        type_pattern = re.compile(
            r'(?:^|\n)\s*(?:export\s+)?type\s+([A-Za-z0-9_$]+)\s*=\s*\{([^}]*)\}',
            re.MULTILINE
        )
        for match in type_pattern.finditer(source_text):
            type_name = match.group(1).strip()
            if not type_name or type_name in existing_names:
                continue

            body_str = match.group(2)
            cls_info = UMLClassInfo(type_name, [], self.module_name)
            cls_info.stereotypes = getattr(cls_info, "stereotypes", []) or []
            cls_info.stereotypes.append("type")

            for line in body_str.split(";"):
                for subline in line.split("\n"):
                    trimmed = subline.strip().rstrip(",")
                    if not trimmed or trimmed.startswith("//") or trimmed.startswith("/*"):
                        continue
                    prop_match = re.match(r'^([A-Za-z0-9_$]+)\s*\??\s*:\s*(.+)$', trimmed)
                    if prop_match:
                        pname = prop_match.group(1)
                        ptype = prop_match.group(2).strip()
                        if ptype:
                            cls_info.attributes.append(f"{ptype} {pname}")
                        else:
                            cls_info.attributes.append(pname)

            self.classes.append(cls_info)
            existing_names.add(type_name)

    def _render_method_params_with_decorators(self, params_node) -> str:
        """Render a method parameter list including TypeScript 5 parameter decorators.

        For each formal parameter walks any preceding ``decorator`` /
        ``decorator_list`` siblings and prepends ``@Body`` / ``@Param('id')``
        style markers onto each decorated parameter so NestJS-style
        controller-injection annotations still appear in the rendered method
        signature.  Falls back to the raw parameter text whenever any child
        scan fails.
        """
        if params_node is None:
            return "()"
        try:
            raw_params = self.text(params_node) or "()"
        except Exception:
            raw_params = "()"
        try:
            children = list(getattr(params_node, "children", []) or [])
            if not children:
                return raw_params
            PARAM_TYPES = frozenset((
                "required_parameter", "optional_parameter", "rest_pattern",
                "pattern", "assignment_pattern",
            ))

            def _decor_marker(node) -> Optional[str]:
                dn = extract_decorator_name(node)
                if not dn:
                    return None
                args = extract_decorator_args(node)
                if not args:
                    return f"@{dn}"
                marker_args = ", ".join(repr(a) for a in args)
                return f"@{dn}({marker_args})"

            param_decor_map: dict[int, List[str]] = {}
            pending: List[str] = []
            for idx, c in enumerate(children):
                ct = getattr(c, "type", "")
                if is_decorator_node(c):
                    m = _decor_marker(c)
                    if m:
                        pending.append(m)
                    continue
                if ct == "decorator_list":
                    for inner in (getattr(c, "children", []) or []):
                        if is_decorator_node(inner):
                            m2 = _decor_marker(inner)
                            if m2:
                                pending.append(m2)
                    continue
                if ct in PARAM_TYPES:
                    if pending:
                        param_decor_map[idx] = list(pending)
                        pending = []
                    continue
                pending = []
            if not param_decor_map:
                return raw_params
            out_parts: List[str] = []
            for idx, c in enumerate(children):
                ct = getattr(c, "type", "")
                if ct in ("(", ")", ","):
                    out_parts.append(self.text(c))
                    continue
                markers = param_decor_map.get(idx)
                if markers is not None:
                    out_parts.append(" ".join(markers) + " ")
                if ct in PARAM_TYPES:
                    out_parts.append(self.text(c))
                elif is_decorator_node(c) or ct == "decorator_list":
                    continue
                else:
                    out_parts.append(self.text(c))
            joined = "".join(out_parts).strip()
            if not joined:
                return raw_params
            if not joined.startswith("("):
                joined = "(" + joined + ")"
            return joined
        except Exception:
            return raw_params

    def _unify_module_exports(self, root_node) -> List[tuple[str, str]]:
        """Unify CommonJS ``module.exports`` / ``exports.X`` and ES Module
        ``export`` / ``export default`` declarations into a single list.

        Returns a list of ``(export_kind, export_name)`` tuples where
        *export_kind* is one of ``"default"``, ``"named"``, ``"reexport"``,
        or ``"cjs_assign"``.  This helper is defensive against malformed
        AST: any node shape that cannot be classified is simply skipped.
        """
        results: List[tuple[str, str]] = []
        if root_node is None:
            return results
        try:
            candidates: List = []
            rtype = getattr(root_node, "type", "")
            if rtype in ("program", "module", "compilation_unit", "script"):
                candidates = list(getattr(root_node, "children", []) or [])
            else:
                candidates = [root_node]

            def _walk(n):
                nt = getattr(n, "type", "")
                if nt == "export_statement" or nt == "export":
                    decl = n.child_by_field_name("declaration") if hasattr(n, "child_by_field_name") else None
                    if decl is not None:
                        dtype = getattr(decl, "type", "")
                        if dtype in ("class_declaration", "function_declaration",
                                     "lexical_declaration", "variable_declaration",
                                     "interface_declaration", "type_alias_declaration", "enum_declaration"):
                            name_node = decl.child_by_field_name("name") if hasattr(decl, "child_by_field_name") else None
                            if name_node is None:
                                for dc in (getattr(decl, "children", []) or []):
                                    if dc.type in ("variable_declarator",):
                                        vname = dc.child_by_field_name("name") if hasattr(dc, "child_by_field_name") else None
                                        if vname is not None:
                                            results.append(("named", _node_text_js(vname)))
                                            break
                            else:
                                results.append(("named", _node_text_js(name_node)))
                        return
                    txt = _node_text_js(n)
                    if "export default" in txt or "default" in txt:
                        raw = txt.replace("export default", "").replace(";", "").strip()
                        head = raw.split()[0] if raw else "default"
                        results.append(("default", head))
                        return
                    for src in (n.children or []):
                        if getattr(src, "type", "") == "export_clause":
                            for sp in (getattr(src, "children", []) or []):
                                if getattr(sp, "type", "") in ("export_specifier", "identifier", "shorthand_property_identifier"):
                                    results.append(("named", _node_text_js(sp)))
                        elif getattr(src, "type", "") == "from_clause":
                            results.append(("reexport", _node_text_js(src)))
                    return
                if nt == "assignment_expression" or nt == "expression_statement":
                    txt = _node_text_js(n)
                    if "module.exports" in txt or txt.startswith("exports."):
                        if "module.exports" in txt:
                            name = "module"
                            head = txt.split("=", 1)[0].replace("module.exports", "").strip(" .[]")
                            if head:
                                name = head
                            results.append(("cjs_assign", name))
                        else:
                            head = txt.split("=", 1)[0]
                            parts = head.split(".", 2)
                            if len(parts) >= 2:
                                results.append(("cjs_assign", parts[1].strip()))
                        return
                for c in (getattr(n, "children", []) or []):
                    _walk(c)

            for node in candidates:
                _walk(node)
        except Exception:
            pass
        return results


class JSERVisitor(BaseTreeSitterVisitor):
    """Detects Mongoose (`.model`) and Sequelize (`.define`) models as EREntity."""

    def __init__(self, source_bytes: bytes) -> None:
        super().__init__(source_bytes)
        self.entities: List[EREntity] = []
        self._pending_entity_name: Optional[str] = None

    def visit_call_expression(self, node: Node) -> bool:
        self._check_model_definition(node)
        return True

    def visit_decorator(self, node: Node) -> None:
        """Detect TypeORM ``@Entity()`` decorators on TypeScript classes."""
        call = self.child(node, "call_expression")
        if call is None:
            ident = self.child(node, "identifier")
            if ident and self.text(ident) == "Entity":
                self._pending_entity_name = "_entity_pending_"
            return
        func = call.child_by_field_name("function")
        if func and self.text(func) == "Entity":
            self._pending_entity_name = "_entity_pending_"

    def visit_class_declaration(self, node: Node) -> None:
        if self._pending_entity_name is not None:
            name_node = node.child_by_field_name("name")
            if name_node:
                name = self.text(name_node)
                entity = EREntity(name)
                self.entities.append(entity)
            self._pending_entity_name = None
        else:
            name_node = node.child_by_field_name("name")
            if name_node:
                class_name = self.text(name_node)
                _dto_suffixes = ("Dto", "DTO", "Response", "Request")
                if any(class_name.endswith(s) for s in _dto_suffixes):
                    entity = EREntity(class_name)
                    self._parse_generic_dto_class(node, entity)
                    if entity.columns:
                        self.entities.append(entity)
        self.generic_visit(node)

    def _check_model_definition(self, node: Node) -> None:
        func = node.child_by_field_name("function")
        args = node.child_by_field_name("arguments")
        if not func or not args:
            return

        func_text = self.text(func)

        if func_text.endswith(".model") or func_text == "model":
            if args.named_child_count >= 1:
                name_arg = args.named_child(0)
                if name_arg.type == "string":
                    name = self.text(name_arg).strip("'\"")
                    entity = EREntity(name)
                    if args.named_child_count >= 2:
                        schema_arg = args.named_child(1)
                        self._parse_mongoose_schema(schema_arg, entity)
                    self.entities.append(entity)

        elif func_text.endswith(".define"):
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
                entity.columns.append((self.text(key), "Field"))

    def _parse_generic_dto_class(self, node: Node, entity: EREntity) -> None:
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


def parse_project_for_js_uml(root_path: str, max_depth: Optional[int] = 4) -> List[UMLClassInfo]:
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
            visitor._extract_ts_interfaces_and_types_from_source()
            all_classes.extend(visitor.classes)
        except Exception:
            continue
    return all_classes


def parse_project_for_js_er(root_path: str, max_depth: Optional[int] = 4) -> List[EREntity]:
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
