"""
Django architecture provider.
"""
import os
from pathlib import Path
from typing import Dict, Any, List, Optional

from bck_nd_hlpr.core.providers.base import BaseArchitectureProvider
from bck_nd_hlpr.core.constants import GLOBAL_IGNORE_DIRS


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
        manage_py = root / "manage.py"
        if manage_py.exists():
            try:
                content = manage_py.read_text(encoding="utf-8", errors="ignore")
                if "django" in content.lower() or "DJANGO_SETTINGS_MODULE" in content:
                    return True
            except Exception:
                pass

        # 2. settings.py with Django markers
        for root_dir, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS and not d.startswith(".")]
            rel = Path(root_dir).relative_to(root)
            if len(rel.parts) > 2:
                dirs.clear()
                continue
            for f in files:
                if f == "settings.py":
                    try:
                        content = (Path(root_dir) / f).read_text(
                            encoding="utf-8", errors="ignore"
                        )
                        if "INSTALLED_APPS" in content or "DJANGO_SETTINGS_MODULE" in content:
                            return True
                    except Exception:
                        continue

        # 3. wsgi.py / asgi.py with django reference
        for name in ("wsgi.py", "asgi.py"):
            for root_dir, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS and not d.startswith(".")]
                rel = Path(root_dir).relative_to(root)
                if len(rel.parts) > 2:
                    dirs.clear()
                    continue
                if name in files:
                    try:
                        content = (Path(root_dir) / name).read_text(
                            encoding="utf-8", errors="ignore"
                        )
                        if "django" in content.lower():
                            return True
                    except Exception:
                        continue

        return False

    # -- Metadata -------------------------------------------------------------

    def get_framework_info(self, root_path: Path) -> Dict[str, Any]:
        features: List[str] = []
        root = Path(root_path)

        # Django always includes its built-in ORM
        orm = "Django ORM"

        # Detect Django REST Framework
        for dep_file in ("requirements.txt", "Pipfile", "pyproject.toml"):
            path = root / dep_file
            if path.exists():
                try:
                    content = path.read_text(encoding="utf-8", errors="ignore").lower()
                    if "djangorestframework" in content or "rest_framework" in content:
                        features.append("Django REST Framework")
                        break
                except Exception:
                    pass

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
        for root_dir, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS and not d.startswith(".")]
            if "models.py" in files:
                results.append(Path(root_dir) / "models.py")
            # Django apps may use a models/ package
            if "models" in dirs:
                models_dir = Path(root_dir) / "models"
                for py in models_dir.glob("*.py"):
                    if py.name != "__init__.py":
                        results.append(py)
        return sorted(results)

    def find_route_files(self, root_path: Path) -> List[Path]:
        root = Path(root_path)
        results: List[Path] = []
        for root_dir, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS and not d.startswith(".")]
            if "urls.py" in files:
                results.append(Path(root_dir) / "urls.py")
            if "views.py" in files:
                results.append(Path(root_dir) / "views.py")
        return sorted(results)

    def find_settings_file(self, root_path: Path) -> Optional[Path]:
        """Locate ``settings.py`` or ``manage.py`` within *root_path*.

        Searches up to 3 directory levels deep and returns the path of the
        first ``settings.py`` found, falling back to ``manage.py`` at the
        project root, or *None* if neither is present.
        """
        root = Path(root_path)
        # Fast check: manage.py at project root
        manage = root / "manage.py"
        if manage.exists():
            return manage
        # Walk up to 3 levels for settings.py
        for root_dir, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS and not d.startswith(".")]
            try:
                depth = len(Path(root_dir).relative_to(root).parts)
            except ValueError:
                depth = 0
            if depth > 3:
                dirs.clear()
                continue
            if "settings.py" in files:
                return Path(root_dir) / "settings.py"
        return None
