import re
from pathlib import Path
from typing import List, Dict, Set
from collections import defaultdict
from bck_nd_hlpr.core.constants import GLOBAL_IGNORE_DIRS
from bck_nd_hlpr.core.utils.indexer import FileSystemIndexer

class DependencyTracker:
    def __init__(self, root_path: str):
        self.root = Path(root_path).resolve()
        # Map: File -> Set of Files that import it (In-degree)
        self.usage_map: Dict[str, Set[str]] = {}
        # Map: File -> Set of Files that it imports (Out-degree)
        self.imports_map: Dict[str, Set[str]] = defaultdict(set)
        self.all_files: Set[str] = set()

    def scan_dependencies(self):
        """Builds the dependency graph."""
        self.usage_map = {}
        self.imports_map = defaultdict(set)
        self.all_files = set()

        file_index = FileSystemIndexer(str(self.root), max_depth=None).build()
        indexed_files = []
        for file_path in file_index.all_files:
            try:
                rel_file_path = str(file_path.relative_to(self.root)).replace("\\", "/")
            except ValueError:
                continue
            self.all_files.add(rel_file_path)
            indexed_files.append((file_path, rel_file_path))

        # Resolve imports only after the complete, ignore-filtered file set is known.
        for file_path, rel_file_path in indexed_files:
            if file_path.suffix.lower() in (".py", ".js", ".ts", ".jsx", ".tsx"):
                self._analyze_file_imports(file_path, rel_file_path)

    def _analyze_file_imports(self, file_path: Path, rel_source_path: str):
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

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

        except Exception:
            pass

    def _resolve_module_to_file(self, module: str, source_file: Path) -> str:
        """Attempts to resolve an import string to a relative file path in the project."""
        # Simple heuristic resolution.
        
        # 1. Check relative imports (starts with .)
        if module.startswith('.'):
            # JS/TS or Python relative
            # Resolve relative to source_file parent
            base = source_file.parent
            # . means current dir, .. means parent
            
            # Naive resolution: join paths
            try:
                candidate = (base / module).resolve()
                # Try extensions
                for ext in ['.py', '.js', '.ts', '', '.jsx', '.tsx']:
                    test = candidate.with_suffix(candidate.suffix + ext) if ext == '' else candidate.with_suffix(ext)
                    # Wait, with_suffix replaces. 
                    # If module is relative './utils', candidate is .../utils
                    # tests: .../utils.py, .../utils.js
                    
                    # Correct logic:
                    # If module ends with extension, maintain it.
                    # Else try appending extensions.
                    
                    possible_paths = []
                    name = candidate.name
                    parent = candidate.parent
                    
                    possible_paths.append(parent / (name + ".py"))
                    possible_paths.append(parent / (name + ".js"))
                    possible_paths.append(parent / (name + ".ts"))
                    possible_paths.append(parent / name / "index.js") # JS index
                    possible_paths.append(parent / name / "index.ts")
                    possible_paths.append(parent / name / "__init__.py") # Python package
                    
                    for p in possible_paths:
                        if p.exists() and self._is_within_root(p):
                            rel_path = str(p.relative_to(self.root)).replace("\\", "/")
                            if rel_path in self.all_files:
                                return rel_path
                            
            except Exception:
                pass
        
        # 2. Check absolute imports (from root)
        # e.g., 'bck_nd_hlpr.scanner' -> src/bck_nd_hlpr/scanner.py
        parts = module.replace(".", "/").split("/")
        
        # Try to find this path relative to Root or Source Root (src)
        candidates = [
            self.root / "/".join(parts),
            self.root / "src" / "/".join(parts)
        ]
        
        for cand in candidates:
            # Try extensions
            possible_paths = [
                cand.with_suffix(".py"),
                cand.with_suffix(".js"),
                cand.with_suffix(".ts"),
                cand / "__init__.py",
                cand / "index.js"
            ]
            for p in possible_paths:
                if p.exists() and self._is_within_root(p):
                    rel_path = str(p.relative_to(self.root)).replace("\\", "/")
                    if rel_path in self.all_files:
                        return rel_path

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
            
        try:
            rel_changed = str(Path(changed_file).resolve().relative_to(self.root)).replace("\\", "/")
        except ValueError:
            return {"changed_file": changed_file, "affected_files": []}

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
            "changed_file": changed_file,
            "affected_files": [item["file"] for item in affected]
        }

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

def analyze_impact(root_path: str):
    tracker = DependencyTracker(root_path)
    tracker.scan_dependencies()
    return tracker.usage_map


