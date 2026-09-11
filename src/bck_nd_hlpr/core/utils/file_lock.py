"""Small cross-platform advisory locks for Backend Helper writers.

The persistent lock file serializes cooperative Backend Helper processes. It is
not an operating-system sandbox and cannot stop a privileged or non-cooperating
process from changing the protected data.
"""

import os
import stat
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional, Tuple


_LOCK_POLL_SECONDS = 0.01


class FileLockError(RuntimeError):
    """A cooperative file lock could not be acquired or validated safely."""


def _is_link_or_reparse(path_stat: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(path_stat.st_mode) or bool(
        getattr(path_stat, "st_file_attributes", 0) & reparse_flag
    )


def _identity(path_stat: os.stat_result) -> Tuple[int, int, int]:
    return (
        path_stat.st_dev,
        path_stat.st_ino,
        stat.S_IFMT(path_stat.st_mode),
    )


def _backend_name(platform_name: Optional[str] = None) -> str:
    """Return the supported lock backend name, failing closed otherwise."""
    selected = os.name if platform_name is None else platform_name
    if selected == "nt":
        return "windows"
    if selected == "posix":
        return "posix"
    raise FileLockError("No safe file-lock backend is available.")


def _open_verified_lock(lock_path: Path) -> int:
    initial_stat: Optional[os.stat_result]
    try:
        initial_stat = lock_path.lstat()
    except FileNotFoundError:
        initial_stat = None
    except OSError as exc:
        raise FileLockError("Unable to inspect the cooperative lock safely.") from exc

    if initial_stat is not None and (
        _is_link_or_reparse(initial_stat)
        or not stat.S_ISREG(initial_stat.st_mode)
    ):
        raise FileLockError("The cooperative lock target is unsafe.")

    flags = os.O_RDWR | os.O_CREAT
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(str(lock_path), flags, 0o600)
    except OSError as exc:
        raise FileLockError("Unable to open the cooperative lock safely.") from exc

    try:
        opened_stat = os.fstat(descriptor)
        current_stat = lock_path.lstat()
        if (
            _is_link_or_reparse(opened_stat)
            or _is_link_or_reparse(current_stat)
            or not stat.S_ISREG(opened_stat.st_mode)
            or _identity(opened_stat) != _identity(current_stat)
            or (
                initial_stat is not None
                and _identity(opened_stat) != _identity(initial_stat)
            )
        ):
            raise FileLockError("The cooperative lock changed while opening.")

        try:
            os.fchmod(descriptor, 0o600)
        except AttributeError:
            pass
        except OSError:
            if os.name != "nt":
                raise

        if opened_stat.st_size < 1:
            os.lseek(descriptor, 0, os.SEEK_SET)
            os.write(descriptor, b"\0")
            os.fsync(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        return descriptor
    except FileLockError:
        os.close(descriptor)
        raise
    except OSError as exc:
        os.close(descriptor)
        raise FileLockError("Unable to initialize the cooperative lock safely.") from exc


def _acquire(descriptor: int, backend: str) -> None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    if backend == "windows":
        import msvcrt

        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        return
    if backend == "posix":
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return
    raise FileLockError("No safe file-lock backend is available.")


def _release(descriptor: int, backend: str) -> None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    if backend == "windows":
        import msvcrt

        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
    elif backend == "posix":
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_UN)


@contextmanager
def exclusive_file_lock(
    lock_path: Path,
    *,
    timeout: float = 5.0,
) -> Iterator[int]:
    """Acquire a bounded exclusive lock and keep its file persistent.

    The lock coordinates Backend Helper writers that use this primitive. The
    file is deliberately not removed after release because deleting it could
    let concurrent writers lock different inodes.
    """
    try:
        timeout_value = max(0.0, float(timeout))
    except (TypeError, ValueError) as exc:
        raise FileLockError("The cooperative lock timeout is invalid.") from exc

    backend = _backend_name()
    descriptor = _open_verified_lock(Path(lock_path))
    acquired = False
    deadline = time.monotonic() + timeout_value
    try:
        while True:
            try:
                _acquire(descriptor, backend)
                acquired = True
                break
            except OSError as exc:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise FileLockError(
                        "Timed out waiting for a cooperative file lock."
                    ) from exc
                time.sleep(min(_LOCK_POLL_SECONDS, remaining))
        try:
            locked_stat = os.fstat(descriptor)
            current_stat = Path(lock_path).lstat()
        except OSError as exc:
            raise FileLockError(
                "The cooperative lock changed during acquisition."
            ) from exc
        if (
            _is_link_or_reparse(locked_stat)
            or _is_link_or_reparse(current_stat)
            or _identity(locked_stat) != _identity(current_stat)
        ):
            raise FileLockError(
                "The cooperative lock changed during acquisition."
            )
        yield descriptor
    finally:
        if acquired:
            try:
                _release(descriptor, backend)
            except OSError:
                pass
        try:
            os.close(descriptor)
        except OSError:
            pass


def fsync_directory(directory: Path) -> None:
    """Best-effort directory sync on platforms that support directory fds."""
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_DIRECTORY", 0)
    descriptor: Optional[int] = None
    try:
        descriptor = os.open(str(directory), flags)
        os.fsync(descriptor)
    except OSError:
        return
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


__all__ = ["FileLockError", "exclusive_file_lock", "fsync_directory"]
