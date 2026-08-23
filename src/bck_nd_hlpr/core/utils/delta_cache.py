"""
DeltaCacheManager — Incremental delta cache engine for bck-nd-hlpr.

Tracks file signatures (mtime + size + sha256 content hash) in
`.bck-nd/cache/delta.json` to identify unmodified files across analysis runs
and skip redundant parsing.
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union


class DeltaCacheManager:
    """
    Manages incremental file signatures and analysis cache state.
    """

    CACHE_DIRECTORY = Path(".bck-nd") / "cache"
    CACHE_FILE_NAME = "delta.json"
    CACHE_VERSION = "1.0"

    def __init__(self, root_path: Union[str, Path]):
        self.root = Path(root_path).resolve()
        self.cache_path = self._resolve_cache_path(self.root)
        self.signatures: Dict[str, Dict[str, Any]] = {}
        self.metadata: Dict[str, Any] = {}
        self.load_cache()

    def _resolve_cache_path(self, root: Path) -> Path:
        cache_dir = root / self.CACHE_DIRECTORY
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            # Keep initialization non-fatal for read-only projects. save_cache
            # will report failure through its existing boolean return value.
            pass
        return cache_dir / self.CACHE_FILE_NAME

    def _get_rel_path(self, file_path: Union[str, Path]) -> str:
        p = Path(file_path).resolve()
        try:
            return str(p.relative_to(self.root)).replace("\\", "/")
        except ValueError:
            return str(p).replace("\\", "/")

    def compute_signature(self, file_path: Union[str, Path]) -> Dict[str, Any]:
        """
        Compute signature (mtime, size, SHA256 hash) for a file.
        """
        p = Path(file_path).resolve()
        if not p.is_file():
            return {}

        try:
            stat = p.stat()
            mtime = stat.st_mtime
            size = stat.st_size
            content = p.read_bytes()
            sha256 = hashlib.sha256(content).hexdigest()
            return {
                "mtime": mtime,
                "size": size,
                "hash": sha256,
            }
        except Exception:
            return {}

    def is_unmodified(self, file_path: Union[str, Path]) -> bool:
        """
        Check if a file has not been modified since the last recorded scan.
        """
        p = Path(file_path).resolve()
        if not p.is_file():
            return False

        rel_key = self._get_rel_path(p)
        stored = self.signatures.get(rel_key)
        if not stored:
            return False

        try:
            stat = p.stat()
            current_mtime = stat.st_mtime
            current_size = stat.st_size

            # Fast path check: mtime and size match
            if current_mtime == stored.get("mtime") and current_size == stored.get("size"):
                return True

            # Fallback check: SHA256 content hash matching
            content = p.read_bytes()
            current_hash = hashlib.sha256(content).hexdigest()
            if current_hash == stored.get("hash"):
                # Update mtime & size in memory for future fast path checks
                stored["mtime"] = current_mtime
                stored["size"] = current_size
                return True
            return False
        except Exception:
            return False

    def update_file(
        self,
        file_path: Union[str, Path],
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Record or update the signature (and optional extra cached analysis data) for a file.
        """
        p = Path(file_path).resolve()
        if not p.is_file():
            return

        sig = self.compute_signature(p)
        if sig:
            if extra_data:
                sig["data"] = extra_data
            rel_key = self._get_rel_path(p)
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
            p = Path(f).resolve()
            if self.is_unmodified(p):
                result.append(p)
        return result

    def get_modified_files(self, file_list: List[Union[str, Path]]) -> List[Path]:
        """
        Filter a list of file paths, returning only those that are new or modified.
        """
        result = []
        for f in file_list:
            p = Path(f).resolve()
            if not self.is_unmodified(p):
                result.append(p)
        return result

    def sync_files(self, current_files: List[Union[str, Path]]) -> None:
        """
        Update signature records for all provided files and remove deleted files from signatures.
        """
        valid_keys: Set[str] = set()
        for f in current_files:
            p = Path(f).resolve()
            if p.is_file():
                rel_key = self._get_rel_path(p)
                valid_keys.add(rel_key)
                if not self.is_unmodified(p):
                    self.update_file(p)

        # Remove keys for files that no longer exist in project
        stale_keys = [k for k in self.signatures if k not in valid_keys]
        for k in stale_keys:
            del self.signatures[k]

    def load_cache(self) -> bool:
        """
        Load signatures from disk cache file.
        """
        if not self.cache_path.exists():
            self.signatures = {}
            self.metadata = {}
            return False

        try:
            content = self.cache_path.read_text(encoding="utf-8")
            data = json.loads(content)
            if isinstance(data, dict):
                self.signatures = data.get("signatures", {})
                self.metadata = data.get("metadata", {})
                return True
        except Exception:
            self.signatures = {}
            self.metadata = {}
        return False

    def save_cache(self) -> bool:
        """
        Persist signatures and metadata to disk cache file.
        """
        try:
            cache_file = self.cache_path
            cache_file.parent.mkdir(parents=True, exist_ok=True)

            data = {
                "version": self.CACHE_VERSION,
                "metadata": self.metadata,
                "signatures": self.signatures,
            }

            temp_file = cache_file.with_suffix(".tmp")
            temp_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
            temp_file.replace(cache_file)
            return True
        except Exception:
            return False

    def clear(self) -> None:
        """
        Clear memory signatures and remove disk cache file.
        """
        self.signatures = {}
        self.metadata = {}
        try:
            if self.cache_path.is_file():
                self.cache_path.unlink()
        except Exception:
            pass
