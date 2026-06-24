"""
Módulo para el análisis estático de código Python y extracción de estructuras UML.
Utiliza el módulo 'ast' nativo para evitar dependencias pesadas.
"""
import ast
import os
from pathlib import Path
from typing import Dict, List, Optional, Set, Any

class UMLClassInfo:
    """Estructura de datos para almacenar info de una clase."""
    def __init__(self, name: str, bases: List[str], module: str):
        self.name = name
        self.bases = bases
        self.methods: List[str] = []
        self.attributes: List[str] = []
        self.module = module  # "carpeta.archivo" para agrupar

class UMLExtractor(ast.NodeVisitor):
    """
    Recorre el AST de un archivo Python para encontrar definiciones de clases.
    """
    def __init__(self, file_path: Path, relative_path: str):
        self.classes: List[UMLClassInfo] = []
        self.current_class: Optional[UMLClassInfo] = None
        self.file_path = file_path
        # Convertimos ruta a notación de punto (ej: src/utils.py -> src.utils)
        self.module_name = str(relative_path).replace(os.sep, ".").replace(".py", "")
        self.imports: Dict[str, str] = {} # Alias -> FullModule

    def visit_Import(self, node: ast.Import):
        """Rastrea imports tipo 'import modulo'"""
        for alias in node.names:
            name = alias.name
            asname = alias.asname or name
            self.imports[asname] = name
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        """Rastrea imports tipo 'from datos import Modelo'"""
        module = node.module or ""
        for alias in node.names:
            name = alias.name
            asname = alias.asname or name
            # Guardamos origen completo
            self.imports[asname] = f"{module}.{name}" if module else name
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        """Encuentra definiciones de clase."""
        bases = []
        for base in node.bases:
            # Intentar resolver el nombre base
            if isinstance(base, ast.Name):
                bases.append(base.id)
            elif isinstance(base, ast.Attribute):
                # Caso: models.User
                bases.append(f"{base.value.id}.{base.attr}") # type: ignore

        self.current_class = UMLClassInfo(node.name, bases, self.module_name)
        self.classes.append(self.current_class)
        
        # Continuar visitando para encontrar métodos
        self.generic_visit(node)
        
        self.current_class = None

    def visit_FunctionDef(self, node: ast.FunctionDef):
        """Encuentra métodos dentro de clases."""
        if self.current_class:
            # Ignoramos métodos privados si empiezan con _ (opcional)
            # if node.name.startswith("_") and not node.name.startswith("__"): return
            
            # Formatear argumentos
            args = [arg.arg for arg in node.args.args if arg.arg != 'self']
            sig = f"{node.name}({', '.join(args)})"
            self.current_class.methods.append(sig)
    
    # Podríamos añadir visit_Assign para detectar atributos self.x = 1

def parse_file_for_uml(file_path: Path, root_path: Path) -> List[UMLClassInfo]:
    """Helper para parsear un archivo único y retornar sus clases."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        
        tree = ast.parse(content)
        rel_path = file_path.relative_to(root_path)
        extractor = UMLExtractor(file_path, str(rel_path))
        extractor.visit(tree)
        return extractor.classes
    except Exception as e:
        # Si falla el parseo (sintaxis invalida, etc), retornamos lista vacía para no romper el flujo
        # print(f"Error parsing {file_path}: {e}")
        return []

def generate_mermaid_class_diagram(all_classes: List[UMLClassInfo]) -> str:
    """Genera código Mermaid Class Diagram a partir de la lista de clases extraídas."""
    lines = ["classDiagram"]
    
    # Agrupar por "Namespaces" (carpetas)
    modules: Dict[str, List[UMLClassInfo]] = {}
    for cls in all_classes:
        # Usamos el directorio padre como namespace principal para simplificar
        # ej: src.controllers.user_ctrl -> controllers
        parts = cls.module.split(".")
        if len(parts) > 1:
            namespace = parts[-2] if parts[-1] != parts[-2] else parts[-2] 
            # Ajuste: si el archivo es root, namespace es ROOT
        else:
            namespace = "Root"
            
        if namespace not in modules: modules[namespace] = []
        modules[namespace].append(cls)

    # Dibujar clases agrupadas
    for namespace, classes in modules.items():
        safe_ns = namespace.replace("-", "_")
        lines.append(f"    namespace {safe_ns} {{")
        for cls in classes:
            safe_cls_name = cls.name.replace("-", "_")
            lines.append(f"      class {safe_cls_name} {{")
            for attr in cls.attributes:
                # Basic sanitation for attributes to avoid breaking mermaid
                clean_attr = " ".join(attr.split())
                safe_attr = clean_attr.replace("{", "").replace("}", "").replace("<", "~").replace(">", "~")
                lines.append(f"        +{safe_attr}")
            for method in cls.methods:
                # Mermaid fails to parse { } or <> inside method signatures
                clean_method = " ".join(method.split())
                safe_method = clean_method.replace("{", "").replace("}", "").replace("<", "~").replace(">", "~")
                lines.append(f"        +{safe_method}")
            lines.append("      }")
        lines.append("    }")

    # Dibujar relaciones (Herencia)
    # Mapeo rápido NombreClase -> ClaseObj para verificar existencia
    class_map = {c.name.replace("-", "_"): c for c in all_classes}

    for cls in all_classes:
        safe_cls_name = cls.name.replace("-", "_")
        for base_name in cls.bases:
            # Intentar limpiar nombre si viene con módulo (models.User -> User)
            clean_base = base_name.split(".")[-1].replace("-", "_")
            
            # Solo dibujamos si la clase base también está en nuestro proyecto
            # Ojo: esto omite herencias de librerías externas (como db.Model), lo cual suele ser deseado
            if clean_base in class_map:
                lines.append(f"    {clean_base} <|-- {safe_cls_name}")
            else:
                # Opcional: Mostrar herencia externa con estilo diferente o ignorar
                pass

    # Dibujar asociaciones y dependencias
    import re
    drawn_associations = set()
    
    # Primero dibujamos asociaciones fuertes (basadas en atributos/propiedades)
    for cls in all_classes:
        safe_cls_name = cls.name.replace("-", "_")
        for attr in cls.attributes:
            words = re.findall(r'\b[A-Z][a-zA-Z0-9_]*\b', attr)
            for word in words:
                if word in class_map and word != safe_cls_name:
                    rel_pair = (safe_cls_name, word)
                    if rel_pair not in drawn_associations:
                        lines.append(f"    {safe_cls_name} --> {word}")
                        drawn_associations.add(rel_pair)
                        
    # Luego dibujamos dependencias débiles (basadas en parámetros de métodos)
    for cls in all_classes:
        safe_cls_name = cls.name.replace("-", "_")
        for method in cls.methods:
            words = re.findall(r'\b[A-Z][a-zA-Z0-9_]*\b', method)
            for word in words:
                if word in class_map and word != safe_cls_name:
                    if (safe_cls_name, word) not in drawn_associations:
                        dep_pair = f"{safe_cls_name}_dep_{word}"
                        if dep_pair not in drawn_associations:
                            lines.append(f"    {safe_cls_name} ..> {word}")
                            drawn_associations.add(dep_pair)

    return "\n".join(lines)
