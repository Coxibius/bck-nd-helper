import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional
from bck_nd_hlpr.constants import GLOBAL_IGNORE_DIRS
from bck_nd_hlpr.detector import ArchitectureDetector
from bck_nd_hlpr.uml_parser import parse_file_for_uml, generate_mermaid_class_diagram, UMLClassInfo

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
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
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
    
    def scan(self, root_path: str, max_depth: int = 5) -> str:
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

            if depth_level > max_depth:
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

            if depth_level > max_depth:
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

    def scan_uml(self, root_path: str, max_depth: int = 5) -> str:
        """Genera un diagrama de clases UML (Mermaid) multi-lenguaje."""
        root = Path(root_path).resolve()
        if not root.exists(): return "Error -> Path_Not_Found"
        
        all_classes: list[UMLClassInfo] = []
        
        # 1. Python (via AST)
        for root_dir, dirs, files in os.walk(root):
            rel_path = Path(root_dir).relative_to(root)
            depth_level = len(rel_path.parts)
            if str(rel_path) == ".": depth_level = 0

            if depth_level > max_depth:
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
            from bck_nd_hlpr.csharp_parser import parse_project_for_csharp_uml
            all_classes.extend(parse_project_for_csharp_uml(root_path, max_depth=max_depth))
        except Exception as e:
            print(f"Error parseando UML C#: {e}", file=sys.stderr)
            
        # 3. Java UML Parser
        try:
            from bck_nd_hlpr.java_parser import parse_project_for_java_uml
            all_classes.extend(parse_project_for_java_uml(root_path, max_depth=max_depth))
        except Exception as e:
            print(f"Error parseando UML Java: {e}", file=sys.stderr)
            
        # 4. JS/TS UML Parser
        try:
            from bck_nd_hlpr.js_parser import parse_project_for_js_uml
            all_classes.extend(parse_project_for_js_uml(root_path, max_depth=max_depth))
        except Exception as e:
            print(f"Error parseando UML JS/TS: {e}", file=sys.stderr)
            
        # 5. PHP UML Parser
        try:
            from bck_nd_hlpr.php_parser import parse_project_for_php_uml
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
                        with open(target_file, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
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

    # TODO: [Health] - Calcular Project Health Score consolidado
    # Orquestar: todo_hunter.scan_for_todos() + security_auditor.scan_security_risks()
    #           + dependency_tracker.analyze_impact()
    # Retornar un dict con score global (0-100) y breakdown por categoría.
    def calculate_health_score(self, root_path: str, max_depth: int = 5) -> dict:
        """[STUB] Calcula un Project Health Score consolidado.
        
        Diseño futuro:
        1. TODOs: Penalizar por cantidad y severidad (FIXME > TODO).
        2. Security: Penalizar por CRITICAL (-20), HIGH (-10), WARNING (-3).
        3. Dependencies: Bonificar bajo acoplamiento, penalizar CORE files sin tests.
        4. Retornar: {score: int, grade: str, breakdown: {todos: {}, security: {}, deps: {}}}.
        """
        pass  # TODO: [Health] - Implementar cálculo y ponderación de métricas

    # TODO: [DataScience] - Soporte para parsear notebooks Jupyter (.ipynb)
    # Extraer celdas de código, detectar imports de pandas/sklearn/torch,
    # identificar pipelines ETL y generar nodos en el diagrama de arquitectura.
    def scan_notebooks(self, root_path: str, max_depth: int = 3) -> list:
        """[STUB] Escanea archivos .ipynb para detectar pipelines de Data Science.
        
        Diseño futuro:
        1. Parsear JSON del .ipynb (cells[].source donde cell_type=='code').
        2. Detectar imports: pandas, numpy, sklearn, torch, tensorflow, pyspark.
        3. Identificar patrones ETL: read_csv → transform → to_sql/to_parquet.
        4. Retornar lista de dicts: [{notebook, imports, pipeline_stages}].
        """
        pass  # TODO: [DataScience] - Implementar parser de notebooks .ipynb

    # TODO: [Teach] - Punto de integración con el onboarding guiado
    # Este método será llamado por cli.py --teach para obtener el recorrido pedagógico.
    # Internamente usa DependencyTracker.get_dependency_heatmap().
    def get_onboarding_path(self, root_path: str) -> list:
        """[STUB] Genera un recorrido pedagógico ordenado del codebase.
        
        Diseño futuro:
        1. Llamar a DependencyTracker(root_path).get_dependency_heatmap().
        2. Para cada archivo CORE, leer las primeras líneas y docstrings.
        3. Generar un "tour" con: [{step, file, category, summary, tip}].
        """
        pass  # TODO: [Teach] - Implementar generación de tour pedagógico
