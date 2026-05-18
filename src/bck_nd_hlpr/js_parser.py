"""
Módulo para el análisis estático de código JavaScript/TypeScript utilizando tree-sitter.
Genera estructuras compatibles con UMLClassInfo y EREntity para Node/Express (Mongoose/Sequelize).
"""
import os
from pathlib import Path
from typing import List, Optional
import tree_sitter
try:
    import tree_sitter_javascript
    JS_LANGUAGE = tree_sitter.Language(tree_sitter_javascript.language())
    PARSER = tree_sitter.Parser(JS_LANGUAGE)
except ImportError:
    JS_LANGUAGE = None
    PARSER = None

from bck_nd_hlpr.uml_parser import UMLClassInfo
from bck_nd_hlpr.er_parser import EREntity

def get_node_text(node: tree_sitter.Node, source_bytes: bytes) -> str:
    return source_bytes[node.start_byte:node.end_byte].decode('utf-8')

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

class JSUMLVisitor:
    def __init__(self, source_bytes: bytes, module_name: str):
        self.source_bytes = source_bytes
        self.module_name = module_name
        self.classes: List[UMLClassInfo] = []
        self.current_class: Optional[UMLClassInfo] = None

    def visit(self, node: tree_sitter.Node):
        if node.type == 'class_declaration':
            self._visit_class(node)
        else:
            for child in node.children: self.visit(child)

    def _visit_class(self, node: tree_sitter.Node):
        name_node = node.child_by_field_name('name')
        if not name_node: return
        
        name = get_node_text(name_node, self.source_bytes)
        bases = []
        
        heritage = find_child_by_type(node, 'class_heritage')
        if heritage:
            for child in heritage.children:
                if child.type == 'identifier':
                    bases.append(get_node_text(child, self.source_bytes))

        cls_info = UMLClassInfo(name, bases, self.module_name)
        self.classes.append(cls_info)
        
        body_node = node.child_by_field_name('body')
        if body_node:
            self.current_class = cls_info
            for child in body_node.children:
                if child.type == 'public_field_definition':
                    n = child.child_by_field_name('name')
                    if n: self.current_class.attributes.append(get_node_text(n, self.source_bytes))
                elif child.type == 'method_definition':
                    n = child.child_by_field_name('name')
                    params = child.child_by_field_name('parameters')
                    if n:
                        m_name = get_node_text(n, self.source_bytes)
                        p_text = "()"
                        if params: p_text = get_node_text(params, self.source_bytes)
                        self.current_class.methods.append(f"{m_name}{p_text}")
            self.current_class = None

class JSERVisitor:
    def __init__(self, source_bytes: bytes):
        self.source_bytes = source_bytes
        self.entities: List[EREntity] = []

    def visit(self, node: tree_sitter.Node):
        # Look for mongoose.model('Name', schema) or sequelize.define('Name', schema)
        if node.type == 'call_expression':
            self._check_model_definition(node)
        
        for child in node.children:
            self.visit(child)

    def _check_model_definition(self, node: tree_sitter.Node):
        func = node.child_by_field_name('function')
        args = node.child_by_field_name('arguments')
        if not func or not args: return
        
        func_text = get_node_text(func, self.source_bytes)
        
        if func_text.endswith('.model') or func_text == 'model':
            # Mongoose
            if args.named_child_count >= 1:
                name_arg = args.named_child(0)
                if name_arg.type == 'string':
                    name = get_node_text(name_arg, self.source_bytes).strip("'\"")
                    entity = EREntity(name)
                    # For mongoose, field extraction is complex because it's usually defined in a previous Schema
                    # For simplicity, we just extract the model name. 
                    # If the schema is passed inline, we could parse it:
                    if args.named_child_count >= 2:
                        schema_arg = args.named_child(1)
                        self._parse_mongoose_schema(schema_arg, entity)
                    self.entities.append(entity)
                    
        elif func_text.endswith('.define'):
            # Sequelize
            if args.named_child_count >= 2:
                name_arg = args.named_child(0)
                schema_arg = args.named_child(1)
                if name_arg.type == 'string':
                    name = get_node_text(name_arg, self.source_bytes).strip("'\"")
                    entity = EREntity(name)
                    if schema_arg.type == 'object':
                        self._parse_sequelize_schema(schema_arg, entity)
                    self.entities.append(entity)

    def _parse_mongoose_schema(self, node: tree_sitter.Node, entity: EREntity):
        # Very basic extraction if new Schema({ ... }) is passed inline
        if node.type == 'new_expression':
            args = node.child_by_field_name('arguments')
            if args and args.named_child_count > 0:
                obj = args.named_child(0)
                if obj.type == 'object':
                    for pair in find_all_descendants(obj, 'pair'):
                        key = pair.child_by_field_name('key')
                        if key:
                            entity.columns.append((get_node_text(key, self.source_bytes), 'Field'))

    def _parse_sequelize_schema(self, node: tree_sitter.Node, entity: EREntity):
        for pair in find_all_descendants(node, 'pair'):
             key = pair.child_by_field_name('key')
             if key:
                 # Usually depth is important to avoid nested objects, but this is a heuristic
                 entity.columns.append((get_node_text(key, self.source_bytes), 'Field'))


def parse_project_for_js_uml(root_path: str, max_depth: int = 4) -> List[UMLClassInfo]:
    if not PARSER:
         print("⚠️ No se pudo cargar tree-sitter-javascript.")
         return []
         
    all_classes = []
    root = Path(root_path)
    ignore_dirs = {'.git', 'node_modules', 'dist', 'build', '.vscode'}

    for root_dir, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        try: current_depth = len(Path(root_dir).relative_to(root).parts)
        except ValueError: current_depth = 0
        if current_depth > max_depth: continue
            
        for file in files:
            if file.endswith((".js", ".ts", ".jsx", ".tsx")):
                file_path = Path(root_dir) / file
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        source_bytes = f.read().encode('utf-8')
                    
                    tree = PARSER.parse(source_bytes)
                    module_name = str(file_path.parent.relative_to(root)).replace(os.sep, ".")
                    if module_name == ".": module_name = "Root"
                         
                    visitor = JSUMLVisitor(source_bytes, module_name)
                    visitor.visit(tree.root_node)
                    all_classes.extend(visitor.classes)
                except Exception:
                    continue
    return all_classes

def parse_project_for_js_er(root_path: str, max_depth: int = 4) -> List[EREntity]:
    if not PARSER:
         return []
         
    all_entities = []
    root = Path(root_path)
    ignore_dirs = {'.git', 'node_modules', 'dist', 'build', '.vscode'}

    for root_dir, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        try: current_depth = len(Path(root_dir).relative_to(root).parts)
        except ValueError: current_depth = 0
        if current_depth > max_depth: continue
            
        for file in files:
            if file.endswith((".js", ".ts")):
                file_path = Path(root_dir) / file
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        source_bytes = f.read().encode('utf-8')
                    
                    tree = PARSER.parse(source_bytes)
                    visitor = JSERVisitor(source_bytes)
                    visitor.visit(tree.root_node)
                    all_entities.extend(visitor.entities)
                except Exception:
                    continue
    return all_entities
