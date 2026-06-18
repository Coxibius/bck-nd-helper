"""
tree_generator: Genera un árbol visual de la estructura de archivos y carpetas
de un proyecto, filtrando automáticamente carpetas de ruido (node_modules, venv,
__pycache__, .git, etc.).

Uso independiente:
    from bck_nd_hlpr.tree_generator import generate_project_tree
    print(generate_project_tree("/path/to/project", depth=4))

Parte del ecosistema bck-nd-hlpr.
"""
import os
from pathlib import Path
from typing import List

from bck_nd_hlpr.constants import GLOBAL_IGNORE_DIRS


def generate_project_tree(root_path: str, depth: int = 4) -> str:
    """
    Genera un árbol ASCII limpio del proyecto.

    Args:
        root_path: Ruta absoluta o relativa al directorio raíz del proyecto.
        depth: Profundidad máxima de escaneo (niveles de subdirectorios).

    Returns:
        String con el árbol completo listo para imprimir o incrustar.
    """
    root = Path(root_path).resolve()
    if not root.exists():
        return f"Error: Path '{root_path}' does not exist."
    if not root.is_dir():
        return f"Error: Path '{root_path}' is not a directory."

    lines: List[str] = [root.name + "/"]
    _walk_tree(root, root, prefix="", depth=0, max_depth=depth, lines=lines)
    return "\n".join(lines)


def _walk_tree(
    current: Path,
    root: Path,
    prefix: str,
    depth: int,
    max_depth: int,
    lines: List[str],
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
    visible = [c for c in children if not _should_ignore(c, root)]

    for i, child in enumerate(visible):
        is_last = i == len(visible) - 1
        connector = "└── " if is_last else "├── "
        extension = "    " if is_last else "│   "

        if child.is_dir():
            lines.append(f"{prefix}{connector}{child.name}/")
            _walk_tree(child, root, prefix + extension, depth + 1, max_depth, lines)
        else:
            lines.append(f"{prefix}{connector}{child.name}")


def _should_ignore(path: Path, root: Path) -> bool:
    """Determina si un archivo o directorio debe ser ignorado del árbol."""
    name = path.name

    # Ignorar carpetas de la lista negra global
    if path.is_dir() and name in GLOBAL_IGNORE_DIRS:
        return True

    # Ignorar si algún componente de la ruta está en la lista negra
    try:
        rel_parts = path.relative_to(root).parts
        if any(p in GLOBAL_IGNORE_DIRS for p in rel_parts):
            return True
    except ValueError:
        if any(p in GLOBAL_IGNORE_DIRS for p in path.parts):
            return True

    # Ignorar carpetas/archivos que empiezan con punto (excepto archivos config comunes)
    if name.startswith(".") and path.is_dir():
        return True

    # Ignorar carpetas que terminan en .egg-info
    if path.is_dir() and name.endswith(".egg-info"):
        return True

    return False
