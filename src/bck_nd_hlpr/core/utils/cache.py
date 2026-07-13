import threading
from pathlib import Path
from typing import Dict

class _FileCacheManager:
    """
    Thread-safe memory cache for file contents to prevent redundant disk I/O
    during a single orchestrator run.
    """
    def __init__(self):
        self._cache: Dict[str, str] = {}
        self._lock = threading.Lock()

    def clear(self):
        """Clears the cache (should be called at the start of a scan)."""
        with self._lock:
            self._cache.clear()

    def read_file(self, file_path, encoding='utf-8', errors='ignore') -> str:
        """
        Reads a file from memory cache if present; otherwise reads from disk
        and caches it. Raises OSError/UnicodeDecodeError if disk read fails.
        """
        path_str = str(Path(file_path).resolve())
        with self._lock:
            if path_str in self._cache:
                return self._cache[path_str]
        
        # Read without holding the lock to allow concurrent I/O on different files
        with open(path_str, 'r', encoding=encoding, errors=errors) as f:
            content = f.read()
            
        with self._lock:
            # Another thread might have populated it while we were reading, which is fine
            self._cache[path_str] = content
            return content

FileCache = _FileCacheManager()
