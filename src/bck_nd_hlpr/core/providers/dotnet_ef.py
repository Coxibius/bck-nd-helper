"""
ASP.NET Core / Entity Framework Core architecture provider.
"""
import os
import re
from pathlib import Path
from typing import Dict, Any, List, Optional

from bck_nd_hlpr.core.providers.base import BaseArchitectureProvider, find_files_by_glob
from bck_nd_hlpr.core.constants import GLOBAL_IGNORE_DIRS


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
    for cs_file in find_files_by_glob(root, "**/*.cs"):
        try:
            text = cs_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
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
        has_dotnet_project = False
        for item in root.iterdir():
            if item.suffix in (".csproj", ".sln"):
                has_dotnet_project = True
                # Check if .csproj references EF Core
                if item.suffix == ".csproj":
                    try:
                        content = item.read_text(encoding="utf-8", errors="ignore")
                        if "Microsoft.EntityFrameworkCore" in content:
                            return True
                    except Exception:
                        pass

        # 2. Recursively check .csproj files in subdirectories
        if not has_dotnet_project:
            for root_dir, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS and not d.startswith(".")]
                rel = Path(root_dir).relative_to(root)
                if len(rel.parts) > 3:
                    dirs.clear()
                    continue
                for f in files:
                    if f.endswith(".csproj") or f.endswith(".sln"):
                        has_dotnet_project = True
                        if f.endswith(".csproj"):
                            try:
                                content = (Path(root_dir) / f).read_text(
                                    encoding="utf-8", errors="ignore"
                                )
                                if "Microsoft.EntityFrameworkCore" in content:
                                    return True
                            except Exception:
                                pass

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
        for root_dir, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS and not d.startswith(".")]
            rel = Path(root_dir).relative_to(root)
            if len(rel.parts) > 3:
                dirs.clear()
                continue
            for f in files:
                if f.endswith(".csproj"):
                    try:
                        content = (Path(root_dir) / f).read_text(
                            encoding="utf-8", errors="ignore"
                        )
                        if "Microsoft.EntityFrameworkCore" in content:
                            return "EF Core"
                        if "Dapper" in content:
                            return "Dapper"
                    except Exception:
                        continue
        return None

    def find_model_files(self, root_path: Path) -> List[Path]:
        root = Path(root_path)
        results: List[Path] = []
        for root_dir, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS and not d.startswith(".")]
            parent_lower = Path(root_dir).name.lower()
            if parent_lower in ("models", "model", "entities", "entity", "domain"):
                for f in files:
                    if f.endswith(".cs"):
                        results.append(Path(root_dir) / f)
        return sorted(results)

    def find_route_files(self, root_path: Path) -> List[Path]:
        root = Path(root_path)
        results: List[Path] = []
        for root_dir, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS and not d.startswith(".")]
            parent_lower = Path(root_dir).name.lower()
            if parent_lower in ("controllers", "controller"):
                for f in files:
                    if f.endswith(".cs"):
                        results.append(Path(root_dir) / f)
        return sorted(results)
