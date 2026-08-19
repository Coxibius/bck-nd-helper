import os
import re
import sys
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from bck_nd_hlpr.core.constants import GLOBAL_IGNORE_DIRS
from bck_nd_hlpr.core.detector import ArchitectureDetector
from bck_nd_hlpr.core.uml_parser import parse_file_for_uml, generate_mermaid_class_diagram, UMLClassInfo
from bck_nd_hlpr.core.base_analyzer import (
    AnalyzerResult,
    ScanContext,
    available_flags,
    get_analyzer,
    register,
)

# Import the analyzer modules so their @register decorators populate the
# registry at import time. Adding a new analysis = drop a class in analysis.py
# (or any module listed here); the dispatcher below needs no changes.
from bck_nd_hlpr.core import analysis as _analysis  # noqa: F401


class ProjectScanner:

    # Archivos que aportan CONTEXTO a la IA (si existen, los leemos)
    CONTEXT_FILES = [
        "README.md", 
        "IA-context.md", 
        "ROADMAP.txt", 
        "ARCHITECTURE.md", 
        "CONTRIBUTING.md",
        "pyproject.toml"
    ]
    
    def __init__(self):
        self.allowed_files = set() 

    def _find_imports(self, file_path: Path) -> list[str]:
        """Busca imports SOLO hacia archivos que están en la lista blanca."""
        detected = []
        try:
            from bck_nd_hlpr.core.utils.cache import FileCache
            content = FileCache.read_file(file_path, encoding='utf-8', errors='ignore')
            patterns = [r'^from\s+(\w+)\s+import', r'^import\s+(\w+)']
            for line in content.splitlines():
                for pat in patterns:
                    match = re.search(pat, line.strip())
                    if match:
                        module = match.group(1)
                        if module in self.allowed_files and module != file_path.stem:
                            detected.append(module)
        except:
            pass
        return detected

    def detect_architecture(self, root_path: str) -> dict:
        """Detecta y retorna información arquitectónica del proyecto."""
        detector = ArchitectureDetector()
        return detector.detect(root_path)

    # ═══════════════════════════════════════════════════════════════════
    # STRATEGY DISPATCHER — replaces the old flag if/elif God-Object block.
    # Any mode (--uml/--er/--todo/--audit/--trace/...) is resolved from the
    # registry. New analyses register themselves; this method never changes.
    # ═══════════════════════════════════════════════════════════════════

    #: Re-export so callers can register without importing base_analyzer.
    register = staticmethod(register)

    @staticmethod
    def available_analyzers() -> List[str]:
        """List every registered analyzer flag."""
        return available_flags()

    def analyze(
        self,
        flag: str,
        root_path: str,
        depth: int = 5,
        arch_info: Optional[Dict[str, Any]] = None,
        plain: bool = True,
    ) -> AnalyzerResult:
        """Dispatch a scan mode through the registry (no hardcoded branches)."""
        analyzer = get_analyzer(flag)
        if analyzer is None:
            raise KeyError(
                f"Unknown analyzer '{flag}'. Available: {', '.join(available_flags())}"
            )
        if arch_info is None:
            arch_info = self.detect_architecture(root_path)
        ctx = ScanContext(path=root_path, depth=depth, arch_info=arch_info, plain=plain)
        return analyzer.run(ctx)


    def scan(self, root_path: str, max_depth: Optional[int] = 5) -> str:
        """Genera la topología (Grafo)."""
        root = Path(root_path).resolve()
        if not root.exists(): return "Error -> Path_Not_Found"
        
        self.allowed_files.clear()
        connections = []
        components = {  # Detectar componentes arquitectónicos
            'controllers': [],
            'models': [],
            'services': [],
            'routes': [],
            'middlewares': [],
            'database': []
        }

        # FASE 1: INDEXADO
        for root_dir, dirs, files in os.walk(root):
            rel_path = Path(root_dir).relative_to(root)
            depth_level = len(rel_path.parts)
            if str(rel_path) == ".": depth_level = 0

            if max_depth is not None and depth_level > max_depth:
                del dirs[:] 
                continue
            
            dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS and not d.startswith('.')]
            
            for f in files:
                if f.endswith(".py") or f.endswith(".cs") or f.endswith((".js", ".ts")):
                    self.allowed_files.add(Path(f).stem)

        # FASE 2: CONEXIÓN
        for root_dir, dirs, files in os.walk(root):
            rel_path = Path(root_dir).relative_to(root)
            depth_level = len(rel_path.parts)
            if str(rel_path) == ".": depth_level = 0

            if max_depth is not None and depth_level > max_depth:
                del dirs[:]
                continue
            
            dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS and not d.startswith('.')]
            folder_name = Path(root_dir).name
            if str(rel_path) == ".": folder_name = "ROOT"

            for file in files:
                # 🐍 PYTHON
                if file.endswith(".py"):
                    full_path = Path(root_dir) / file
                    file_lower = file.lower()
                    
                    # Clasificar componentes por patrón de nombres
                    if 'controller' in file_lower or 'ctrl' in file_lower:
                        components['controllers'].append(file)
                        connections.append(f"[Controller] {file} -> API")
                    elif 'model' in file_lower or 'entity' in file_lower or 'schema' in file_lower:
                        components['models'].append(file)
                        connections.append(f"[Model] {file} -> Database")
                    elif 'service' in file_lower or 'svc' in file_lower:
                        components['services'].append(file)
                        connections.append(f"[Service] {file} -> Business_Logic")
                    elif 'route' in file_lower or 'router' in file_lower:
                        components['routes'].append(file)
                        connections.append(f"[Route] {file} -> Endpoints")
                    elif 'middleware' in file_lower:
                        components['middlewares'].append(file)
                        connections.append(f"[Middleware] {file} -> Request_Pipeline")
                    else:
                        deps = self._find_imports(full_path)
                        if deps:
                            for dep in deps: connections.append(f"{file} -> {dep}.py")
                        else:
                            connections.append(f"{folder_name} [DIR] -> {file}")
                
                # 🐳 DOCKER
                elif file == "Dockerfile":
                    # El Dockerfile construye la App
                    connections.append(f"{folder_name} [DIR] -> Dockerfile")
                elif file == "docker-compose.yml":
                    # El compose orquesta todo
                    connections.append(f"docker-compose.yml -> {folder_name} [App]")

                # 🦀 RUST / JS / GO / ETC
                elif file in ["Cargo.toml", "package.json", "go.mod", "pom.xml", "tsconfig.json"]:
                    # Archivos de definición de proyecto = Nodos Centrales
                    connections.append(f"{folder_name} [DIR] -> {file}")
                    
                # 🔷 C# / .NET
                elif file.endswith(".cs"):
                    file_lower = file.lower()
                    if 'controller' in file_lower:
                        components['controllers'].append(file)
                        connections.append(f"[Controller] {file} -> API")
                    elif 'model' in file_lower or 'entity' in file_lower:
                        components['models'].append(file)
                        connections.append(f"[Model] {file} -> Database")
                    elif 'service' in file_lower or 'repository' in file_lower:
                        components['services'].append(file)
                        connections.append(f"[Service] {file} -> Business_Logic")
                    else:
                        connections.append(f"{folder_name} [DIR] -> {file}")
                    
                # ⚙️ .NET PROJECTS
                elif file.endswith(".csproj") or file.endswith(".sln"):
                    connections.append(f"{folder_name} [Solution/Project] -> {file}")

                # ☁️ INFRAESTRUCTURA
                elif file.endswith(".tf"): # Terraform
                    connections.append(f"Terraform -> {file}")

                # 🗄️ DATOS (Archivos estáticos)
                elif file.endswith((".sql", ".db", ".sqlite")):
                    components['database'].append(file)
                    connections.append(f"[Database] {file} -> Data_Storage")

        if not connections: return ""
        return " ; ".join(sorted(list(set(connections))))

    def scan_file(self, file_path: str) -> str:
        """Escanear un único archivo para ver sus importaciones locales."""
        path = Path(file_path).resolve()
        if not path.exists(): return ""
        
        # Necesitamos poblar allowed_files si está vacío para la whitelist
        if not self.allowed_files:
            # Buscar otros archivos hermanos/padres en el proyecto para whitelist
            root = path.parent
            for r_dir, r_dirs, files in os.walk(root):
                r_dirs[:] = [d for d in r_dirs if d not in GLOBAL_IGNORE_DIRS]
                for f in files:
                    if f.endswith((".py", ".cs", ".js", ".ts")):
                        self.allowed_files.add(Path(f).stem)
                        
        deps = self._find_imports(path)
        if deps:
            connections = [f"{path.name} -> {dep}.py" for dep in deps]
            return " ; ".join(connections)
        return ""

    def scan_uml(self, root_path: str, max_depth: Optional[int] = 5) -> str:
        """Genera un diagrama de clases UML (Mermaid) multi-lenguaje."""
        root = Path(root_path).resolve()
        if not root.exists(): return "Error -> Path_Not_Found"
        
        all_classes: list[UMLClassInfo] = []
        
        # 1. Python (via AST)
        for root_dir, dirs, files in os.walk(root):
            rel_path = Path(root_dir).relative_to(root)
            depth_level = len(rel_path.parts)
            if str(rel_path) == ".": depth_level = 0

            if max_depth is not None and depth_level > max_depth:
                del dirs[:] 
                continue
            
            dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS and not d.startswith('.')]
            
            for file in files:
                if file.endswith(".py"):
                    full_path = Path(root_dir) / file
                    classes = parse_file_for_uml(full_path, root)
                    all_classes.extend(classes)
        
        # 2. C# UML Parser
        try:
            from bck_nd_hlpr.core.csharp_parser import parse_project_for_csharp_uml
            all_classes.extend(parse_project_for_csharp_uml(root_path, max_depth=max_depth))
        except Exception as e:
            print(f"Error parseando UML C#: {e}", file=sys.stderr)
            
        # 3. Java UML Parser
        try:
            from bck_nd_hlpr.core.java_parser import parse_project_for_java_uml
            all_classes.extend(parse_project_for_java_uml(root_path, max_depth=max_depth))
        except Exception as e:
            print(f"Error parseando UML Java: {e}", file=sys.stderr)
            
        # 4. JS/TS UML Parser
        try:
            from bck_nd_hlpr.core.js_parser import parse_project_for_js_uml
            all_classes.extend(parse_project_for_js_uml(root_path, max_depth=max_depth))
        except Exception as e:
            print(f"Error parseando UML JS/TS: {e}", file=sys.stderr)
            
        # 5. PHP UML Parser
        try:
            from bck_nd_hlpr.core.php_parser import parse_project_for_php_uml
            all_classes.extend(parse_project_for_php_uml(root_path, max_depth=max_depth))
        except Exception as e:
            print(f"Error parseando UML PHP: {e}", file=sys.stderr)

        if not all_classes:
            return "classDiagram\n    note \"No classes found in scanned directories.\""

        return generate_mermaid_class_diagram(all_classes)

    def get_docs_content(self, root_path: str) -> str:
        """
        Lee el contenido de archivos de documentación clave para dar contexto a la IA.
        """
        root = Path(root_path).resolve()
        docs_buffer = []
        
        print("📚 [Scanner] Buscando documentación para contexto...", file=sys.stderr)
        
        # Buscamos en la raíz, en docs/ y en mis_apuntes/ si existen
        search_paths = [root, root / "docs", root / "mis_apuntes"]
        
        for base_path in search_paths:
            if not base_path.exists(): continue
            
            for file_name in self.CONTEXT_FILES:
                target_file = base_path / file_name
                if target_file.exists():
                    try:
                        from bck_nd_hlpr.core.utils.cache import FileCache
                        content = FileCache.read_file(target_file, encoding='utf-8', errors='ignore')
                        # Limitamos el tamaño por seguridad (máx 3000 caracteres por archivo)
                        if len(content) > 3000:
                            content = content[:3000] + "\n... [TRUNCADO POR EXCESO DE LONGITUD]"
                        
                        docs_buffer.append(f"\n--- CONTENIDO DE {file_name} ---")
                        docs_buffer.append(content)
                        docs_buffer.append("--------------------------------\n")
                    except Exception:
                        pass # Si falla leer uno, seguimos
        
        return "\n".join(docs_buffer)

    # ═══════════════════════════════════════════════════════════════════
    # FUTURE METHODS — Cimientos para features planificadas
    # ═══════════════════════════════════════════════════════════════════

    def calculate_health_score(self, root_path: str, max_depth: Optional[int] = 5) -> dict:
        """Calcula un Project Health Score consolidado."""
        try:
            from bck_nd_hlpr.core.todo_hunter import scan_for_todos
            todos = scan_for_todos(root_path, max_depth=max_depth) or []
        except Exception:
            todos = []
            
        try:
            from bck_nd_hlpr.core.security_auditor import scan_security_risks
            risks = scan_security_risks(root_path, max_depth=max_depth) or []
        except Exception:
            risks = []
            
        from bck_nd_hlpr.core.constants import GLOBAL_IGNORE_DIRS
        from pathlib import Path
        
        def is_test_file(file_path: str) -> bool:
            if not file_path:
                return False
            p = Path(file_path)
            # check directory names in the path
            for part in p.parts[:-1]:
                if part in ["tests", "test_project"] or part in GLOBAL_IGNORE_DIRS:
                    return True
            # check file name
            if p.name.startswith("test_"):
                return True
            return False

        todos = [t for t in todos if not is_test_file(t.get("file", ""))]
        risks = [r for r in risks if not is_test_file(r.get("file", ""))]
            
        critical_risks = 0
        high_risks = 0
        for risk in risks:
            sev = risk.get("severity", "").upper()
            if sev == "CRITICAL":
                critical_risks += 1
            elif sev in ["HIGH", "WARNING"]:
                high_risks += 1
                
        fixme_bugs = 0
        todos_hacks = 0
        for t in todos:
            ttype = t.get("type", "").upper()
            if ttype in ["FIXME", "BUG", "XXX"]:
                fixme_bugs += 1
            elif ttype in ["TODO", "HACK"]:
                todos_hacks += 1
                
        score = 100
        score -= (critical_risks * 25)
        score -= (high_risks * 10)
        score -= (fixme_bugs * 3)
        score -= (todos_hacks * 1)
        
        score = max(0, min(100, score))
        
        if score >= 90:
            grade = "A"
        elif score >= 80:
            grade = "B"
        elif score >= 70:
            grade = "C"
        elif score >= 60:
            grade = "D"
        else:
            grade = "F"
        
        return {
            "score": score,
            "grade": grade,
            "breakdown": {
                "critical_risks": critical_risks,
                "high_risks": high_risks,
                "fixme_bugs": fixme_bugs,
                "todos_hacks": todos_hacks
            }
        }

    def _parse_notebook_lineage(self, file_path: Path) -> dict:
        """Parse a Jupyter Notebook for input and output data references."""
        result = {"notebook": file_path.name, "inputs": [], "outputs": []}
        try:
            from bck_nd_hlpr.core.utils.cache import FileCache
            content = FileCache.read_file(file_path, encoding="utf-8", errors="ignore")
            data = json.loads(content)
        except Exception:
            return result

        cells = data.get("cells", [])
        if not isinstance(cells, list):
            return result

        code_text = []
        for cell in cells:
            if isinstance(cell, dict) and cell.get("cell_type") == "code":
                source = cell.get("source", [])
                if isinstance(source, list):
                    code_text.extend(source)
                elif isinstance(source, str):
                    code_text.append(source)
                    
        full_code = "\n".join(code_text)
        
        # Regex to find inputs and outputs
        input_pattern = re.compile(r"(?:read_csv|read_parquet|read_sql|read_json|read_excel|open)\s*\(\s*['\"]([^'\"]+)['\"]")
        output_pattern = re.compile(r"(?:to_csv|to_parquet|to_sql|to_json|to_excel|save|dump)\s*\(\s*['\"]([^'\"]+)['\"]")
        
        inputs = input_pattern.findall(full_code)
        outputs = output_pattern.findall(full_code)
        
        # Deduplicate while preserving order mostly
        result["inputs"] = list(dict.fromkeys(inputs))
        result["outputs"] = list(dict.fromkeys(outputs))
        
        return result

    def scan_notebooks(self, root_path: str, max_depth: Optional[int] = 3) -> str:
        """Generates a Mermaid graph LR representing the data lineage from Jupyter Notebooks."""
        root = Path(root_path).resolve()
        if not root.exists(): return ""
        
        lineages = []
        
        for root_dir, dirs, files in os.walk(root):
            rel_path = Path(root_dir).relative_to(root)
            depth_level = len(rel_path.parts) if str(rel_path) != "." else 0

            if max_depth is not None and depth_level > max_depth:
                del dirs[:] 
                continue
            
            dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS and not d.startswith('.')]
            
            for f in files:
                if f.endswith(".ipynb"):
                    full_path = Path(root_dir) / f
                    lineage = self._parse_notebook_lineage(full_path)
                    if lineage["inputs"] or lineage["outputs"]:
                        lineages.append(lineage)
                        
        if not lineages:
            return ""
            
        mermaid_lines = ["graph LR"]
        
        def sanitize_id(name: str) -> str:
            return name.replace(".", "_").replace("-", "_").replace(" ", "_").replace("/", "_").replace("\\", "_")
            
        for lin in lineages:
            nb_name = lin["notebook"]
            nb_id = sanitize_id(nb_name)
            
            for inp in lin["inputs"]:
                inp_id = sanitize_id(inp)
                # Input Data (Cylinder) --> Notebook (Rounded)
                mermaid_lines.append(f"    {inp_id}[(\"{inp}\")] --> {nb_id}(\"{nb_name}\")")
                
            for out in lin["outputs"]:
                out_id = sanitize_id(out)
                # Notebook (Rounded) --> Output Data (Cylinder)
                mermaid_lines.append(f"    {nb_id}(\"{nb_name}\") --> {out_id}[(\"{out}\")]")
                
        # Deduplicate connection lines
        seen_lines = set()
        dedup_lines = []
        for line in mermaid_lines:
            if line not in seen_lines:
                seen_lines.add(line)
                dedup_lines.append(line)
                
        return "\n".join(dedup_lines)

    def get_onboarding_path(self, root_path: str) -> list:
        """Genera un recorrido pedagógico ordenado del codebase."""
        from bck_nd_hlpr.core.dependency_tracker import DependencyTracker
        tracker = DependencyTracker(root_path)
        tracker.scan_dependencies()
        return tracker.get_onboarding_path()
