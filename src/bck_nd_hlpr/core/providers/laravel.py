"""
Laravel architecture provider.
"""
import json
from pathlib import Path
from typing import Dict, Any, List

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
        if (root / "artisan").exists():
            return True

        # 2. composer.json listing laravel/framework
        composer = root / "composer.json"
        if composer.exists():
            try:
                data = json.loads(composer.read_text(encoding="utf-8", errors="ignore"))
                deps = {
                    **data.get("require", {}),
                    **data.get("require-dev", {}),
                }
                if "laravel/framework" in deps:
                    return True
            except Exception:
                pass

        # 3. Conventional app/Models directory
        if (root / "app" / "Models").is_dir():
            return True

        return False

    # -- Metadata -------------------------------------------------------------

    def get_framework_info(self, root_path: Path) -> Dict[str, Any]:
        root = Path(root_path)
        features: List[str] = []

        # Detect Eloquent ORM (always present in Laravel)
        orm = "Eloquent"

        # Detect some common Laravel features
        if (root / "routes" / "api.php").exists():
            features.append("API Routes")
        if (root / "routes" / "web.php").exists():
            features.append("Web Routes")
        if (root / "database" / "migrations").is_dir():
            features.append("Migrations")
        if (root / "app" / "Http" / "Middleware").is_dir():
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
        models_dir = root / "app" / "Models"
        if models_dir.is_dir():
            return sorted(models_dir.glob("*.php"))
        # Older Laravel (<8) stored models directly in app/
        app_dir = root / "app"
        if app_dir.is_dir():
            return sorted(
                p for p in app_dir.glob("*.php")
                if p.name not in ("Kernel.php", "Providers")
            )
        return []

    def find_route_files(self, root_path: Path) -> List[Path]:
        root = Path(root_path)
        routes: List[Path] = []
        for name in ("web.php", "api.php", "channels.php", "console.php"):
            route_file = root / "routes" / name
            if route_file.exists():
                routes.append(route_file)
        return routes
