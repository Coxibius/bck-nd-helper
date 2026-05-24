import os
import sys
import traceback
from typing import Optional
from mcp.server.fastmcp import FastMCP

# Ensure the package modules are in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from bck_nd_hlpr.scanner import ProjectScanner
from bck_nd_hlpr.router import Router
from bck_nd_hlpr.narrator import Narrator
from bck_nd_hlpr.er_parser import parse_project_for_er, generate_mermaid_er
from bck_nd_hlpr.route_parser import parse_project_routes, generate_mermaid_sequence
from bck_nd_hlpr.infra_parser import parse_infra, parse_docker_compose, generate_mermaid_infra
from bck_nd_hlpr.todo_hunter import scan_for_todos, get_todos_table_string
from bck_nd_hlpr.security_auditor import scan_security_risks, get_security_report_string
from bck_nd_hlpr.dependency_tracker import analyze_impact, get_impact_report_string
from bck_nd_hlpr.doc_generator import DocGenerator

mcp = FastMCP("Backend Helper MCP Server")

@mcp.tool()
def scan_project(path: str = ".", depth: int = 3, format: str = "ascii") -> str:
    """Scan a project's architecture and return detected framework and structural diagram.

    Args:
        path: Path to the project directory (default: ".").
        depth: Traversal depth for scanning files (default: 3).
        format: Output format ('ascii' or 'mermaid', default: 'ascii').
    """
    try:
        scanner = ProjectScanner()
        arch_info = scanner.detect_architecture(path)
        
        result = []
        result.append(f"🔍 Architectural Scan of: {os.path.abspath(path)}")
        if arch_info.get('framework') != 'Unknown':
            result.append(f"💻 Framework: {arch_info['framework']}")
        if arch_info.get('architecture'):
            result.append(f"🏭 Architecture Pattern: {arch_info['architecture']}")
        if arch_info.get('features'):
            result.append(f"✨ Features: {', '.join(arch_info['features'])}")
        if arch_info.get('summary'):
            result.append(f"📝 Summary: {arch_info['summary']}")
            
        flow_string = scanner.scan(path, max_depth=depth)
        if not flow_string:
            result.append(f"\n⚠️ No source files found under depth {depth}.")
            return "\n".join(result)
            
        router = Router()
        if format.lower() == 'mermaid':
            mermaid_code = router.to_mermaid(flow_string)
            result.append("\n🧜 Mermaid Diagram:")
            result.append("```mermaid")
            result.append(mermaid_code)
            result.append("```")
        else:
            ascii_diagram = router.render_ascii(flow_string)
            result.append("\n📊 Architecture Diagram (ASCII):")
            result.append(ascii_diagram)
            
        return "\n".join(result)
    except Exception as e:
        return f"❌ Error scanning project: {str(e)}\n{traceback.format_exc()}"

@mcp.tool()
def get_uml_diagram(path: str = ".", depth: int = 3) -> str:
    """Generate a Mermaid.js UML class diagram for the project's codebase.

    Args:
        path: Path to the project directory (default: ".").
        depth: Search depth for parsing classes (default: 3).
    """
    try:
        scanner = ProjectScanner()
        arch_info = scanner.detect_architecture(path)
        
        if arch_info.get('framework') == '.NET Core / C#':
            from bck_nd_hlpr.csharp_parser import parse_project_for_csharp_uml
            from bck_nd_hlpr.uml_parser import generate_mermaid_class_diagram
            classes = parse_project_for_csharp_uml(path, max_depth=depth)
            uml_code = generate_mermaid_class_diagram(classes)
        else:
            uml_code = scanner.scan_uml(path, max_depth=depth)
            
        if not uml_code:
            return "⚠️ No classes detected to generate a UML diagram."
            
        return f"```mermaid\n{uml_code}\n```"
    except Exception as e:
        return f"❌ Error generating UML diagram: {str(e)}\n{traceback.format_exc()}"

@mcp.tool()
def get_er_diagram(path: str = ".", depth: int = 3) -> str:
    """Generate a Mermaid.js Entity-Relationship (ER) diagram for project database models.

    Args:
        path: Path to the project directory (default: ".").
        depth: Traversal depth for locating database model definitions (default: 3).
    """
    try:
        scanner = ProjectScanner()
        arch_info = scanner.detect_architecture(path)
        
        if arch_info.get('framework') == '.NET Core / C#':
            from bck_nd_hlpr.csharp_parser import parse_project_for_csharp_er
            entities = parse_project_for_csharp_er(path, max_depth=depth)
        else:
            entities = parse_project_for_er(path, max_depth=depth)
            
        er_code = generate_mermaid_er(entities)
        if not er_code or len(entities) == 0:
            return "⚠️ No database models/entities detected for ER diagram."
            
        return f"```mermaid\n{er_code}\n```"
    except Exception as e:
        return f"❌ Error generating ER diagram: {str(e)}\n{traceback.format_exc()}"

@mcp.tool()
def get_routes_diagram(path: str = ".", depth: int = 3) -> str:
    """Generate a Mermaid.js Sequence diagram showing Flask/FastAPI routes mapping.

    Args:
        path: Path to the project directory (default: ".").
        depth: Traversal depth for parsing routes (default: 3).
    """
    try:
        detected_routes = parse_project_routes(path, max_depth=depth)
        seq_code = generate_mermaid_sequence(detected_routes)
        if not seq_code:
            return "⚠️ No API routes detected to generate a route map."
            
        return f"```mermaid\n{seq_code}\n```"
    except Exception as e:
        return f"❌ Error generating routes map: {str(e)}\n{traceback.format_exc()}"

@mcp.tool()
def get_infra_diagram(path: str = ".") -> str:
    """Parse docker-compose.yml files and return a Mermaid.js infrastructure layout diagram.

    Args:
        path: Path to the project directory containing docker-compose.yml (default: ".").
    """
    try:
        compose_file = parse_infra(path)
        if not compose_file:
            return "⚠️ No docker-compose.yml file detected in the project."
            
        services = parse_docker_compose(compose_file)
        if not services:
            return "⚠️ No services found in docker-compose.yml."
            
        infra_code = generate_mermaid_infra(services)
        return f"```mermaid\n{infra_code}\n```"
    except Exception as e:
        return f"❌ Error generating infrastructure diagram: {str(e)}\n{traceback.format_exc()}"

@mcp.tool()
def scan_todos(path: str = ".", depth: int = 3) -> str:
    """Scan the project for technical debt comments (TODO, FIXME, HACK, XXX, BUG) and return a debt table.

    Args:
        path: Path to the project directory to scan (default: ".").
        depth: Search depth for scanning comments in files (default: 3).
    """
    try:
        todos = scan_for_todos(path, max_depth=depth)
        if not todos:
            return "✨ No technical debt comments (TODO/FIXME/HACK/etc.) were found in the codebase."
            
        table_str = get_todos_table_string(todos, plain=True)
        return table_str
    except Exception as e:
        return f"❌ Error scanning technical debt: {str(e)}\n{traceback.format_exc()}"

@mcp.tool()
def audit_security(path: str = ".", depth: int = 3) -> str:
    """Audit the project for security risks such as hardcoded API keys, private keys, databases and secrets.

    Args:
        path: Path to the project directory to scan (default: ".").
        depth: Traversal depth for locating secrets (default: 3).
    """
    try:
        risks = scan_security_risks(path, max_depth=depth)
        report_str = get_security_report_string(risks, plain=True)
        return report_str
    except Exception as e:
        return f"❌ Error executing security audit: {str(e)}\n{traceback.format_exc()}"

@mcp.tool()
def analyze_impact(path: str = ".") -> str:
    """Analyze imports across files and return a heatmap report highlighting high-impact core modules.

    Args:
        path: Path to the project directory to analyze (default: ".").
    """
    try:
        usage_map = analyze_impact(path)
        report_str = get_impact_report_string(usage_map, plain=True)
        return report_str
    except Exception as e:
        return f"❌ Error analyzing dependency impact: {str(e)}\n{traceback.format_exc()}"

@mcp.tool()
def generate_html_docs(path: str = ".", output: str = "docs") -> str:
    """Generate a static self-contained HTML documentation portal with live Mermaid diagrams.

    Args:
        path: Path to the project directory to analyze (default: ".").
        output: Destination directory where documentation index.html will be created (default: "docs").
    """
    try:
        generator = DocGenerator()
        out_file = generator.generate(path, output)
        return f"💾 Static HTML documentation portal generated successfully at:\n{os.path.abspath(out_file)}"
    except Exception as e:
        return f"❌ Error generating documentation portal: {str(e)}\n{traceback.format_exc()}"

@mcp.tool()
def render_flow_diagram(layout: str) -> str:
    """Translate a manual flow string (e.g. 'Client -> Gateway -> Service') into a beautiful ASCII diagram.

    Args:
        layout: Flow definition string layout.
    """
    try:
        router = Router()
        # capture the output since router.process prints directly
        import io
        from contextlib import redirect_stdout
        
        f = io.StringIO()
        with redirect_stdout(f):
            router.process(layout)
        return f.getvalue()
    except Exception as e:
        return f"❌ Error rendering manual flow: {str(e)}\n{traceback.format_exc()}"

@mcp.tool()
def explain_architecture_with_ai(path: str = ".", depth: int = 3, style: str = "pro", provider: Optional[str] = None) -> str:
    """Assemble all project contexts and query the active AI provider for a comprehensive architectural audit report.

    Args:
        path: Path to the project directory to scan (default: ".").
        depth: Traversal depth for context gathering (default: 3).
        style: Review personality style ('pro', 'hacker', 'ramsay', 'eli5', 'jarvis', 'soviet', etc.) (default: 'pro').
        provider: Force a specific AI provider ('openai', 'anthropic', 'gemini', 'ollama', 'webhook').
    """
    try:
        scanner = ProjectScanner()
        arch_info = scanner.detect_architecture(path)
        flow_string = scanner.scan(path, max_depth=depth)
        
        if not flow_string:
            return f"❌ Could not gather codebase context. Folder is empty or contains no recognized files."
            
        # Build context
        arch_context = f"\n\n--- DETECTED ARCHITECTURE ---\n"
        arch_context += f"Framework: {arch_info.get('framework', 'Unknown')}\n"
        arch_context += f"Type: {arch_info.get('architecture', 'Unknown')}\n"
        arch_context += f"Features: {', '.join(arch_info.get('features', []))}\n"
        
        extra_diagrams = "\n\n--- ADVANCED MERMAID DIAGRAMS ---\n"
        
        # Infra
        compose_file = parse_infra(path)
        if compose_file:
            services = parse_docker_compose(compose_file)
            if services:
                extra_diagrams += "Infrastructure (docker-compose):\n```mermaid\n" + generate_mermaid_infra(services) + "\n```\n"

        # Routes
        detected_routes = parse_project_routes(path, max_depth=depth)
        if detected_routes:
            extra_diagrams += "API Routes:\n```mermaid\n" + generate_mermaid_sequence(detected_routes) + "\n```\n"

        # ER/UML
        if arch_info.get('framework') == '.NET Core / C#':
            from bck_nd_hlpr.csharp_parser import parse_project_for_csharp_er, parse_project_for_csharp_uml
            
            entities = parse_project_for_csharp_er(path, max_depth=depth)
            if entities:
                extra_diagrams += "Entity-Relationship (EF Models):\n```mermaid\n" + generate_mermaid_er(entities) + "\n```\n"
            
            classes = parse_project_for_csharp_uml(path, max_depth=depth)
            if classes:
                from bck_nd_hlpr.uml_parser import generate_mermaid_class_diagram
                extra_diagrams += "UML Class Diagram:\n```mermaid\n" + generate_mermaid_class_diagram(classes) + "\n```\n"
        else:
            entities = parse_project_for_er(path, max_depth=depth)
            if entities:
                extra_diagrams += "Entity-Relationship:\n```mermaid\n" + generate_mermaid_er(entities) + "\n```\n"
                
            uml_code = scanner.scan_uml(path, max_depth=depth)
            if uml_code and "note " not in uml_code.lower():
                extra_diagrams += "UML Class Diagram:\n```mermaid\n" + uml_code + "\n```\n"

        docs = scanner.get_docs_content(path)
        if docs:
            full_context = flow_string + arch_context + extra_diagrams + "\n\n--- PROJECT DOCUMENTATION ---\n" + docs
        else:
            full_context = flow_string + arch_context + extra_diagrams
            
        narrator = Narrator(force_provider=provider)
        ai_response = narrator.explain(full_context, use_ai=True, style=style)
        return ai_response
    except Exception as e:
        return f"❌ Error generating AI analysis: {str(e)}\n{traceback.format_exc()}"

def main():
    mcp.run(transport="stdio")

if __name__ == "__main__":
    main()
