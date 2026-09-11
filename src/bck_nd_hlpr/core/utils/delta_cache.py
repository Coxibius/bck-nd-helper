"""
DeltaCacheManager — Incremental delta cache engine for bck-nd-hlpr.

Tracks file signatures (mtime + size + sha256 content hash) in
`.bck-nd/cache/delta.json` to identify unmodified files across analysis runs
and skip redundant parsing.
"""

import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Dict, List, Optional, Set, Union

from bck_nd_hlpr.core.utils import cache as cache_module
from bck_nd_hlpr.core.utils.file_lock import (
    FileLockError,
    exclusive_file_lock,
    fsync_directory,
)
from bck_nd_hlpr.core.utils.secure_write import (
    SecureWriteError,
    atomic_write_artifact,
    ensure_project_artifact_parent,
    read_verified_artifact,
    validate_artifact_target,
)


MAX_DELTA_CACHE_BYTES = 8 * 1024 * 1024


class DeltaCacheManager:
    """
    Manages incremental file signatures and analysis cache state.
    """

    CACHE_DIRECTORY = Path(".bck-nd") / "cache"
    CACHE_FILE_NAME = "delta.json"
    CACHE_VERSION = "1.0"

    def __init__(self, root_path: Union[str, Path]):
        self.root = Path(os.path.abspath(str(root_path)))
        self.cache_path = self._resolve_cache_path(self.root)
        self.signatures: Dict[str, Dict[str, Any]] = {}
        self.metadata: Dict[str, Any] = {}
        self._loaded_cache_content: Optional[bytes] = None
        self._cache_persistence_allowed = True
        self.load_cache()

    def _resolve_cache_path(self, root: Path) -> Path:
        return root / self.CACHE_DIRECTORY / self.CACHE_FILE_NAME

    def _get_rel_path(self, file_path: Union[str, Path]) -> str:
        if cache_module._has_unsafe_syntax(file_path):
            return ""
        raw = Path(str(file_path))
        p = Path(os.path.abspath(str(raw if raw.is_absolute() else self.root / raw)))
        if not cache_module._is_within(p, self.root):
            return ""
        try:
            return str(p.relative_to(self.root)).replace("\\", "/")
        except ValueError:
            return ""

    def compute_signature(self, file_path: Union[str, Path]) -> Dict[str, Any]:
        """
        Compute signature (mtime, size, SHA256 hash) for a file.
        """
        rel_key = self._get_rel_path(file_path)
        if not rel_key:
            return {}
        try:
            p = self.root / Path(rel_key)
            _path, state, content = cache_module._read_project_bytes_verified(
                self.root,
                p,
            )
            sha256 = hashlib.sha256(content).hexdigest()
            return {
                "mtime": state[4] / 1_000_000_000,
                "size": state[3],
                "hash": sha256,
            }
        except OSError:
            return {}

    def is_unmodified(self, file_path: Union[str, Path]) -> bool:
        """
        Check if a file has not been modified since the last recorded scan.
        """
        rel_key = self._get_rel_path(file_path)
        if not rel_key:
            return False
        stored = self.signatures.get(rel_key)
        if not isinstance(stored, dict):
            return False

        try:
            _root, _target, states = cache_module._verified_project_target(
                self.root,
                self.root / Path(rel_key),
            )
            state = states[-1][1]
            current_mtime = state[4] / 1_000_000_000
            current_size = state[3]

            # Fast path check: mtime and size match
            if current_mtime == stored.get("mtime") and current_size == stored.get("size"):
                return True

            # Fallback check: SHA256 content hash matching
            signature = self.compute_signature(self.root / Path(rel_key))
            if signature and signature.get("hash") == stored.get("hash"):
                # Update mtime & size in memory for future fast path checks
                stored["mtime"] = signature["mtime"]
                stored["size"] = signature["size"]
                return True
            return False
        except OSError:
            return False

    def update_file(
        self,
        file_path: Union[str, Path],
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Record or update the signature (and optional extra cached analysis data) for a file.
        """
        rel_key = self._get_rel_path(file_path)
        if not rel_key:
            return
        sig = self.compute_signature(self.root / Path(rel_key))
        if sig:
            if extra_data:
                sig["data"] = extra_data
            self.signatures[rel_key] = sig

    def get_file_data(self, file_path: Union[str, Path]) -> Optional[Dict[str, Any]]:
        """
        Retrieve cached extra analysis data associated with a file, if unmodified.
        """
        if not self.is_unmodified(file_path):
            return None
        rel_key = self._get_rel_path(file_path)
        sig = self.signatures.get(rel_key, {})
        return sig.get("data")

    def remove_file(self, file_path: Union[str, Path]) -> None:
        """
        Remove a file entry from cache.
        """
        rel_key = self._get_rel_path(file_path)
        self.signatures.pop(rel_key, None)

    def get_unmodified_files(self, file_list: List[Union[str, Path]]) -> List[Path]:
        """
        Filter a list of file paths, returning only those that are unmodified.
        """
        result = []
        for f in file_list:
            if self.is_unmodified(f):
                rel_key = self._get_rel_path(f)
                if rel_key:
                    result.append(self.root / Path(rel_key))
        return result

    def get_modified_files(self, file_list: List[Union[str, Path]]) -> List[Path]:
        """
        Filter a list of file paths, returning only those that are new or modified.
        """
        result = []
        for f in file_list:
            rel_key = self._get_rel_path(f)
            if rel_key and not self.is_unmodified(f):
                result.append(self.root / Path(rel_key))
        return result

    def sync_files(self, current_files: List[Union[str, Path]]) -> None:
        """
        Update signature records for all provided files and remove deleted files from signatures.
        """
        valid_keys: Set[str] = set()
        for f in current_files:
            rel_key = self._get_rel_path(f)
            if not rel_key:
                continue
            try:
                cache_module._verified_project_target(
                    self.root,
                    self.root / Path(rel_key),
                )
            except OSError:
                continue
            valid_keys.add(rel_key)
            if not self.is_unmodified(f):
                self.update_file(f)

        # Remove keys for files that no longer exist in project
        stale_keys = [k for k in self.signatures if k not in valid_keys]
        for k in stale_keys:
            del self.signatures[k]

    def load_cache(self) -> bool:
        """
        Load signatures from disk cache file.
        """
        self.signatures = {}
        self.metadata = {}
        self._loaded_cache_content = None
        self._cache_persistence_allowed = False
        try:
            try:
                path_stat = self.cache_path.lstat()
            except FileNotFoundError:
                self._cache_persistence_allowed = True
                return False
            if path_stat.st_size > MAX_DELTA_CACHE_BYTES:
                return False
            raw_content = cache_module.FileCache.read_project_bytes(
                self.root,
                self.cache_path,
            )
            if len(raw_content) > MAX_DELTA_CACHE_BYTES:
                return False
            self._loaded_cache_content = raw_content
            self._cache_persistence_allowed = True
            data = json.loads(raw_content.decode("utf-8"))
            if not isinstance(data, dict):
                return False
            signatures = data.get("signatures", {})
            metadata = data.get("metadata", {})
            if not isinstance(signatures, dict) or not isinstance(metadata, dict):
                return False
            for key, signature in signatures.items():
                if not self._valid_cache_key(key) or not isinstance(signature, dict):
                    return False
            self.signatures = dict(signatures)
            self.metadata = dict(metadata)
            return True
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            self.signatures = {}
            self.metadata = {}
        return False

    def _serialize_cache(self) -> bytes:
        """Serialize the complete cache deterministically before any mutation."""
        if not isinstance(self.signatures, dict) or not isinstance(self.metadata, dict):
            raise ValueError("Delta cache state is incompatible.")
        for key, signature in self.signatures.items():
            if not self._valid_cache_key(key) or not isinstance(signature, dict):
                raise ValueError("Delta cache state is incompatible.")
        data = {
            "version": self.CACHE_VERSION,
            "metadata": self.metadata,
            "signatures": self.signatures,
        }
        rendered = json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ) + "\n"
        return rendered.encode("utf-8")

    @staticmethod
    def _valid_cache_key(value: object) -> bool:
        if not isinstance(value, str) or not value.strip():
            return False
        normalized = value.replace("\\", "/")
        posix = PurePosixPath(normalized)
        windows = PureWindowsPath(value)
        return (
            not posix.is_absolute()
            and not windows.is_absolute()
            and not windows.drive
            and ".." not in posix.parts
        )

    def save_cache(self) -> bool:
        """
        Persist signatures and metadata to disk cache file.
        """
        try:
            payload = self._serialize_cache()
            if len(payload) > MAX_DELTA_CACHE_BYTES:
                return False
            if not self._cache_persistence_allowed:
                return False

            ensure_project_artifact_parent(self.root, self.cache_path)
            lock_path = self.cache_path.parent / ".delta.lock"
            with exclusive_file_lock(lock_path, timeout=5.0):
                current = read_verified_artifact(self.root, self.cache_path)
                if current != self._loaded_cache_content:
                    return False
                atomic_write_artifact(self.root, self.cache_path, payload)
                self._loaded_cache_content = payload
                self._cache_persistence_allowed = True
            return True
        except (
            FileLockError,
            SecureWriteError,
            OSError,
            TypeError,
            ValueError,
            OverflowError,
            RecursionError,
        ):
            return False

    def clear(self) -> None:
        """
        Clear memory signatures and remove disk cache file.
        """
        self.signatures = {}
        self.metadata = {}
        try:
            if not self._cache_persistence_allowed:
                return
            try:
                self.cache_path.parent.lstat()
            except FileNotFoundError:
                self._loaded_cache_content = None
                return
            validate_artifact_target(self.root, self.cache_path)
            lock_path = self.cache_path.parent / ".delta.lock"
            with exclusive_file_lock(lock_path, timeout=5.0):
                current = read_verified_artifact(self.root, self.cache_path)
                if current is None:
                    self._loaded_cache_content = None
                    return
                if self._loaded_cache_content is None or current != self._loaded_cache_content:
                    return
                validate_artifact_target(self.root, self.cache_path)
                self.cache_path.unlink()
                fsync_directory(self.cache_path.parent)
                self._loaded_cache_content = None
        except (FileLockError, SecureWriteError, OSError):
            return
