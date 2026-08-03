"""
Module for static analysis of PHP code using Tree-Sitter.
Generates structures compatible with UMLClassInfo and EREntity for Laravel/Eloquent.
"""
import os
from pathlib import Path
from typing import List, Optional
import tree_sitter
try:
    import tree_sitter_php
    PHP_LANGUAGE = tree_sitter.Language(tree_sitter_php.language_php())
    PARSER = tree_sitter.Parser(PHP_LANGUAGE)
except ImportError:
    try:
        # Fallback to older tree_sitter_php versions
        PHP_LANGUAGE = tree_sitter.Language(tree_sitter_php.language())
        PARSER = tree_sitter.Parser(PHP_LANGUAGE)
    except Exception:
        PHP_LANGUAGE = None
        PARSER = None

from bck_nd_hlpr.core.uml_parser import UMLClassInfo
from bck_nd_hlpr.core.er_parser import EREntity
from bck_nd_hlpr.core.constants import GLOBAL_IGNORE_DIRS

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
    # Strip ::class suffix if present
    cleaned = re.sub(r'::class$', '', cleaned, flags=re.IGNORECASE)
    # Replace forward slashes or double backslashes
    cleaned = cleaned.replace('/', '\\')
    # Split by backslash and take the last component
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

# TODO(audit): Add support for PHP 8.1-8.3 language features: enum_declaration nodes,
# TODO(audit): readonly class modifiers, #[...] attribute list annotations, and constructor_property_promotion.
class PHPUMLVisitor:
    def __init__(self, source_bytes: bytes, module_name: str):
        self.source_bytes = source_bytes
        self.module_name = module_name
        self.classes: List[UMLClassInfo] = []
        self.current_class: Optional[UMLClassInfo] = None

    def visit(self, node: tree_sitter.Node):
        # TODO(audit): Dispatch enum_declaration nodes (PHP 8.1 backed enums with int/string backing types)
        # TODO(audit): alongside class/interface declarations to capture enum cases and value mappings.
        if node.type in ['class_declaration', 'interface_declaration', 'enum_declaration']:
            self._visit_class(node)
        elif node.type == 'namespace_definition':
            # We could extract namespace to use as module_name
            name_node = find_child_by_type(node, 'namespace_name')
            if name_node:
                self.module_name = get_node_text(name_node, self.source_bytes)
            for child in node.children: self.visit(child)
        else:
            for child in node.children: self.visit(child)

    def _visit_class(self, node: tree_sitter.Node):
        # TODO(audit): Inspect class_declaration modifier list for the `readonly` keyword (PHP 8.2 readonly classes)
        # TODO(audit): and propagate readonly semantics to all declared properties and UML attribute stereotypes.
        name_node = node.child_by_field_name('name')
        if not name_node: return

        name = get_node_text(name_node, self.source_bytes)

        # Check for PHP 8.2 `readonly` class modifier
        is_readonly = False
        modifier_node = node.child_by_field_name('modifier')
        if modifier_node is None:
            # Some grammars expose modifiers as unnamed children before the class keyword
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
            self.current_class = None

    def _visit_property(self, node: tree_sitter.Node):
        if not self.current_class: return
        for child in node.children:
            if child.type == 'property_element':
                name_node = child.child_by_field_name('name')
                if name_node:
                    n = get_node_text(name_node, self.source_bytes)
                    self.current_class.attributes.append(n)

    def _visit_method(self, node: tree_sitter.Node):
        if not self.current_class: return
        name_node = node.child_by_field_name('name')
        params_node = node.child_by_field_name('parameters')
        if name_node:
            name = get_node_text(name_node, self.source_bytes)
            params_text = "()"
            if params_node:
                params_text = get_node_text(params_node, self.source_bytes)
            self.current_class.methods.append(f"{name}{params_text}")


# TODO(audit): Parse PHP 8 #[...] attribute list annotations instead of legacy PHPDoc @annotations
# TODO(audit): for detecting ORM entity markers such as #[ORM\Entity], #[ORM\Column], #[ORM\ManyToOne], etc.
class PHPERVisitor:
    def __init__(self, source_bytes: bytes):
        self.source_bytes = source_bytes
        self.entities: List[EREntity] = []

    def visit(self, node: tree_sitter.Node):
        if node.type == 'class_declaration':
            self._visit_class(node)
        else:
            for child in node.children:
                self.visit(child)

    def _visit_class(self, node: tree_sitter.Node):
        name_node = node.child_by_field_name('name')
        if not name_node: return

        # Check if extends Model
        is_model = False
        # TODO(audit): Check class-level attribute_lists for #[Model] or #[ORM\Entity] style PHP 8 attributes
        # TODO(audit): in addition to the base_clause Model inheritance check.
        extends = find_child_by_type(node, 'base_clause')
        if extends:
            for child in extends.children:
                if child.type == 'name':
                    if "Model" in get_node_text(child, self.source_bytes) or "Authenticatable" in get_node_text(child, self.source_bytes):
                        is_model = True

        # PHP 8 #[...] attribute list inspection for ORM markers
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
                    # Extract $fillable columns for ER
                    for prop in child.children:
                        if prop.type == 'property_element':
                            pname = prop.child_by_field_name('name')
                            if pname and get_node_text(pname, self.source_bytes) == '$fillable':
                                default_val = prop.child_by_field_name('default_value')
                                if default_val and default_val.type == 'array_creation_expression':
                                    strs = find_all_descendants(default_val, 'string')
                                    for s in strs:
                                        col = get_node_text(s, self.source_bytes).strip("'\"")
                                        entity.columns.append((col, "string"))
                
                elif child.type == 'method_declaration':
                    # Extract relationships: hasMany, belongsTo, etc.
                    m_name = child.child_by_field_name('name')
                    if not m_name: continue
                    rel_name = get_node_text(m_name, self.source_bytes)
                    
                    m_body = child.child_by_field_name('body')
                    if m_body:
                        # Find return statement
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
                                        
                                        # Fallback inspection of return call body if target is still Unknown
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
            # Add anyway if it's a model
            self.entities.append(entity)

def parse_project_for_php_uml(root_path: str, max_depth: int = 4) -> List[UMLClassInfo]:
    if not PARSER:
         print("⚠️ Could not load Tree-Sitter parser (tree-sitter-php).")
         return []
         
    all_classes = []
    root = Path(root_path)

    for root_dir, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS]
        try: current_depth = len(Path(root_dir).relative_to(root).parts)
        except ValueError: current_depth = 0
        if current_depth > max_depth: continue
            
        for file in files:
            if file.endswith(".php"):
                file_path = Path(root_dir) / file
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        source_bytes = f.read().encode('utf-8')
                    
                    tree = PARSER.parse(source_bytes)
                    module_name = str(file_path.parent.relative_to(root)).replace(os.sep, ".")
                    if module_name == ".": module_name = "Root"
                         
                    visitor = PHPUMLVisitor(source_bytes, module_name)
                    visitor.visit(tree.root_node)
                    all_classes.extend(visitor.classes)
                except Exception:
                    continue
    return all_classes

def parse_project_for_php_er(root_path: str, max_depth: int = 4) -> List[EREntity]:
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
            if file.endswith(".php"):
                # Laravel models are usually in app/Models
                file_path = Path(root_dir) / file
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
