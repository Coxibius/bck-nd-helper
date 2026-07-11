import ast
import os
import re
from pathlib import Path
from typing import List, Optional, Tuple, Dict
from bck_nd_hlpr.constants import GLOBAL_IGNORE_DIRS

class RouteInfo:
    def __init__(self, method: str, path: str, filename: str, lineno: int):
        self.method = method.upper()
        self.path = path
        self.filename = filename 
        self.lineno = lineno

class RouteExtractor(ast.NodeVisitor):
    def __init__(self, filename: str):
        self.routes: List[RouteInfo] = []
        self.filename = filename

    def visit_FunctionDef(self, node: ast.FunctionDef):
        for decorator in node.decorator_list:
            # Case Call (e.g. @app.route(...))
            if isinstance(decorator, ast.Call):
                if hasattr(decorator.func, 'attr'):
                    attr_name = decorator.func.attr
                    
                    # FLASK: @app.route('/path', methods=['POST'])
                    if attr_name == 'route':
                        path = "unknown"
                        methods = ["GET"] # Default Flask
                        
                        # Extract path (Arg 0)
                        if decorator.args and isinstance(decorator.args[0], ast.Constant):
                            path = str(decorator.args[0].value)
                        elif decorator.args and isinstance(decorator.args[0], ast.Str): # Python < 3.8
                             path = decorator.args[0].s
                        
                        # Extract methods (Keyword arg)
                        for kw in decorator.keywords:
                            if kw.arg == 'methods' and isinstance(kw.value, ast.List):
                                methods = []
                                for elt in kw.value.elts:
                                    if isinstance(elt, ast.Constant):
                                        methods.append(str(elt.value))
                                    elif isinstance(elt, ast.Str): # Python < 3.8
                                        methods.append(elt.s)
                        
                        for m in methods:
                            self.routes.append(RouteInfo(m, path, self.filename, node.lineno))

                    # FASTAPI: @app.get('/path')
                    elif attr_name in ['get', 'post', 'put', 'delete', 'patch', 'options', 'head']:
                        path = "unknown"
                        if decorator.args and isinstance(decorator.args[0], ast.Constant):
                            path = str(decorator.args[0].value)
                        elif decorator.args and isinstance(decorator.args[0], ast.Str): # Python < 3.8
                            path = decorator.args[0].s
                        
                        self.routes.append(RouteInfo(attr_name, path, self.filename, node.lineno))
        
        self.generic_visit(node)

class JSRouteExtractor:
    """Regex-based parser for Node.js (Express, NestJS)"""
    def __init__(self, filename: str):
        self.filename = filename
        self.routes: List[RouteInfo] = []

    def parse(self, content: str):
        self._parse_express(content)
        self._parse_nestjs(content)
        return self.routes

    def _parse_express(self, content: str):
        # Express: app.get('/path', ...) or router.post('/path', ...)
        # Regex: (app|router)\.(get|post|put|delete|patch)\s*\(\s*['"]([^'"]+)['"]
        pattern = r'(app|router)\.(get|post|put|delete|patch)\s*\(\s*[\'"]([^\'"]+)[\'"]'
        
        for i, line in enumerate(content.splitlines(), 1):
            matches = re.finditer(pattern, line)
            for match in matches:
                method = match.group(2)
                path = match.group(3)
                self.routes.append(RouteInfo(method, path, self.filename, i))

    def _parse_nestjs(self, content: str):
        # NestJS: @Get('/path') or @Controller('/base')
        # Simple approach: Find @Get, @Post etc.
        # Problem: Controller prefix. We will ignore prefix for now to keep it simple and stateless.
        
        # Regex: @(Get|Post|Put|Delete|Patch)\s*\(\s*['"]?([^'"]*)['"]?\s*\)
        pattern = r'@(Get|Post|Put|Delete|Patch|Options|Head)\s*\(\s*[\'"]?([^\'"]*)[\'"]?\s*\)'
        
        for i, line in enumerate(content.splitlines(), 1):
            matches = re.finditer(pattern, line, re.IGNORECASE)
            for match in matches:
                method = match.group(1)
                path = match.group(2)
                if not path: path = "/" # @Get() means root relative
                self.routes.append(RouteInfo(method, path, self.filename, i))


def parse_nextjs_routes(root_path: Path) -> List[RouteInfo]:
    routes = []
    
    # 1. App Router (app or src/app)
    app_dirs = [root_path / 'app', root_path / 'src' / 'app']
    for app_dir in app_dirs:
        if app_dir.exists() and app_dir.is_dir():
            for root_dir, dirs, files in os.walk(app_dir):
                for file in files:
                    file_path = Path(root_dir) / file
                    if file in ('page.tsx', 'page.jsx', 'page.js', 'page.ts'):
                        rel = Path(root_dir).relative_to(app_dir)
                        parts = []
                        for part in rel.parts:
                            if part.startswith('(') and part.endswith(')'):
                                continue
                            parts.append(part)
                        
                        route_path = "/" + "/".join(parts)
                        route_path = route_path.replace("//", "/")
                        routes.append(RouteInfo("GET", route_path, f"app/{rel.as_posix()}/{file}", 1))
                        
                    elif file in ('route.ts', 'route.js'):
                        rel = Path(root_dir).relative_to(app_dir)
                        parts = []
                        for part in rel.parts:
                            if part.startswith('(') and part.endswith(')'):
                                continue
                            parts.append(part)
                        route_path = "/" + "/".join(parts)
                        route_path = route_path.replace("//", "/")
                        
                        methods = []
                        try:
                            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                                content = f.read()
                            matches = re.finditer(r'export\s+(async\s+)?function\s+(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\b', content)
                            for m in matches:
                                methods.append(m.group(2))
                        except Exception:
                            pass
                        
                        if not methods:
                            methods = ["GET"]
                            
                        for method in methods:
                            routes.append(RouteInfo(method, route_path, f"app/{rel.as_posix()}/{file}", 1))
                            
    # 2. Pages Router (pages or src/pages)
    pages_dirs = [root_path / 'pages', root_path / 'src' / 'pages']
    for pages_dir in pages_dirs:
        if pages_dir.exists() and pages_dir.is_dir():
            for root_dir, dirs, files in os.walk(pages_dir):
                for file in files:
                    if file.startswith('_') or not file.endswith(('.js', '.jsx', '.ts', '.tsx')):
                        continue
                    
                    file_path = Path(root_dir) / file
                    rel = file_path.relative_to(pages_dir)
                    parts = list(rel.parent.parts)
                    stem = rel.stem
                    if stem != 'index':
                        parts.append(stem)
                        
                    route_path = "/" + "/".join(parts)
                    route_path = route_path.replace("//", "/")
                    
                    if 'api' in parts:
                        routes.append(RouteInfo("GET", route_path, f"pages/{rel.as_posix()}", 1))
                        routes.append(RouteInfo("POST", route_path, f"pages/{rel.as_posix()}", 1))
                    else:
                        routes.append(RouteInfo("GET", route_path, f"pages/{rel.as_posix()}", 1))
                        
    return routes

def parse_project_routes(root_path: str, max_depth: int = 3) -> List[RouteInfo]:
    all_routes = []
    root = Path(root_path)
    
    # Next.js Routing
    nextjs_routes = parse_nextjs_routes(root)
    if nextjs_routes:
        all_routes.extend(nextjs_routes)
    
    for root_dir, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS]
        
        try:
            current_depth = len(Path(root_dir).relative_to(root).parts)
        except ValueError:
            current_depth = 0
            
        if current_depth > max_depth:
            continue
            
        for file in files:
            file_path = Path(root_dir) / file
            display_name = str(file_path.relative_to(root)).replace("\\", "/")
            
            # Python AST Parsing
            if file.endswith(".py"):
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    
                    tree = ast.parse(content)
                    extractor = RouteExtractor(display_name)
                    extractor.visit(tree)
                    all_routes.extend(extractor.routes)
                except Exception:
                    continue
            
            # JS/TS Regex Parsing (New!)
            elif file.endswith((".js", ".ts")):
                 try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    
                    extractor = JSRouteExtractor(display_name)
                    extractor.parse(content)
                    all_routes.extend(extractor.routes)
                 except Exception:
                    continue

    return all_routes

def generate_mermaid_sequence(all_routes: List[RouteInfo]) -> str:
    if not all_routes:
        return ""
        
    diagram = ["sequenceDiagram", "    participant Client"]
    
    # Sort files to ensure consistent order
    files = sorted(list(set(r.filename for r in all_routes)))
    
    alias_map = {}
    for i, f in enumerate(files):
        alias = f"P{i}"
        alias_map[f] = alias
        diagram.append(f'    participant {alias} as "{f}"')
        
    diagram.append("")
    
    for route in all_routes:
        alias = alias_map[route.filename]
        # Clean path and method to avoid breaking the diagram description
        clean_path = " ".join(route.path.split()).replace('"', "'")
        clean_method = " ".join(route.method.split()).replace('"', "'")
        diagram.append(f"    Client->>+{alias}: [{clean_method}] {clean_path}")
        diagram.append(f"    {alias}-->>-Client: Response")
        
    return "\n".join(diagram)


# ═══════════════════════════════════════════════════════════════════════════════
# FUTURE FUNCTIONS — Cimientos para features planificadas
# ═══════════════════════════════════════════════════════════════════════════════

def generate_api_contract_map(root_path: str, max_depth: int = 3) -> list:
    from bck_nd_hlpr.er_parser import get_entities_for_contract_map
    
    routes = parse_project_routes(root_path, max_depth)
    entities = get_entities_for_contract_map(root_path, max_depth)
    
    contract_map = []
    
    for route in routes:
        best_match_name = None
        columns = {}
        
        route_path_lower = route.path.lower()
        file_lower = route.filename.lower()
        handler_name = getattr(route, "handler_name", "unknown")
        handler_lower = handler_name.lower()
        
        for entity_name, entity_data in entities.items():
            ent_lower = entity_name.lower()
            
            path_match = False
            for part in route_path_lower.split('/'):
                if ent_lower == part or ent_lower + "s" == part or ent_lower + "es" == part or (ent_lower.endswith("y") and ent_lower[:-1] + "ies" == part):
                    path_match = True
                    break
            
            handler_match = False
            if handler_name != "unknown" and ent_lower in handler_lower:
                handler_match = True
                
            file_match = False
            # Check if file has the entity name (e.g. user.controller.ts)
            name_parts = file_lower.replace("\\", "/").split("/")[-1].split(".")
            if ent_lower in name_parts:
                file_match = True
                
            if path_match or handler_match or file_match:
                best_match_name = entity_name
                columns = entity_data["columns"]
                break

        contract_map.append({
            "route": f"{route.method} {route.path}",
            "handler": handler_name,
            "file": route.filename,
            "matched_model": best_match_name,
            "columns": columns
        })
        
    return contract_map


def get_routes_affected_by_file(root_path: str, changed_file: str, max_depth: int = 3) -> dict:
    from bck_nd_hlpr.dependency_tracker import DependencyTracker
    tracker = DependencyTracker(root_path)
    impact_data = tracker.calculate_impact_radius(changed_file)
    
    affected_files = impact_data["affected_files"]
    if not affected_files:
        return {"changed_file": changed_file, "affected_files": [], "affected_routes": []}
        
    all_routes = parse_project_routes(root_path, max_depth)
    
    affected_routes = []
    try:
        rel_changed = str(Path(changed_file).resolve().relative_to(Path(root_path).resolve())).replace("\\", "/")
    except ValueError:
        rel_changed = changed_file
        
    for route in all_routes:
        if route.filename in affected_files or route.filename == rel_changed:
            affected_routes.append({
                "method": route.method,
                "path": route.path,
                "file": route.filename
            })
            
    return {
        "changed_file": changed_file,
        "affected_files": affected_files,
        "affected_routes": affected_routes
    }
