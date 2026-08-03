"""
FastAPI architecture provider.
"""
import os
from pathlib import Path
from typing import Dict, Any, List, Optional

from bck_nd_hlpr.core.providers.base import BaseArchitectureProvider
from bck_nd_hlpr.core.constants import GLOBAL_IGNORE_DIRS


class FastApiProvider(BaseArchitectureProvider):
    """Detects FastAPI (Python) projects."""

    @property
    def name(self) -> str:
        return "FastAPI"

    @property
    def language(self) -> str:
        return "python"

    # -- Detection ------------------------------------------------------------

    def detect(self, root_path: Path) -> bool:
        root = Path(root_path)

        # 1. Check dependency files
        for dep_file in ("requirements.txt", "Pipfile"):
            path = root / dep_file
            if path.exists():
                try:
                    content = path.read_text(encoding="utf-8", errors="ignore").lower()
                    if "fastapi" in content:
                        return True
                except Exception:
                    pass

        # 2. Check pyproject.toml
        pyproject = root / "pyproject.toml"
        if pyproject.exists():
            try:
                content = pyproject.read_text(encoding="utf-8", errors="ignore").lower()
                if "fastapi" in content:
                    return True
            except Exception:
                pass

        # 3. Scan .py files for fastapi imports (limited depth)
        for root_dir, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS and not d.startswith(".")]
            # Limit scan depth to 3 levels
            rel = Path(root_dir).relative_to(root)
            if len(rel.parts) > 3:
                dirs.clear()
                continue
            for f in files:
                if f.endswith(".py"):
                    try:
                        content = (Path(root_dir) / f).read_text(
                            encoding="utf-8", errors="ignore"
                        )
                        if "from fastapi import" in content or "import fastapi" in content:
                            return True
                    except Exception:
                        continue
        return False

    # -- Metadata -------------------------------------------------------------

    def get_framework_info(self, root_path: Path) -> Dict[str, Any]:
        root = Path(root_path)
        features: List[str] = []
        orm = self._detect_orm(root)

        if orm:
            features.append(f"{orm} ORM")

        return {
            "framework": "FastAPI",
            "language": "python",
            "architecture_type": "REST API",
            "orm": orm,
            "features": features,
        }

    # -- Helpers --------------------------------------------------------------

    def _detect_orm(self, root: Path) -> str | None:
        """Inspect dependency files to determine the ORM in use."""
        dep_content = ""
        for dep_file in ("requirements.txt", "Pipfile", "pyproject.toml"):
            path = root / dep_file
            if path.exists():
                try:
                    dep_content += path.read_text(encoding="utf-8", errors="ignore").lower()
                except Exception:
                    pass

        if "sqlalchemy" in dep_content or "sqlmodel" in dep_content:
            return "SQLAlchemy"
        if "tortoise" in dep_content:
            return "Tortoise-ORM"
        if "peewee" in dep_content:
            return "Peewee"
        return None

    def find_model_files(self, root_path: Path) -> List[Path]:
        root = Path(root_path)
        results: List[Path] = []
        for root_dir, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS and not d.startswith(".")]
            for f in files:
                if f.endswith(".py"):
                    fpath = Path(root_dir) / f
                    name_lower = f.lower()
                    if "model" in name_lower or "schema" in name_lower or "entity" in name_lower:
                        results.append(fpath)
        return sorted(results)

    def find_route_files(self, root_path: Path) -> List[Path]:
        root = Path(root_path)
        results: List[Path] = []
        for root_dir, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS and not d.startswith(".")]
            for f in files:
                if f.endswith(".py"):
                    name_lower = f.lower()
                    if "route" in name_lower or "router" in name_lower or "endpoint" in name_lower:
                        results.append(Path(root_dir) / f)
        return sorted(results)

    def find_main_app_file(self, root_path: Path) -> Optional[Path]:
        """Locate ``main.py`` or a Python file instantiating ``FastAPI()``.

        Checks for ``main.py`` at the project root first (most common FastAPI
        convention), then does a bounded depth-3 walk scanning files for a
        ``FastAPI()`` constructor call.  Returns the first match or *None*.
        """
        root = Path(root_path)
        # Fast path: main.py at project root
        main_py = root / "main.py"
        if main_py.exists():
            return main_py
        # Walk up to depth 3 looking for FastAPI() instantiation
        for root_dir, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS and not d.startswith(".")]
            try:
                depth = len(Path(root_dir).relative_to(root).parts)
            except ValueError:
                depth = 0
            if depth > 3:
                dirs.clear()
                continue
            for f in files:
                if not f.endswith(".py"):
                    continue
                fpath = Path(root_dir) / f
                try:
                    content = fpath.read_text(encoding="utf-8", errors="ignore")
                    if "FastAPI()" in content or "FastAPI(" in content:
                        return fpath
                except Exception:
                    continue
        return None
