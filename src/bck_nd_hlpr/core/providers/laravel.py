"""
Laravel architecture provider.
"""
import json
from pathlib import Path
from typing import Dict, Any, List, Optional

from bck_nd_hlpr.core.providers.base import BaseArchitectureProvider


class LaravelProvider(BaseArchitectureProvider):
    """Detects Laravel (PHP) projects and provides Eloquent ORM metadata."""

    @property
    def name(self) -> str:
        return "Laravel"

    @property
    def language(self) -> str:
        return "php"

    # -- Detection ------------------------------------------------------------

    def detect(self, root_path: Path) -> bool:
        root = Path(root_path)

        # 1. artisan CLI file is the strongest signal
        if self._file(root, "artisan") is not None:
            return True

        # 2. composer.json listing laravel/framework
        composer = self._file(root, "composer.json")
        if composer is not None:
            try:
                content = self._read(root, composer)
                if content is None:
                    return False
                data = json.loads(content)
                deps = {
                    **data.get("require", {}),
                    **data.get("require-dev", {}),
                }
                if "laravel/framework" in deps:
                    return True
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

        # 3. Conventional app/Models directory
        if self._has_directory(root, "app/Models"):
            return True

        return False

    # -- Metadata -------------------------------------------------------------

    def get_framework_info(self, root_path: Path) -> Dict[str, Any]:
        root = Path(root_path)
        features: List[str] = []

        # Detect Eloquent ORM (always present in Laravel)
        orm = "Eloquent"

        # Detect some common Laravel features
        if self._file(root, "routes/api.php") is not None:
            features.append("API Routes")
        if self._file(root, "routes/web.php") is not None:
            features.append("Web Routes")
        if self._has_directory(root, "database/migrations"):
            features.append("Migrations")
        if self._has_directory(root, "app/Http/Middleware"):
            features.append("Middleware")

        return {
            "framework": "Laravel",
            "language": "php",
            "architecture_type": "MVC Pattern",
            "orm": orm,
            "features": features,
        }

    # -- File discovery -------------------------------------------------------

    def find_model_files(self, root_path: Path) -> List[Path]:
        root = Path(root_path)
        models = [
            path
            for path in self._files(root, suffixes=(".php",))
            if path.parent.relative_to(root).as_posix().casefold() == "app/models"
        ]
        if models:
            return models
        # Older Laravel (<8) stored models directly in app/
        legacy = [
            path
            for path in self._files(root, suffixes=(".php",))
            if path.parent.relative_to(root).as_posix().casefold() == "app"
            and path.name not in ("Kernel.php", "Providers")
        ]
        if legacy:
            return legacy
        return []

    def find_route_files(self, root_path: Path) -> List[Path]:
        root = Path(root_path)
        routes: List[Path] = []
        for name in ("web.php", "api.php", "channels.php", "console.php"):
            route_file = self._file(root, f"routes/{name}")
            if route_file is not None:
                routes.append(route_file)
        return routes

    def find_artisan_file(self, root_path: Path) -> Optional[Path]:
        """Return the path to the Laravel ``artisan`` CLI file, or *None*.

        The ``artisan`` file at the project root is the canonical signal for a
        Laravel project.  This helper exposes the check as a reusable method so
        callers (e.g. CI generators, route scanners) can locate it without
        duplicating the root-level file probe.
        """
        return self._file(Path(root_path), "artisan")
