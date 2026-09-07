"""
FastAPI architecture provider.
"""
from pathlib import Path
from typing import Dict, Any, List, Optional

from bck_nd_hlpr.core.providers.base import BaseArchitectureProvider


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
            path = self._file(root, dep_file)
            if path is not None:
                content = self._read(root, path)
                if content is not None and "fastapi" in content.lower():
                    return True

        # 2. Check pyproject.toml
        pyproject = self._file(root, "pyproject.toml")
        if pyproject is not None:
            content = self._read(root, pyproject)
            if content is not None and "fastapi" in content.lower():
                return True

        # 3. Scan .py files for fastapi imports (limited depth)
        for path in self._files(root, suffixes=(".py",), max_depth=3):
            content = self._read(root, path)
            if content is not None and (
                "from fastapi import" in content or "import fastapi" in content
            ):
                return True
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
            path = self._file(root, dep_file)
            if path is not None:
                content = self._read(root, path)
                if content is not None:
                    dep_content += content.lower()

        if "sqlalchemy" in dep_content or "sqlmodel" in dep_content:
            return "SQLAlchemy"
        if "tortoise" in dep_content:
            return "Tortoise-ORM"
        if "peewee" in dep_content:
            return "Peewee"
        return None

    def find_model_files(self, root_path: Path) -> List[Path]:
        root = Path(root_path)
        return [
            path
            for path in self._files(root, suffixes=(".py",))
            if any(token in path.name.lower() for token in ("model", "schema", "entity"))
        ]

    def find_route_files(self, root_path: Path) -> List[Path]:
        root = Path(root_path)
        return [
            path
            for path in self._files(root, suffixes=(".py",))
            if any(token in path.name.lower() for token in ("route", "router", "endpoint"))
        ]

    def find_main_app_file(self, root_path: Path) -> Optional[Path]:
        """Locate ``main.py`` or a Python file instantiating ``FastAPI()``.

        Checks for ``main.py`` at the project root first (most common FastAPI
        convention), then does a bounded depth-3 walk scanning files for a
        ``FastAPI()`` constructor call.  Returns the first match or *None*.
        """
        root = Path(root_path)
        # Fast path: main.py at project root
        main_py = self._file(root, "main.py")
        if main_py is not None:
            return main_py
        # Walk up to depth 3 looking for FastAPI() instantiation
        for path in self._files(root, suffixes=(".py",), max_depth=3):
            content = self._read(root, path)
            if content is not None and "FastAPI(" in content:
                return path
        return None
