import os
import stat
import threading
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Dict, List, Tuple


MAX_SCANNED_FILE_BYTES = 8 * 1024 * 1024
_READ_DENIED = "Project file read denied."
_FileState = Tuple[int, int, int, int, int]


def _is_link_or_reparse(path_stat: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(path_stat.st_mode) or bool(
        getattr(path_stat, "st_file_attributes", 0) & reparse_flag
    )


def _state(path_stat: os.stat_result) -> _FileState:
    return (
        path_stat.st_dev,
        path_stat.st_ino,
        stat.S_IFMT(path_stat.st_mode),
        path_stat.st_size,
        path_stat.st_mtime_ns,
    )


def _read_all(descriptor: int) -> bytes:
    chunks = []
    total = 0
    while True:
        remaining = MAX_SCANNED_FILE_BYTES - total
        chunk = os.read(descriptor, min(64 * 1024, remaining + 1))
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > MAX_SCANNED_FILE_BYTES:
            raise OSError(_READ_DENIED)
        chunks.append(chunk)


def _has_unsafe_syntax(value: object) -> bool:
    text = str(value).strip()
    if not text:
        return True
    normalized = text.replace("\\", "/")
    if ".." in PurePosixPath(normalized).parts:
        return True
    windows_path = PureWindowsPath(text)
    posix_path = PurePosixPath(normalized)
    native_path = Path(text)
    return (
        (bool(windows_path.drive) and not native_path.is_absolute())
        or (windows_path.is_absolute() and not native_path.is_absolute())
        or (posix_path.is_absolute() and not native_path.is_absolute())
    )


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        root_text = os.path.normcase(os.path.abspath(str(root)))
        candidate_text = os.path.normcase(os.path.abspath(str(candidate)))
        return os.path.commonpath([root_text, candidate_text]) == root_text
    except (OSError, ValueError):
        return False


def _verified_project_target(
    project_root: object,
    file_path: object,
) -> Tuple[Path, Path, Tuple[Tuple[Path, _FileState], ...]]:
    """Validate one project target and every repository-controlled component."""
    if _has_unsafe_syntax(project_root):
        raise OSError(_READ_DENIED)
    root = Path(os.path.abspath(str(project_root)))
    try:
        root_stat = root.lstat()
        if _is_link_or_reparse(root_stat) or not stat.S_ISDIR(root_stat.st_mode):
            raise OSError(_READ_DENIED)
        canonical_root = root.resolve(strict=True)
    except (OSError, RuntimeError):
        raise OSError(_READ_DENIED) from None

    if _has_unsafe_syntax(file_path):
        raise OSError(_READ_DENIED)
    raw_target = Path(str(file_path))
    target = (
        Path(os.path.abspath(str(raw_target)))
        if raw_target.is_absolute()
        else root / raw_target
    )
    target = Path(os.path.abspath(str(target)))
    if not _is_within(target, root):
        raise OSError(_READ_DENIED)
    try:
        relative = target.relative_to(root)
    except ValueError:
        raise OSError(_READ_DENIED) from None

    if not relative.parts:
        raise OSError(_READ_DENIED)
    states: List[Tuple[Path, _FileState]] = [(root, _state(root_stat))]
    current = root
    for index, part in enumerate(relative.parts):
        current = current / part
        try:
            current_stat = current.lstat()
        except OSError:
            raise OSError(_READ_DENIED) from None
        if _is_link_or_reparse(current_stat):
            raise OSError(_READ_DENIED)
        is_target = index == len(relative.parts) - 1
        if is_target:
            if not stat.S_ISREG(current_stat.st_mode):
                raise OSError(_READ_DENIED)
            if current_stat.st_size > MAX_SCANNED_FILE_BYTES:
                raise OSError(_READ_DENIED)
        elif not stat.S_ISDIR(current_stat.st_mode):
            raise OSError(_READ_DENIED)
        states.append((current, _state(current_stat)))

    if not states:
        raise OSError(_READ_DENIED)
    try:
        canonical_target = target.resolve(strict=True)
    except (OSError, RuntimeError):
        raise OSError(_READ_DENIED) from None
    if not _is_within(canonical_target, canonical_root):
        raise OSError(_READ_DENIED)
    return canonical_root, target, tuple(states)


def _verified_project_directory(project_root: object, directory_path: object) -> Path:
    """Validate one contained real directory without following project links."""
    if _has_unsafe_syntax(project_root) or _has_unsafe_syntax(directory_path):
        raise OSError(_READ_DENIED)
    root = Path(os.path.abspath(str(project_root)))
    raw_directory = Path(str(directory_path))
    directory = Path(
        os.path.abspath(
            str(raw_directory if raw_directory.is_absolute() else root / raw_directory)
        )
    )
    if not _is_within(directory, root):
        raise OSError(_READ_DENIED)
    try:
        relative = directory.relative_to(root)
        root_stat = root.lstat()
        if _is_link_or_reparse(root_stat) or not stat.S_ISDIR(root_stat.st_mode):
            raise OSError(_READ_DENIED)
        canonical_root = root.resolve(strict=True)
        current = root
        for part in relative.parts:
            current = current / part
            current_stat = current.lstat()
            if _is_link_or_reparse(current_stat) or not stat.S_ISDIR(
                current_stat.st_mode
            ):
                raise OSError(_READ_DENIED)
        canonical_directory = directory.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        raise OSError(_READ_DENIED) from None
    if not _is_within(canonical_directory, canonical_root):
        raise OSError(_READ_DENIED)
    return directory


def _revalidate_components(
    states: Tuple[Tuple[Path, _FileState], ...],
) -> None:
    for component, expected in states:
        try:
            current = component.lstat()
        except OSError:
            raise OSError(_READ_DENIED) from None
        if _is_link_or_reparse(current) or _state(current) != expected:
            raise OSError(_READ_DENIED)


def _read_project_bytes_verified(
    project_root: object,
    file_path: object,
) -> Tuple[str, _FileState, bytes]:
    _canonical_root, target, component_states = _verified_project_target(
        project_root,
        file_path,
    )
    initial_state = component_states[-1][1]
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = None
    try:
        descriptor = os.open(str(target), flags)
        opened_stat = os.fstat(descriptor)
        if (
            _is_link_or_reparse(opened_stat)
            or not stat.S_ISREG(opened_stat.st_mode)
            or _state(opened_stat) != initial_state
        ):
            raise OSError(_READ_DENIED)
        content = _read_all(descriptor)
        final_descriptor = os.fstat(descriptor)
        if _state(final_descriptor) != initial_state:
            raise OSError(_READ_DENIED)
        _revalidate_components(component_states)
        return str(target), initial_state, content
    except OSError:
        raise OSError(_READ_DENIED) from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


class _FileCacheManager:
    """Thread-safe cache for verified repository file contents."""

    def __init__(self):
        self._cache: Dict[object, Tuple[_FileState, object]] = {}
        self._lock = threading.Lock()

    def clear(self):
        """Clear all text and byte entries at the start of a scan."""
        with self._lock:
            self._cache.clear()

    def is_project_directory(self, project_root, directory_path) -> bool:
        try:
            _verified_project_directory(project_root, directory_path)
            return True
        except OSError:
            return False

    def is_project_file(self, project_root, file_path) -> bool:
        """Return whether a candidate is a contained regular non-link file now."""
        try:
            _verified_project_target(project_root, file_path)
            return True
        except OSError:
            return False

    def read_file(self, file_path, encoding='utf-8', errors='ignore') -> str:
        """Compatibility reader for non-project callers; rejects linked targets."""
        path = Path(os.path.abspath(str(file_path)))
        boundary_root = Path(path.anchor)
        try:
            _canonical_root, target, states = _verified_project_target(
                boundary_root, path
            )
            initial_state = states[-1][1]
            key = ("legacy", str(target), encoding, errors)
            with self._lock:
                cached = self._cache.get(key)
                if cached is not None and cached[0] == initial_state:
                    return cached[1]  # type: ignore[return-value]

            _path_str, read_state, file_bytes = _read_project_bytes_verified(
                boundary_root, path
            )
            content = file_bytes.decode(encoding, errors=errors)
            content = content.replace("\r\n", "\n").replace("\r", "\n")
            with self._lock:
                self._cache[key] = (read_state, content)
            return content
        except (OSError, UnicodeError):
            raise OSError("Unsafe file read denied.") from None

    def read_project_bytes(self, project_root, file_path) -> bytes:
        """Read one regular contained project file through the verified boundary."""
        _canonical_root, target, states = _verified_project_target(
            project_root,
            file_path,
        )
        state = states[-1][1]
        key = ("bytes", str(target))
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None and cached[0] == state:
                return cached[1]  # type: ignore[return-value]

        path_str, read_state, content = _read_project_bytes_verified(
            project_root,
            file_path,
        )
        _canonical_root, _target, final_states = _verified_project_target(
            project_root,
            path_str,
        )
        if final_states[-1][1] != read_state:
            raise OSError(_READ_DENIED)
        with self._lock:
            existing = self._cache.get(key)
            if existing is not None and existing[0] == read_state:
                return existing[1]  # type: ignore[return-value]
            self._cache[key] = (read_state, content)
        return content

    def read_project_file(
        self,
        project_root,
        file_path,
        encoding='utf-8',
        errors='ignore',
    ) -> str:
        """Read and cache decoded content only after contained verified I/O."""
        _canonical_root, target, states = _verified_project_target(
            project_root,
            file_path,
        )
        state = states[-1][1]
        key = ("text", str(target), encoding, errors)
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None and cached[0] == state:
                return cached[1]  # type: ignore[return-value]

        path_str, read_state, file_bytes = _read_project_bytes_verified(
            project_root,
            file_path,
        )
        try:
            content = file_bytes.decode(encoding, errors=errors)
            content = content.replace("\r\n", "\n").replace("\r", "\n")
            _canonical_root, _target, final_states = _verified_project_target(
                project_root,
                path_str,
            )
            if final_states[-1][1] != read_state:
                raise OSError(_READ_DENIED)
            with self._lock:
                existing = self._cache.get(key)
                if existing is not None and existing[0] == read_state:
                    return existing[1]  # type: ignore[return-value]
                self._cache[key] = (read_state, content)
            return content
        except (OSError, UnicodeError):
            raise OSError(_READ_DENIED) from None


FileCache = _FileCacheManager()
