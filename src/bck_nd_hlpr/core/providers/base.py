"""
Abstract base class for framework architecture providers.

Each provider encapsulates detection logic and metadata for a single
framework/language ecosystem, enabling a plugin-style architecture
where new frameworks can be added without modifying the core detector.
"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, List, Optional

import os

from bck_nd_hlpr.core.constants import GLOBAL_IGNORE_DIRS


def find_files_by_glob(root_path: Path, pattern: str) -> List[Path]:
    """Return files matching *pattern* anywhere below *root_path*.

    Walks the directory tree respecting ``GLOBAL_IGNORE_DIRS`` and matches each
    file name against the glob *pattern* (e.g. ``"models.py"`` or ``"*.py"``).
    Relative files are returned under the ``models/`` package style directories
    (all ``*.py`` except ``__init__.py``).  Results are sorted for deterministic
    ordering.  Any I/O or permission errors are silently skipped so callers do
    not need to wrap this helper in additional ``try/except`` blocks.

    Typical usage::

        from bck_nd_hlpr.core.providers.base import find_files_by_glob

        models = find_files_by_glob(Path("."), "models.py")
        py_models = find_files_by_glob(Path("."), "**/models/*.py")
    """
    root = Path(root_path)
    results: List[Path] = []
    try:
        if "**" in pattern:
            try:
                matched = list(root.glob(pattern))
                for p in matched:
                    if not p.is_file():
                        continue
                    parts = set(p.relative_to(root).parts) if p.is_absolute() else set(p.parts)
                    if parts & GLOBAL_IGNORE_DIRS:
                        continue
                    results.append(p)
                return sorted(results)
            except Exception:
                pass
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS and not d.startswith(".")]
            d = Path(dirpath)
            for fname in files:
                if _match_glob(fname, pattern) or _match_glob(str(d / fname), pattern):
                    fp = d / fname
                    if fp.is_file():
                        results.append(fp)
    except Exception:
        pass
    return sorted(results)


def _match_glob(name: str, pattern: str) -> bool:
    """Tiny glob matcher supporting ``*`` and ``**`` on top of :mod:`fnmatch`."""
    import fnmatch
    import os.path
    base_pattern = pattern.split("/")[-1] if "/" in pattern else pattern
    if base_pattern == pattern:
        return fnmatch.fnmatch(name, pattern)
    return fnmatch.fnmatch(os.path.basename(name), base_pattern)


class BaseArchitectureProvider(ABC):
    """Abstract base class for framework architecture providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the framework (e.g. 'laravel', 'fastapi', 'django',
        'spring_boot', 'ef_core', 'express_typeorm')."""
        pass

    @property
    @abstractmethod
    def language(self) -> str:
        """Primary programming language
        ('php', 'python', 'java', 'csharp', 'javascript', 'typescript')."""
        pass

    @abstractmethod
    def detect(self, root_path: Path) -> bool:
        """Return True if this framework/architecture is present in *root_path*."""
        pass

    @abstractmethod
    def get_framework_info(self, root_path: Path) -> Dict[str, Any]:
        """Return architectural metadata dictionary containing at least:

        - ``framework``  : str
        - ``language``   : str
        - ``architecture_type`` : str  (e.g. 'MVC', 'REST API', 'Monolith')
        - ``orm``        : Optional[str]
        - ``features``   : List[str]
        """
        pass

    def find_model_files(self, root_path: Path) -> List[Path]:
        """Override to return paths to ORM / Database model files."""
        return []

    def find_route_files(self, root_path: Path) -> List[Path]:
        """Override to return paths to API / HTTP controllers or routers."""
        return []

    def get_supported_extensions(self) -> List[str]:
        """Return default source file extensions for this provider's language.

        The base implementation derives a sensible default from the ``language``
        property so callers always receive a non-empty list.  Subclasses may
        override to return a precise set of extensions.

        Example::

            provider.get_supported_extensions()  # ['.java'] for a Spring Boot provider
        """
        _language_extension_map: dict[str, List[str]] = {
            "python":     [".py"],
            "php":        [".php"],
            "java":       [".java"],
            "csharp":     [".cs"],
            "javascript": [".js", ".jsx"],
            "typescript": [".ts", ".tsx"],
            "go":         [".go"],
            "rust":       [".rs"],
            "ruby":       [".rb"],
        }
        try:
            lang = self.language.lower()
        except Exception:
            lang = ""
        return _language_extension_map.get(lang, [])
