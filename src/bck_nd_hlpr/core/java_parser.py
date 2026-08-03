"""
Module for static analysis of Java code using Tree-Sitter.
Generates structures compatible with UMLClassInfo and EREntity for Spring Boot / JPA.
"""
import os
from pathlib import Path
from typing import List, Optional
import tree_sitter
try:
    import tree_sitter_java
    JAVA_LANGUAGE = tree_sitter.Language(tree_sitter_java.language())
    PARSER = tree_sitter.Parser(JAVA_LANGUAGE)
except ImportError:
    JAVA_LANGUAGE = None
    PARSER = None

from bck_nd_hlpr.core.uml_parser import UMLClassInfo
from bck_nd_hlpr.core.er_parser import EREntity
from bck_nd_hlpr.core.constants import GLOBAL_IGNORE_DIRS

def get_node_text(node: tree_sitter.Node, source_bytes: bytes) -> str:
    """Helper to extract text from a node."""
    return source_bytes[node.start_byte:node.end_byte].decode('utf-8')

def find_child_by_type(node: tree_sitter.Node, node_type: str) -> Optional[tree_sitter.Node]:
    for child in node.children:
        if child.type == node_type:
            return child
    return None

def find_children_by_type(node: tree_sitter.Node, node_type: str) -> List[tree_sitter.Node]:
    return [child for child in node.children if child.type == node_type]


class JavaUMLVisitor:
    def __init__(self, source_bytes: bytes, module_name: str):
        self.source_bytes = source_bytes
        self.module_name = module_name
        self.classes: List[UMLClassInfo] = []
        self.current_class: Optional[UMLClassInfo] = None

    def visit(self, node: tree_sitter.Node):
        if node is None:
            return
        t = node.type
        if t in ['class_declaration', 'interface_declaration', 'enum_declaration', 'record_declaration']:
            self._visit_class(node)
            return
        if t == 'instanceof_expression' or t == 'pattern_expression' or t == 'type_pattern':
            for child in node.children:
                self.visit(child)
            return
        for child in node.children:
            self.visit(child)

    def _visit_class(self, node: tree_sitter.Node):
        name_node = node.child_by_field_name('name')
        if not name_node:
            return

        name = get_node_text(name_node, self.source_bytes)
        bases = []

        superclass = node.child_by_field_name('superclass')
        if superclass:
            bases.append(get_node_text(superclass, self.source_bytes).replace("extends ", "").strip())

        interfaces = node.child_by_field_name('interfaces')
        if interfaces:
            bases.append(get_node_text(interfaces, self.source_bytes).replace("implements ", "").strip())

        cls_info = UMLClassInfo(name, bases, self.module_name)

        modifiers = node.child_by_field_name('modifiers')
        is_sealed = False
        permits_list: List[str] = []
        if modifiers is not None:
            for mod in modifiers.children:
                mod_text = get_node_text(mod, self.source_bytes).strip()
                if mod_text == 'sealed':
                    is_sealed = True
                elif mod.type == 'permits' or mod_text.startswith('permits'):
                    for child in getattr(mod, 'children', []) or []:
                        if child.type in ('identifier', 'type_identifier', 'scoped_identifier', 'name'):
                            permits_list.append(get_node_text(child, self.source_bytes))
        permits_node = None
        try:
            permits_node = node.child_by_field_name('permits')
        except Exception:
            permits_node = None
        if permits_node is None:
            for child in node.children:
                if child.type == 'permits' or get_node_text(child, self.source_bytes).strip().startswith('permits'):
                    permits_node = child
                    break
        if permits_node is not None:
            for child in getattr(permits_node, 'children', []) or []:
                if child.type in ('identifier', 'type_identifier', 'scoped_identifier', 'name', 'generic_type'):
                    permits_list.append(get_node_text(child, self.source_bytes))
                elif child.type == 'type_list':
                    for tc in child.children:
                        if tc.type not in (',', '(', ')'):
                            t = get_node_text(tc, self.source_bytes).strip()
                            if t:
                                permits_list.append(t)
        cls_info.metadata = getattr(cls_info, 'metadata', {})
        if is_sealed:
            cls_info.metadata['sealed'] = True
        if is_non_sealed:
            cls_info.metadata['non-sealed'] = True
        if permits_list:
            seen: set = set()
            unique_permits: List[str] = []
            for p in permits_list:
                p_clean = p.strip().rstrip(',')
                if p_clean and p_clean not in seen:
                    seen.add(p_clean)
                    unique_permits.append(p_clean)
            if unique_permits:
                cls_info.metadata['permits'] = unique_permits

        self.classes.append(cls_info)

        body_node = node.child_by_field_name('body')
        if node.type == 'record_declaration':
            record_components = None
            try:
                record_components = node.child_by_field_name('components')
            except Exception:
                record_components = None
            if record_components is None:
                params = node.child_by_field_name('parameters')
                if params is not None:
                    record_components = params
            if record_components is None:
                for child in node.children:
                    if child.type in ('record_component_list', 'formal_parameter_list', 'parameters'):
                        record_components = child
                        break
            if record_components is not None:
                self.current_class = cls_info
                for comp in record_components.children:
                    if comp.type in ('record_component', 'formal_parameter', 'parameter'):
                        comp_type = comp.child_by_field_name('type')
                        comp_name = comp.child_by_field_name('name')
                        if comp_type is None:
                            for c in comp.children:
                                if c.type in ('integral_type', 'floating_point_type', 'boolean_type',
                                              'type_identifier', 'identifier', 'generic_type', 'scoped_type'):
                                    comp_type = c
                                    break
                        if comp_name is None:
                            for c in comp.children:
                                if c.type in ('identifier', 'variable_declarator_id'):
                                    comp_name = c
                                    break
                        if comp_type is not None and comp_name is not None:
                            t = get_node_text(comp_type, self.source_bytes)
                            n = get_node_text(comp_name, self.source_bytes)
                            cls_info.attributes.append(f"{t} {n}")
                self.current_class = None

        if body_node:
            self.current_class = cls_info
            for child in body_node.children:
                if child.type == 'field_declaration':
                    self._visit_field(child)
                elif child.type == 'method_declaration':
                    self._visit_method(child)
            self.current_class = None

    def _visit_field(self, node: tree_sitter.Node):
        if not self.current_class: return

        type_node = node.child_by_field_name('type')
        declarator = find_child_by_type(node, 'variable_declarator')
        if type_node and declarator:
            id_node = declarator.child_by_field_name('name')
            if id_node:
                t = get_node_text(type_node, self.source_bytes)
                n = get_node_text(id_node, self.source_bytes)
                self.current_class.attributes.append(f"{t} {n}")

    def _visit_method(self, node: tree_sitter.Node):
        if not self.current_class: return

        name_node = node.child_by_field_name('name')
        params_node = node.child_by_field_name('parameters')

        if name_node and params_node:
            name = get_node_text(name_node, self.source_bytes)
            params_text = get_node_text(params_node, self.source_bytes)
            self.current_class.methods.append(f"{name}{params_text}")


class JavaERVisitor:
    def __init__(self, source_bytes: bytes):
        self.source_bytes = source_bytes
        self.entities: List[EREntity] = []
        self.current_entity: Optional[EREntity] = None

    def visit(self, node: tree_sitter.Node):
        if node.type == 'class_declaration':
            self._visit_class(node)
        elif node.type == 'record_declaration':
            self._visit_record(node)
        else:
            for child in node.children:
                self.visit(child)

    def _is_entity(self, name_node: tree_sitter.Node, node: tree_sitter.Node) -> bool:
        modifiers = node.child_by_field_name('modifiers')
        if modifiers:
            for child in modifiers.children:
                if child.type == 'annotation':
                    ann_name = child.child_by_field_name('name')
                    if ann_name:
                        name_text = get_node_text(ann_name, self.source_bytes)
                        _jakarta_aliases = {'jakarta.persistence.Entity', 'jakarta.persistence.Table'}
                        _javax_aliases  = {'javax.persistence.Entity',   'javax.persistence.Table'}
                        if name_text in ['Entity', 'Table', 'Document'] or name_text in _jakarta_aliases | _javax_aliases:
                            return True
        body = node.child_by_field_name('body')
        if body:
            for child in body.children:
                if child.type in ('field_declaration', 'compact_constructor_declaration',
                                   'record_component', 'formal_parameter', 'parameter'):
                    f_mods = child.child_by_field_name('modifiers')
                    if f_mods:
                        for fm in f_mods.children:
                            if fm.type == 'annotation':
                                an = fm.child_by_field_name('name')
                                if an and get_node_text(an, self.source_bytes) in ['Id', 'Column', 'ManyToOne', 'OneToMany']:
                                    return True
        return False

    def _visit_record(self, node: tree_sitter.Node):
        name_node = node.child_by_field_name('name')
        if not name_node:
            return
        if not self._is_entity(name_node, node):
            return

        name = get_node_text(name_node, self.source_bytes)
        self.current_entity = EREntity(name)

        record_components = None
        try:
            record_components = node.child_by_field_name('components')
        except Exception:
            record_components = None
        if record_components is None:
            params = node.child_by_field_name('parameters')
            if params is not None:
                record_components = params
        if record_components is None:
            for child in node.children:
                if child.type in ('record_component_list', 'formal_parameter_list', 'parameters'):
                    record_components = child
                    break

        if record_components is not None:
            for comp in record_components.children:
                if comp.type in ('record_component', 'formal_parameter', 'parameter'):
                    comp_type = comp.child_by_field_name('type')
                    comp_name = comp.child_by_field_name('name')
                    if comp_type is None:
                        for c in comp.children:
                            if c.type in ('integral_type', 'floating_point_type', 'boolean_type',
                                          'type_identifier', 'identifier', 'generic_type', 'scoped_type'):
                                comp_type = c
                                break
                    if comp_name is None:
                        for c in comp.children:
                            if c.type in ('identifier', 'variable_declarator_id'):
                                comp_name = c
                                break
                    if comp_type is not None and comp_name is not None:
                        t_str = get_node_text(comp_type, self.source_bytes).strip()
                        n_str = get_node_text(comp_name, self.source_bytes).strip()
                        col_type = t_str
                        is_relation = False
                        target_class = ""
                        rel_type = ""
                        if t_str.startswith("List<") or t_str.startswith("Set<") or t_str.startswith("Collection<"):
                            is_relation = True
                            start = t_str.find("<")
                            end = t_str.rfind(">")
                            if start != -1 and end != -1:
                                target_class = t_str[start + 1:end].strip()
                            rel_type = "||--o{"
                        else:
                            primitives = {"int", "long", "short", "byte", "char", "float", "double",
                                          "boolean", "String", "Integer", "Long", "Double", "Float",
                                          "Boolean", "LocalDate", "LocalDateTime", "LocalTime",
                                          "Instant", "ZonedDateTime", "BigDecimal", "UUID"}
                            clean_t = t_str.replace("?", "").strip()
                            if clean_t not in primitives and clean_t and clean_t[0].isupper():
                                is_relation = True
                                target_class = clean_t
                                rel_type = "}o--||"
                        if is_relation and target_class:
                            self.current_entity.relationships.append((target_class, rel_type, n_str))
                        else:
                            self.current_entity.columns.append((n_str, col_type))

        body_node = node.child_by_field_name('body')
        if body_node:
            for child in body_node.children:
                if child.type == 'field_declaration':
                    self._visit_field(child)

        if self.current_entity.columns or self.current_entity.relationships:
            self.entities.append(self.current_entity)
        self.current_entity = None

    def _visit_class(self, node: tree_sitter.Node):
        is_entity = False
        modifiers = node.child_by_field_name('modifiers')
        if modifiers:
            for child in modifiers.children:
                if child.type == 'annotation':
                    ann_name = child.child_by_field_name('name')
                    if ann_name:
                        name_text = get_node_text(ann_name, self.source_bytes)
                        _jakarta_aliases = {'jakarta.persistence.Entity', 'jakarta.persistence.Table'}
                        _javax_aliases  = {'javax.persistence.Entity',   'javax.persistence.Table'}
                        if name_text in ['Entity', 'Table', 'Document'] or name_text in _jakarta_aliases | _javax_aliases:
                            is_entity = True

        name_node = node.child_by_field_name('name')
        if not name_node:
            return

        name = get_node_text(name_node, self.source_bytes)

        if not is_entity:
            body = node.child_by_field_name('body')
            if body:
                for child in body.children:
                    if child.type == 'field_declaration':
                        f_mods = child.child_by_field_name('modifiers')
                        if f_mods:
                            for fm in f_mods.children:
                                if fm.type == 'annotation':
                                    an = fm.child_by_field_name('name')
                                    if an and get_node_text(an, self.source_bytes) in ['Id', 'Column', 'ManyToOne', 'OneToMany']:
                                        is_entity = True
                                        break
                    if is_entity: break

        if not is_entity:
            return

        self.current_entity = EREntity(name)

        body_node = node.child_by_field_name('body')
        if body_node:
            for child in body_node.children:
                if child.type == 'field_declaration':
                    self._visit_field(child)

        if self.current_entity.columns or self.current_entity.relationships:
             self.entities.append(self.current_entity)
        self.current_entity = None

    def _visit_field(self, node: tree_sitter.Node):
        if not self.current_entity: return

        is_id = False
        is_transient = False
        relation_type = None

        modifiers = node.child_by_field_name('modifiers')
        if modifiers:
            for child in modifiers.children:
                if child.type == 'annotation':
                    ann_name = child.child_by_field_name('name')
                    if ann_name:
                        name_text = get_node_text(ann_name, self.source_bytes)
                        if name_text == 'Id': is_id = True
                        if name_text == 'Transient': is_transient = True
                        if name_text in ['ManyToOne', 'OneToOne']: relation_type = '}o--||'
                        if name_text in ['OneToMany', 'ManyToMany']: relation_type = '||--o{'

        if is_transient: return

        type_node = node.child_by_field_name('type')
        declarator = find_child_by_type(node, 'variable_declarator')

        if type_node and declarator:
            id_node = declarator.child_by_field_name('name')
            if id_node:
                t_str = get_node_text(type_node, self.source_bytes).strip()
                n_str = get_node_text(id_node, self.source_bytes).strip()

                if relation_type:
                    target_class = t_str
                    if "<" in t_str and ">" in t_str:
                        start = t_str.find("<")
                        end = t_str.rfind(">")
                        target_class = t_str[start+1:end].strip()

                    self.current_entity.relationships.append((target_class, relation_type, n_str))
                else:
                    col_type = t_str
                    if is_id:
                        col_type += " PK"
                    self.current_entity.columns.append((n_str, col_type))

def parse_project_for_java_uml(root_path: str, max_depth: int = 4) -> List[UMLClassInfo]:
    if not PARSER:
         print("⚠️ Could not load Tree-Sitter parser (tree-sitter-java).")
         return []

    all_classes = []
    root = Path(root_path)

    for root_dir, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS]
        try: current_depth = len(Path(root_dir).relative_to(root).parts)
        except ValueError: current_depth = 0
        if current_depth > max_depth: continue

        for file in files:
            if file.endswith(".java"):
                file_path = Path(root_dir) / file
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        source_bytes = f.read().encode('utf-8')

                    tree = PARSER.parse(source_bytes)
                    module_name = str(file_path.parent.relative_to(root)).replace(os.sep, ".")
                    if module_name == ".": module_name = "Root"

                    visitor = JavaUMLVisitor(source_bytes, module_name)
                    visitor.visit(tree.root_node)
                    all_classes.extend(visitor.classes)
                except Exception:
                    continue
    return all_classes

def parse_project_for_java_er(root_path: str, max_depth: int = 4) -> List[EREntity]:
    if not PARSER:
         return []

    all_entities = []
    root = Path(root_path)

    for root_dir, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS]
        try: current_depth = len(Path(root_dir).relative_to(root).parts)
        except ValueError: current_depth = 0
        if current_depth > max_depth: continue

        for file in files:
            if file.endswith(".java"):
                file_path = Path(root_dir) / file
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        source_bytes = f.read().encode('utf-8')

                    tree = PARSER.parse(source_bytes)
                    visitor = JavaERVisitor(source_bytes)
                    visitor.visit(tree.root_node)
                    all_entities.extend(visitor.entities)
                except Exception:
                    continue
    return all_entities
