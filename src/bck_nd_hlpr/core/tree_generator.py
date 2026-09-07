"""
tree_generator: Genera un árbol visual de la estructura de archivos y carpetas
de un proyecto, filtrando automáticamente carpetas de ruido (node_modules, venv,
__pycache__, .git, etc.).

Uso independiente:
    from bck_nd_hlpr.core.tree_generator import generate_project_tree
    print(generate_project_tree("/path/to/project"))        # unlimited depth
    print(generate_project_tree("/path/to/project", depth=4))  # capped at 4

Parte del ecosistema bck-nd-hlpr.
"""
import os
import stat
from pathlib import Path
from typing import List, Optional

from bck_nd_hlpr.core.constants import (
    BCK_ND_CACHE_DIRECTORY,
    BCK_ND_DIRECTORY,
    DEFAULT_OUTPUT_FILE,
    GLOBAL_IGNORE_DIRS,
    SKIP_DIRS,
    SKIP_EXTENSIONS,
    SKIP_FILES,
)
from bck_nd_hlpr.core.utils.gitignore_parser import GitIgnoreMatcher


def _is_link_or_reparse(path_stat: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(path_stat.st_mode) or bool(
        getattr(path_stat, "st_file_attributes", 0) & reparse_flag
    )


def _safe_path_kind(path: Path) -> Optional[str]:
    try:
        path_stat = path.lstat()
    except OSError:
        return None
    if _is_link_or_reparse(path_stat):
        return None
    if stat.S_ISDIR(path_stat.st_mode):
        return "directory"
    if stat.S_ISREG(path_stat.st_mode):
        return "file"
    return None


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        root_text = os.path.normcase(os.path.abspath(str(root)))
        candidate_text = os.path.normcase(os.path.abspath(str(candidate)))
        return os.path.commonpath([root_text, candidate_text]) == root_text
    except (OSError, ValueError):
        return False


def generate_project_tree(
    root_path: str,
    depth: Optional[int] = None,
    output_file: Optional[str] = None,
    extra_ignores: Optional[List[str]] = None,
    gitignore_matcher: Optional[GitIgnoreMatcher] = None,
) -> str:
    """
    Genera un árbol ASCII limpio del proyecto.

    Args:
        root_path: Ruta absoluta o relativa al directorio raíz del proyecto.
        depth: Profundidad máxima de escaneo (niveles de subdirectorios).
               None (default) = unlimited recursive traversal.
        output_file: Nombre del archivo de salida a excluir del tree (ej: ai_context.txt).
        extra_ignores: Lista adicional de nombres de archivo/directorio a ignorar.

    Returns:
        String con el árbol completo listo para imprimir o incrustar.
    """
    root_candidate = Path(os.path.abspath(str(root_path)))
    if _safe_path_kind(root_candidate) != "directory":
        return "Error: Project tree root is unavailable."
    try:
        root = root_candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        return "Error: Project tree root is unavailable."

    matcher = gitignore_matcher or GitIgnoreMatcher(root)

    # Resolver nombre del archivo de output a excluir
    resolved_output = output_file or DEFAULT_OUTPUT_FILE

    # Construir set de ignores extra
    extra_set = set(extra_ignores) if extra_ignores else set()

    lines: List[str] = [root.name + "/"]
    _walk_tree(
        root, root,
        prefix="", current_depth=0, max_depth=depth,
        lines=lines,
        gitignore_matcher=matcher,
        output_file=resolved_output,
        extra_ignores=extra_set,
    )
    return "\n".join(lines)


def _walk_tree(
    current: Path,
    root: Path,
    prefix: str,
    current_depth: int,
    max_depth: Optional[int],
    lines: List[str],
    gitignore_matcher: GitIgnoreMatcher,
    output_file: str,
    extra_ignores: set,
) -> None:
    """Recorre recursivamente el árbol de directorios."""
    if max_depth is not None and current_depth >= max_depth:
        return

    if _safe_path_kind(current) != "directory":
        return
    try:
        canonical_current = current.resolve(strict=True)
    except (OSError, RuntimeError):
        return
    if not _is_within(canonical_current, root):
        return

    gitignore_matcher.load_directory(current)
    try:
        classified_children = []
        for child in current.iterdir():
            kind = _safe_path_kind(child)
            if kind is not None:
                classified_children.append((child, kind))
        children = sorted(
            classified_children,
            key=lambda item: (
                0 if item[1] == "directory" else 1,
                item[0].name.casefold(),
                item[0].name,
            ),
        )
    except OSError:
        return

    # Filtrar directorios/archivos ignorados
    visible = [
        (child, kind) for child, kind in children
        if not _should_ignore(
            child,
            kind == "directory",
            root,
            gitignore_matcher,
            output_file,
            extra_ignores,
        )
    ]

    for i, (child, kind) in enumerate(visible):
        is_last = i == len(visible) - 1
        connector = "└── " if is_last else "├── "
        extension = "    " if is_last else "│   "

        if kind == "directory":
            lines.append(f"{prefix}{connector}{child.name}/")
            _walk_tree(
                child, root,
                prefix + extension, current_depth + 1, max_depth,
                lines,
                gitignore_matcher, output_file, extra_ignores,
            )
        else:
            lines.append(f"{prefix}{connector}{child.name}")


def _should_ignore(
    path: Path,
    is_directory: bool,
    root: Path,
    gitignore_matcher: GitIgnoreMatcher,
    output_file: str,
    extra_ignores: set,
) -> bool:
    """Determina si un archivo o directorio debe ser ignorado del árbol o del dump."""
    name = path.name

    try:
        rel_parts = path.relative_to(root).parts
    except ValueError:
        rel_parts = path.parts

    # Hide only Backend Helper's legacy and current generated cache roots.
    # Generic `cache/` directories and user-authored `.bck-nd/product/` and
    # `.bck-nd/requirements/` remain visible.
    if rel_parts and rel_parts[0] == ".bck-nd-cache":
        return True
    if len(rel_parts) >= 2 and rel_parts[:2] == (
        BCK_ND_DIRECTORY,
        BCK_ND_CACHE_DIRECTORY,
    ):
        return True

    # ── 0. Excluir el propio archivo de output ──
    if not is_directory and name == output_file:
        return True

    # ── 0b. Excluir ignores extra ──
    if name in extra_ignores:
        return True

    # ── 1. Reglas estáticas (constantes) ──
    if is_directory:
        # Ignorar carpetas de la lista negra global o skip_dirs
        if name in GLOBAL_IGNORE_DIRS or name in SKIP_DIRS:
            return True

        # Ignorar si algún componente de la ruta está en la lista negra o skip_dirs
        try:
            if any(p in GLOBAL_IGNORE_DIRS or p in SKIP_DIRS for p in rel_parts):
                return True
        except ValueError:
            if any(p in GLOBAL_IGNORE_DIRS or p in SKIP_DIRS for p in path.parts):
                return True

        # Ignorar carpetas/archivos que empiezan con punto (excepto archivos config comunes)
        if name.startswith(".") and name != BCK_ND_DIRECTORY:
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
    if gitignore_matcher.matches(
        path,
        is_dir=is_directory,
        load_parents=False,
    ):
        return True

    return False
