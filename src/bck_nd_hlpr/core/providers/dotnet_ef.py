"""
ASP.NET Core / Entity Framework Core architecture provider.
"""
import re
from pathlib import Path
from typing import Dict, Any, List, Optional

from bck_nd_hlpr.core.providers.base import BaseArchitectureProvider, find_files_by_glob


_DBCONTEXT_CLASS_RE = re.compile(
    r"\bclass\s+\w+\s*:\s*[^\{]*?\bDbContext\b",
    re.MULTILINE | re.DOTALL,
)


def find_dbcontext_files(root_path: Path) -> List[Path]:
    """Locate C# source files whose contents declare a class inheriting from ``DbContext``.

    Walks ``*.cs`` files below *root_path* (respecting ``GLOBAL_IGNORE_DIRS``) and
    returns those whose content matches ``class X : ...DbContext`` patterns.
    Useful for EF Core architecture detection and targeted schema extraction.
    """
    root = Path(root_path)
    matched: List[Path] = []
    provider = DotNetEFProvider()
    snapshot = provider._snapshot(root)
    for cs_file in find_files_by_glob(root, "**/*.cs", file_index=snapshot):
        text = provider._read(root, cs_file)
        if text is None:
            continue
        if _DBCONTEXT_CLASS_RE.search(text):
            matched.append(cs_file)
    return sorted(matched)


class DotNetEFProvider(BaseArchitectureProvider):
    """Detects ASP.NET Core / EF Core (C#) projects."""

    @property
    def name(self) -> str:
        return ".NET Core / C#"

    @property
    def language(self) -> str:
        return "csharp"

    # -- Detection ------------------------------------------------------------

    def detect(self, root_path: Path) -> bool:
        root = Path(root_path)

        # 1. Find any .csproj or .sln file
        project_files = self._files(
            root,
            suffixes=(".csproj", ".sln"),
            max_depth=3,
        )
        has_dotnet_project = bool(project_files)
        for item in project_files:
            if item.suffix.casefold() == ".csproj":
                content = self._read(root, item)
                if content is not None and "Microsoft.EntityFrameworkCore" in content:
                    return True

        # 3. Check for DbContext in .cs files
        if has_dotnet_project:
            return True

        return False

    # -- Metadata -------------------------------------------------------------

    def get_framework_info(self, root_path: Path) -> Dict[str, Any]:
        root = Path(root_path)
        features: List[str] = []
        orm = self._detect_orm(root)

        if orm:
            features.append(orm)

        return {
            "framework": ".NET Core / C#",
            "language": "csharp",
            "architecture_type": "MVC + Services (Layered)",
            "orm": orm,
            "features": features,
        }

    # -- Helpers --------------------------------------------------------------

    def _detect_orm(self, root: Path) -> str | None:
        """Scan .csproj files for EF Core or Dapper references."""
        for path in self._files(root, suffixes=(".csproj",), max_depth=3):
            content = self._read(root, path)
            if content is None:
                continue
            if "Microsoft.EntityFrameworkCore" in content:
                return "EF Core"
            if "Dapper" in content:
                return "Dapper"
        return None

    def find_model_files(self, root_path: Path) -> List[Path]:
        root = Path(root_path)
        return [
            path
            for path in self._files(root, suffixes=(".cs",))
            if path.parent.name.lower()
            in ("models", "model", "entities", "entity", "domain")
        ]

    def find_route_files(self, root_path: Path) -> List[Path]:
        root = Path(root_path)
        return [
            path
            for path in self._files(root, suffixes=(".cs",))
            if path.parent.name.lower() in ("controllers", "controller")
        ]
