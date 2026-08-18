import os
import sys
import traceback
from typing import Optional
from functools import wraps
from mcp.server.fastmcp import FastMCP

# Reconfigure stdout/stderr on Windows to support UTF-8 characters
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

def redirect_stdout_to_stderr(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        original_stdout = sys.stdout
        sys.stdout = sys.stderr
        try:
            return func(*args, **kwargs)
        finally:
            sys.stdout = original_stdout
    return wrapper

# Ensure the package modules are in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from bck_nd_hlpr.core.scanner import ProjectScanner
from bck_nd_hlpr.core.router import Router
from bck_nd_hlpr.core.narrator import Narrator
from bck_nd_hlpr.core.er_parser import parse_project_for_er, generate_mermaid_er
from bck_nd_hlpr.core.route_parser import parse_project_routes, generate_mermaid_sequence
from bck_nd_hlpr.core.infra_parser import parse_infra, parse_docker_compose, generate_mermaid_infra
from bck_nd_hlpr.core.todo_hunter import scan_for_todos
from bck_nd_hlpr.core.security_auditor import scan_security_risks
from bck_nd_hlpr.core.doc_generator import DocGenerator
from bck_nd_hlpr.core.ci_generator import generate_ci_workflow
from bck_nd_hlpr.core.traceability import parse_project_traceability, generate_mermaid_traceability
from bck_nd_hlpr.core.tree_generator import generate_project_tree
from bck_nd_hlpr.cli.formatters import (
    get_todos_table_string,
    get_security_report_string,
    get_impact_report_string,
)

mcp = FastMCP(
    "Backend Helper MCP Server",
    instructions="""
You have access to a suite of backend architecture analysis tools.
Use them proactively when the user asks about their project structure, database schema,
API routes, technical debt, security vulnerabilities, or wants to understand any codebase.

ROUTING GUIDE — call the right tool for the right question:
- "analyze / scan / understand this project"   → scan_project
- "what classes / object model / UML?"         → get_uml_diagram
- "database schema / tables / entities / ER?"  → get_er_diagram
- "API endpoints / routes / REST surface?"      → get_routes_diagram
- "Docker / containers / services / infra?"     → get_infra_diagram
- "TODOs / FIXME / tech debt / cleanup?"        → scan_todos
- "security / secrets / hardcoded keys?"        → audit_security
- "which files are critical / blast radius?"    → analyze_impact
- "share context with another AI / export?"     → generate_ai_context
- "generate HTML docs / documentation site?"    → generate_html_docs
- "draw a custom diagram from my description?"  → render_flow_diagram
- "AI review / architectural audit?"            → explain_architecture_with_ai
- "trace endpoints / route to database / data flow?" → get_traceability_diagram
- "project structure / file tree / directory layout?" → get_project_tree
- "requirements / user stories / acceptance criteria / business rules?" → get_requirements_summary
- "setup CI / GitHub Actions / auto-documentation workflow?" → init_ci

Default path is always "." (current directory) unless the user specifies a different path.
"""
)


@mcp.tool()
@redirect_stdout_to_stderr
def scan_project(path: str = ".", depth: int = 3) -> str:
    """Perform a full architectural scan of a software project directory.

    Use this tool when:
    - The user asks to "analyze", "scan", "understand", or "reverse-engineer" a project.
    - The user wants a high-level overview of an unknown codebase.
    - You need to gather comprehensive context before answering questions about the project.
    - The user asks "what does this project do?" or "what's the architecture here?".

    This tool runs ALL sub-analyzers in one call and returns:
    - Detected framework (Flask, FastAPI, Django, Next.js, Express, Spring Boot, Laravel, .NET, etc.)
    - Architecture pattern (MVC, Microservices, Layered, REST API, etc.)
    - Key features detected (Docker, Auth, ORM, CI/CD, etc.)
    - Infrastructure map (from docker-compose.yml) as Mermaid graph
    - API routes map as Mermaid sequenceDiagram
    - UML class diagram as Mermaid classDiagram
    - Entity-Relationship diagram as Mermaid erDiagram
    - Technical debt summary (TODO/FIXME/HACK/BUG comments)

    Do NOT use this for targeted queries. Prefer specialized tools (get_uml_diagram,
    get_er_diagram, etc.) when the user asks about one specific diagram type.

    Args:
        path: Absolute or relative path to the project root. Use "." for current directory.
              Example: "/home/user/my-api" or "C:/projects/backend".
        depth: Directory levels to scan. Default 3 covers most projects.
               Increase to 5-6 for deeply nested monorepos or multi-module Maven/Gradle projects.
    """
    try:
        scanner = ProjectScanner()
        arch_info = scanner.detect_architecture(path)

        result = []
        result.append(f"Architectural Scan of: {os.path.abspath(path)}")
        if arch_info.get('framework') != 'Unknown':
            result.append(f"Framework: {arch_info['framework']}")
        if arch_info.get('architecture'):
            result.append(f"Architecture Pattern: {arch_info['architecture']}")
        if arch_info.get('features'):
            result.append(f"Features: {', '.join(arch_info['features'])}")
        if arch_info.get('summary'):
            result.append(f"Summary: {arch_info['summary']}")

        result.append("\nPROJECT ARCHITECTURE (COMPLETE):")

        # 0. PROJECT TREE
        tree_output = generate_project_tree(path, depth=depth)
        if tree_output:
            result.append("\n[TREE] PROJECT STRUCTURE:")
            result.append(tree_output)
        else:
            result.append("\n[TREE] PROJECT STRUCTURE:\nCould not generate project tree.")

        # 1. INFRA
        compose_file = parse_infra(path)
        if compose_file:
            services = parse_docker_compose(compose_file)
            if services:
                result.append("\n[INFRA] INFRASTRUCTURE MAP:")
                result.append(f"```mermaid\n{generate_mermaid_infra(services)}\n```")
            else:
                result.append("\n[INFRA] INFRASTRUCTURE MAP:\nNo services found in docker-compose.")
        else:
            result.append("\n[INFRA] INFRASTRUCTURE MAP:\ndocker-compose.yml not detected.")

        # 2. API ROUTES
        detected_routes = parse_project_routes(path, max_depth=depth)
        if detected_routes:
            seq_code = generate_mermaid_sequence(detected_routes)
            if seq_code:
                result.append("\n[API] ROUTES MAP:")
                result.append(f"```mermaid\n{seq_code}\n```")
            else:
                result.append("\n[API] ROUTES MAP:\nCould not render routes sequence.")
        else:
            result.append("\n[API] ROUTES MAP:\nNo API routes detected (Flask/FastAPI/Express).")

        # 3. UML CLASS DIAGRAM
        uml_code = scanner.scan_uml(path, max_depth=depth)
        if uml_code and "class Empty" not in uml_code and "note " not in uml_code.lower():
            result.append("\n[UML] CLASS DIAGRAM:")
            result.append(f"```mermaid\n{uml_code}\n```")
        else:
            result.append("\n[UML] CLASS DIAGRAM:\nNo classes detected for UML.")

        # 4. ER DIAGRAM
        entities = parse_project_for_er(path, max_depth=depth)
        if entities:
            er_code = generate_mermaid_er(entities)
            if er_code:
                result.append("\n[ER] ENTITY-RELATIONSHIP:")
                result.append(f"```mermaid\n{er_code}\n```")
            else:
                result.append("\n[ER] ENTITY-RELATIONSHIP:\nCould not render ER diagram.")
        else:
            result.append("\n[ER] ENTITY-RELATIONSHIP:\nNo database models/entities detected.")

        # 5. TECHNICAL DEBT
        todos = scan_for_todos(path, max_depth=depth)
        if todos:
            result.append("\n[TODO] TECHNICAL DEBT:")
            result.append(get_todos_table_string(todos, plain=True))
        else:
            result.append("\n[TODO] TECHNICAL DEBT:\nNo technical debt comments found.")

        # 6. SECURITY RISK AUDIT
        try:
            risks = scan_security_risks(path, max_depth=depth)
            if risks:
                result.append("\n[SECURITY] SECURITY RISK AUDIT:")
                result.append(get_security_report_string(risks, plain=True))
            else:
                result.append("\n[SECURITY] SECURITY RISK AUDIT:\nNo security risks detected.")
        except Exception as e:
            result.append(f"\n[SECURITY] SECURITY RISK AUDIT:\nError scanning security: {str(e)}")

        # 7. DEPENDENCY IMPACT HEATMAP
        try:
            from bck_nd_hlpr.core.dependency_tracker import analyze_impact as _analyze_impact
            usage_map = _analyze_impact(path)
            if usage_map:
                result.append("\n[IMPACT] DEPENDENCY HEATMAP:")
                result.append(get_impact_report_string(usage_map, plain=True))
        except Exception as e:
            result.append(f"\n[IMPACT] DEPENDENCY HEATMAP:\nError running heatmap: {str(e)}")

        # 8. ROUTE-TO-DB TRACEABILITY
        try:
            traces = parse_project_traceability(path, max_depth=depth)
            if traces:
                trace_code = generate_mermaid_traceability(traces)
                if trace_code:
                    result.append("\n[TRACE] ROUTE-TO-DB TRACEABILITY:")
                    result.append(f"```mermaid\n{trace_code}\n```")
                else:
                    result.append("\n[TRACE] ROUTE-TO-DB TRACEABILITY:\nCould not render traceability sequence.")
            else:
                result.append("\n[TRACE] ROUTE-TO-DB TRACEABILITY:\nNo traceability traces found.")
        except Exception as e:
            result.append(f"\n[TRACE] ROUTE-TO-DB TRACEABILITY:\nError running traceability: {str(e)}")

        return "\n".join(result)
    except Exception as e:
        return f"Error scanning project: {str(e)}\n{traceback.format_exc()}"


@mcp.tool()
@redirect_stdout_to_stderr
def get_project_tree(path: str = ".", depth: int = 4) -> str:
    """Generate a clean ASCII directory tree of the project, filtering out noise directories.

    Use this tool when:
    - The user asks about "project structure", "file tree", "directory layout", or "folder structure".
    - The user asks "what files are in this project?" or "show me the project tree".
    - The user wants to understand the project layout before diving into code.
    - The user wants to share the project structure with another AI or paste it somewhere.

    Output: A clean ASCII tree using Unicode box-drawing characters (├── └── │),
    automatically filtering out noise directories like node_modules, venv, __pycache__,
    .git, dist, build, etc.

    This is a READ-ONLY tool — it does not create or modify any files.

    Args:
        path: Path to the project root. Default "." is the current directory.
        depth: Directory depth to display. Default 4 covers most project layouts.
               Increase to 6-8 for deeply nested monorepos.
    """
    try:
        tree_output = generate_project_tree(path, depth=depth)
        if not tree_output:
            return "Could not generate project tree. The path may not exist or may be empty."
        return tree_output
    except Exception as e:
        return f"Error generating project tree: {str(e)}\n{traceback.format_exc()}"


@mcp.tool()
@redirect_stdout_to_stderr
def get_uml_diagram(path: str = ".", depth: int = 3) -> str:
    """Generate a Mermaid.js UML class diagram showing classes, methods, attributes, and relationships.

    Use this tool when:
    - The user asks about "classes", "object model", "class hierarchy", or "inheritance".
    - The user asks "what classes exist in this project?" or "show me the UML".
    - The user wants to understand component structure before refactoring.
    - You need to understand the code structure to answer questions about a specific class.

    Output: A ```mermaid classDiagram``` block ready to render in any Mermaid-compatible viewer.
    Supports: Python (AST), C# (.NET / Entity Framework), Java (Spring Boot / JPA),
              JavaScript/TypeScript (Next.js / Express), PHP (Laravel).

    Do NOT use this to find database tables — use get_er_diagram for that.
    Do NOT use this to find API endpoints — use get_routes_diagram for that.

    Args:
        path: Path to the project root. Default "." is the current directory.
        depth: Directory scan depth. Use 4-5 for large projects with nested packages.
    """
    try:
        scanner = ProjectScanner()
        uml_code = scanner.scan_uml(path, max_depth=depth)

        if not uml_code or "No classes found" in uml_code:
            return "No classes detected. The project may not use OOP patterns, or try increasing depth."

        return f"```mermaid\n{uml_code}\n```"
    except Exception as e:
        return f"Error generating UML diagram: {str(e)}\n{traceback.format_exc()}"


@mcp.tool()
@redirect_stdout_to_stderr
def get_er_diagram(path: str = ".", depth: int = 3) -> str:
    """Generate a Mermaid.js Entity-Relationship (ER) diagram from database model definitions.

    Use this tool when:
    - The user asks about "database schema", "tables", "entities", or "data model".
    - The user asks "what does the database look like?" or "show me the ER diagram".
    - The user wants to understand relationships between tables before writing a query.
    - The user is planning a migration or wants to audit the data model.

    Output: A ```mermaid erDiagram``` block showing tables, columns (with PK markers),
    and foreign key relationships.

    Detects models from:
    - Python: SQLAlchemy, Django ORM
    - JavaScript/TypeScript: Prisma (schema.prisma), Drizzle ORM, Sequelize, Mongoose
    - Java: Spring Boot / JPA @Entity annotations
    - C#: Entity Framework DbContext / data annotations
    - PHP: Laravel / Eloquent migrations
    - SQL: Raw .sql migration files (CREATE TABLE statements)

    Do NOT use this to find Python/JS classes — use get_uml_diagram for that.

    Args:
        path: Path to the project root. Default "." is the current directory.
        depth: Directory depth to search for model files. Increase for nested module structures.
    """
    try:
        entities = parse_project_for_er(path, max_depth=depth)
        er_code = generate_mermaid_er(entities)

        if not er_code or len(entities) == 0:
            return "No database models or entities detected. The project may not use an ORM, or try increasing depth."

        return f"```mermaid\n{er_code}\n```"
    except Exception as e:
        return f"Error generating ER diagram: {str(e)}\n{traceback.format_exc()}"


@mcp.tool()
@redirect_stdout_to_stderr
def get_routes_diagram(path: str = ".", depth: int = 3) -> str:
    """Generate a Mermaid.js Sequence diagram mapping HTTP API routes and their handlers.

    Use this tool when:
    - The user asks about "API endpoints", "routes", "REST API", or "HTTP methods".
    - The user asks "what endpoints does this API expose?" or "show me the route map".
    - The user wants to document or audit the API surface before integration.
    - The user is writing API tests and needs to know what endpoints exist.

    Output: A ```mermaid sequenceDiagram``` block showing Client -> API interactions
    with HTTP methods (GET, POST, PUT, DELETE) and route paths.

    Supports: Flask (@app.route, Blueprint), FastAPI (@router.get/post/etc.),
              Express.js (app.get/post/router.use), NestJS (@Controller/@Get),
              Next.js (pages/api/* file routes).

    Args:
        path: Path to the project root. Default "." is the current directory.
        depth: How deep to search for route files. Increase for nested router structures.
    """
    try:
        detected_routes = parse_project_routes(path, max_depth=depth)
        seq_code = generate_mermaid_sequence(detected_routes)

        if not seq_code:
            return "No API routes detected. Supported frameworks: Flask, FastAPI, Express, NestJS, Next.js."

        return f"```mermaid\n{seq_code}\n```"
    except Exception as e:
        return f"Error generating routes diagram: {str(e)}\n{traceback.format_exc()}"


@mcp.tool()
@redirect_stdout_to_stderr
def get_infra_diagram(path: str = ".") -> str:
    """Parse docker-compose.yml and generate a Mermaid.js infrastructure topology diagram.

    Use this tool when:
    - The user asks about "Docker services", "containers", "infrastructure", or "deployment".
    - The user asks "what services does docker-compose define?" or "show me the infra".
    - The user wants to understand service dependencies before deploying or debugging.
    - The user is reviewing a microservices architecture.

    Output: A ```mermaid graph LR``` block showing all Docker services, their images,
    exposed ports, volume mounts, and inter-service dependencies.
    Database services (postgres, redis, mysql, mongo, elasticsearch) are shown as cylinders.

    Do NOT use this if the project doesn't use Docker — it will return "not detected".

    Args:
        path: Path to the project root containing docker-compose.yml. Default ".".
    """
    try:
        compose_file = parse_infra(path)
        if not compose_file:
            return "No docker-compose.yml file found. This tool only works with Docker Compose projects."

        services = parse_docker_compose(compose_file)
        if not services:
            return "docker-compose.yml found but contains no service definitions."

        return f"```mermaid\n{generate_mermaid_infra(services)}\n```"
    except Exception as e:
        return f"Error generating infrastructure diagram: {str(e)}\n{traceback.format_exc()}"


@mcp.tool()
@redirect_stdout_to_stderr
def scan_todos(path: str = ".", depth: int = 3) -> str:
    """Scan source files for technical debt comments and return a structured report.

    Use this tool when:
    - The user asks about "TODOs", "technical debt", "FIXME", "unfinished work", or "cleanup".
    - The user asks "what needs to be fixed?" or "show me what's left to do".
    - The user is planning a sprint and wants to prioritize technical debt.
    - You need to assess code quality before recommending refactors.

    Output: A plain-text table listing all found comments with:
    - File path and line number
    - Comment type (TODO / FIXME / HACK / XXX / BUG)
    - Full comment message
    - Debt level summary (Low / Medium / High)

    Scans all .py, .js, .ts, .cs, .java, .php, .go, .rs files.

    Args:
        path: Path to the project root to scan. Default ".".
        depth: Directory depth for the scan. Increase for deeply nested projects.
    """
    try:
        todos = scan_for_todos(path, max_depth=depth)
        if not todos:
            return "No technical debt comments (TODO/FIXME/HACK/XXX/BUG) found. Clean codebase!"

        return get_todos_table_string(todos, plain=True)
    except Exception as e:
        return f"Error scanning technical debt: {str(e)}\n{traceback.format_exc()}"


@mcp.tool()
@redirect_stdout_to_stderr
def audit_security(path: str = ".", depth: int = 3) -> str:
    """Scan the project for hardcoded secrets, credentials, API keys, and security anti-patterns.

    Use this tool when:
    - The user asks about "security", "secrets", "credentials", "API keys", or "vulnerabilities".
    - The user asks "is there anything sensitive hardcoded?" or "run a security audit".
    - Before pushing code to a public repository or deploying to production.
    - The user suspects a secret was accidentally committed.

    Output: A report categorized by severity:
    - CRITICAL: Private PEM keys, AWS Access Keys (AKIA...), GitHub tokens
    - HIGH: Hardcoded passwords, database connection strings with credentials
    - WARNING: Hardcoded IP addresses, suspicious variable names with secret values

    Each finding includes: file path, line number, matched pattern, and severity level.

    Args:
        path: Path to the project root to audit. Default ".".
        depth: Scan depth. Use higher values to catch secrets in nested config files.
    """
    try:
        risks = scan_security_risks(path, max_depth=depth)
        return get_security_report_string(risks, plain=True)
    except Exception as e:
        return f"Error executing security audit: {str(e)}\n{traceback.format_exc()}"


@mcp.tool()
@redirect_stdout_to_stderr
def analyze_impact(path: str = ".") -> str:
    """Analyze import dependencies and return a heatmap ranking files by their change risk/impact.

    Use this tool when:
    - The user asks "which files are most critical?" or "what will break if I change X?".
    - The user wants to know which modules are imported the most across the project.
    - Before a major refactor, to identify high-risk files that many others depend on.
    - When assessing the blast radius of a proposed code change.

    Output: A ranked list of files with their Impact Score (number of files that import them),
    labeled as HIGH / MEDIUM / LOW impact.
    - HIGH impact = "Core" module — risky to modify, touched by many files.
    - LOW impact  = "Peripheral" module — safe to refactor freely.

    Args:
        path: Path to the project root to analyze. Default ".".
    """
    try:
        from bck_nd_hlpr.core.dependency_tracker import analyze_impact as _analyze_impact
        usage_map = _analyze_impact(path)
        return get_impact_report_string(usage_map, plain=True)
    except Exception as e:
        return f"Error analyzing dependency impact: {str(e)}\n{traceback.format_exc()}"


@mcp.tool()
@redirect_stdout_to_stderr
def generate_ai_context(path: str = ".", depth: int = 4, output: str = "ai_context.txt") -> str:
    """Generate a single LLM-optimized context file with the full project structure, diagrams, and core source files.

    Use this tool when:
    - The user says "give me context for this project", "prepare a context file", or "share with another AI".
    - The user wants to copy-paste the project context into ChatGPT, Claude, or another LLM.
    - The user wants a single file that summarizes the entire codebase for AI consumption.
    - Before starting a complex task in a new codebase, to bootstrap understanding quickly.

    Output: Writes a UTF-8 .txt file to disk and returns the file path + a summary.
    The file uses XML-like tags optimized for LLM parsing:
    - <project_tree>:      Clean ASCII directory tree (ignoring venv, node_modules, .git, etc.)
    - <architecture_uml>:  UML Class Diagram in Mermaid format
    - <architecture_er>:   Entity-Relationship Diagram in Mermaid format

    The user can open the file, Select All, Copy, and paste it as context into any LLM chat.

    Do NOT use this when the user just wants to VIEW the architecture — use scan_project for that.
    This tool is for EXPORTING context to be used OUTSIDE this conversation.

    Args:
        path: Path to the project root to analyze. Default ".".
        depth: Directory scan depth. Default 4 covers most project structures.
        output: Output file path. Default "ai_context.txt" in the current directory.
    """
    try:
        from bck_nd_hlpr.core.context_dumper import ContextDumper
        dumper = ContextDumper(path=path, depth=depth)
        context = dumper.build()

        output_path = os.path.abspath(output)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(context)

        uml = dumper.get_uml_diagram()
        er = dumper.get_er_diagram()
        file_size_kb = round(os.path.getsize(output_path) / 1024, 1)

        return (
            f"AI context file successfully generated!\n\n"
            f"File: {output_path}\n"
            f"Size: {file_size_kb} KB\n"
            f"UML Diagram:  {'Generated' if uml else 'Not detected'}\n"
            f"ER Diagram:   {'Generated' if er else 'Not detected'}\n\n"
            f"The user can now open '{output}', Select All, Copy, and paste it into ChatGPT or Claude."
        )
    except Exception as e:
        return f"Error generating AI context file: {str(e)}\n{traceback.format_exc()}"


@mcp.tool()
@redirect_stdout_to_stderr
def generate_html_docs(path: str = ".", output: str = "docs") -> str:
    """Generate a self-contained static HTML documentation portal with live interactive Mermaid diagrams.

    Use this tool when:
    - The user asks to "generate documentation", "create a docs site", or "build HTML docs".
    - The user wants to publish architecture docs to GitHub Pages or an internal wiki.
    - After running bck-nd init-ci, to preview the documentation that will be auto-deployed.

    Output: Creates an index.html file in the output directory with all diagrams rendered
    interactively via MermaidJS CDN. Returns the absolute path to the generated file.
    The site is fully self-contained — just open index.html in a browser.

    Args:
        path: Path to the project root to document. Default ".".
        output: Directory where index.html will be written. Default "docs".
                Will be created if it doesn't exist.
    """
    try:
        generator = DocGenerator()
        out_file = generator.generate(path, output)
        return (
            f"Static HTML documentation portal generated successfully.\n"
            f"File: {os.path.abspath(out_file)}\n"
            f"Open this file in a browser to view the interactive architecture diagrams."
        )
    except Exception as e:
        return f"Error generating documentation portal: {str(e)}\n{traceback.format_exc()}"


@mcp.tool()
@redirect_stdout_to_stderr
def render_flow_diagram(layout: str) -> str:
    """Convert a simple text flow description into a rendered ASCII architecture diagram.

    Use this tool when:
    - The user wants to visualize a custom flow or architecture they describe verbally.
    - The user says "draw a diagram of X -> Y -> Z" using their own component names.
    - The user wants a quick ASCII diagram NOT based on scanning real code.
    - The user wants to prototype or sketch an architecture concept.

    This tool does NOT read any files — it only renders what the user provides as text.
    Use scan_project or get_routes_diagram for diagrams based on actual project code.

    Output: A rendered ASCII box diagram showing the described flow.

    Syntax guide for the layout string:
    - "A -> B"           Simple connection from A to B
    - "A -> [B, C]"      A connects to multiple nodes B and C
    - "A -> B ; C -> D"  Multiple rows separated by semicolons
    - "A [DB]"           Render A as a database cylinder
    - "A [Service]"      Render A as a soft rounded box
    - "A [?]"            Render A as a decision diamond

    Args:
        layout: Flow description string.
                Example: "Client -> API -> [AuthService, UserService] ; UserService -> DB [DB]"
    """
    try:
        router = Router()
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            router.process(layout)
        return f.getvalue()
    except Exception as e:
        return f"Error rendering manual flow: {str(e)}\n{traceback.format_exc()}"


@mcp.tool()
@redirect_stdout_to_stderr
def explain_architecture_with_ai(
    path: str = ".",
    depth: int = 3,
    style: str = "pro",
    provider: Optional[str] = None
) -> str:
    """Gather full project context and request a comprehensive architectural audit from the configured AI provider.

    Use this tool when:
    - The user explicitly asks for an "AI analysis", "AI audit", or "AI review" of their code.
    - The user asks for design pattern recommendations, refactoring suggestions, or code quality insights.
    - The user wants an expert opinion on the architecture, not just diagrams.
    - After scanning a project, the user wants deeper insight than diagrams can provide.

    IMPORTANT: Requires an AI provider API key in the environment:
    OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY, GROQ_API_KEY, DEEPSEEK_API_KEY,
    or Ollama running locally. Raises an error with guidance if no provider is configured.

    Output: A free-text architectural analysis report from the AI in the requested style.

    Available styles:
    - "pro"       -> Senior Software Architect: technical, formal, actionable (default)
    - "hacker"    -> Security Expert: focuses on attack surfaces and vulnerabilities
    - "ramsay"    -> Gordon Ramsay: brutally critical code review
    - "eli5"      -> Explain Like I'm 5: simple, beginner-friendly explanations
    - "jarvis"    -> Tony Stark's AI: elegant, concise, helpful
    - "soviet"    -> Soviet Engineer: efficiency and resource-focused
    - "corporate" -> Manager mode: buzzword-heavy stakeholder report
    - "doom"      -> Doom Slayer: bugs are demons to be eliminated

    Args:
        path: Path to the project root. Default ".".
        depth: Scan depth for context gathering. Default 3, increase for large projects.
        style: AI personality style (see above). Default "pro".
        provider: Force a specific provider: "openai", "anthropic", "gemini",
                  "groq", "deepseek", "openrouter", "ollama". Auto-detects if None.
    """
    try:
        scanner = ProjectScanner()
        arch_info = scanner.detect_architecture(path)
        flow_string = scanner.scan(path, max_depth=depth)

        if not flow_string:
            return "Could not gather codebase context. Folder is empty or contains no recognized source files."

        arch_context = "\n\n--- DETECTED ARCHITECTURE ---\n"
        arch_context += f"Framework: {arch_info.get('framework', 'Unknown')}\n"
        arch_context += f"Type: {arch_info.get('architecture', 'Unknown')}\n"
        arch_context += f"Features: {', '.join(arch_info.get('features', []))}\n"

        extra_diagrams = "\n\n--- ADVANCED MERMAID DIAGRAMS ---\n"

        compose_file = parse_infra(path)
        if compose_file:
            services = parse_docker_compose(compose_file)
            if services:
                extra_diagrams += "Infrastructure (docker-compose):\n```mermaid\n" + generate_mermaid_infra(services) + "\n```\n"

        detected_routes = parse_project_routes(path, max_depth=depth)
        if detected_routes:
            extra_diagrams += "API Routes:\n```mermaid\n" + generate_mermaid_sequence(detected_routes) + "\n```\n"

        entities = parse_project_for_er(path, max_depth=depth)
        if entities:
            extra_diagrams += "Entity-Relationship:\n```mermaid\n" + generate_mermaid_er(entities) + "\n```\n"

        uml_code = scanner.scan_uml(path, max_depth=depth)
        if uml_code and "note " not in uml_code.lower():
            extra_diagrams += "UML Class Diagram:\n```mermaid\n" + uml_code + "\n```\n"

        docs = scanner.get_docs_content(path)
        full_context = flow_string + arch_context + extra_diagrams
        if docs:
            full_context += "\n\n--- PROJECT DOCUMENTATION ---\n" + docs

        narrator = Narrator(force_provider=provider)
        return narrator.explain(full_context, use_ai=True, style=style)
    except Exception as e:
        return f"Error generating AI analysis: {str(e)}\n{traceback.format_exc()}"


@mcp.tool()
@redirect_stdout_to_stderr
def get_traceability_diagram(path: str = ".", depth: int = 3) -> str:
    """Generate a Mermaid.js Route-to-DB traceability diagram mapping endpoints to services/models.

    Use this tool when:
    - The user asks to "trace routes", "see data flow", or "trace endpoints to database/models".
    - The user wants to see what services or database models are called by which API endpoints.
    - You need to analyze the end-to-end flow of API requests.

    Output: A ```mermaid graph LR``` block tracing routes to their calls.
    Supports: Python (FastAPI/Flask).

    Args:
        path: Path to the project root. Default "." is the current directory.
        depth: Scan depth. Increase for deeply nested route files.
    """
    try:
        traces = parse_project_traceability(path, max_depth=depth)
        if not traces:
            return "No routes or calls detected to trace. Traceability is currently supported for Python (Flask/FastAPI)."
        
        trace_code = generate_mermaid_traceability(traces)
        if not trace_code:
            return "Could not generate the traceability graph."
            
        return f"```mermaid\n{trace_code}\n```"
    except Exception as e:
        return f"Error generating traceability diagram: {str(e)}\n{traceback.format_exc()}"


@mcp.tool()
@redirect_stdout_to_stderr
def init_ci(path: str = ".") -> str:
    """Configure GitHub Actions workflow (bck-nd-docs.yml) for auto-documentation on GitHub Pages (triggered on push to main).

    Use this tool when:
    - The user asks to "setup CI", "integrate with GitHub Actions", or "configure auto-docs".
    - The user wants to configure a workflow to automatically build and host static docs.

    Args:
        path: Path to the project root. Default ".".
    """
    try:
        workflow_path = generate_ci_workflow(path)
        return (
            f"GitHub Actions workflow for auto-documentation successfully initialized!\n"
            f"Created workflow file: {workflow_path}\n\n"
            f"Next steps for the user:\n"
            f"1. Push the changes to GitHub: git add . && git commit -m 'ci: add auto-docs' && git push origin main\n"
            f"2. Go to repository settings on GitHub > Pages.\n"
            f"3. Under 'Build and deployment', choose 'GitHub Actions' as the source."
        )
    except Exception as e:
        return f"Error configuring CI: {str(e)}\n{traceback.format_exc()}"


# ═══════════════════════════════════════════════════════════════════════════════
# NEW MCP TOOLS
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
@redirect_stdout_to_stderr
def get_project_health(root_path: str = ".", depth: int = 3) -> str:
    """Get a consolidated Project Health Score combining TODOs, Security, and Dependencies.
    
    Use this tool when:
    - The user asks about the overall health, score, or tech debt metrics of the codebase.
    
    Args:
        root_path: Path to the project root. Default "." is the current directory.
        depth: Scan depth.
    """
    try:
        scanner = ProjectScanner()
        result = scanner.calculate_health_score(root_path, max_depth=depth)
        
        report = []
        report.append(f"Project Health Score: {result['score']}/100")
        report.append(f"Grade: {result['grade']}\n")
        
        breakdown = result["breakdown"]
        report.append("Deductions Breakdown:")
        if breakdown['critical_risks'] > 0:
            report.append(f"- {breakdown['critical_risks']} Critical Security risks (-{breakdown['critical_risks'] * 25} pts)")
        if breakdown['high_risks'] > 0:
            report.append(f"- {breakdown['high_risks']} High/Warning Security risks (-{breakdown['high_risks'] * 10} pts)")
        if breakdown['fixme_bugs'] > 0:
            report.append(f"- {breakdown['fixme_bugs']} FIXMEs/BUGs (-{breakdown['fixme_bugs'] * 3} pts)")
        if breakdown['todos_hacks'] > 0:
            report.append(f"- {breakdown['todos_hacks']} TODOs/HACKs (-{breakdown['todos_hacks'] * 1} pts)")
            
        if result['score'] == 100:
            report.append("No technical debt or security risks detected. Perfect score!")
            
        return "\n".join(report)
    except Exception as e:
        return f"Error calculating health score: {str(e)}\n{traceback.format_exc()}"


@mcp.tool()
@redirect_stdout_to_stderr
def get_guided_onboarding(root_path: str = ".", depth: int = 3) -> str:
    """Generate a guided onboarding walkthrough of the codebase ordered by dependency criticality.
    
    Use this tool when:
    - The user is new to the project and wants to know where to start reading.
    
    Args:
        root_path: Path to the project root. Default ".".
        depth: Scan depth.
    """
    try:
        from bck_nd_hlpr.core.dependency_tracker import DependencyTracker
        tracker = DependencyTracker(root_path)
        tracker.scan_dependencies()
        path_list = tracker.get_onboarding_path()
        
        if not path_list:
            return "No project structure detected to create an onboarding path."
            
        report = ["Guided Onboarding Path:"]
        for i, item in enumerate(path_list, 1):
            report.append(f"{i}. {item['file']} ({item['role']}) - {item['hint']}")
            
        return "\n".join(report)
    except Exception as e:
        return f"Error generating onboarding path: {str(e)}\n{traceback.format_exc()}"


@mcp.tool()
@redirect_stdout_to_stderr
def export_data_dictionary(root_path: str = ".", format: str = "json") -> str:
    """Export detected ORM entities as a Data Dictionary in JSON or CSV format.
    
    Use this tool when:
    - The user asks for a data dictionary, database schema export, or raw JSON/CSV of entities.
    
    Args:
        root_path: Path to the project root. Default ".".
        format: Format to export, either 'json' or 'csv'. Default "json".
    """
    try:
        from bck_nd_hlpr.core.er_parser import export_entities_as_dict
        return export_entities_as_dict(root_path, format)
    except Exception as e:
        return f"Error exporting data dictionary: {str(e)}\n{traceback.format_exc()}"


@mcp.tool()
@redirect_stdout_to_stderr
def get_impact_radius(root_path: str = ".", changed_file: str = "", depth: int = 3) -> str:
    """Given a changed file, return which API routes and files are transitively affected.
    
    Use this tool when:
    - The user wants to know the blast radius or QA test prioritization for modifying a specific file.
    
    Args:
        root_path: Path to the project root. Default ".".
        changed_file: Absolute or relative path to the file being modified.
        depth: Scan depth.
    """
    try:
        from bck_nd_hlpr.core.route_parser import get_routes_affected_by_file
        
        abs_path = os.path.abspath(changed_file)
        if not os.path.exists(abs_path):
            return f"Error: The file '{changed_file}' does not exist."
            
        report_data = get_routes_affected_by_file(root_path, abs_path, max_depth=depth)
        
        report = [f"Impact Radius for: {report_data['changed_file']}\n"]
        
        report.append(f"Transitively Affected Files ({len(report_data['affected_files'])}):")
        for f in report_data["affected_files"]:
            report.append(f"- {f}")
            
        report.append(f"\nAffected API Routes ({len(report_data['affected_routes'])}):")
        if not report_data["affected_routes"]:
            report.append("None. No API endpoints seem to be transitively affected by this change.")
        else:
            for r in report_data["affected_routes"]:
                report.append(f"- [{r['method']}] {r['path']} (in {r['file']})")
                
        return "\n".join(report)
    except Exception as e:
        return f"Error calculating impact radius: {str(e)}\n{traceback.format_exc()}"


@mcp.tool()
@redirect_stdout_to_stderr
def get_api_contract_map(root_path: str = ".", depth: int = 3) -> str:
    """Generate an API Contract Map crossing routes with ER models and exposed fields.
    
    Use this tool when:
    - The user wants to map HTTP endpoints to database models.
    
    Args:
        root_path: Path to the project root. Default ".".
        depth: Scan depth.
    """
    try:
        from bck_nd_hlpr.core.route_parser import generate_api_contract_map
        contracts = generate_api_contract_map(root_path, max_depth=depth)
        
        if not contracts:
            return "No routes or models found to generate a contract map."
            
        report = ["| Route | File | Matched Model | Columns |", "|---|---|---|---|"]
        for c in contracts:
            cols = ", ".join(c['columns'].keys()) if c['columns'] else "None"
            model = c['matched_model'] or "None (Pure HTTP)"
            report.append(f"| {c['route']} | {c['file']} | {model} | {cols} |")
            
        return "\n".join(report)
    except Exception as e:
        return f"Error generating API contract map: {str(e)}\n{traceback.format_exc()}"


@mcp.tool()
@redirect_stdout_to_stderr
def get_asg_graph(root_path: str = ".", depth: int = 3) -> str:
    """Get the structured JSON representation of the Abstract Semantic Graph (ASG) for the project.

    Use this tool when:
    - The user asks for the ASG graph, semantic graph, structural JSON IR, or graph representation of the project.

    Args:
        root_path: Path to the project root. Default ".".
        depth: Scan depth.
    """
    try:
        from bck_nd_hlpr.core.asg import ASGGraph, ASGBuilder
        from bck_nd_hlpr.core.er_parser import parse_project_for_er
        from bck_nd_hlpr.core.route_parser import parse_project_routes
        from bck_nd_hlpr.cli.formatters import format_asg_json
        from pathlib import Path

        graph = ASGGraph()

        try:
            entities = parse_project_for_er(root_path, max_depth=depth)
            if entities:
                ASGBuilder.from_er_entities(entities, graph=graph)
        except Exception:
            pass

        try:
            routes = parse_project_routes(root_path, max_depth=depth)
            if routes:
                ASGBuilder.from_routes(routes, graph=graph)
        except Exception:
            pass

        return format_asg_json(graph)
    except Exception as e:
        return f"Error generating ASG graph: {str(e)}\n{traceback.format_exc()}"


@mcp.tool()
@redirect_stdout_to_stderr
def get_architecture_summary(root_path: str = ".", depth: int = 3) -> str:
    """Get a high-level architectural summary of the project including framework, architecture pattern, features, and provider metadata.

    Use this tool when:
    - The user asks for an architecture summary, provider info, framework overview, or high-level architecture stats.

    Args:
        root_path: Path to the project root. Default ".".
        depth: Scan depth.
    """
    try:
        from pathlib import Path
        from bck_nd_hlpr.core.detector import ArchitectureDetector
        from bck_nd_hlpr.core.providers.registry import ProviderRegistry

        detector = ArchitectureDetector()
        arch_info = detector.detect(root_path)

        summary_lines = []
        summary_lines.append(f"Architectural Summary of: {os.path.abspath(root_path)}")
        summary_lines.append(f"Framework: {arch_info.get('framework', 'Unknown')}")
        summary_lines.append(f"Architecture Pattern: {arch_info.get('architecture', 'Unknown')}")

        features = arch_info.get("features", [])
        if features:
            summary_lines.append(f"Features: {', '.join(features)}")

        if arch_info.get("summary"):
            summary_lines.append(f"Summary: {arch_info.get('summary')}")

        provider = getattr(detector, "_matched_provider", None)
        if not provider:
            provider = ProviderRegistry.get_instance().detect_provider(Path(root_path))

        if provider:
            summary_lines.append("\nProvider Metadata:")
            summary_lines.append(f"- Provider Name: {getattr(provider, 'name', 'generic')}")
            summary_lines.append(f"- Primary Language: {getattr(provider, 'language', 'unknown')}")
            if hasattr(provider, "get_framework_info"):
                try:
                    f_info = provider.get_framework_info(Path(root_path))
                    if isinstance(f_info, dict):
                        if f_info.get("orm"):
                            summary_lines.append(f"- ORM: {f_info.get('orm')}")
                        if f_info.get("architecture_type"):
                            summary_lines.append(f"- Provider Architecture Type: {f_info.get('architecture_type')}")
                except Exception:
                    pass

        return "\n".join(summary_lines)
    except Exception as e:
        return f"Error getting architecture summary: {str(e)}\n{traceback.format_exc()}"


@mcp.tool()
@redirect_stdout_to_stderr
def get_requirements_summary(project_path: str = ".") -> str:
    """Scan and summarize User Stories, Acceptance Criteria, and Business Rules from .bck-nd/requirements/.

    Use this tool when:
    - The user asks about "requirements", "user stories", "acceptance criteria", "business rules", or "specs".
    - The user asks "what features are planned / in progress / done?" or "show me the user stories".
    - You need to align implementation or tests with functional requirements and business rules.

    Args:
        project_path: Path to the project root containing .bck-nd/requirements/. Default ".".
    """
    try:
        from bck_nd_hlpr.core.requirements import RequirementsParser
        specs = RequirementsParser.load_from_directory(project_path)

        if not specs:
            return "No requirements found under .bck-nd/requirements/. Create JSON specifications under .bck-nd/requirements/ to define User Stories."

        status_counts = {"TODO": 0, "IN_PROGRESS": 0, "TESTING": 0, "DONE": 0}
        for spec in specs:
            status = spec.story.status.upper() if spec.story.status else "TODO"
            if status in status_counts:
                status_counts[status] += 1
            else:
                status_counts[status] = 1

        summary = [
            "# Requirements Summary\n",
            f"**Total Stories**: {len(specs)} (TODO: {status_counts.get('TODO', 0)}, "
            f"IN_PROGRESS: {status_counts.get('IN_PROGRESS', 0)}, "
            f"TESTING: {status_counts.get('TESTING', 0)}, "
            f"DONE: {status_counts.get('DONE', 0)})\n",
        ]

        for spec in specs:
            story = spec.story
            status_tag = f"[{story.status}]" if story.status else "[TODO]"
            summary.append(f"### {story.id} {status_tag} - {story.title}")
            if story.role:
                summary.append(f"- **As a**: {story.role}")
            if story.want:
                summary.append(f"- **I want**: {story.want}")
            if story.benefit:
                summary.append(f"- **So that**: {story.benefit}")

            if spec.business_rules:
                summary.append(f"- **Business Rules** ({len(spec.business_rules)}):")
                for br in spec.business_rules:
                    summary.append(f"  - `{br.id}`: {br.description}")

            if spec.acceptance_criteria:
                summary.append(f"- **Acceptance Criteria** ({len(spec.acceptance_criteria)}):")
                for ac in spec.acceptance_criteria:
                    summary.append(f"  - `{ac.id}`: **Given** {ac.given} **When** {ac.when} **Then** {ac.then}")

            if spec.required_data:
                summary.append(f"- **Required Data**: {spec.required_data}")

            if spec.validations:
                summary.append(f"- **Validations**: {spec.validations}")

            if spec.exceptions:
                summary.append(f"- **Exceptions**: {spec.exceptions}")

            if spec.open_questions:
                summary.append(f"- **Open Questions** ({len(spec.open_questions)}):")
                for q in spec.open_questions:
                    summary.append(f"  - {q}")

            summary.append("")

        return "\n".join(summary).rstrip()
    except Exception as e:
        return f"Error getting requirements summary: {str(e)}\n{traceback.format_exc()}"



def main():
    mcp.run(transport="stdio")

if __name__ == "__main__":
    main()

