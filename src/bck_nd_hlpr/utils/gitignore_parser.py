"""
gitignore_parser: Parsea .gitignore y devuelve utilidades para
comprobar si un path debe ser ignorado según sus patrones.

Maneja correctamente:
  - Patrones con trailing slash (dist/) → solo matchea directorios
  - Patrones sin slash (dist) → matchea archivos y directorios
  - Glob patterns (*.log, *.pyc)
  - Comentarios (#) y líneas en blanco
  - Patrones con ruta parcial (docs/temp)
  - Ignora patrones de negación (!) por simplicidad
"""
from fnmatch import fnmatch
from pathlib import Path
from typing import List


def parse_gitignore(root: Path) -> List[str]:
    """
    Lee el .gitignore de la raíz del proyecto y retorna los patrones
    como lista de strings sin procesar (pero sin comentarios ni blanks).

    Si el archivo no existe, retorna lista vacía sin error.
    """
    gitignore_path = root / ".gitignore"
    if not gitignore_path.is_file():
        return []

    patterns: List[str] = []
    try:
        with open(gitignore_path, "r", encoding="utf-8", errors="ignore") as f:
            for raw_line in f:
                line = raw_line.strip()
                # Ignorar líneas vacías y comentarios
                if not line or line.startswith("#"):
                    continue
                # Ignorar patrones de negación (complejidad innecesaria)
                if line.startswith("!"):
                    continue
                patterns.append(line)
    except OSError:
        return []

    return patterns


def matches_gitignore(path: Path, root: Path, patterns: List[str]) -> bool:
    """
    Determina si un path matchea algún patrón de .gitignore.

    Reglas clave:
      - "dist/"  → solo matchea si `path` es un directorio llamado "dist"
      - "dist"   → matchea archivos Y directorios llamados "dist"
      - "*.log"  → matchea cualquier archivo/dir que termine en .log
      - "docs/temp" → matchea la ruta relativa docs/temp
      - "*.py[cod]" → matchea .pyc, .pyo, .pyd via fnmatch

    Args:
        path: Path absoluto del archivo o directorio a evaluar.
        root: Path absoluto de la raíz del proyecto.
        patterns: Lista de patrones de .gitignore (output de parse_gitignore).

    Returns:
        True si el path debe ser ignorado.
    """
    if not patterns:
        return False

    # Calcular path relativo con forward slashes (estilo git)
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False

    rel_str = str(rel).replace("\\", "/")
    name = path.name
    is_dir = path.is_dir()

    for raw_pattern in patterns:
        pattern = raw_pattern

        # ── 1. Patrón con trailing slash: solo matchea directorios ──
        dir_only = pattern.endswith("/")
        if dir_only:
            pattern = pattern.rstrip("/")
            if not is_dir:
                continue  # patrón es dir-only pero path es archivo → skip

        # ── 2. Patrón con slash interno: matchear contra ruta relativa ──
        if "/" in pattern:
            # Limpiar leading slash si existe
            clean = pattern.lstrip("/")
            if fnmatch(rel_str, clean) or fnmatch(rel_str, clean + "/**"):
                return True
            # También comprobar cada componente parcial
            # e.g. "docs/temp" debería matchear "docs/temp/file.txt"
            if rel_str.startswith(clean + "/") or rel_str == clean:
                return True
            continue

        # ── 3. Patrón simple (sin slash): matchear contra el nombre ──
        if fnmatch(name, pattern):
            return True

        # ── 4. Matchear contra cada parte de la ruta relativa ──
        #    Esto permite que "dist" matchee "src/dist/file.js"
        for part in rel.parts:
            if fnmatch(part, pattern):
                # Si el patrón era dir_only, solo matchear si esa parte
                # corresponde a un directorio (no la última parte si es archivo)
                if dir_only:
                    # La parte matcheada es directorio si no es la última,
                    # o si es la última y el path es directorio
                    part_index = list(rel.parts).index(part)
                    if part_index < len(rel.parts) - 1 or is_dir:
                        return True
                else:
                    return True

    return False
