import ast
import os
from pathlib import Path
from typing import List, Dict, Set, Tuple, Optional
from bck_nd_hlpr.core.constants import GLOBAL_IGNORE_DIRS

class TraceNode:
    def __init__(self, route_method: str, route_path: str, handler_name: str, handler_file: str):
        self.route_method = route_method.upper()
        self.route_path = route_path
        self.handler_name = handler_name
        self.handler_file = handler_file
        self.calls: Set[str] = set() # Store names of services/models called

class TraceabilityScanner(ast.NodeVisitor):
    def __init__(self, filename: str, file_content: str):
        self.filename = filename
        self.file_content = file_content
        self.traces: List[TraceNode] = []
        self.imports: Dict[str, str] = {} # name -> module
        self.current_trace: TraceNode = None
        
        # We need to parse imports first to resolve where calls go
        self.tree = ast.parse(file_content)
        self._parse_imports()

    def _parse_imports(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname or alias.name
                    self.imports[name] = alias.name
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    name = alias.asname or alias.name
                    self.imports[name] = f"{module}.{alias.name}"

    def visit_FunctionDef(self, node: ast.FunctionDef):
        # Detect if it's a route
        is_route = False
        route_path = "unknown"
        route_method = "GET"
        
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call):
                if hasattr(decorator.func, 'attr'):
                    attr_name = decorator.func.attr
                    # Flask
                    if attr_name == 'route':
                        is_route = True
                        if decorator.args and isinstance(decorator.args[0], ast.Constant):
                            route_path = str(decorator.args[0].value)
                        for kw in decorator.keywords:
                            if kw.arg == 'methods' and isinstance(kw.value, ast.List):
                                if kw.value.elts and isinstance(kw.value.elts[0], ast.Constant):
                                    route_method = str(kw.value.elts[0].value)
                    # FastAPI
                    elif attr_name in ['get', 'post', 'put', 'delete', 'patch', 'options', 'head']:
                        is_route = True
                        route_method = attr_name.upper()
                        if decorator.args and isinstance(decorator.args[0], ast.Constant):
                            route_path = str(decorator.args[0].value)

        if is_route:
            self.current_trace = TraceNode(route_method, route_path, node.name, self.filename)
            self.traces.append(self.current_trace)
            # Visit body of the route handler to find calls
            for stmt in node.body:
                self.visit(stmt)
            self.current_trace = None
        else:
            self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        if self.current_trace:
            call_name = None
            if isinstance(node.func, ast.Name):
                call_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name):
                    # e.g., UserService.get_user -> UserService
                    call_name = node.func.value.id
                else:
                    call_name = node.func.attr
            
            if call_name:
                # Check if this call is likely a Service or Model
                # We can check its name or if it's imported
                lower_name = call_name.lower()
                if 'service' in lower_name or 'model' in lower_name or 'repository' in lower_name or call_name in self.imports:
                    # Resolve to module if imported, else just use the name
                    resolved = call_name
                    self.current_trace.calls.add(resolved)
                    
        self.generic_visit(node)

def parse_project_traceability(root_path: str, max_depth: Optional[int] = 3) -> List[TraceNode]:
    all_traces = []
    root = Path(root_path)
    
    for root_dir, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS]
        try:
            current_depth = len(Path(root_dir).relative_to(root).parts)
        except ValueError:
            current_depth = 0
            
        if max_depth is not None and current_depth > max_depth:
            continue
            
        for file in files:
            if file.endswith(".py"):
                file_path = Path(root_dir) / file
                display_name = str(file_path.relative_to(root)).replace("\\", "/")
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    
                    scanner = TraceabilityScanner(display_name, content)
                    scanner.visit(scanner.tree)
                    all_traces.extend(scanner.traces)
                except Exception:
                    continue
                    
    return all_traces

def generate_mermaid_traceability(traces: List[TraceNode]) -> str:
    if not traces:
        return ""
        
    diagram = ["graph LR"]
    
    # Track nodes to avoid duplicates or syntactical errors
    # Mermaid nodes can be: NodeID["Label"]
    node_id_counter = 1
    node_map = {}
    
    def get_node_id(label: str) -> str:
        nonlocal node_id_counter
        if label not in node_map:
            node_id = f"N{node_id_counter}"
            node_id_counter += 1
            node_map[label] = node_id
            # Clean label for display
            clean_label = " ".join(label.split()).replace('"', "'")
            diagram.append(f"    {node_id}[\"{clean_label}\"]")
        return node_map[label]

    for trace in traces:
        route_label = f"[{trace.route_method}] {trace.route_path}"
        route_id = get_node_id(route_label)
        
        handler_label = f"{trace.handler_file}::{trace.handler_name}"
        handler_id = get_node_id(handler_label)
        
        # Route -> Handler
        diagram.append(f"    {route_id} --> {handler_id}")
        
        for call in trace.calls:
            call_id = get_node_id(call)
            # Handler -> Service/Model
            diagram.append(f"    {handler_id} --> {call_id}")
            
    return "\n".join(diagram)


# ═══════════════════════════════════════════════════════════════════════════════
# FUTURE FUNCTIONS — Cimientos para features planificadas
# ═══════════════════════════════════════════════════════════════════════════════

def generate_impact_aware_traceability(root_path: str, max_depth: Optional[int] = 3) -> list:
    """[STUB] Genera trazabilidad ruta→servicio→modelo con riesgo de impacto por nodo.
    
    Diseño futuro:
    1. Obtener traces via parse_project_traceability().
    2. Obtener usage_map via DependencyTracker.scan_dependencies().
    3. Para cada TraceNode.calls, agregar: {call_name, risk: CORE|SHARED|PERIPHERAL}.
    4. Retornar traces enriquecidos con metadatos de riesgo.
    """
    pass


def enrich_traces_with_er(traces: list, entities: list) -> list:
    """[STUB] Cruza TraceNode.calls con entidades ER para mostrar columnas expuestas.
    
    Diseño futuro:
    1. Para cada trace.calls que coincida con un nombre de EREntity,
       agregar: {entity_name, columns: [(name, type)], relationships: [...]}.
    2. Permite generar diagramas de trazabilidad que muestran:
       Route → Handler → Service → Model.columns (con campos sensibles marcados).
    """
    pass
