import os
import re
from pathlib import Path
from bck_nd_hlpr.detector import ArchitectureDetector
from bck_nd_hlpr.uml_parser import parse_file_for_uml, generate_mermaid_class_diagram, UMLClassInfo

class ProjectScanner:
    IGNORE_DIRS = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', 'dist', 'build', '.idea', '.vscode', 'research', 'ascii_architect.egg-info', 'bck-nd-hlpr.egg-info'} # Added egg-info ignore for new package too
    
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
        self.IGNORE_DIRS.add('bck-nd-hlpr') # Ignore self if inside (though it won't scan recursively up hopefully)

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
    
    def scan(self, root_path: str, max_depth: int = 1) -> str:
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

            if depth_level >= max_depth:
                del dirs[:] 
                continue
            
            dirs[:] = [d for d in dirs if d not in self.IGNORE_DIRS and not d.startswith('.')]
            
            for f in files:
                if f.endswith(".py"):
                    self.allowed_files.add(f.replace(".py", ""))

        # FASE 2: CONEXIÓN
        for root_dir, dirs, files in os.walk(root):
            rel_path = Path(root_dir).relative_to(root)
            depth_level = len(rel_path.parts)
            if str(rel_path) == ".": depth_level = 0

            if depth_level >= max_depth:
                del dirs[:]
                continue
            
            dirs[:] = [d for d in dirs if d not in self.IGNORE_DIRS and not d.startswith('.')]
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
                elif file in ["Cargo.toml", "package.json", "go.mod", "pom.xml"]:
                    # Archivos de definición de proyecto = Nodos Centrales
                    connections.append(f"{folder_name} [DIR] -> {file}")

                # ☁️ INFRAESTRUCTURA
                elif file.endswith(".tf"): # Terraform
                    connections.append(f"Terraform -> {file}")

                # 🗄️ DATOS (Archivos estáticos)
                elif file.endswith((".sql", ".db", ".sqlite")):
                    components['database'].append(file)
                    connections.append(f"[Database] {file} -> Data_Storage")

        if not connections: return ""
        if not connections: return ""
        return " ; ".join(sorted(list(set(connections))))

    def scan_uml(self, root_path: str, max_depth: int = 1) -> str:
        """Genera un diagrama de clases UML (Mermaid)."""
        root = Path(root_path).resolve()
        if not root.exists(): return "Error -> Path_Not_Found"
        
        all_classes: list[UMLClassInfo] = []
        
        # Recorremos archivos
        for root_dir, dirs, files in os.walk(root):
            rel_path = Path(root_dir).relative_to(root)
            depth_level = len(rel_path.parts)
            if str(rel_path) == ".": depth_level = 0

            if depth_level >= max_depth:
                del dirs[:] 
                continue
            
            # Filtrar directorios ignorados
            dirs[:] = [d for d in dirs if d not in self.IGNORE_DIRS and not d.startswith('.')]
            
            for file in files:
                if file.endswith(".py"):
                    full_path = Path(root_dir) / file
                    classes = parse_file_for_uml(full_path, root)
                    all_classes.extend(classes)
        
        if not all_classes:
            return "classDiagram\n    note \"No Python classes found in scanned directories.\""

        return generate_mermaid_class_diagram(all_classes)

    def get_docs_content(self, root_path: str) -> str:
        """
        Lee el contenido de archivos de documentación clave para dar contexto a la IA.
        """
        root = Path(root_path).resolve()
        docs_buffer = []
        
        print("📚 [Scanner] Buscando documentación para contexto...")
        
        # Buscamos en la raíz y en una carpeta docs/ si existe
        search_paths = [root, root / "docs"]
        
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
