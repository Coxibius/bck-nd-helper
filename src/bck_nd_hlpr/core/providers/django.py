"""
Django architecture provider.
"""
from pathlib import Path
from typing import Dict, Any, List, Optional

from bck_nd_hlpr.core.providers.base import BaseArchitectureProvider, find_files_by_glob


class DjangoProvider(BaseArchitectureProvider):
    """Detects Django (Python) projects."""

    @property
    def name(self) -> str:
        return "Django"

    @property
    def language(self) -> str:
        return "python"

    # -- Detection ------------------------------------------------------------

    def detect(self, root_path: Path) -> bool:
        root = Path(root_path)

        # 1. manage.py is the canonical Django marker
        manage_py = self._file(root, "manage.py")
        if manage_py is not None:
            content = self._read(root, manage_py)
            if content is not None and (
                "django" in content.lower() or "DJANGO_SETTINGS_MODULE" in content
            ):
                return True

        # 2. settings.py with Django markers
        for path in self._files(root, names=("settings.py",), max_depth=2):
            content = self._read(root, path)
            if content is not None and (
                "INSTALLED_APPS" in content or "DJANGO_SETTINGS_MODULE" in content
            ):
                return True

        # 3. wsgi.py / asgi.py with django reference
        for path in self._files(
            root, names=("wsgi.py", "asgi.py"), max_depth=2
        ):
            content = self._read(root, path)
            if content is not None and "django" in content.lower():
                return True

        return False

    # -- Metadata -------------------------------------------------------------

    def get_framework_info(self, root_path: Path) -> Dict[str, Any]:
        features: List[str] = []
        root = Path(root_path)

        # Django always includes its built-in ORM
        orm = "Django ORM"

        # Detect Django REST Framework
        for dep_file in ("requirements.txt", "Pipfile", "pyproject.toml"):
            path = self._file(root, dep_file)
            if path is not None:
                content = self._read(root, path)
                if content is not None and (
                    "djangorestframework" in content.lower()
                    or "rest_framework" in content.lower()
                ):
                    features.append("Django REST Framework")
                    break

        return {
            "framework": "Django",
            "language": "python",
            "architecture_type": "MVC + Services (Layered)",
            "orm": orm,
            "features": features,
        }

    # -- File discovery -------------------------------------------------------

    def find_model_files(self, root_path: Path) -> List[Path]:
        root = Path(root_path)
        results: List[Path] = []
        snapshot = self._snapshot(root)
        for p in find_files_by_glob(root, "models.py", file_index=snapshot):
            results.append(p)
        for p in find_files_by_glob(root, "**/models/*.py", file_index=snapshot):
            if p.name != "__init__.py":
                results.append(p)
        return sorted(set(results))

    def find_route_files(self, root_path: Path) -> List[Path]:
        root = Path(root_path)
        return self._files(root, names=("urls.py", "views.py"))

    def find_settings_file(self, root_path: Path) -> Optional[Path]:
        """Locate ``settings.py`` or ``manage.py`` within *root_path*.

        Searches up to 3 directory levels deep and returns the path of the
        first ``settings.py`` found, falling back to ``manage.py`` at the
        project root, or *None* if neither is present.
        """
        root = Path(root_path)
        # Fast check: manage.py at project root
        manage = self._file(root, "manage.py")
        if manage is not None:
            return manage
        settings = self._files(root, names=("settings.py",), max_depth=3)
        return settings[0] if settings else None
