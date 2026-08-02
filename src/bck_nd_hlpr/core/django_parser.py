"""
Módulo para el análisis estático de código Python enfocado en Django usando el módulo AST nativo.
Extrae UML y ER especializados.
"""
import ast
import os
from pathlib import Path
from typing import List

from bck_nd_hlpr.core.uml_parser import UMLClassInfo
from bck_nd_hlpr.core.er_parser import EREntity
from bck_nd_hlpr.core.constants import GLOBAL_IGNORE_DIRS
from bck_nd_hlpr.core.er_parser import ERExtractor

# We can re-use the generic AST extractors because they already do a great job,
# but we wrap them here to maintain the same API signature as the tree-sitter ones.
# If we need Django specific enhancements in the future, we can override the Visitors here.

# TODO(audit): Add support for Python 3.10-3.12 syntax features: ast.TypeAlias (PEP 695 `type` statements),
# TODO(audit): ast.Match structural pattern matching (match/case), and robust SQLAlchemy 2.0 Mapped[...] type
# TODO(audit): annotation parsing with declarative-style mapped_column() declarations.
class DjangoERExtractor(ERExtractor):
    """Extends the generic ERExtractor to enforce Django models only (optional) or add specific heuristics."""
    # TODO(audit): Override visit_ClassDef to detect class-level `type` alias statements (PEP 695)
    # TODO(audit): inside Django model classes to resolve forward-referenced Mapped[...] generic type strings.
    def _is_model(self, bases: List[ast.expr]) -> bool:
        # Django models inherit from models.Model
        for base in bases:
            if isinstance(base, ast.Attribute) and base.attr == 'Model':
                return True
            if isinstance(base, ast.Name) and base.id in ['Model', 'AbstractUser']:
                return True
        return False

def parse_project_for_django_uml(root_path: str, max_depth: int = 4) -> List[UMLClassInfo]:
    all_classes = []
    root = Path(root_path)

    for root_dir, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS]
        try: current_depth = len(Path(root_dir).relative_to(root).parts)
        except ValueError: current_depth = 0
        if current_depth > max_depth: continue
            
        for file in files:
            if file.endswith(".py"):
                file_path = Path(root_dir) / file
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    
                    tree = ast.parse(content)
                    rel_path = file_path.relative_to(root)
                    extractor = UMLExtractor(file_path, str(rel_path))
                    extractor.visit(tree)
                    all_classes.extend(extractor.classes)
                except Exception:
                    continue
    return all_classes

def parse_project_for_django_er(root_path: str, max_depth: int = 4) -> List[EREntity]:
    all_entities = []
    root = Path(root_path)

    for root_dir, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS]
        try: current_depth = len(Path(root_dir).relative_to(root).parts)
        except ValueError: current_depth = 0
        if current_depth > max_depth: continue
            
        for file in files:
            # En Django, los modelos suelen estar en models.py
            if file.endswith(".py"):
                file_path = Path(root_dir) / file
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    
                    tree = ast.parse(content)
                    # We use our specific DjangoERExtractor
                    extractor = DjangoERExtractor()
                    extractor.visit(tree)
                    all_entities.extend(extractor.entities)
                except Exception:
                    continue
    return all_entities
