import os
import re
from pathlib import Path
from typing import List, Dict, Set
from collections import defaultdict
from bck_nd_hlpr.constants import GLOBAL_IGNORE_DIRS
from rich.console import Console
from rich.table import Table
from rich.text import Text

class DependencyTracker:
    def __init__(self, root_path: str):
        self.root = Path(root_path).resolve()
        # Map: File -> Set of Files that import it
        self.usage_map: Dict[str, Set[str]] = {}
        self.all_files: Set[str] = set()

    def scan_dependencies(self):
        """Builds the dependency graph."""
        for root_dir, dirs, files in os.walk(self.root):
            rel_root = Path(root_dir).relative_to(self.root)
            if str(rel_root) == ".": depth = 0
            else: depth = len(rel_root.parts)
            
            # Skip deep nesting or ignored dirs
            if any(part in GLOBAL_IGNORE_DIRS for part in rel_root.parts):
                del dirs[:]
                continue
            
            dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS]

            for file in files:
                file_path = Path(root_dir) / file
                rel_file_path = str(file_path.relative_to(self.root)).replace("\\", "/") # Normalize to forward slash
                self.all_files.add(rel_file_path)
                
                if file.endswith((".py", ".js", ".ts", ".jsx", ".tsx")):
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
                            return str(p.relative_to(self.root)).replace("\\", "/")
                            
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
                     return str(p.relative_to(self.root)).replace("\\", "/")

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

    # TODO: [ImpactRadius] - Calcular radio de impacto conectando dependencias con rutas API
    # Dado un archivo modificado, retornar qué rutas HTTP se ven afectadas.
    # Input: archivo cambiado → Output: lista de RouteInfo afectados.
    # Requiere integración con route_parser.parse_project_routes().
    def calculate_impact_radius(self, changed_file: str) -> list:
        """[STUB] Calcula qué rutas API se ven afectadas por un cambio en `changed_file`.
        
        Diseño futuro:
        1. Obtener dependientes transitivos de `changed_file` vía usage_map.
        2. Cruzar con route_parser para identificar qué endpoints tocan esos archivos.
        3. Retornar lista de RouteInfo con método HTTP, path y handler afectado.
        """
        pass  # TODO: [ImpactRadius] - Implementar traversal transitivo + cruce con RouteInfo

    # TODO: [Teach] - Generar datos para el sendero pedagógico de onboarding
    # Ordenar archivos desde CORE → SHARED → PERIPHERAL con metadatos útiles.
    def get_dependency_heatmap(self) -> list:
        """[STUB] Retorna archivos ordenados por criticidad para onboarding guiado.
        
        Diseño futuro:
        1. Ejecutar scan_dependencies() si no se ha hecho.
        2. Clasificar en CORE (>5 dependientes), SHARED (2-5), PERIPHERAL (<2).
        3. Retornar lista de dicts: [{file, score, category, dependents}].
        """
        pass  # TODO: [Teach] - Implementar clasificación y ranking de archivos

    # TODO: [APIContractMap] - Retornar el grafo de dependencias filtrado por archivos de rutas
    # Para cruzar con modelos ER y generar el API Contract Map.
    def get_dependency_graph_for_routes(self, route_files: list) -> dict:
        """[STUB] Filtra el grafo de dependencias para incluir solo la cadena de archivos de rutas.
        
        Diseño futuro:
        1. Dado un set de archivos que contienen rutas API,
           retornar subgrafo: route_file → servicios → modelos.
        2. Será consumido por el API Contract Map para cruzar con ER.
        """
        pass  # TODO: [APIContractMap] - Implementar filtrado de subgrafo

def analyze_impact(root_path: str):
    tracker = DependencyTracker(root_path)
    tracker.scan_dependencies()
    return tracker.usage_map

def get_impact_report_string(usage_map: Dict[str, Set[str]], plain: bool = False) -> str:
    import io
    output = io.StringIO()
    
    if plain:
        console = Console(file=output, force_terminal=False, no_color=True, width=120)
    else:
        console = Console(file=output, force_terminal=True, width=120)
        
    table = Table(
        title="🔥 DEPENDENCY IMPACT HEATMAP (What breaks if I touch this?)",
        show_header=True,
        header_style="bold red" if not plain else None,
        border_style="red" if not plain else None,
        title_style="bold red" if not plain else None
    )
    
    table.add_column("File (The Dependency)", style="cyan" if not plain else None)
    table.add_column("Impact Score", justify="right", style="bold white" if not plain else None)
    table.add_column("Risk Category", justify="center", style="bold" if not plain else None)
    table.add_column("Imported By (Dependents)", style="white" if not plain else None)

    # Sort by number of dependents (High impact first)
    sorted_files = sorted(usage_map.items(), key=lambda item: len(item[1]), reverse=True)
    
    # Take top 50 to avoid noise?
    
    for file, dependents in sorted_files:
        score = len(dependents)
        deps_list = ", ".join(sorted(list(dependents))[:3]) # Show first 3
        if len(dependents) > 3:
            deps_list += f" (+{len(dependents)-3} more)"
            
        color = "white"
        risk_category = "🟢 PERIPHERAL"
        risk_color = "green"

        if score > 5:
            color = "bold red"
            risk_category = "🔥 CORE"
            risk_color = "bold red"
        elif score >= 2:
            color = "bold yellow"
            risk_category = "🟡 SHARED"
            risk_color = "bold yellow"
        
        count_styled = Text(str(score), style=color if not plain else None)
        risk_styled = Text(risk_category, style=risk_color if not plain else None)
        
        table.add_row(file, count_styled, risk_styled, deps_list)
        
    console.print(table)
    
    if not usage_map:
        console.print("\n[yellow]No internal dependencies detected (or project is flat).[/yellow]" if not plain else "\nNo internal dependencies detected.")
        
    return output.getvalue()
