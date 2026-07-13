"""
FileSystemIndexer — Single-pass filesystem scanner for bck-nd-hlpr v3.0.0.

Walks the target directory once, applies GLOBAL_IGNORE_DIRS pruning and
.gitignore filtering, and produces a categorized FileIndex snapshot.

This eliminates redundant os.walk calls across todo_hunter, security_auditor,
ProjectScanner, and the various polyglot parsers.

Usage:
    from bck_nd_hlpr.core.utils.indexer import FileSystemIndexer

    indexer = FileSystemIndexer(root_path=".", max_depth=5)
    file_index = indexer.build()

    # Pre-categorized lists ready for consumers
    file_index.python_files   # [Path(...), ...]
    file_index.all_files      # every non-ignored file
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from bck_nd_hlpr.core.constants import GLOBAL_IGNORE_DIRS
from bck_nd_hlpr.core.utils.gitignore_parser import parse_gitignore, matches_gitignore


# ── Extension Groups ─────────────────────────────────────────────────────────
_PYTHON_EXTS = frozenset({".py"})
_CSHARP_EXTS = frozenset({".cs"})
_JS_TS_EXTS = frozenset({".js", ".ts", ".jsx", ".tsx"})
_JAVA_EXTS = frozenset({".java"})
_PHP_EXTS = frozenset({".php"})
_CONFIG_EXTS = frozenset({".json", ".yml", ".yaml", ".xml", ".toml", ".ini", ".conf"})
_CONFIG_NAMES = frozenset({".env", ".env.local"})
_NOTEBOOK_EXTS = frozenset({".ipynb"})
_DOCKER_COMPOSE_NAMES = frozenset({"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"})


@dataclass
class FileIndex:
    """
    Immutable snapshot of categorized file paths produced by FileSystemIndexer.

    Once built, this object can be safely shared across analyzers.
    All lists are sorted by path for deterministic output.
    """

    root: Path
    all_files: List[Path] = field(default_factory=list)
    python_files: List[Path] = field(default_factory=list)
    csharp_files: List[Path] = field(default_factory=list)
    js_ts_files: List[Path] = field(default_factory=list)
    java_files: List[Path] = field(default_factory=list)
    php_files: List[Path] = field(default_factory=list)
    config_files: List[Path] = field(default_factory=list)
    jupyter_notebooks: List[Path] = field(default_factory=list)
    docker_compose: Optional[Path] = None
    by_extension: Dict[str, List[Path]] = field(default_factory=dict)

    def files_with_suffix(self, *suffixes: str) -> List[Path]:
        """
        Filter all_files by one or more extensions without re-walking disk.

        Args:
            *suffixes: File extensions including the dot, e.g. ".py", ".rs"

        Returns:
            Sorted list of matching Path objects.
        """
        suffix_set = frozenset(suffixes)
        return [f for f in self.all_files if f.suffix.lower() in suffix_set]


class FileSystemIndexer:
    """
    Performs a single os.walk pass over a project directory, applying
    GLOBAL_IGNORE_DIRS pruning and .gitignore filtering, and produces
    a categorized FileIndex.
    """

    def __init__(self, root_path: str, max_depth: int = 10):
        """
        Args:
            root_path: Root directory of the project to index.
            max_depth: Maximum directory depth to traverse (0 = root only).
        """
        self.root = Path(root_path).resolve()
        self.max_depth = max_depth

    def build(self) -> FileIndex:
        """
        Execute the single-pass walk and return a FileIndex snapshot.

        Returns:
            FileIndex with all categorized file lists populated.
        """
        index = FileIndex(root=self.root)

        if not self.root.exists() or not self.root.is_dir():
            return index

        # Parse .gitignore once
        gitignore_patterns = parse_gitignore(self.root)

        for root_dir, dirs, files in os.walk(self.root):
            current = Path(root_dir)

            # ── Depth Check ──────────────────────────────────────────────
            try:
                rel = current.relative_to(self.root)
                depth = len(rel.parts) if str(rel) != "." else 0
            except ValueError:
                continue

            if depth > self.max_depth:
                del dirs[:]
                continue

            # ── Prune Ignored Directories (in-place) ─────────────────────
            dirs[:] = [
                d for d in dirs
                if d not in GLOBAL_IGNORE_DIRS
                and not d.startswith(".")
                and not d.endswith(".egg-info")
                and not (
                    gitignore_patterns
                    and matches_gitignore(current / d, self.root, gitignore_patterns)
                )
            ]

            # ── Categorize Files ─────────────────────────────────────────
            for fname in files:
                file_path = current / fname

                # Apply .gitignore filtering to files
                if gitignore_patterns and matches_gitignore(
                    file_path, self.root, gitignore_patterns
                ):
                    continue

                ext = file_path.suffix.lower()

                # Track in master list
                index.all_files.append(file_path)

                # Track by raw extension
                index.by_extension.setdefault(ext, []).append(file_path)

                # Categorize into typed lists
                if ext in _PYTHON_EXTS:
                    index.python_files.append(file_path)
                elif ext in _CSHARP_EXTS:
                    index.csharp_files.append(file_path)
                elif ext in _JS_TS_EXTS:
                    index.js_ts_files.append(file_path)
                elif ext in _JAVA_EXTS:
                    index.java_files.append(file_path)
                elif ext in _PHP_EXTS:
                    index.php_files.append(file_path)
                elif ext in _NOTEBOOK_EXTS:
                    index.jupyter_notebooks.append(file_path)

                # Config files (can overlap with other categories, e.g. .json)
                if ext in _CONFIG_EXTS or fname in _CONFIG_NAMES:
                    index.config_files.append(file_path)

                # Docker Compose detection (first match wins)
                if index.docker_compose is None and fname in _DOCKER_COMPOSE_NAMES:
                    index.docker_compose = file_path

        # Sort all lists for deterministic output
        index.all_files.sort()
        index.python_files.sort()
        index.csharp_files.sort()
        index.js_ts_files.sort()
        index.java_files.sort()
        index.php_files.sort()
        index.config_files.sort()
        index.jupyter_notebooks.sort()
        for ext_list in index.by_extension.values():
            ext_list.sort()

        return index
