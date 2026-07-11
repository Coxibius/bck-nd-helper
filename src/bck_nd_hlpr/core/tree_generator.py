"""
tree_generator: Genera un árbol visual de la estructura de archivos y carpetas
de un proyecto, filtrando automáticamente carpetas de ruido (node_modules, venv,
__pycache__, .git, etc.).

Uso independiente:
    from bck_nd_hlpr.core.tree_generator import generate_project_tree
    print(generate_project_tree("/path/to/project", depth=4))

Parte del ecosistema bck-nd-hlpr.
"""
import os
from pathlib import Path
from typing import List, Optional

from bck_nd_hlpr.core.constants import GLOBAL_IGNORE_DIRS, SKIP_DIRS, SKIP_FILES, SKIP_EXTENSIONS, DEFAULT_OUTPUT_FILE
from bck_nd_hlpr.core.utils.gitignore_parser import parse_gitignore, matches_gitignore


def generate_project_tree(
    root_path: str,
    depth: int = 4,
    output_file: Optional[str] = None,
    extra_ignores: Optional[List[str]] = None,
) -> str:
    """
    Genera un árbol ASCII limpio del proyecto.

    Args:
        root_path: Ruta absoluta o relativa al directorio raíz del proyecto.
        depth: Profundidad máxima de escaneo (niveles de subdirectorios).
        output_file: Nombre del archivo de salida a excluir del tree (ej: ai_context.txt).
        extra_ignores: Lista adicional de nombres de archivo/directorio a ignorar.

    Returns:
        String con el árbol completo listo para imprimir o incrustar.
    """
    root = Path(root_path).resolve()
    if not root.exists():
        return f"Error: Path '{root_path}' does not exist."
    if not root.is_dir():
        return f"Error: Path '{root_path}' is not a directory."

    # Parsear .gitignore una sola vez al inicio
    gitignore_patterns = parse_gitignore(root)

    # Resolver nombre del archivo de output a excluir
    resolved_output = output_file or DEFAULT_OUTPUT_FILE

    # Construir set de ignores extra
    extra_set = set(extra_ignores) if extra_ignores else set()

    lines: List[str] = [root.name + "/"]
    _walk_tree(
        root, root,
        prefix="", depth=0, max_depth=depth,
        lines=lines,
        gitignore_patterns=gitignore_patterns,
        output_file=resolved_output,
        extra_ignores=extra_set,
    )
    return "\n".join(lines)


def _walk_tree(
    current: Path,
    root: Path,
    prefix: str,
    depth: int,
    max_depth: int,
    lines: List[str],
    gitignore_patterns: List[str],
    output_file: str,
    extra_ignores: set,
) -> None:
    """Recorre recursivamente el árbol de directorios."""
    if depth >= max_depth:
        return

    try:
        children = sorted(
            current.iterdir(),
            key=lambda p: (p.is_file(), p.name.lower()),
        )
    except OSError:
        return

    # Filtrar directorios/archivos ignorados
    visible = [
        c for c in children
        if not _should_ignore(c, root, gitignore_patterns, output_file, extra_ignores)
    ]

    for i, child in enumerate(visible):
        is_last = i == len(visible) - 1
        connector = "└── " if is_last else "├── "
        extension = "    " if is_last else "│   "

        if child.is_dir():
            lines.append(f"{prefix}{connector}{child.name}/")
            _walk_tree(
                child, root,
                prefix + extension, depth + 1, max_depth,
                lines,
                gitignore_patterns, output_file, extra_ignores,
            )
        else:
            lines.append(f"{prefix}{connector}{child.name}")


def _should_ignore(
    path: Path,
    root: Path,
    gitignore_patterns: List[str],
    output_file: str,
    extra_ignores: set,
) -> bool:
    """Determina si un archivo o directorio debe ser ignorado del árbol o del dump."""
    name = path.name

    # ── 0. Excluir el propio archivo de output ──
    if not path.is_dir() and name == output_file:
        return True

    # ── 0b. Excluir ignores extra ──
    if name in extra_ignores:
        return True

    # ── 1. Reglas estáticas (constantes) ──
    if path.is_dir():
        # Ignorar carpetas de la lista negra global o skip_dirs
        if name in GLOBAL_IGNORE_DIRS or name in SKIP_DIRS:
            return True

        # Ignorar si algún componente de la ruta está en la lista negra o skip_dirs
        try:
            rel_parts = path.relative_to(root).parts
            if any(p in GLOBAL_IGNORE_DIRS or p in SKIP_DIRS for p in rel_parts):
                return True
        except ValueError:
            if any(p in GLOBAL_IGNORE_DIRS or p in SKIP_DIRS for p in path.parts):
                return True

        # Ignorar carpetas/archivos que empiezan con punto (excepto archivos config comunes)
        if name.startswith(".") and path.is_dir():
            return True

        # Ignorar carpetas que terminan en .egg-info
        if name.endswith(".egg-info"):
            return True
    else:
        # Ignorar archivos específicos
        if name in SKIP_FILES:
            return True

        # Ignorar extensiones específicas
        name_lower = name.lower()
        if any(name_lower.endswith(ext.lower()) for ext in SKIP_EXTENSIONS):
            return True

    # ── 2. Reglas dinámicas (.gitignore) ──
    if gitignore_patterns and matches_gitignore(path, root, gitignore_patterns):
        return True

    return False
