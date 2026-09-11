import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Dict, List, Optional, Set
from collections import defaultdict
from bck_nd_hlpr.core.constants import GLOBAL_IGNORE_DIRS
from bck_nd_hlpr.core.utils.cache import FileCache
from bck_nd_hlpr.core.utils.indexer import FileIndex, FileSystemIndexer

class DependencyTracker:
    def __init__(self, root_path: str, *, file_index: Optional[FileIndex] = None):
        self.root = file_index.root if file_index is not None else Path(root_path).absolute()
        self.file_index = file_index
        # Map: File -> Set of Files that import it (In-degree)
        self.usage_map: Dict[str, Set[str]] = {}
        # Map: File -> Set of Files that it imports (Out-degree)
        self.imports_map: Dict[str, Set[str]] = defaultdict(set)
        self.all_files: Set[str] = set()
        self._indexed_paths: Dict[str, Path] = {}

    def scan_dependencies(self):
        """Builds the dependency graph."""
        self.usage_map = {}
        self.imports_map = defaultdict(set)
        self.all_files = set()
        self._indexed_paths = {}

        try:
            file_index = self.file_index or FileSystemIndexer(
                str(self.root), max_depth=None
            ).build()
        except (OSError, RuntimeError, ValueError):
            return
        self.file_index = file_index
        self.root = file_index.root
        indexed_files = []
        for file_path in file_index.all_files:
            try:
                rel_file_path = str(file_path.relative_to(self.root)).replace("\\", "/")
            except ValueError:
                continue
            self.all_files.add(rel_file_path)
            self._indexed_paths[rel_file_path] = file_path
            indexed_files.append((file_path, rel_file_path))

        # Resolve imports only after the complete, ignore-filtered file set is known.
        for file_path, rel_file_path in indexed_files:
            if file_path.suffix.lower() in (".py", ".js", ".ts", ".jsx", ".tsx"):
                self._analyze_file_imports(file_path, rel_file_path)

    def _analyze_file_imports(self, file_path: Path, rel_source_path: str):
        try:
            content = FileCache.read_project_file(
                self.root,
                file_path,
                encoding='utf-8',
                errors='ignore',
            )

            # PATTERNS
            
            # Python: from x import y, import x
            # JS/TS: import ... from 'x', require('x')
            
            imported_modules = set()
            
            # Python Logic
            if file_path.suffix == '.py':
                # from module import ...
                matches = re.findall(r'^from\s+(\S+)\s+import', content, re.MULTILINE)
                imported_modules.update(matches)
                # import module
                matches = re.findall(r'^import\s+(\S+)', content, re.MULTILINE)
                imported_modules.update(matches)
                
            # JS/TS Logic
            elif file_path.suffix in ('.js', '.ts', '.jsx', '.tsx'):
                # import ... from 'module'
                matches = re.findall(r'from\s+[\'"]([^\'"]+)[\'"]', content)
                imported_modules.update(matches)
                # require('module')
                matches = re.findall(r'require\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)', content)
                imported_modules.update(matches)

            # Resolve to files
            for mod in imported_modules:
                target_file = self._resolve_module_to_file(mod, file_path)
                if target_file:
                    # target_file is IMPORTED BY rel_source_path
                    if target_file not in self.usage_map:
                        self.usage_map[target_file] = set()
                    self.usage_map[target_file].add(rel_source_path)
                    self.imports_map[rel_source_path].add(target_file)

        except (OSError, UnicodeError, ValueError, TypeError):
            pass

    def _resolve_module_to_file(self, module: str, source_file: Path) -> str:
        """Attempts to resolve an import string to a relative file path in the project."""
        if not isinstance(module, str) or not module.strip():
            return None
        module = module.strip()
        if PureWindowsPath(module).is_absolute() or PurePosixPath(
            module.replace("\\", "/")
        ).is_absolute():
            return None

        # 1. Resolve relative imports lexically against the indexed source.
        if module.startswith('.'):
            source_relative = source_file.relative_to(self.root).as_posix()
            source_parent = PurePosixPath(source_relative).parent
            if module.startswith("./") or module.startswith("../"):
                module_path = module
            else:
                dot_count = len(module) - len(module.lstrip("."))
                base_parts = list(source_parent.parts)
                if dot_count > len(base_parts) + 1:
                    return None
                for _ in range(max(0, dot_count - 1)):
                    if not base_parts:
                        return None
                    base_parts.pop()
                remainder = module[dot_count:].replace(".", "/")
                module_path = "/".join([*base_parts, remainder]).strip("/")
                return self._first_indexed_candidate(module_path)

            normalized = self._normalize_relative_module(source_parent, module_path)
            if normalized is None:
                return None
            return self._first_indexed_candidate(normalized)
        
        # 2. Check absolute imports (from root)
        # e.g., 'bck_nd_hlpr.scanner' -> src/bck_nd_hlpr/scanner.py
        normalized = module.replace(".", "/").replace("\\", "/").strip("/")
        for base in (normalized, f"src/{normalized}"):
            matched = self._first_indexed_candidate(base)
            if matched:
                return matched

        return None

    @staticmethod
    def _normalize_relative_module(
        source_parent: PurePosixPath,
        module: str,
    ) -> Optional[str]:
        parts = list(source_parent.parts)
        for part in module.replace("\\", "/").split("/"):
            if part in {"", "."}:
                continue
            if part == "..":
                if not parts:
                    return None
                parts.pop()
            else:
                parts.append(part)
        return "/".join(parts)

    def _first_indexed_candidate(self, base: str) -> Optional[str]:
        candidates = (
            base,
            f"{base}.py",
            f"{base}.js",
            f"{base}.ts",
            f"{base}.jsx",
            f"{base}.tsx",
            f"{base}/index.js",
            f"{base}/index.ts",
            f"{base}/__init__.py",
        )
        for candidate in candidates:
            normalized = PurePosixPath(candidate).as_posix()
            if normalized in self.all_files:
                return normalized
        return None

    def _is_within_root(self, path: Path) -> bool:
        try:
            path.relative_to(self.root)
            return True
        except ValueError:
            return False

    # ═══════════════════════════════════════════════════════════════════
    # FUTURE METHODS — Cimientos para features planificadas
    # ═══════════════════════════════════════════════════════════════════

    def calculate_impact_radius(self, changed_file: str) -> dict:
        """Calculates what files are transitively affected by a change in `changed_file`."""
        if not self.all_files:
            self.scan_dependencies()
            
        rel_changed = self._safe_changed_file(changed_file)
        if rel_changed is None or rel_changed not in self.all_files:
            return {"changed_file": "<outside-project>", "affected_files": []}

        affected = []
        visited = set()
        queue = [(rel_changed, 0)]
        
        while queue:
            current, depth = queue.pop(0)
            if current not in visited:
                visited.add(current)
                if current != rel_changed:
                    affected.append({"file": current, "depth": depth})
                
                for dependent in self.usage_map.get(current, set()):
                    queue.append((dependent, depth + 1))
                    
        affected.sort(key=lambda x: x["depth"])
        
        return {
            "changed_file": rel_changed,
            "affected_files": [item["file"] for item in affected]
        }

    def _safe_changed_file(self, changed_file: str) -> Optional[str]:
        text = str(changed_file).strip()
        if not text:
            return None
        normalized = text.replace("\\", "/")
        pure = PurePosixPath(normalized)
        if ".." in pure.parts:
            return None
        windows = PureWindowsPath(text)
        native = Path(text)
        if windows.is_absolute() and not native.is_absolute():
            return None
        candidate = native if native.is_absolute() else self.root / native
        try:
            return candidate.relative_to(self.root).as_posix()
        except ValueError:
            return None

    def get_onboarding_path(self) -> list:
        """Generates a structured pedagogical reading path based on in/out degrees."""
        if not self.all_files:
            self.scan_dependencies()
            
        onboarding_list = []
        
        # Determine roles based on in/out degree and naming heuristics
        for file in self.all_files:
            file_lower = file.lower()
            
            p = Path(file)
            skip = False
            
            # Check extensions
            skip_extensions = {".exe", ".bat", ".ps1", ".cfg", ".json", ".yaml", ".yml", ".toml", ".ini", ".md", ".txt"}
            if p.suffix.lower() in skip_extensions:
                skip = True
                
            # Check path parts for exclusions
            for part in p.parts:
                part_lower = part.lower()
                if part in GLOBAL_IGNORE_DIRS:
                    skip = True
                    break
                if part_lower in ["cuarentena_env", ".venv", "env", "venv", "__pycache__"]:
                    skip = True
                    break
                if part.startswith(".") and part not in [".", ".."]:
                    skip = True
                    break
                    
            if skip:
                continue
                
            # Skip noise
            if any(n in file_lower for n in ["test_", ".test.", ".spec.", "conftest"]): continue
            
            in_degree = len(self.usage_map.get(file, set()))
            out_degree = len(self.imports_map.get(file, set()))
            
            tier = 4
            role = "Peripheral / Helper"
            hint = "Auxiliary or utility logic."
            
            # TIER 3: Database & Infra Setup
            # Evaluated first to prevent high-in-degree DB files from being marked as CORE.
            if any(k in file_lower for k in ["db", "models", "schema", "orm", "database", "infra", "config", "settings"]):
                tier = 3
                role = "Database & Infra"
                hint = "Defines data schemas, ORM setup, or infrastructure configurations."
                
            # TIER 1: Entrypoints & Routers
            elif (in_degree <= 1 and out_degree >= 1) or any(k in file_lower for k in ["main", "app", "index", "router", "server"]):
                tier = 1
                role = "Entrypoint & Router"
                hint = "Acts as the application entrypoint or defines primary HTTP routes."
                
            # TIER 2: Core Business Logic
            elif in_degree >= 2 or any(k in file_lower for k in ["service", "controller", "util", "helper", "manager", "handler"]):
                tier = 2
                role = "Core Business Logic"
                hint = "Contains central domain logic imported by multiple other files."
                
            onboarding_list.append({
                "file": file,
                "tier": tier,
                "role": role,
                "hint": hint,
                "in_degree": in_degree,
                "out_degree": out_degree
            })
            
        # Fallback if usage_map is completely empty (no internal imports detected)
        if not self.usage_map:
            # We already populated tier 1,2,3 based on name heuristics.
            pass
            
        # Sort by tier (1->2->3->4), then descending in_degree (more important first)
        onboarding_list.sort(key=lambda x: (x["tier"], -x["in_degree"], x["file"]))
        
        # Filter out tier 4 to keep it concise, unless everything is tier 4
        filtered_list = [item for item in onboarding_list if item["tier"] <= 3]
        if not filtered_list:
            filtered_list = onboarding_list[:15] # Just show up to 15 files if nothing else
            
        return filtered_list

    def get_dependency_graph_for_routes(self, route_files: list) -> dict:
        """[STUB] Filtra el grafo de dependencias para incluir solo la cadena de archivos de rutas.
        
        Diseño futuro:
        1. Dado un set de archivos que contienen rutas API,
           retornar subgrafo: route_file → servicios → modelos.
        2. Será consumido por el API Contract Map para cruzar con ER.
        """
        pass

def analyze_impact(
    root_path: str, *, file_index: Optional[FileIndex] = None
):
    tracker = DependencyTracker(root_path, file_index=file_index)
    tracker.scan_dependencies()
    return tracker.usage_map


