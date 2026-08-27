"""
Module for static analysis of PHP code using Tree-Sitter.
Generates structures compatible with UMLClassInfo and EREntity for Laravel/Eloquent.
"""
from pathlib import Path
from typing import List, Optional
import tree_sitter
try:
    import tree_sitter_php
    PHP_LANGUAGE = tree_sitter.Language(tree_sitter_php.language_php())
    PARSER = tree_sitter.Parser(PHP_LANGUAGE)
except ImportError:
    try:
        PHP_LANGUAGE = tree_sitter.Language(tree_sitter_php.language())
        PARSER = tree_sitter.Parser(PHP_LANGUAGE)
    except Exception:
        PHP_LANGUAGE = None
        PARSER = None

from bck_nd_hlpr.core.uml_parser import UMLClassInfo
from bck_nd_hlpr.core.er_parser import EREntity
from bck_nd_hlpr.core.base_tree_sitter import walk_source_files, module_name_for

import re

def get_node_text(node: tree_sitter.Node, source_bytes: bytes) -> str:
    return source_bytes[node.start_byte:node.end_byte].decode('utf-8')

def sanitize_php_class_name(raw_name: str) -> str:
    """Sanitizes PHP class strings or namespace references.

    Examples:
        - '\\App\\Models\\Solicitud' -> 'Solicitud'
        - 'App\\Models\\Solicitud::class' -> 'Solicitud'
        - 'Solicitud::class' -> 'Solicitud'
        - "'App\\\\Models\\\\Solicitud'" -> 'Solicitud'
    """
    if not raw_name:
        return "Unknown"
    cleaned = raw_name.strip("'\" \t\r\n")
    cleaned = re.sub(r'::class$', '', cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace('/', '\\')
    parts = [p for p in cleaned.split('\\') if p]
    if parts:
        result = parts[-1].strip("'\" ")
        if result and result.lower() != "class":
            return result
    return "Unknown"

def find_child_by_type(node: tree_sitter.Node, node_type: str) -> Optional[tree_sitter.Node]:
    for child in node.children:
        if child.type == node_type: return child
    return None

def find_all_descendants(node: tree_sitter.Node, node_type: str) -> List[tree_sitter.Node]:
    found = []
    if node.type == node_type: found.append(node)
    for child in node.children:
        found.extend(find_all_descendants(child, node_type))
    return found


_PHPC_PRIMITIVES = frozenset({
    "int", "string", "bool", "float", "array", "object", "callable",
    "mixed", "iterable", "void", "null", "false", "true",
    "self", "parent", "static",
})


def _normalize_php_dnf_type(type_node: tree_sitter.Node, source_bytes: bytes) -> Optional[str]:
    """Normalize a PHP 8.2 DNF (Disjunctive Normal Form) type node to a string.

    Handles ``(A&B)|null`` style declarations by recursively walking union,
    intersection, parenthesized, and named-type children and concatenating
    the canonical text form.  Returns *None* when the node cannot be
    classified so callers can fall back to regex heuristics.
    """
    if type_node is None:
        return None
    try:
        t = getattr(type_node, "type", "")
        children = getattr(type_node, "children", []) or []
        if t in ("union_type", "intersection_type"):
            parts = []
            sep = "|" if t == "union_type" else "&"
            for c in children:
                if getattr(c, "type", "") in ("(", ")", ","):
                    continue
                sub = _normalize_php_dnf_type(c, source_bytes)
                if sub is not None:
                    parts.append(sub)
            if parts:
                return sep.join(parts)
        if t in ("parenthesized_expression", "parenthesized_type"):
            inner_parts = []
            for c in children:
                if getattr(c, "type", "") in ("(", ")"):
                    continue
                sub = _normalize_php_dnf_type(c, source_bytes)
                if sub is not None:
                    inner_parts.append(sub)
            if inner_parts:
                return "(" + "".join(inner_parts) + ")"
        if t in ("named_type", "type_declaration", "identifier", "name",
                 "nullable_type", "scoped_resolution_expression",
                 "qualified_name", "relative_scope"):
            txt = get_node_text(type_node, source_bytes).strip()
            if txt:
                return txt
        if len(children) == 0:
            txt = get_node_text(type_node, source_bytes).strip()
            if txt:
                return txt
        generic_parts = []
        for c in children:
            sub = _normalize_php_dnf_type(c, source_bytes)
            if sub is not None:
                generic_parts.append(sub)
        if generic_parts:
            return "".join(generic_parts)
    except Exception:
        pass
    return None


class PHPUMLVisitor:
    def __init__(self, source_bytes: bytes, module_name: str):
        self.source_bytes = source_bytes
        self.module_name = module_name
        self.classes: List[UMLClassInfo] = []
        self.current_class: Optional[UMLClassInfo] = None

    def visit(self, node: tree_sitter.Node):
        if node.type in ['class_declaration', 'interface_declaration', 'enum_declaration']:
            self._visit_class(node)
        elif node.type == 'namespace_definition':
            name_node = find_child_by_type(node, 'namespace_name')
            if name_node:
                self.module_name = get_node_text(name_node, self.source_bytes)
            for child in node.children: self.visit(child)
        else:
            for child in node.children: self.visit(child)

    def _visit_class(self, node: tree_sitter.Node):
        name_node = node.child_by_field_name('name')
        if not name_node: return

        name = get_node_text(name_node, self.source_bytes)

        is_readonly = False
        modifier_node = node.child_by_field_name('modifier')
        if modifier_node is None:
            for child in node.children:
                if child.type in ('readonly', 'modifier') or get_node_text(child, self.source_bytes).strip() == 'readonly':
                    is_readonly = True
                    break
        else:
            if get_node_text(modifier_node, self.source_bytes).strip() == 'readonly':
                is_readonly = True
        if is_readonly:
            name = f"\u00abreadonly\u00bb {name}"

        bases = []

        extends = find_child_by_type(node, 'base_clause')
        if extends:
            for child in extends.children:
                if child.type == 'name':
                    bases.append(get_node_text(child, self.source_bytes))

        implements = find_child_by_type(node, 'class_interface_clause')
        if implements:
             for child in implements.children:
                if child.type == 'name':
                    bases.append(get_node_text(child, self.source_bytes))

        cls_info = UMLClassInfo(name, bases, self.module_name)
        self.classes.append(cls_info)

        body_node = node.child_by_field_name('body')
        if body_node:
            self.current_class = cls_info
            for child in body_node.children:
                if child.type == 'property_declaration':
                    self._visit_property(child)
                elif child.type == 'method_declaration':
                    self._visit_method(child)
                elif child.type == 'constructor_declaration':
                    self._extract_promoted_constructor_properties(child, cls_info)
            self.current_class = None

    def _extract_promoted_constructor_properties(
        self, node: tree_sitter.Node, cls_info: UMLClassInfo
    ) -> None:
        """Extract PHP 8 constructor property promotion parameters as UML attributes.

        For ``__construct(public string $name, private int $age = 0)`` the
        parameters with visibility modifiers (``public``, ``protected``,
        ``private``) are promoted to class properties and are surfaced here
        as ``string $name`` style attributes on the class info.
        """
        formal_params = None
        try:
            formal_params = node.child_by_field_name('parameters')
        except Exception:
            formal_params = None
        if formal_params is None:
            for c in node.children:
                if c.type in ('formal_parameters', 'parameters', 'parameter_list'):
                    formal_params = c
                    break
        if formal_params is None:
            return
        children = getattr(formal_params, 'children', []) or []
        for param_group in children:
            candidates = [param_group] if param_group.type in (
                'simple_parameter', 'promoted_parameter', 'parameter'
            ) else []
            if param_group.type in ('formal_parameter_list',):
                candidates = list(param_group.children)
            for param in candidates:
                if param.type in ('(', ')', ',', ';'):
                    continue
                _promotion_kw = {'public', 'protected', 'private',
                                 'readonly', 'static'}
                text = get_node_text(param, self.source_bytes)
                has_visibility = False
                for kw in ('public', 'protected', 'private'):
                    if kw + ' ' in text or kw + "\t" in text or text.startswith(kw):
                        has_visibility = True
                        break
                if not has_visibility:
                    for c in getattr(param, 'children', []) or []:
                        c_txt = get_node_text(c, self.source_bytes).strip()
                        if c_txt in ('public', 'protected', 'private'):
                            has_visibility = True
                            break
                if not has_visibility:
                    continue
                p_type: Optional[str] = None
                p_name: Optional[str] = None
                p_vis: List[str] = []
                for c in getattr(param, 'children', []) or []:
                    c_txt = get_node_text(c, self.source_bytes).strip()
                    c_type = getattr(c, 'type', '')
                    if c_txt in ('public', 'protected', 'private', 'readonly', 'static'):
                        p_vis.append(c_txt)
                        continue
                    if c_type in ('type_declaration', 'named_type', 'union_type',
                                  'intersection_type', 'identifier', 'name',
                                  'nullable_type') or (
                        c_txt and c_txt[0].islower()
                        and c_txt not in _PHPC_PRIMITIVES
                        and c_txt[0] not in ('$', '(', ')', ',', '=', ';', '?')
                    ):
                        if p_type is None and c_txt and c_txt not in _PHPC_PRIMITIVES | {'?'}:
                            pass
                        candidate = c_txt
                        if candidate and candidate[0] != '$' and p_type is None:
                            p_type = candidate
                    if c_type in ('variable_name',) or (c_txt.startswith('$') and len(c_txt) > 1):
                        p_name = c_txt
                if p_type is None:
                    m = re.match(
                        r'(?:(?:public|protected|private|readonly|static)\s+)*'
                        r'([A-Za-z_][\w\\|?&]*)\s+(\$\w+)',
                        text,
                    )
                    if m:
                        p_type = m.group(1)
                        p_name = m.group(2)
                if p_name is None:
                    m = re.search(r'(\$\w+)', text)
                    if m:
                        p_name = m.group(1)
                if p_type is None:
                    p_type = ''
                if p_name:
                    vis_prefix = ' '.join(p_vis) + ' ' if p_vis else ''
                    if p_type:
                        cls_info.attributes.append(f"{vis_prefix}{p_type} {p_name}")
                    else:
                        cls_info.attributes.append(f"{vis_prefix}{p_name}")

    def _visit_property(self, node: tree_sitter.Node):
        if not self.current_class: return
        p_type: Optional[str] = None
        type_decl = None
        for c in node.children:
            if c.type in ('type_declaration', 'named_type', 'union_type',
                          'intersection_type', 'nullable_type',
                          'parenthesized_expression', 'parenthesized_type'):
                type_decl = c
                break
        if type_decl is not None:
            dnf_normalized = _normalize_php_dnf_type(type_decl, self.source_bytes)
            if dnf_normalized:
                p_type = dnf_normalized
            else:
                raw = get_node_text(type_decl, self.source_bytes).strip()
                if raw:
                    p_type = raw
        if p_type is None:
            text = get_node_text(node, self.source_bytes)
            m = re.match(
                r'(?:(?:public|protected|private|readonly|static)\s+)*'
                r'(?:#\[.*?\]\s*)*'
                r'([A-Za-z_][\w\\|?&]*)\s+\$',
                text,
            )
            if m:
                p_type = m.group(1)
        for child in node.children:
            if child.type == 'property_element':
                name_node = child.child_by_field_name('name')
                if name_node:
                    n = get_node_text(name_node, self.source_bytes)
                    if p_type:
                        self.current_class.attributes.append(f"{p_type} {n}")
                    else:
                        self.current_class.attributes.append(n)

    def _visit_method(self, node: tree_sitter.Node):
        if not self.current_class: return
        name_node = node.child_by_field_name('name')
        params_node = node.child_by_field_name('parameters')
        return_type_node = node.child_by_field_name('return_type')
        if name_node:
            name = get_node_text(name_node, self.source_bytes)
            params_text = "()"
            if params_node:
                params_text = get_node_text(params_node, self.source_bytes)
            if return_type_node is not None:
                raw_rt = _normalize_php_dnf_type(return_type_node, self.source_bytes)
                if raw_rt is None:
                    raw_rt = get_node_text(return_type_node, self.source_bytes).strip()
                if raw_rt:
                    self.current_class.methods.append(f"{name}{params_text}: {raw_rt}")
                    return
            self.current_class.methods.append(f"{name}{params_text}")


class PHPERVisitor:
    def __init__(self, source_bytes: bytes):
        self.source_bytes = source_bytes
        self.entities: List[EREntity] = []

    def visit(self, node: tree_sitter.Node):
        if node.type == 'class_declaration':
            self._visit_class(node)
        elif node.type == 'enum_declaration':
            self._visit_enum(node)
        else:
            for child in node.children:
                self.visit(child)

    def _visit_enum(self, node: tree_sitter.Node) -> None:
        """Extract PHP 8.1 backed enums as ER entities.

        For declarations like ``enum Status: string`` the backing type is
        recorded as the single column type (``value: string`` or
        ``value: int``) so downstream ER renderers still show a useful
        table-level mapping for lookups.  The enum members are not
        individually enumerated because the goal is to capture structural
        relationships without raising a visitor error on ``enum_declaration``.
        """
        name_node = node.child_by_field_name('name')
        if not name_node:
            return
        backing_type: Optional[str] = None
        for c in getattr(node, 'children', []) or []:
            c_type = getattr(c, 'type', '')
            c_txt = get_node_text(c, self.source_bytes).strip()
            if c_type in ('enum_backing_type', 'backing_type') or c_txt in ('string', 'int'):
                if c_txt in ('string', 'int'):
                    backing_type = c_txt
                else:
                    for sub in getattr(c, 'children', []) or []:
                        sub_txt = get_node_text(sub, self.source_bytes).strip()
                        if sub_txt in ('string', 'int'):
                            backing_type = sub_txt
                            break
                if backing_type:
                    break
            if c_type == 'identifier' and c_txt in ('string', 'int') and backing_type is None:
                backing_type = c_txt
        name = get_node_text(name_node, self.source_bytes)
        entity = EREntity(name)
        if backing_type is not None:
            entity.columns.append(('value', backing_type))
        member_types: set = set()
        body = node.child_by_field_name('body')
        if body is not None:
            for child in body.children:
                if child.type == 'enum_case_declaration':
                    expr = find_child_by_type(child, 'scalar')
                    if expr is None:
                        for c2 in getattr(child, 'children', []) or []:
                            c2t = getattr(c2, 'type', '')
                            if c2t in ('string', 'integer', 'float', 'boolean') or c2t.endswith('_literal'):
                                expr = c2
                                break
                    if expr is not None:
                        raw = get_node_text(expr, self.source_bytes).strip("'\" ")
                        if raw:
                            if raw.lstrip('-').isdigit():
                                member_types.add('int')
                            else:
                                member_types.add('string')
        if backing_type is None:
            if len(member_types) == 1:
                (only,) = member_types
                entity.columns.append(('value', only))
            elif member_types:
                entity.columns.append(('value', 'string'))
        self.entities.append(entity)

    def _visit_class(self, node: tree_sitter.Node):
        name_node = node.child_by_field_name('name')
        if not name_node: return

        is_model = False
        extends = find_child_by_type(node, 'base_clause')
        if extends:
            for child in extends.children:
                if child.type == 'name':
                    if "Model" in get_node_text(child, self.source_bytes) or "Authenticatable" in get_node_text(child, self.source_bytes):
                        is_model = True

        if not is_model:
            _orm_markers = {'Entity', 'Model', 'ORM\\Entity', 'ORM\\Model'}
            for attr_list in find_all_descendants(node, 'attribute_list'):
                for attr in find_all_descendants(attr_list, 'attribute'):
                    attr_text = get_node_text(attr, self.source_bytes).strip('#[] \t')
                    for marker in _orm_markers:
                        if attr_text.endswith(marker):
                            is_model = True
                            break
                if is_model:
                    break

        if not is_model: return

        name = get_node_text(name_node, self.source_bytes)
        entity = EREntity(name)

        body_node = node.child_by_field_name('body')
        if body_node:
            for child in body_node.children:
                if child.type == 'property_declaration':
                    self._extract_typed_property_columns(child, entity)
                    for prop in child.children:
                        if prop.type == 'property_element':
                            pname = prop.child_by_field_name('name')
                            if pname and get_node_text(pname, self.source_bytes) == '$fillable':
                                default_val = prop.child_by_field_name('default_value')
                                if default_val and default_val.type == 'array_creation_expression':
                                    strs = find_all_descendants(default_val, 'string')
                                    for s in strs:
                                        col = get_node_text(s, self.source_bytes).strip("'\"")
                                        already = {c[0] for c in entity.columns}
                                        if col and col not in already:
                                            entity.columns.append((col, "string"))

                elif child.type == 'constructor_declaration':
                    self._extract_promoted_constructor_columns(child, entity)

                elif child.type == 'method_declaration':
                    m_name = child.child_by_field_name('name')
                    if not m_name: continue
                    rel_name = get_node_text(m_name, self.source_bytes)

                    m_body = child.child_by_field_name('body')
                    if m_body:
                        returns = find_all_descendants(m_body, 'return_statement')
                        for ret in returns:
                            calls = find_all_descendants(ret, 'member_call_expression')
                            for call in calls:
                                method = call.child_by_field_name('name')
                                if method:
                                    method_txt = get_node_text(method, self.source_bytes)
                                    args = call.child_by_field_name('arguments')
                                    rel_methods = [
                                        'hasMany', 'belongsTo', 'hasOne', 'belongsToMany',
                                        'hasOneThrough', 'hasManyThrough', 'morphOne',
                                        'morphMany', 'morphTo', 'morphToMany', 'morphedByMany'
                                    ]
                                    if method_txt in rel_methods:
                                        rel_type = "||--o{" if "Many" in method_txt else "}o--||"
                                        target = "Unknown"
                                        if args:
                                            for arg_child in args.children:
                                                if arg_child.type == 'argument':
                                                    sr_expr = find_child_by_type(arg_child, 'scoped_resolution_expression')
                                                    if sr_expr:
                                                        scope = sr_expr.child_by_field_name('scope')
                                                        if scope:
                                                            target = sanitize_php_class_name(get_node_text(scope, self.source_bytes))
                                                        else:
                                                            target = sanitize_php_class_name(get_node_text(sr_expr, self.source_bytes))
                                                    else:
                                                        strs = find_all_descendants(arg_child, 'string')
                                                        if strs:
                                                            val = get_node_text(strs[0], self.source_bytes)
                                                            target = sanitize_php_class_name(val)
                                                        else:
                                                            raw_txt = get_node_text(arg_child, self.source_bytes)
                                                            target = sanitize_php_class_name(raw_txt)
                                                    if target != "Unknown":
                                                        break

                                        if target == "Unknown":
                                            scopes = find_all_descendants(ret, 'scoped_resolution_expression')
                                            for s in scopes:
                                                sc_node = s.child_by_field_name('scope')
                                                if sc_node:
                                                    possible_target = sanitize_php_class_name(get_node_text(sc_node, self.source_bytes))
                                                    if possible_target != "Unknown":
                                                        target = possible_target
                                                        break

                                        entity.relationships.append((target, rel_type, rel_name))

        if entity.columns or entity.relationships:
            self.entities.append(entity)
        else:
            self.entities.append(entity)

    def _extract_typed_property_columns(
        self, node: tree_sitter.Node, entity: EREntity
    ) -> None:
        """Extract typed property declarations as ER column metadata.

        For PHP 7.4+ typed properties (``public string $name``) and PHP 8
        attributes this helper inspects the ``property_declaration`` children
        and appends ``(field_name, col_type)`` entries onto *entity.columns*.
        Duplicate names are skipped so later ``$fillable`` heuristics can
        still override the inferred column set.
        """
        existing = {c[0] for c in entity.columns}
        p_type: Optional[str] = None
        type_decl = None
        for c in node.children:
            if c.type in ('type_declaration', 'named_type', 'union_type',
                          'intersection_type', 'nullable_type'):
                type_decl = c
                break
        if type_decl is not None:
            raw = get_node_text(type_decl, self.source_bytes).strip()
            if raw.startswith('?'):
                raw = raw[1:]
            if raw:
                p_type = raw
        if p_type is None:
            text = get_node_text(node, self.source_bytes)
            m = re.match(
                r'(?:(?:public|protected|private|readonly|static)\s+)*'
                r'(?:#\[.*?\]\s*)*'
                r'([A-Za-z_][\w\\|?&]*)\s+\$',
                text,
            )
            if m:
                raw = m.group(1)
                if raw.startswith('?'):
                    raw = raw[1:]
                p_type = raw
        if p_type is None:
            return
        normalized = p_type.lower().replace('?', '')
        if normalized not in _PHPC_PRIMITIVES:
            return
        col_type = {
            'int': 'int',
            'string': 'string',
            'bool': 'bool',
            'float': 'float',
            'array': 'array',
            'mixed': 'mixed',
        }.get(normalized, normalized)
        for child in node.children:
            if child.type == 'property_element':
                name_node = child.child_by_field_name('name')
                if name_node:
                    raw_name = get_node_text(name_node, self.source_bytes).lstrip('$')
                    if raw_name and raw_name not in existing:
                        entity.columns.append((raw_name, col_type))
                        existing.add(raw_name)

    def _extract_promoted_constructor_columns(
        self, node: tree_sitter.Node, entity: EREntity
    ) -> None:
        """Extract PHP 8+ constructor property promotion parameters with type
        hints as ER table columns.

        Constructor parameters prefixed with a visibility keyword (``public``,
        ``protected``, ``private``) declare promoted class properties.  When
        a type hint is present and maps to a primitive PHP type the parameter
        is surfaced as an ER column; class-name types are emitted as
        relationships using the ``}o--||`` cardinality marker.
        """
        existing_cols = {c[0] for c in entity.columns}
        existing_rels = {r[0] for r in entity.relationships}
        formal_params = None
        try:
            formal_params = node.child_by_field_name('parameters')
        except Exception:
            formal_params = None
        if formal_params is None:
            for c in node.children:
                if c.type in ('formal_parameters', 'parameters', 'parameter_list'):
                    formal_params = c
                    break
        if formal_params is None:
            return
        children = getattr(formal_params, 'children', []) or []
        for param_group in children:
            candidates = [param_group] if param_group.type in (
                'simple_parameter', 'promoted_parameter', 'parameter'
            ) else []
            if param_group.type in ('formal_parameter_list',):
                candidates = list(param_group.children)
            for param in candidates:
                if param.type in ('(', ')', ',', ';'):
                    continue
                text = get_node_text(param, self.source_bytes)
                has_visibility = False
                for kw in ('public', 'protected', 'private'):
                    if kw + ' ' in text or kw + "\t" in text or text.startswith(kw):
                        has_visibility = True
                        break
                if not has_visibility:
                    for c in getattr(param, 'children', []) or []:
                        c_txt = get_node_text(c, self.source_bytes).strip()
                        if c_txt in ('public', 'protected', 'private'):
                            has_visibility = True
                            break
                if not has_visibility:
                    continue
                p_type: Optional[str] = None
                p_name: Optional[str] = None
                type_decl = None
                for c in getattr(param, 'children', []) or []:
                    c_txt = get_node_text(c, self.source_bytes).strip()
                    c_type = getattr(c, 'type', '')
                    if c_type in ('type_declaration', 'named_type', 'union_type',
                                  'intersection_type', 'nullable_type'):
                        type_decl = c
                    if c_type in ('variable_name',) or (c_txt.startswith('$') and len(c_txt) > 1):
                        p_name = c_txt.lstrip('$')
                if type_decl is not None:
                    raw = get_node_text(type_decl, self.source_bytes).strip()
                    if raw.startswith('?'):
                        raw = raw[1:]
                    if raw:
                        p_type = raw
                if p_type is None:
                    m = re.match(
                        r'(?:(?:public|protected|private|readonly|static)\s+)*'
                        r'(?:#\[.*?\]\s*)*'
                        r'([A-Za-z_][\w\\|?&]*)\s+(\$\w+)',
                        text,
                    )
                    if m:
                        raw_type = m.group(1)
                        if raw_type.startswith('?'):
                            raw_type = raw_type[1:]
                        p_type = raw_type
                        if p_name is None:
                            p_name = m.group(2).lstrip('$')
                if p_name is None:
                    m = re.search(r'\$(\w+)', text)
                    if m:
                        p_name = m.group(1)
                if not p_name or not p_type:
                    continue
                normalized = p_type.lower().replace('?', '')
                col_type = {
                    'int': 'int',
                    'string': 'string',
                    'bool': 'bool',
                    'float': 'float',
                    'array': 'array',
                    'mixed': 'mixed',
                }.get(normalized, None)
                if col_type is not None and p_name not in existing_cols:
                    entity.columns.append((p_name, col_type))
                    existing_cols.add(p_name)
                elif col_type is None and p_type[0].isupper():
                    target = sanitize_php_class_name(p_type)
                    if target != "Unknown" and target not in existing_rels:
                        entity.relationships.append((target, "}o--||", p_name))
                        existing_rels.add(target)

def parse_project_for_php_uml(root_path: str, max_depth: Optional[int] = 4) -> List[UMLClassInfo]:
    if not PARSER:
         print("⚠️ Could not load Tree-Sitter parser (tree-sitter-php).")
         return []

    all_classes = []
    root = Path(root_path)

    for file_path, rel_path in walk_source_files(
        str(root), (".php",), max_depth=max_depth
    ):
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                source_bytes = f.read().encode('utf-8')

            tree = PARSER.parse(source_bytes)
            visitor = PHPUMLVisitor(source_bytes, module_name_for(rel_path))
            visitor.visit(tree.root_node)
            all_classes.extend(visitor.classes)
        except Exception:
            continue
    return all_classes

def parse_project_for_php_er(root_path: str, max_depth: Optional[int] = 4) -> List[EREntity]:
    if not PARSER:
         return []

    all_entities = []
    root = Path(root_path)

    for file_path, _rel_path in walk_source_files(
        str(root), (".php",), max_depth=max_depth
    ):
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                source_bytes = f.read().encode('utf-8')

            tree = PARSER.parse(source_bytes)
            visitor = PHPERVisitor(source_bytes)
            visitor.visit(tree.root_node)
            all_entities.extend(visitor.entities)
        except Exception:
            continue
    return all_entities
