"""Verified atomic publication for Backend Helper generated artifacts."""

import errno
import os
import stat
import tempfile
from pathlib import Path, PureWindowsPath
from typing import Callable, Iterable, Optional, Tuple, Union

from bck_nd_hlpr.core.utils.file_lock import fsync_directory


class SecureWriteError(RuntimeError):
    """An artifact destination could not be written without risking user data."""


class ArtifactAlreadyExistsError(SecureWriteError):
    """A no-clobber artifact publication lost to an existing destination."""


def _is_destination_exists_error(error: OSError) -> bool:
    """Recognize only portable destination-collision errors from ``os.link``."""
    return (
        isinstance(error, FileExistsError)
        or error.errno == errno.EEXIST
        or getattr(error, "winerror", None) in {80, 183}
    )


def _is_link_or_reparse(path_stat: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(path_stat.st_mode) or bool(
        getattr(path_stat, "st_file_attributes", 0) & reparse_flag
    )


def _state(path_stat: os.stat_result) -> Tuple[int, int, int, int, int]:
    return (
        path_stat.st_dev,
        path_stat.st_ino,
        stat.S_IFMT(path_stat.st_mode),
        path_stat.st_size,
        path_stat.st_mtime_ns,
    )


def _identity(path_stat: os.stat_result) -> Tuple[int, int, int]:
    return (
        path_stat.st_dev,
        path_stat.st_ino,
        stat.S_IFMT(path_stat.st_mode),
    )


def _serialized_bytes(content: Union[str, bytes, bytearray, memoryview]) -> bytes:
    if isinstance(content, str):
        return content.encode("utf-8")
    if isinstance(content, (bytes, bytearray, memoryview)):
        return bytes(content)
    raise SecureWriteError("Artifact publication was denied safely.")


def _is_within(candidate: Path, project_root: Path) -> bool:
    try:
        root_text = os.path.normcase(os.path.abspath(str(project_root)))
        candidate_text = os.path.normcase(os.path.abspath(str(candidate)))
        return os.path.commonpath([root_text, candidate_text]) == root_text
    except (OSError, ValueError):
        return False


def _canonical_project(project_root: Union[str, Path]) -> Path:
    try:
        root = Path(project_root).resolve(strict=True)
        root_stat = root.lstat()
    except (OSError, RuntimeError) as exc:
        raise SecureWriteError("Artifact publication was denied safely.") from exc
    if (
        _is_link_or_reparse(root_stat)
        or not stat.S_ISDIR(root_stat.st_mode)
    ):
        raise SecureWriteError("Artifact publication was denied safely.")
    return root


def resolve_project_target(
    project_root: Union[str, Path],
    requested_path: Union[str, Path],
) -> Path:
    """Resolve a lexical target inside a canonical project without following it."""
    root = _canonical_project(project_root)
    raw = str(requested_path or "").strip()
    normalized = raw.replace("\\", "/")
    windows_path = PureWindowsPath(raw)
    if (
        not raw
        or "://" in normalized
        or any(part == ".." for part in normalized.split("/"))
        or (os.name != "nt" and (windows_path.drive or windows_path.is_absolute()))
    ):
        raise SecureWriteError("Artifact publication was denied safely.")

    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = Path(os.path.abspath(str(candidate)))
    if not _is_within(candidate, root):
        raise SecureWriteError("Artifact publication was denied safely.")
    return candidate


def _validate_existing_components(root: Path, target: Path) -> None:
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise SecureWriteError("Artifact publication was denied safely.") from exc

    current = root
    root_stat = root.lstat()
    if _is_link_or_reparse(root_stat) or not stat.S_ISDIR(root_stat.st_mode):
        raise SecureWriteError("Artifact publication was denied safely.")

    for part in relative.parts[:-1]:
        current = current / part
        try:
            current_stat = current.lstat()
        except FileNotFoundError:
            break
        except OSError as exc:
            raise SecureWriteError("Artifact publication was denied safely.") from exc
        if (
            _is_link_or_reparse(current_stat)
            or not stat.S_ISDIR(current_stat.st_mode)
        ):
            raise SecureWriteError("Artifact publication was denied safely.")

    try:
        target_stat = target.lstat()
    except FileNotFoundError:
        target_stat = None
    except OSError as exc:
        raise SecureWriteError("Artifact publication was denied safely.") from exc
    if target_stat is not None and (
        _is_link_or_reparse(target_stat)
        or not stat.S_ISREG(target_stat.st_mode)
    ):
        raise SecureWriteError("Artifact publication was denied safely.")

    try:
        resolved_parent = target.parent.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise SecureWriteError("Artifact publication was denied safely.") from exc
    if not _is_within(resolved_parent, root):
        raise SecureWriteError("Artifact publication was denied safely.")
    if target_stat is not None:
        try:
            resolved_target = target.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise SecureWriteError("Artifact publication was denied safely.") from exc
        if not _is_within(resolved_target, root):
            raise SecureWriteError("Artifact publication was denied safely.")


def validate_artifact_target(
    project_root: Union[str, Path],
    target: Union[str, Path],
) -> Path:
    """Validate every existing component without creating or changing anything."""
    root = _canonical_project(project_root)
    candidate = resolve_project_target(root, target)
    _validate_existing_components(root, candidate)
    return candidate


def validate_artifact_targets(
    project_root: Union[str, Path],
    targets: Iterable[Union[str, Path]],
) -> Tuple[Path, ...]:
    """Validate a group before the caller performs its first mutation."""
    root = _canonical_project(project_root)
    return tuple(validate_artifact_target(root, target) for target in targets)


def _read_verified(
    project_root: Union[str, Path],
    target: Union[str, Path],
) -> Optional[Tuple[bytes, os.stat_result]]:
    root = _canonical_project(project_root)
    candidate = validate_artifact_target(root, target)
    try:
        initial_stat = candidate.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise SecureWriteError("Artifact publication was denied safely.") from exc

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(str(candidate), flags)
    except OSError as exc:
        raise SecureWriteError("Artifact publication was denied safely.") from exc
    try:
        opened_stat = os.fstat(descriptor)
        if (
            _is_link_or_reparse(opened_stat)
            or not stat.S_ISREG(opened_stat.st_mode)
            or _state(opened_stat) != _state(initial_stat)
        ):
            raise SecureWriteError("Artifact publication was denied safely.")
        chunks = []
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        final_descriptor_stat = os.fstat(descriptor)
    except SecureWriteError:
        raise
    except OSError as exc:
        raise SecureWriteError("Artifact publication was denied safely.") from exc
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass

    try:
        final_path_stat = candidate.lstat()
    except OSError as exc:
        raise SecureWriteError("Artifact publication was denied safely.") from exc
    if (
        _is_link_or_reparse(final_path_stat)
        or _state(final_descriptor_stat) != _state(opened_stat)
        or _state(final_path_stat) != _state(initial_stat)
    ):
        raise SecureWriteError("Artifact publication was denied safely.")
    _validate_existing_components(root, candidate)
    return b"".join(chunks), final_path_stat


def read_verified_artifact(
    project_root: Union[str, Path],
    target: Union[str, Path],
) -> Optional[bytes]:
    """Return stable bytes for an existing safe artifact, otherwise ``None``."""
    verified = _read_verified(project_root, target)
    return verified[0] if verified is not None else None


def ensure_existing_artifact_allowed(
    project_root: Union[str, Path],
    target: Union[str, Path],
    validator: Callable[[bytes], bool],
) -> Optional[bytes]:
    """Reject an existing file unless it is recognized as tool-generated."""
    existing = read_verified_artifact(project_root, target)
    if existing is not None and not validator(existing):
        raise SecureWriteError("Artifact publication was denied safely.")
    return existing


def _ensure_safe_parent(root: Path, target: Path) -> None:
    relative_parent = target.parent.relative_to(root)
    current = root
    for part in relative_parent.parts:
        current = current / part
        try:
            current.mkdir(mode=0o700)
        except FileExistsError:
            pass
        except OSError as exc:
            raise SecureWriteError("Artifact publication was denied safely.") from exc
        try:
            current_stat = current.lstat()
        except OSError as exc:
            raise SecureWriteError("Artifact publication was denied safely.") from exc
        if (
            _is_link_or_reparse(current_stat)
            or not stat.S_ISDIR(current_stat.st_mode)
        ):
            raise SecureWriteError("Artifact publication was denied safely.")
    _validate_existing_components(root, target)


def ensure_project_artifact_parent(
    project_root: Union[str, Path],
    target: Union[str, Path],
) -> Path:
    """Create and validate a target parent strictly inside a project root."""
    root = _canonical_project(project_root)
    candidate = validate_artifact_target(root, target)
    _ensure_safe_parent(root, candidate)
    return candidate.parent


def _absolute_explicit_target(target: Union[str, Path]) -> Path:
    raw = str(target or "")
    if not raw:
        raise SecureWriteError("Explicit output publication was denied safely.")
    return Path(os.path.abspath(raw))


def _validate_explicit_components(candidate: Path) -> None:
    """Validate an absolute lexical path without following parent links."""
    parent = candidate.parent
    directories = []
    current = parent
    while True:
        directories.append(current)
        if current == current.parent:
            break
        current = current.parent

    for directory in reversed(directories):
        try:
            directory_stat = directory.lstat()
        except OSError as exc:
            raise SecureWriteError(
                "Explicit output publication was denied safely."
            ) from exc
        if (
            _is_link_or_reparse(directory_stat)
            or not stat.S_ISDIR(directory_stat.st_mode)
        ):
            raise SecureWriteError(
                "Explicit output publication was denied safely."
            )

    try:
        target_stat = candidate.lstat()
    except FileNotFoundError:
        target_stat = None
    except OSError as exc:
        raise SecureWriteError(
            "Explicit output publication was denied safely."
        ) from exc
    if target_stat is not None and (
        _is_link_or_reparse(target_stat)
        or not stat.S_ISREG(target_stat.st_mode)
    ):
        raise SecureWriteError("Explicit output publication was denied safely.")


def ensure_safe_explicit_directory(directory: Union[str, Path]) -> Path:
    """Create an explicitly requested directory without traversing links."""
    candidate = _absolute_explicit_target(directory)
    chain = []
    current = candidate
    while True:
        chain.append(current)
        if current == current.parent:
            break
        current = current.parent

    for component in reversed(chain):
        try:
            component_stat = component.lstat()
        except FileNotFoundError:
            try:
                component.mkdir(mode=0o700)
            except FileExistsError:
                pass
            except OSError as exc:
                raise SecureWriteError(
                    "Explicit output directory creation was denied safely."
                ) from exc
            try:
                component_stat = component.lstat()
            except OSError as exc:
                raise SecureWriteError(
                    "Explicit output directory creation was denied safely."
                ) from exc
        except OSError as exc:
            raise SecureWriteError(
                "Explicit output directory creation was denied safely."
            ) from exc
        if (
            _is_link_or_reparse(component_stat)
            or not stat.S_ISDIR(component_stat.st_mode)
        ):
            raise SecureWriteError(
                "Explicit output directory creation was denied safely."
            )
    return candidate


def _read_verified_explicit(
    candidate: Path,
) -> Optional[Tuple[bytes, os.stat_result]]:
    _validate_explicit_components(candidate)
    try:
        initial_stat = candidate.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise SecureWriteError(
            "Explicit output publication was denied safely."
        ) from exc

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(str(candidate), flags)
    except OSError as exc:
        raise SecureWriteError(
            "Explicit output publication was denied safely."
        ) from exc
    try:
        opened_stat = os.fstat(descriptor)
        if (
            _is_link_or_reparse(opened_stat)
            or not stat.S_ISREG(opened_stat.st_mode)
            or _state(opened_stat) != _state(initial_stat)
        ):
            raise SecureWriteError(
                "Explicit output publication was denied safely."
            )
        chunks = []
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        final_descriptor_stat = os.fstat(descriptor)
    except SecureWriteError:
        raise
    except OSError as exc:
        raise SecureWriteError(
            "Explicit output publication was denied safely."
        ) from exc
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass

    try:
        final_path_stat = candidate.lstat()
    except OSError as exc:
        raise SecureWriteError(
            "Explicit output publication was denied safely."
        ) from exc
    if (
        _is_link_or_reparse(final_path_stat)
        or _state(final_descriptor_stat) != _state(opened_stat)
        or _state(final_path_stat) != _state(initial_stat)
    ):
        raise SecureWriteError("Explicit output publication was denied safely.")
    _validate_explicit_components(candidate)
    return b"".join(chunks), final_path_stat


def atomic_write_explicit_output(
    target: Union[str, Path],
    content: Union[str, bytes, bytearray, memoryview],
    *,
    existing_validator: Optional[Callable[[bytes], bool]] = None,
) -> Path:
    """Atomically replace one explicitly requested regular output file."""
    payload = _serialized_bytes(content)
    candidate = _absolute_explicit_target(target)
    existing = _read_verified_explicit(candidate)
    if existing is not None and existing_validator is not None:
        try:
            allowed = bool(existing_validator(existing[0]))
        except Exception as exc:
            raise SecureWriteError(
                "Explicit output publication was denied safely."
            ) from exc
        if not allowed:
            raise SecureWriteError(
                "Explicit output publication was denied safely."
            )
    temp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=candidate.parent,
            prefix=f".{candidate.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_file.write(payload)
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_path = Path(temp_file.name)
        if existing is not None:
            os.chmod(temp_path, stat.S_IMODE(existing[1].st_mode))

        latest = _read_verified_explicit(candidate)
        if existing is None:
            if latest is not None:
                raise SecureWriteError(
                    "Explicit output publication was denied safely."
                )
        elif (
            latest is None
            or latest[0] != existing[0]
            or _state(latest[1]) != _state(existing[1])
        ):
            raise SecureWriteError(
                "Explicit output publication was denied safely."
            )
        _validate_explicit_components(candidate)
        os.replace(temp_path, candidate)
        temp_path = None
        fsync_directory(candidate.parent)
        return candidate
    except SecureWriteError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise SecureWriteError(
            "Explicit output publication was denied safely."
        ) from exc
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass


def atomic_create_project_artifact(
    project_root: Union[str, Path],
    target: Union[str, Path],
    content: Union[str, bytes, bytearray, memoryview],
) -> Path:
    """Publish a project artifact atomically without replacing any target."""
    payload = _serialized_bytes(content)
    root = _canonical_project(project_root)
    candidate = resolve_project_target(root, target)
    _ensure_safe_parent(root, candidate)
    candidate = validate_artifact_target(root, candidate)
    try:
        candidate.lstat()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise SecureWriteError("Artifact creation was denied safely.") from exc
    else:
        raise ArtifactAlreadyExistsError("Artifact already exists.")

    temp_path: Optional[Path] = None
    published = False
    completed = False
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=candidate.parent,
            prefix=f".{candidate.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_file.write(payload)
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_path = Path(temp_file.name)

        _validate_existing_components(root, candidate)
        try:
            os.link(temp_path, candidate, follow_symlinks=False)
        except OSError as exc:
            if _is_destination_exists_error(exc):
                raise ArtifactAlreadyExistsError("Artifact already exists.") from exc
            raise
        published = True
        temp_stat = temp_path.lstat()
        target_stat = candidate.lstat()
        if (
            _is_link_or_reparse(target_stat)
            or not stat.S_ISREG(target_stat.st_mode)
            or _identity(temp_stat) != _identity(target_stat)
        ):
            raise SecureWriteError("Artifact creation was denied safely.")
        _validate_existing_components(root, candidate)
        fsync_directory(candidate.parent)
        completed = True
        return candidate
    except (ArtifactAlreadyExistsError, SecureWriteError):
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise SecureWriteError("Artifact creation was denied safely.") from exc
    finally:
        if published and not completed and temp_path is not None:
            try:
                target_stat = candidate.lstat()
                temp_stat = temp_path.lstat()
                if _identity(target_stat) == _identity(temp_stat):
                    candidate.unlink()
                    fsync_directory(candidate.parent)
            except OSError:
                pass
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass


def atomic_write_artifact(
    project_root: Union[str, Path],
    target: Union[str, Path],
    content: bytes,
    *,
    existing_validator: Optional[Callable[[bytes], bool]] = None,
) -> Path:
    """Publish bytes atomically after component, ownership and race checks."""
    root = _canonical_project(project_root)
    candidate = validate_artifact_target(root, target)
    existing = _read_verified(root, candidate)
    if (
        existing is not None
        and existing_validator is not None
        and not existing_validator(existing[0])
    ):
        raise SecureWriteError("Artifact publication was denied safely.")

    _ensure_safe_parent(root, candidate)
    current = _read_verified(root, candidate)
    if existing is None and current is not None:
        raise SecureWriteError("Artifact publication was denied safely.")
    if existing is not None and (
        current is None
        or current[0] != existing[0]
        or _state(current[1]) != _state(existing[1])
    ):
        raise SecureWriteError("Artifact publication was denied safely.")

    temp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=candidate.parent,
            prefix=f".{candidate.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_file.write(content)
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_path = Path(temp_file.name)
        if existing is not None:
            os.chmod(temp_path, stat.S_IMODE(existing[1].st_mode))

        latest = _read_verified(root, candidate)
        if existing is None:
            if latest is not None:
                raise SecureWriteError("Artifact publication was denied safely.")
        elif (
            latest is None
            or latest[0] != existing[0]
            or _state(latest[1]) != _state(existing[1])
        ):
            raise SecureWriteError("Artifact publication was denied safely.")
        _validate_existing_components(root, candidate)
        os.replace(temp_path, candidate)
        temp_path = None
        fsync_directory(candidate.parent)
        return candidate
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass


__all__ = [
    "ArtifactAlreadyExistsError",
    "SecureWriteError",
    "atomic_create_project_artifact",
    "atomic_write_explicit_output",
    "atomic_write_artifact",
    "ensure_project_artifact_parent",
    "ensure_safe_explicit_directory",
    "ensure_existing_artifact_allowed",
    "read_verified_artifact",
    "resolve_project_target",
    "validate_artifact_target",
    "validate_artifact_targets",
]
