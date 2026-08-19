"""
Módulo para el análisis estático de código Python enfocado en Django usando el módulo AST nativo.
Extrae UML y ER especializados.
"""
import ast
import os
from pathlib import Path
from typing import List, Optional

from bck_nd_hlpr.core.uml_parser import UMLClassInfo, UMLExtractor
from bck_nd_hlpr.core.er_parser import EREntity
from bck_nd_hlpr.core.constants import GLOBAL_IGNORE_DIRS
from bck_nd_hlpr.core.er_parser import ERExtractor


class DjangoERExtractor(ERExtractor):
    """Extends the generic ERExtractor to enforce Django models only (optional) or add specific heuristics."""

    def _resolve_forward_type_ref(self, type_str: str) -> str:
        """Resolve a forward-reference type string against collected PEP 695
        ``type`` aliases and module-level imports.

        For Django 5+ model field annotations that reference PEP 695 type
        aliases by name (e.g. ``Mapped['UserId']`` where the module has
        ``type UserId = int``), this helper first consults the shared
        ``imports`` dict populated by :meth:`visit_TypeAlias` overrides and
        returns the canonical alias key when present.  String-quoted forward
        references are unquoted so downstream ER-extraction logic can match
        them against class names in the same compilation unit.  Returns the
        input unchanged when no mapping is found.
        """
        if not type_str:
            return type_str
        unquoted = type_str.strip()
        if len(unquoted) >= 2 and unquoted[0] in ("'", '"') and unquoted[-1] == unquoted[0]:
            unquoted = unquoted[1:-1].strip()
        if unquoted and unquoted in self.imports:
            mapped = self.imports[unquoted]
            if mapped and isinstance(mapped, str):
                return mapped
        return unquoted if unquoted else type_str

    def _is_model(self, bases: List[ast.expr]) -> bool:
        for base in bases:
            if isinstance(base, ast.Attribute) and base.attr == 'Model':
                return True
            if isinstance(base, ast.Name) and base.id in ['Model', 'AbstractUser']:
                return True
        return False

    def visit_TypeAlias(self, node: ast.AST) -> None:
        """Record Python 3.12 PEP 695 ``type X = ...`` statements at module scope.

        For Django ORM sources, aliases defined at the module level are
        frequently used as forward-reference strings in ``Mapped['Alias']`` type
        annotations.  This override stores the alias key in the shared ``imports``
        dictionary so the base ER type-extraction logic can resolve it later,
        and then continues traversal of child nodes via ``generic_visit``.
        """
        try:
            alias_name = getattr(node, "name", None)
            if alias_name is not None:
                key = getattr(alias_name, "id", None) or str(alias_name)
                if key and key not in self.imports:
                    self.imports[key] = key
        except Exception:
            pass
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        """Visit a class, additionally resolving PEP 695 ``type X = ...``
        aliases declared within class scope.

        For Django model classes, any ``type X = SomeType`` statements inside
        the class body are inspected so that forward-referenced
        ``Mapped['X']`` strings can resolve to concrete types later.
        The base-class logic still runs so class bodies are fully traversed
        and model fields / relationships are extracted as usual.
        """
        if self._is_model(node.bases) or self.is_model_file:
            for stmt in node.body:
                if isinstance(stmt, ast.TypeAlias):
                    try:
                        alias_name = getattr(stmt, "name", None)
                        if alias_name is not None:
                            key = getattr(alias_name, "id", None) or str(alias_name)
                            if key and key not in self.imports:
                                self.imports[key] = key
                    except Exception:
                        pass
            self.current_entity = EREntity(node.name)
            self.entities.append(self.current_entity)
            self.generic_visit(node)
            self.current_entity = None
        else:
            has_tablename = any(
                isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == '__tablename__' for t in n.targets)
                for n in node.body
            )
            if has_tablename:
                self.current_entity = EREntity(node.name)
                self.entities.append(self.current_entity)
                self.generic_visit(node)
                self.current_entity = None


def parse_project_for_django_uml(root_path: str, max_depth: Optional[int] = 4) -> List[UMLClassInfo]:
    all_classes = []
    root = Path(root_path)

    for root_dir, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS]
        try: current_depth = len(Path(root_dir).relative_to(root).parts)
        except ValueError: current_depth = 0
        if max_depth is not None and current_depth > max_depth: continue

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

def parse_project_for_django_er(root_path: str, max_depth: Optional[int] = 4) -> List[EREntity]:
    all_entities = []
    root = Path(root_path)

    for root_dir, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS]
        try: current_depth = len(Path(root_dir).relative_to(root).parts)
        except ValueError: current_depth = 0
        if max_depth is not None and current_depth > max_depth: continue

        for file in files:
            if file.endswith(".py"):
                file_path = Path(root_dir) / file
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()

                    tree = ast.parse(content)
                    extractor = DjangoERExtractor()
                    extractor.visit(tree)
                    all_entities.extend(extractor.entities)
                except Exception:
                    continue
    return all_entities
