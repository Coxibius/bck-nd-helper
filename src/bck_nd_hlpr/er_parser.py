"""
Módulo para la generación de Diagramas E-R (Entity-Relationship) mediante análisis estático.
Soporta detección básica de modelos SQLAlchemy y Django.
"""
import ast
import os
from pathlib import Path
from typing import Dict, List, Optional, Any

class EREntity:
    """Representa una entidad (tabla) en el diagrama ER."""
    def __init__(self, name: str):
        self.name = name
        self.columns: List[tuple[str, str]] = []  # (name, type)
        self.relationships: List[tuple[str, str, str]] = [] # (target_entity, relation_type, label)

class ERExtractor(ast.NodeVisitor):
    """
    Analiza AST para encontrar modelos de base de datos.
    """
    def __init__(self):
        self.entities: List[EREntity] = []
        self.current_entity: Optional[EREntity] = None
        self.imports: Dict[str, str] = {}

    def visit_ImportFrom(self, node: ast.ImportFrom):
        module = node.module or ""
        for alias in node.names:
            name = alias.name
            asname = alias.asname or name
            self.imports[asname] = f"{module}.{name}" if module else name
        self.generic_visit(node)

    def _is_model(self, bases: List[Any]) -> bool:
        """Heurística para determinar si es un modelo ORM."""
        model_bases = {'Base', 'Model', 'db.Model', 'models.Model', 'DeclarativeBase'}
        for base in bases:
            if isinstance(base, ast.Name) and base.id in model_bases:
                return True
            if isinstance(base, ast.Attribute) and base.attr == 'Model':
                return True
        return False

    def visit_ClassDef(self, node: ast.ClassDef):
        if self._is_model(node.bases):
            self.current_entity = EREntity(node.name)
            self.entities.append(self.current_entity)
            self.generic_visit(node)
            self.current_entity = None
        else:
            # Aún si no hereda explícitamente, buscamos si tiene __tablename__
            has_tablename = any(
                isinstance(n, ast.Assign) and 
                any(isinstance(t, ast.Name) and t.id == '__tablename__' for t in n.targets)
                for n in node.body
            )
            if has_tablename:
                self.current_entity = EREntity(node.name)
                self.entities.append(self.current_entity)
                self.generic_visit(node)
                self.current_entity = None

    def visit_Assign(self, node: ast.Assign):
        if not self.current_entity:
            return

        target_name = ""
        for target in node.targets:
            if isinstance(target, ast.Name):
                target_name = target.id
        
        if not target_name:
            return

        if isinstance(node.value, ast.Call):
            func_name = ""
            if isinstance(node.value.func, ast.Name):
                func_name = node.value.func.id
            elif isinstance(node.value.func, ast.Attribute):
                func_name = node.value.func.attr

            # SQLAlchemy
            if func_name in ['Column', 'Mapped']:
                col_type = "Unknown"
                if node.value.args:
                    arg0 = node.value.args[0]
                    if isinstance(arg0, ast.Name):
                        col_type = arg0.id
                    elif isinstance(arg0, ast.Attribute):
                        col_type = arg0.attr
                self.current_entity.columns.append((target_name, col_type))
                
                # Busqueda simple de ForeignKey en args
                for arg in node.value.args:
                    if isinstance(arg, ast.Call) and getattr(arg.func, 'id', '') == 'ForeignKey':
                         if arg.args and isinstance(arg.args[0], ast.Constant):
                             # 'users.id' -> target 'User' (heuristic)
                             fk_ref = str(arg.args[0].value)
                             target_table = fk_ref.split('.')[0]
                             self.current_entity.relationships.append((target_table, "}o--||", "FK"))

            # Django
            elif 'Field' in func_name:
                col_type = func_name.replace("Field", "")
                self.current_entity.columns.append((target_name, col_type))
                
                if 'ForeignKey' in func_name or 'OneToOne' in func_name:
                     if node.value.args:
                        arg0 = node.value.args[0]
                        target = "Unknown"
                        if isinstance(arg0, ast.Name):
                            target = arg0.id
                        elif isinstance(arg0, ast.Constant):
                            target = str(arg0.value)
                        elif isinstance(arg0, ast.Str): # Python < 3.8
                             target = arg0.s
                        self.current_entity.relationships.append((target, "}o--||", "FK"))

    def visit_AnnAssign(self, node: ast.AnnAssign):
        # TODO: Soportar Mapped[int] si es necesario en el futuro
        pass

def parse_project_for_er(root_path: str, max_depth: int = 3) -> List[EREntity]:
    all_entities = []
    root = Path(root_path)
    
    # Extensiones de archivos a ignorar para velocidad
    ignore_dirs = {'venv', 'env', '.venv', '__pycache__', '.git', 'node_modules', 'dist', 'build'}

    for root_dir, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        
        try:
            current_depth = len(Path(root_dir).relative_to(root).parts)
        except ValueError:
            current_depth = 0
            
        if current_depth > max_depth:
            continue
            
        for file in files:
            if file.endswith(".py"):
                file_path = Path(root_dir) / file
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    tree = ast.parse(content)
                    extractor = ERExtractor()
                    extractor.visit(tree)
                    all_entities.extend(extractor.entities)
                except Exception:
                    continue
    return all_entities

def generate_mermaid_er(entities: List[EREntity]) -> str:
    lines = ["erDiagram"]
    
    if not entities:
        return ""

    entity_names = {e.name for e in entities}
    
    # 1. Definir Entidades
    for entity in entities:
        lines.append(f"    {entity.name} {{")
        for col_name, col_type in entity.columns:
            # Mermaid ER no soporta espacios en tipos, limpiamos un poco
            clean_type = str(col_type).replace(" ", "_")
            lines.append(f"        {clean_type} {col_name}")
        lines.append("    }")
    
    # 2. Definir Relaciones
    for entity in entities:
        for target, rel_type, label in entity.relationships:
            # Heurística para encontrar el nombre real de la clase destino
            real_target = target
            
            # Si target es 'users' (tabla) y tenemos clase 'User'
            candidate_singular = target.capitalize()
            # Quitamos 's' final simple
            candidate_singular_s = target[:-1].capitalize() if target.endswith('s') else target

            if target in entity_names:
                real_target = target
            elif candidate_singular in entity_names:
                real_target = candidate_singular
            elif candidate_singular_s in entity_names:
                real_target = candidate_singular_s
            
            # Solo dibujamos si el target existe (o lo forzamos si se prefiere)
            # Para robustez, dibujamos igual, Mermaid lo creará si no existe
            lines.append(f"    {entity.name} {rel_type} {real_target} : \"{label}\"")
            
    return "\n".join(lines)
