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

# TODO(audit): Implement support for Java 17-21 language features including record_declaration nodes,
# TODO(audit): sealed/permitted subclasses on class/interface modifiers, and pattern matching for_instance patterns.
# TODO(audit): Add proper parsing of jakarta.* package imports and references (replace javax.* legacy mappings).
class JavaUMLVisitor:
    def __init__(self, source_bytes: bytes, module_name: str):
        self.source_bytes = source_bytes
        self.module_name = module_name
        self.classes: List[UMLClassInfo] = []
        self.current_class: Optional[UMLClassInfo] = None

    def visit(self, node: tree_sitter.Node):
        # TODO(audit): Extend dispatch to handle record_declaration (Java 14+) and sealed_class_declaration (Java 17+)
        # TODO(audit): node types alongside existing class/interface/enum declarations.
        if node.type in ['class_declaration', 'interface_declaration', 'enum_declaration', 'record_declaration']:
            self._visit_class(node)
        else:
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
        self.classes.append(cls_info)
        
        body_node = node.child_by_field_name('body')
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

# TODO(audit): Map jakarta.persistence.* annotations (Entity, Table, Id, Column, ManyToOne, etc.)
# TODO(audit): alongside existing javax.persistence.* legacy mappings for Spring Boot 3+ compatibility.
class JavaERVisitor:
    def __init__(self, source_bytes: bytes):
        self.source_bytes = source_bytes
        self.entities: List[EREntity] = []
        self.current_entity: Optional[EREntity] = None

    def visit(self, node: tree_sitter.Node):
        if node.type == 'class_declaration':
            self._visit_class(node)
        else:
            for child in node.children:
                self.visit(child)

    def _visit_class(self, node: tree_sitter.Node):
        # Look for @Entity or @Table annotation
        is_entity = False
        modifiers = node.child_by_field_name('modifiers')
        # TODO(audit): Support sealed/permitted class hierarchy and record components when
        # TODO(audit): extracting JPA entities from Java 17+ record-based projections.
        if modifiers:
            for child in modifiers.children:
                if child.type == 'annotation':
                    ann_name = child.child_by_field_name('name')
                    if ann_name:
                        name_text = get_node_text(ann_name, self.source_bytes)
                        # TODO(audit): Also check for fully-qualified jakarta.persistence.Entity / jakarta.persistence.Table
                        # TODO(audit): annotation references in addition to the short-form names.
                        _jakarta_aliases = {'jakarta.persistence.Entity', 'jakarta.persistence.Table'}
                        _javax_aliases  = {'javax.persistence.Entity',   'javax.persistence.Table'}
                        if name_text in ['Entity', 'Table', 'Document'] or name_text in _jakarta_aliases | _javax_aliases: # Includes Mongo Document
                            is_entity = True
        
        if not is_entity:
            # We only extract explicitly annotated entities for Java/Spring
            # but we can also just allow classes in a "models" or "entities" package.
            # For strictness we check annotations. If it's not annotated, we skip.
            # But let's check class name or package later if needed. For now, rely on annotations.
            pass
            
        name_node = node.child_by_field_name('name')
        if not name_node:
            return
            
        name = get_node_text(name_node, self.source_bytes)
        
        # If it's an entity, we process it. Alternatively, if it looks like a DTO we might ignore it.
        # We'll rely on the annotations. If no annotation is found but the user put it in 'models', we might miss it.
        # Let's assume `@Entity` is present for now, or just extract everything and let Mermaid decide.
        # It's better to only extract @Entity for ER.
        # If we didn't find @Entity, let's peek inside to see if there are @Id or @Column annotations.
        if not is_entity and modifiers:
             pass # still false
             
        # Actually, let's just make everything a potential entity if we call parse_er, but wait, Java has many classes.
        # We MUST filter by @Entity or @Table.
        if not is_entity:
            # Maybe check fields for @Id or @Column
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
                
                # If relation annotation exists, add relation
                if relation_type:
                    target_class = t_str
                    # Extract from List<User> or Set<User>
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
