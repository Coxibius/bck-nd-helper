"""
Abstract base class for framework architecture providers.

Each provider encapsulates detection logic and metadata for a single
framework/language ecosystem, enabling a plugin-style architecture
where new frameworks can be added without modifying the core detector.
"""
from abc import ABC, abstractmethod
import fnmatch
from pathlib import Path
from typing import Dict, Any, List, Optional

from bck_nd_hlpr.core.utils.cache import FileCache
from bck_nd_hlpr.core.utils.gitignore_parser import GitIgnoreMatcher
from bck_nd_hlpr.core.utils.indexer import FileIndex, FileSystemIndexer


def find_files_by_glob(
    root_path: Path,
    pattern: str,
    *,
    file_index: Optional[FileIndex] = None,
) -> List[Path]:
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
    try:
        requested_root = Path(root_path).absolute()
        snapshot = file_index or FileSystemIndexer(
            str(requested_root), max_depth=None
        ).build()
    except (OSError, RuntimeError):
        return []
    root = requested_root
    if not FileCache.is_project_directory(snapshot.root, root):
        return []
    results: List[Path] = []
    normalized_pattern = pattern.replace("\\", "/")
    basename_pattern = normalized_pattern.rsplit("/", 1)[-1]
    for candidate in snapshot.all_files:
        try:
            relative = candidate.relative_to(root).as_posix()
        except ValueError:
            continue
        if (
            fnmatch.fnmatch(relative, normalized_pattern)
            or fnmatch.fnmatch(candidate.name, basename_pattern)
        ) and FileCache.is_project_file(snapshot.root, candidate):
            results.append(candidate)
    return sorted(set(results))


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

    def _set_file_index(self, file_index: FileIndex) -> None:
        """Attach a trusted snapshot without changing the public provider API."""
        self._file_index = file_index

    def _snapshot(self, root_path: Path) -> Optional[FileIndex]:
        existing = getattr(self, "_file_index", None)
        if isinstance(existing, FileIndex):
            return existing
        try:
            existing = FileSystemIndexer(
                str(root_path), max_depth=None
            ).build()
        except (OSError, RuntimeError):
            return None
        self._file_index = existing
        return existing

    def _files(
        self,
        root_path: Path,
        *,
        suffixes: tuple[str, ...] = (),
        names: tuple[str, ...] = (),
        max_depth: Optional[int] = None,
    ) -> List[Path]:
        scope_root = Path(root_path).absolute()
        snapshot = self._snapshot(scope_root)
        if snapshot is None:
            return []
        if not FileCache.is_project_directory(snapshot.root, scope_root):
            return []
        results: List[Path] = []
        suffix_set = {item.casefold() for item in suffixes}
        name_set = {item.casefold() for item in names}
        for path in snapshot.all_files:
            try:
                relative = path.relative_to(scope_root)
            except ValueError:
                continue
            if max_depth is not None and len(relative.parent.parts) > max_depth:
                continue
            if suffix_set and path.suffix.casefold() not in suffix_set:
                continue
            if name_set and path.name.casefold() not in name_set:
                continue
            if not FileCache.is_project_file(snapshot.root, path):
                continue
            results.append(path)
        return sorted(results)

    def _file(self, root_path: Path, relative_path: str) -> Optional[Path]:
        normalized = relative_path.replace("\\", "/").strip("/").casefold()
        scope_root = Path(root_path).absolute()
        snapshot = self._snapshot(scope_root)
        if snapshot is None:
            return None
        for path in self._files(root_path):
            try:
                relative = path.relative_to(scope_root).as_posix().casefold()
            except ValueError:
                continue
            if relative == normalized:
                return path
        return None

    def _read(self, root_path: Path, file_path: Path) -> Optional[str]:
        try:
            return FileCache.read_project_file(root_path, file_path)
        except (OSError, UnicodeError):
            return None

    def _has_directory(self, root_path: Path, relative_path: str) -> bool:
        snapshot = self._snapshot(Path(root_path).absolute())
        if snapshot is None:
            return False
        boundary_root = snapshot.root
        scope_root = Path(root_path).absolute()
        if not FileCache.is_project_directory(boundary_root, scope_root):
            return False
        prefix = relative_path.replace("\\", "/").strip("/").casefold()
        prefix_with_separator = prefix + "/"
        for path in self._files(root_path):
            try:
                relative = path.relative_to(scope_root).as_posix().casefold()
            except ValueError:
                continue
            if relative.startswith(prefix_with_separator):
                return True
        candidate = scope_root / Path(relative_path)
        if not FileCache.is_project_directory(boundary_root, candidate):
            return False
        try:
            return not GitIgnoreMatcher(boundary_root).matches(candidate, is_dir=True)
        except (OSError, RuntimeError, ValueError):
            return False

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
