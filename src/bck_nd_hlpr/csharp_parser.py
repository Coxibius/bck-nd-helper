"""
Módulo para el análisis estático de código C# utilizando tree-sitter.
Genera estructuras compatibles con UMLClassInfo y EREntity.
"""
import os
from pathlib import Path
from typing import List, Optional, Tuple, Dict
import tree_sitter
try:
    import tree_sitter_c_sharp
    CSHARP_LANGUAGE = tree_sitter.Language(tree_sitter_c_sharp.language())
    PARSER = tree_sitter.Parser(CSHARP_LANGUAGE)
except ImportError:
    CSHARP_LANGUAGE = None
    PARSER = None

from bck_nd_hlpr.uml_parser import UMLClassInfo
from bck_nd_hlpr.er_parser import EREntity

def get_node_text(node: tree_sitter.Node, source_bytes: bytes) -> str:
    """Helper para extraer el texto de un nodo."""
    return source_bytes[node.start_byte:node.end_byte].decode('utf-8')

def find_child_by_type(node: tree_sitter.Node, node_type: str) -> Optional[tree_sitter.Node]:
    """Helper para encontrar el primer hijo de un tipo específico."""
    for child in node.children:
        if child.type == node_type:
            return child
    return None

def find_children_by_type(node: tree_sitter.Node, node_type: str) -> List[tree_sitter.Node]:
    """Helper para encontrar todos los hijos de un tipo específico."""
    return [child for child in node.children if child.type == node_type]

class CSharpUMLVisitor:
    def __init__(self, source_bytes: bytes, module_name: str):
        self.source_bytes = source_bytes
        self.module_name = module_name
        self.classes: List[UMLClassInfo] = []
        self.current_class: Optional[UMLClassInfo] = None

    def visit(self, node: tree_sitter.Node):
        if node.type == 'class_declaration' or node.type == 'interface_declaration':
            self._visit_class(node)
        elif node.type == 'namespace_declaration' or node.type == 'file_scoped_namespace_declaration':
            for child in node.children:
                self.visit(child)
        else:
            for child in node.children:
                self.visit(child)

    def _visit_class(self, node: tree_sitter.Node):
        name_node = find_child_by_type(node, 'identifier')
        if not name_node:
            return
        
        name = get_node_text(name_node, self.source_bytes)
        
        # Obtener herencia (bases)
        bases = []
        base_list_node = find_child_by_type(node, 'base_list')
        if base_list_node:
            for child in base_list_node.children:
                if child.type == 'identifier':
                    bases.append(get_node_text(child, self.source_bytes))
                elif child.type == 'generic_name':
                    bases.append(get_node_text(child, self.source_bytes))

        # El modulo será el nombre del namespace actual o del archivo
        cls_info = UMLClassInfo(name, bases, self.module_name)
        self.classes.append(cls_info)
        
        # Procesar el cuerpo de la clase
        body_node = find_child_by_type(node, 'declaration_list')
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
        
        type_node = node.child_by_field_name("type")
        id_node = node.child_by_field_name("name")
        
        if type_node and id_node:
            t = get_node_text(type_node, self.source_bytes)
            n = get_node_text(id_node, self.source_bytes)
            self.current_class.attributes.append(f"{t} {n}")

    def _visit_method(self, node: tree_sitter.Node):
        if not self.current_class: return
        
        name_node = find_child_by_type(node, 'identifier')
        params_node = find_child_by_type(node, 'parameter_list')
        
        if name_node and params_node:
            name = get_node_text(name_node, self.source_bytes)
            # Solo sacar los nombres de los parámetros como texto
            params_text = get_node_text(params_node, self.source_bytes)
            self.current_class.methods.append(f"{name}{params_text}")


class CSharpERVisitor:
    def __init__(self, source_bytes: bytes):
        self.source_bytes = source_bytes
        self.entities: List[EREntity] = []
        self.current_entity: Optional[EREntity] = None

    def visit(self, node: tree_sitter.Node):
        if node.type == 'class_declaration':
            self._visit_class(node)
        elif node.type == 'namespace_declaration' or node.type == 'file_scoped_namespace_declaration':
            for child in node.children:
                self.visit(child)
        else:
            for child in node.children:
                self.visit(child)

    def _visit_class(self, node: tree_sitter.Node):
        name_node = find_child_by_type(node, 'identifier')
        if not name_node:
            return
        
        name = get_node_text(name_node, self.source_bytes)
        
        # Por simplificación y convención de C#, casi cualquier clase en Models/Entities es una tabla
        # O podemos filtrar las que no parecen modelos, pero como este método se llama sobre proyectos
        # para extraer ER, asumimos que todas las clases encontradas en las rutas de escaneo son entidades.
        self.current_entity = EREntity(name)
        
        # Procesar atributos (propiedades)
        body_node = find_child_by_type(node, 'declaration_list')
        if body_node:
            for child in body_node.children:
                if child.type == 'property_declaration':
                    self._visit_property(child)
                    
        # Añadir si tiene columnas (es decir, propiedades)
        if self.current_entity.columns or self.current_entity.relationships:
             self.entities.append(self.current_entity)
        self.current_entity = None

    def _visit_property(self, node: tree_sitter.Node):
        if not self.current_entity: return
        
        # Verificamos si tiene data annotations como [Key], [Required]
        # attribute_list -> attribute -> name
        is_key = False
        is_required = False
        fk_target = None
        
        attr_lists = find_children_by_type(node, 'attribute_list')
        for attr_list in attr_lists:
            attrs = find_children_by_type(attr_list, 'attribute')
            for attr in attrs:
                attr_name = get_node_text(attr, self.source_bytes).replace("[", "").replace("]", "").strip()
                if attr_name.startswith("Key"):
                    is_key = True
                elif attr_name.startswith("Required"):
                    is_required = True
                elif attr_name.startswith("ForeignKey"):
                    # Basic extraction
                    fk_target = attr_name

        type_node = node.child_by_field_name("type")
        id_node = node.child_by_field_name("name")
                
        if type_node and id_node:
            t_str = get_node_text(type_node, self.source_bytes).strip()
            n_str = get_node_text(id_node, self.source_bytes).strip()
            
            # Detectar si es relación
            # 1. Collection (Ej: ICollection<User>, List<Post>)
            # 2. Virtual con un tipo de clase (Ej: virtual User user)
            is_relation = False
            target_class = ""
            rel_type = ""
            
            if "ICollection<" in t_str or "List<" in t_str or "IEnumerable<" in t_str:
                is_relation = True
                # Extraer target class
                start_idx = t_str.find("<")
                end_idx = t_str.rfind(">")
                if start_idx != -1 and end_idx != -1:
                    target_class = t_str[start_idx+1:end_idx].strip()
                rel_type = "||--o{" # 1 to Many
            else:
                # Si no es primitivo, asumimos que es una propiedad de navegación
                primitivos = ["int", "string", "bool", "double", "float", "decimal", "DateTime", "Guid", "long", "short", "byte", "char", "TimeSpan", "DateTimeOffset"]
                clean_type = t_str.replace("?", "").strip()
                if clean_type not in primitivos:
                    is_relation = True
                    target_class = clean_type
                    rel_type = "}o--||" # Many to 1 (Foreign key)
            
            if is_relation and target_class:
                label = "FK" if fk_target else n_str
                self.current_entity.relationships.append((target_class, rel_type, label))
            else:
                # Si es columna normal
                col_type = t_str
                if is_key:
                    col_type += " PK"
                self.current_entity.columns.append((n_str, col_type))

def parse_project_for_csharp_uml(root_path: str, max_depth: int = 3) -> List[UMLClassInfo]:
    if not PARSER:
         print("⚠️ No se pudo cargar tree-sitter. Asegúrate de tener tree-sitter y tree-sitter-c-sharp instalados.")
         return []
         
    all_classes = []
    root = Path(root_path)
    ignore_dirs = {'.git', 'node_modules', 'bin', 'obj', 'Properties', '.vs'}

    for root_dir, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        
        try:
            current_depth = len(Path(root_dir).relative_to(root).parts)
        except ValueError:
            current_depth = 0
            
        if current_depth > max_depth:
            continue
            
        for file in files:
            if file.endswith(".cs"):
                file_path = Path(root_dir) / file
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        source_bytes = f.read().encode('utf-8')
                    
                    tree = PARSER.parse(source_bytes)
                    
                    rel_path = file_path.relative_to(root)
                    # Convertir path a namespace module
                    module_name = str(rel_path.parent).replace(os.sep, ".")
                    if module_name == ".":
                         module_name = "Root"
                         
                    visitor = CSharpUMLVisitor(source_bytes, module_name)
                    visitor.visit(tree.root_node)
                    all_classes.extend(visitor.classes)
                except Exception as e:
                    print(f"Error parsing {file}: {e}")
                    continue
    return all_classes

def parse_project_for_csharp_er(root_path: str, max_depth: int = 3) -> List[EREntity]:
    if not PARSER:
         print("⚠️ No se pudo cargar tree-sitter. Asegúrate de tener tree-sitter y tree-sitter-c-sharp instalados.")
         return []
         
    all_entities = []
    root = Path(root_path)
    ignore_dirs = {'.git', 'node_modules', 'bin', 'obj', 'Properties', '.vs'}
    
    # Heurística: normalmente buscamos en carpetas "Models", "Entities", "Data" o archivos directos.
    # Pero el walk lo hará general.

    for root_dir, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        
        try:
            current_depth = len(Path(root_dir).relative_to(root).parts)
        except ValueError:
            current_depth = 0
            
        if current_depth > max_depth:
            continue
            
        for file in files:
            if file.endswith(".cs"):
                # Omitimos program, startup, controllers si podemos.
                if file.lower() in ["program.cs", "startup.cs"] or "Controller" in file:
                     continue
                     
                file_path = Path(root_dir) / file
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        source_bytes = f.read().encode('utf-8')
                    
                    tree = PARSER.parse(source_bytes)
                    visitor = CSharpERVisitor(source_bytes)
                    visitor.visit(tree.root_node)
                    
                    all_entities.extend(visitor.entities)
                except Exception:
                    continue
    return all_entities
