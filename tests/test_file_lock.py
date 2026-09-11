"""Regression tests for the cooperative cross-platform file lock."""

import os
import sys
import threading
from pathlib import Path

import pytest

import bck_nd_hlpr.core.utils.file_lock as file_lock_module
from bck_nd_hlpr.core.utils.file_lock import FileLockError, exclusive_file_lock


def test_lock_is_acquired_released_and_persists_without_sensitive_content(tmp_path):
    lock_path = tmp_path / ".writer.lock"

    with exclusive_file_lock(lock_path, timeout=0.2) as descriptor:
        assert lock_path.is_file()
        assert os.fstat(descriptor).st_size <= 1
        os.fstat(descriptor)

    with pytest.raises(OSError):
        os.fstat(descriptor)
    assert lock_path.is_file()
    assert lock_path.stat().st_size <= 1
    assert lock_path.read_bytes() in {b"", b"\0"}


def test_second_acquisition_times_out_then_succeeds_after_release(tmp_path):
    lock_path = tmp_path / ".writer.lock"
    started = threading.Event()
    finished = threading.Event()
    errors = []

    def contend():
        started.set()
        try:
            with exclusive_file_lock(lock_path, timeout=0.05):
                errors.append(AssertionError("contender acquired an occupied lock"))
        except FileLockError as exc:
            errors.append(exc)
        finally:
            finished.set()

    with exclusive_file_lock(lock_path, timeout=0.2):
        thread = threading.Thread(target=contend)
        thread.start()
        assert started.wait(1.0)
        assert finished.wait(1.0)

    thread.join(timeout=1.0)
    assert len(errors) == 1
    assert isinstance(errors[0], FileLockError)
    with exclusive_file_lock(lock_path, timeout=0.2):
        pass


def test_exception_inside_context_releases_lock(tmp_path):
    lock_path = tmp_path / ".writer.lock"

    with pytest.raises(RuntimeError, match="fixture failure"):
        with exclusive_file_lock(lock_path, timeout=0.2):
            raise RuntimeError("fixture failure")

    with exclusive_file_lock(lock_path, timeout=0.2):
        pass


def test_link_or_reparse_lock_target_is_rejected(tmp_path, monkeypatch):
    lock_path = tmp_path / ".writer.lock"
    lock_path.write_bytes(b"\0")
    monkeypatch.setattr(file_lock_module, "_is_link_or_reparse", lambda _stat: True)

    with pytest.raises(FileLockError) as error:
        with exclusive_file_lock(lock_path, timeout=0):
            pass

    assert str(lock_path) not in str(error.value)


def test_backend_selection_is_explicit_and_fails_closed():
    assert file_lock_module._backend_name("nt") == "windows"
    assert file_lock_module._backend_name("posix") == "posix"
    with pytest.raises(FileLockError):
        file_lock_module._backend_name("unsupported")


@pytest.mark.parametrize(
    ("backend", "module_name", "exclusive", "nonblocking", "unlock"),
    [
        ("windows", "msvcrt", 11, 0, 12),
        ("posix", "fcntl", 21, 22, 23),
    ],
)
def test_each_backend_uses_its_exclusive_nonblocking_api(
    tmp_path,
    monkeypatch,
    backend,
    module_name,
    exclusive,
    nonblocking,
    unlock,
):
    calls = []

    class FakeBackend:
        LK_NBLCK = exclusive
        LK_UNLCK = unlock
        LOCK_EX = exclusive
        LOCK_NB = nonblocking
        LOCK_UN = unlock

        @staticmethod
        def locking(descriptor, operation, amount):
            calls.append(("locking", operation, amount))

        @staticmethod
        def flock(descriptor, operation):
            calls.append(("flock", operation))

    monkeypatch.setitem(sys.modules, module_name, FakeBackend)
    target = tmp_path / f"{backend}.lock"
    target.write_bytes(b"\0")
    descriptor = os.open(str(target), os.O_RDWR)
    try:
        file_lock_module._acquire(descriptor, backend)
        file_lock_module._release(descriptor, backend)
    finally:
        os.close(descriptor)

    if backend == "windows":
        assert calls == [
            ("locking", exclusive, 1),
            ("locking", unlock, 1),
        ]
    else:
        assert calls == [
            ("flock", exclusive | nonblocking),
            ("flock", unlock),
        ]
