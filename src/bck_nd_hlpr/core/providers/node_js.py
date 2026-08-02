"""
Node.js / JavaScript / TypeScript architecture provider.

Covers Express, NestJS, Fastify, Koa, Next.js, and ORM detection
for Prisma, TypeORM, Sequelize, and Mongoose.
"""
import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from bck_nd_hlpr.core.providers.base import BaseArchitectureProvider


# Maps package.json dependency keys → (framework display name, architecture type)
_FRAMEWORK_MAP: List[Tuple[str, str, str]] = [
    ("@nestjs/core", "NestJS", "MVC + Services (Layered)"),
    ("next", "Next.js", "Next.js Project"),
    ("fastify", "Fastify", "REST API"),
    ("koa", "Koa", "REST API"),
    ("express", "Express.js", "REST API"),
]

# Maps dependency keys → ORM display name
_ORM_MAP: List[Tuple[str, str]] = [
    ("prisma", "Prisma"),
    ("@prisma/client", "Prisma"),
    ("typeorm", "TypeORM"),
    ("sequelize", "Sequelize"),
    ("mongoose", "Mongoose"),
    ("drizzle-orm", "Drizzle"),
    ("knex", "Knex.js"),
]


class NodeJsProvider(BaseArchitectureProvider):
    """Detects Node.js / JavaScript / TypeScript projects."""

    @property
    def name(self) -> str:
        return "Node.js"

    @property
    def language(self) -> str:
        return "javascript"

    # -- Detection ------------------------------------------------------------

    def detect(self, root_path: Path) -> bool:
        root = Path(root_path)
        package_json = root / "package.json"
        if not package_json.exists():
            return False

        try:
            data = json.loads(
                package_json.read_text(encoding="utf-8", errors="ignore")
            )
            deps = {
                **data.get("dependencies", {}),
                **data.get("devDependencies", {}),
            }
            # Match if any known framework or ORM dependency is present
            known_keys = {key for key, _, _ in _FRAMEWORK_MAP} | {key for key, _ in _ORM_MAP}
            return bool(known_keys & set(deps.keys()))
        except Exception:
            pass

        return False

    # -- Metadata -------------------------------------------------------------

    def get_framework_info(self, root_path: Path) -> Dict[str, Any]:
        root = Path(root_path)
        deps = self._read_deps(root)
        framework, arch_type = self._resolve_framework(deps, root)
        orm = self._resolve_orm(deps)
        features: List[str] = []

        if orm:
            features.append(f"{orm} ORM")

        # Detect TypeScript
        if (root / "tsconfig.json").exists():
            features.append("TypeScript")

        return {
            "framework": framework,
            "language": "typescript" if "TypeScript" in features else "javascript",
            "architecture_type": arch_type,
            "orm": orm,
            "features": features,
        }

    # -- Helpers --------------------------------------------------------------

    @staticmethod
    def _read_deps(root: Path) -> Dict[str, str]:
        package_json = root / "package.json"
        if not package_json.exists():
            return {}
        try:
            data = json.loads(
                package_json.read_text(encoding="utf-8", errors="ignore")
            )
            return {
                **data.get("dependencies", {}),
                **data.get("devDependencies", {}),
            }
        except Exception:
            return {}

    @staticmethod
    def _resolve_framework(
        deps: Dict[str, str], root: Path
    ) -> Tuple[str, str]:
        """Return (framework_name, architecture_type) for the first matching
        framework dependency."""
        for key, name, arch in _FRAMEWORK_MAP:
            if key in deps:
                # Refine Next.js architecture type
                if name == "Next.js":
                    if (root / "app").exists() or (root / "src" / "app").exists():
                        arch = "Next.js App Router"
                    elif (root / "pages").exists() or (root / "src" / "pages").exists():
                        arch = "Next.js Pages Router"
                return name, arch
        return "Node.js", "REST API"

    @staticmethod
    def _resolve_orm(deps: Dict[str, str]) -> Optional[str]:
        for key, name in _ORM_MAP:
            if key in deps:
                return name
        return None

    # -- File discovery -------------------------------------------------------

    def find_model_files(self, root_path: Path) -> List[Path]:
        root = Path(root_path)
        results: List[Path] = []

        # Prisma schema
        prisma_schema = root / "prisma" / "schema.prisma"
        if prisma_schema.exists():
            results.append(prisma_schema)

        # TypeORM / Sequelize entities
        src = root / "src"
        if src.is_dir():
            for ext in ("*.ts", "*.js"):
                for p in src.rglob(ext):
                    parent_lower = p.parent.name.lower()
                    if parent_lower in (
                        "models", "model", "entities", "entity",
                        "schemas", "schema",
                    ):
                        results.append(p)
        return sorted(results)

    def find_route_files(self, root_path: Path) -> List[Path]:
        root = Path(root_path)
        results: List[Path] = []
        src = root / "src"
        if src.is_dir():
            for ext in ("*.ts", "*.js"):
                for p in src.rglob(ext):
                    parent_lower = p.parent.name.lower()
                    name_lower = p.stem.lower()
                    if parent_lower in (
                        "routes", "route", "controllers", "controller",
                    ) or "route" in name_lower or "controller" in name_lower:
                        results.append(p)
        return sorted(results)
