"""
Node.js / JavaScript / TypeScript architecture provider.

Covers Express, NestJS, Fastify, Koa, Next.js, and ORM detection
for Prisma, TypeORM, Sequelize, and Mongoose.
"""
import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from bck_nd_hlpr.core.providers.base import BaseArchitectureProvider, find_files_by_glob


def find_package_json(root_path: Path) -> Optional[Path]:
    """Return the canonical ``package.json`` path for *root_path*.

    First checks for ``root_path / "package.json"`` (the common single-package layout).
    For monorepos without a top-level manifest the helper performs a shallow 3-level walk
    and returns the first ``package.json`` found closest to the project root.
    Returns *None* if no manifest is discoverable.
    """
    root = Path(root_path)
    direct = root / "package.json"
    if direct.is_file():
        return direct
    try:
        candidates = find_files_by_glob(root, "**/package.json")
    except Exception:
        return None
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except Exception:
            continue
    return None


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


def find_routes_or_controllers(root_path: Path) -> List[Path]:
    """Locate NestJS and Express route / controller source files.

    Covers the conventional directory layouts used by NestJS (``src/*/``
    with ``*.controller.ts``), Express (``routes/``, ``controllers/``),
    and monorepo-style packages with a top-level ``src``.  Also scans
    the project root for route files when no ``src`` directory exists,
    and includes any ``app.ts`` / ``server.ts`` / ``index.ts`` bootstrap
    files that define route mounts directly.  Results are de-duplicated
    and returned sorted alphabetically.
    """
    root = Path(root_path)
    seen: set = set()
    results: List[Path] = []

    def _accept(p: Path) -> None:
        try:
            key = p.resolve()
        except Exception:
            key = Path(str(p)).absolute()
        if key in seen or not p.is_file():
            return
        seen.add(key)
        results.append(p)

    try:
        existing = NodeJsProvider().find_route_files(root)
        for p in existing:
            _accept(p)
    except Exception:
        pass

    bootstrap_names = {"app", "server", "index", "main", "routes", "router"}

    def _scan_dir(d: Path) -> None:
        if not d.is_dir():
            return
        for ext in ("*.ts", "*.js", "*.tsx", "*.jsx"):
            for p in d.rglob(ext):
                try:
                    rel = p.relative_to(root)
                except ValueError:
                    rel = Path(p.name)
                parts_lower = [part.lower() for part in rel.parts]
                name_lower = p.stem.lower()
                parent_lower = p.parent.name.lower()
                is_route_dir = any(seg in ("routes", "route", "controllers", "controller")
                                   for seg in parts_lower)
                is_route_name = ("route" in name_lower or "controller" in name_lower
                                 or "handler" in name_lower)
                is_bootstrap = name_lower in bootstrap_names
                if is_route_dir or is_route_name or (
                    is_bootstrap and parent_lower in ("src", "")
                ):
                    _accept(p)

    for candidate in (
        root / "src",
        root / "packages",
        root / "apps",
        root / "server",
        root,
    ):
        _scan_dir(candidate)

    return sorted(results)
