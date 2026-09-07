import asyncio
import inspect
import io
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import threading
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Optional, Tuple
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
from bck_nd_hlpr.core.sanitizer import sanitize_text
from bck_nd_hlpr.core.doc_generator import DocGenerator
from bck_nd_hlpr.core.ci_generator import generate_ci_workflow
from bck_nd_hlpr.core.traceability import parse_project_traceability, generate_mermaid_traceability
from bck_nd_hlpr.core.tree_generator import generate_project_tree
from bck_nd_hlpr.core.product.renderer import (
    DEFAULT_PRODUCT_CONTEXT_CHARS,
    ProductContextError,
    build_product_context,
)
from bck_nd_hlpr.core.requirements import (
    RequirementsParser,
    discover_requirements_locations,
    render_requirements_scope,
    render_requirements_summary,
)
from bck_nd_hlpr.cli.formatters import (
    get_todos_table_string,
    get_security_report_string,
    get_impact_report_string,
)
from bck_nd_hlpr.core.utils.file_lock import (
    FileLockError,
    exclusive_file_lock,
    fsync_directory,
)
from bck_nd_hlpr.core.utils.secure_write import (
    SecureWriteError,
    atomic_write_artifact,
    ensure_existing_artifact_allowed,
    read_verified_artifact,
    resolve_project_target,
)


class MCPProjectAccessError(ValueError):
    """A requested project is outside the server's local read boundary."""


class MCPConfigError(RuntimeError):
    """An MCP client configuration could not be updated without data loss."""


MCP_ACCESS_DENIED = (
    "Access denied: requested path is outside the configured MCP roots."
)
MCP_ARTIFACT_WRITE_DENIED = (
    "Artifact write denied: requested destination is not a safe Backend Helper artifact."
)
MCP_TOOL_ERROR = "Error executing MCP tool safely."
MCP_ARGUMENT_ERROR = "Invalid MCP tool arguments."
MAX_MCP_DEPTH = 20
MAX_MCP_LAYOUT_CHARS = 8192
MCP_CONFIG_LOCK_TIMEOUT = 5.0
_MCP_STREAM_LOCK = threading.RLock()
_AI_CONTEXT_MARKER = b"<!-- bck-nd-hlpr generated AI context -->\n"
_AI_CONTEXT_PREFIX = b"<!-- bck-nd-hlpr"
_HTML_DOCS_MARKER = b"<!-- bck-nd-hlpr generated documentation -->\n"
_HTML_DOCS_PREFIX = b"<!-- bck-nd-hlpr generated documentation -->"


def _validated_mcp_call(func, args, kwargs):
    """Bind and validate the small public argument surface before analysis."""
    try:
        bound = inspect.signature(func).bind(*args, **kwargs)
    except TypeError:
        return None
    bound.apply_defaults()
    values = bound.arguments

    if "depth" in values:
        depth = values["depth"]
        if (
            isinstance(depth, bool)
            or not isinstance(depth, int)
            or depth < 0
            or depth > MAX_MCP_DEPTH
        ):
            return None
    if "format" in values:
        output_format = values["format"]
        if not isinstance(output_format, str) or output_format not in {"json", "csv"}:
            return None
    if "layout" in values:
        layout = values["layout"]
        if not isinstance(layout, str) or len(layout) > MAX_MCP_LAYOUT_CHARS:
            return None
    return bound


def _bound_project_root(bound) -> Optional[Path]:
    """Authorize the filesystem root once at the outer MCP boundary."""
    for parameter in ("path", "root_path", "project_path"):
        if parameter in bound.arguments:
            return _safe_mcp_project_root(bound.arguments[parameter])
    return None


def _replace_exact_root(text: str, root: Path) -> str:
    """Replace only complete selected-root prefixes, including JSON escaping."""
    raw_forms = {str(root), root.as_posix()}
    raw_forms.update(value.replace("\\", "\\\\") for value in tuple(raw_forms))
    flags = re.IGNORECASE if os.name == "nt" else 0
    result = text
    for value in sorted(raw_forms, key=len, reverse=True):
        if not value:
            continue
        pattern = re.compile(
            re.escape(value) + r"(?=$|[\\/]|[^A-Za-z0-9_.-])",
            flags,
        )
        result = pattern.sub(".", result)
    return result


def _finalize_mcp_output(result, project_root: Optional[Path] = None) -> str:
    """Apply the universal, idempotent trust boundary to successful text."""
    if result in {MCP_ACCESS_DENIED, MCP_ARTIFACT_WRITE_DENIED}:
        return result
    text = "" if result is None else str(result)
    if project_root is not None:
        text = _replace_exact_root(text, project_root)
    return sanitize_text(text)


def redirect_stdout_to_stderr(func):
    """Finalize an MCP tool while suppressing incidental process streams safely."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        bound = _validated_mcp_call(func, args, kwargs)
        if bound is None:
            return MCP_ARGUMENT_ERROR
        try:
            project_root = _bound_project_root(bound)
        except MCPProjectAccessError:
            return MCP_ACCESS_DENIED
        except Exception:
            return MCP_TOOL_ERROR

        try:
            with _MCP_STREAM_LOCK:
                captured_stdout = io.StringIO()
                captured_stderr = io.StringIO()
                with redirect_stdout(captured_stdout), redirect_stderr(captured_stderr):
                    result = func(*args, **kwargs)
        except MCPProjectAccessError:
            return MCP_ACCESS_DENIED
        except SecureWriteError:
            return MCP_ARTIFACT_WRITE_DENIED
        except Exception:
            return MCP_TOOL_ERROR
        return _finalize_mcp_output(result, project_root)

    return wrapper


def _canonical_allowed_roots(values) -> Tuple[Path, ...]:
    """Validate, canonicalize and deterministically deduplicate explicit roots."""
    raw_values = list(values)
    if not raw_values:
        raise ValueError("No explicit MCP roots were configured.")
    canonical = {}
    for value in raw_values:
        raw = str(value or "").strip()
        candidate = Path(raw)
        windows_path = PureWindowsPath(raw)
        if (
            not raw
            or not candidate.is_absolute()
            or (os.name != "nt" and (windows_path.drive or windows_path.is_absolute()))
        ):
            raise ValueError("An explicit MCP root is invalid.")
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError("An explicit MCP root is invalid.") from exc
        if not resolved.is_dir():
            raise ValueError("An explicit MCP root is invalid.")
        key = os.path.normcase(os.path.abspath(str(resolved)))
        canonical[key] = resolved
    return tuple(canonical[key] for key in sorted(canonical))


def _environment_allowed_roots() -> Tuple[Path, ...]:
    configured = os.environ.get("BCK_ND_MCP_ALLOWED_ROOTS")
    if configured is None:
        raise ValueError("No explicit MCP roots were configured.")
    return _canonical_allowed_roots(configured.split(os.pathsep))


def _raise_mcp_access_denied() -> None:
    raise MCPProjectAccessError(MCP_ACCESS_DENIED) from None


def _safe_mcp_project_root(project_path: str) -> Path:
    """Resolve an existing project inside BCK_ND_MCP_ALLOWED_ROOTS."""
    try:
        allowed_roots = _environment_allowed_roots()
    except ValueError:
        _raise_mcp_access_denied()

    raw = str(project_path or "").strip()
    normalized = raw.replace("\\", "/")
    if (
        not raw
        or "://" in normalized
        or any(part == ".." for part in normalized.split("/"))
    ):
        _raise_mcp_access_denied()

    windows_path = PureWindowsPath(raw)
    posix_path = PurePosixPath(normalized)
    if os.name == "nt":
        if (
            (windows_path.drive and not windows_path.is_absolute())
            or (posix_path.is_absolute() and not windows_path.is_absolute())
        ):
            _raise_mcp_access_denied()
        is_absolute = windows_path.is_absolute()
    else:
        if windows_path.drive or windows_path.is_absolute():
            _raise_mcp_access_denied()
        is_absolute = posix_path.is_absolute()

    if is_absolute:
        candidate = Path(raw)
    else:
        if len(allowed_roots) != 1:
            _raise_mcp_access_denied()
        relative_parts = tuple(
            part for part in normalized.split("/") if part not in ("", ".")
        )
        candidate = allowed_roots[0].joinpath(*relative_parts)

    try:
        candidate = candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        raise MCPProjectAccessError(MCP_ACCESS_DENIED) from None
    if not candidate.is_dir():
        _raise_mcp_access_denied()

    candidate_text = os.path.normcase(os.path.abspath(str(candidate)))
    for root in allowed_roots:
        root_text = os.path.normcase(os.path.abspath(str(root)))
        try:
            if os.path.commonpath([root_text, candidate_text]) == root_text:
                return candidate
        except ValueError:
            continue
    _raise_mcp_access_denied()


def _safe_mcp_child_path(
    project_root: Path,
    requested_path: str,
    *,
    must_exist: bool = True,
    expected_type: str = "file",
) -> Path:
    """Resolve one secondary path strictly inside an authorized project."""
    raw = str(requested_path or "").strip()
    normalized = raw.replace("\\", "/")
    if (
        not raw
        or "://" in normalized
        or any(part == ".." for part in normalized.split("/"))
    ):
        _raise_mcp_access_denied()

    windows_path = PureWindowsPath(raw)
    if os.name != "nt" and (windows_path.drive or windows_path.is_absolute()):
        _raise_mcp_access_denied()

    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = project_root / candidate
    try:
        resolved = candidate.resolve(strict=must_exist)
    except (OSError, RuntimeError) as exc:
        raise MCPProjectAccessError(MCP_ACCESS_DENIED) from exc

    root_text = os.path.normcase(os.path.abspath(str(project_root)))
    candidate_text = os.path.normcase(os.path.abspath(str(resolved)))
    try:
        if os.path.commonpath([root_text, candidate_text]) != root_text:
            _raise_mcp_access_denied()
    except ValueError:
        _raise_mcp_access_denied()

    if must_exist or resolved.exists():
        if expected_type == "file" and not resolved.is_file():
            _raise_mcp_access_denied()
        if expected_type == "directory" and not resolved.is_dir():
            _raise_mcp_access_denied()
    return resolved


def _relative_mcp_path(project_root: Path, path: Path) -> str:
    """Expose an authorized result relative to its project root."""
    try:
        relative = path.relative_to(project_root).as_posix()
    except ValueError:
        _raise_mcp_access_denied()
    return relative or "."


def _safe_context_artifact_target(project_root: Path, requested_path: str) -> Path:
    target = resolve_project_target(project_root, requested_path)
    try:
        relative = target.relative_to(project_root)
    except ValueError as exc:
        raise SecureWriteError("Artifact publication was denied safely.") from exc
    parts = relative.parts
    allowed_root_file = parts == ("ai_context.txt",)
    allowed_generated_file = (
        len(parts) >= 4
        and parts[:3] == (".bck-nd", "generated", "contexts")
        and target.suffix.casefold() == ".txt"
    )
    if not allowed_root_file and not allowed_generated_file:
        raise SecureWriteError("Artifact publication was denied safely.")
    return target


def _safe_docs_artifact_target(project_root: Path, requested_output: str) -> Path:
    output_directory = resolve_project_target(project_root, requested_output)
    try:
        relative = output_directory.relative_to(project_root).parts
    except ValueError as exc:
        raise SecureWriteError("Artifact publication was denied safely.") from exc
    if relative not in {
        ("docs",),
        (".bck-nd", "generated", "docs"),
    }:
        raise SecureWriteError("Artifact publication was denied safely.")
    return output_directory / "index.html"

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
- "product intent / PRD / scope / goals?"       → get_product_context
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
        safe_project = _safe_mcp_project_root(path)
        path = str(safe_project)
        scanner = ProjectScanner()
        arch_info = scanner.detect_architecture(path)

        result = []
        result.append("Architectural Scan of: .")
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
        from bck_nd_hlpr.core.uml_parser import is_empty_mermaid_class_diagram
        if not is_empty_mermaid_class_diagram(uml_code):
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
        except Exception:
            result.append("\n[SECURITY] SECURITY RISK AUDIT:\nAnalysis unavailable.")

        # 7. DEPENDENCY IMPACT HEATMAP
        try:
            from bck_nd_hlpr.core.dependency_tracker import analyze_impact as _analyze_impact
            usage_map = _analyze_impact(path)
            if usage_map:
                result.append("\n[IMPACT] DEPENDENCY HEATMAP:")
                result.append(get_impact_report_string(usage_map, plain=True))
        except Exception:
            result.append("\n[IMPACT] DEPENDENCY HEATMAP:\nAnalysis unavailable.")

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
        except Exception:
            result.append("\n[TRACE] ROUTE-TO-DB TRACEABILITY:\nAnalysis unavailable.")

        return "\n".join(result)
    except MCPProjectAccessError:
        return MCP_ACCESS_DENIED
    except Exception:
        return MCP_TOOL_ERROR


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
        safe_project = _safe_mcp_project_root(path)
        path = str(safe_project)
        tree_output = generate_project_tree(path, depth=depth)
        if not tree_output:
            return "Could not generate project tree. The path may not exist or may be empty."
        return tree_output
    except MCPProjectAccessError:
        return MCP_ACCESS_DENIED
    except Exception:
        return MCP_TOOL_ERROR


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
        safe_project = _safe_mcp_project_root(path)
        path = str(safe_project)
        scanner = ProjectScanner()
        uml_code = scanner.scan_uml(path, max_depth=depth)

        from bck_nd_hlpr.core.uml_parser import is_empty_mermaid_class_diagram
        if is_empty_mermaid_class_diagram(uml_code):
            return "No classes detected. The project may not use OOP patterns, or try increasing depth."

        return f"```mermaid\n{uml_code}\n```"
    except MCPProjectAccessError:
        return MCP_ACCESS_DENIED
    except Exception:
        return MCP_TOOL_ERROR


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
        safe_project = _safe_mcp_project_root(path)
        path = str(safe_project)
        entities = parse_project_for_er(path, max_depth=depth)
        er_code = generate_mermaid_er(entities)

        if not er_code or len(entities) == 0:
            return "No database models or entities detected. The project may not use an ORM, or try increasing depth."

        return f"```mermaid\n{er_code}\n```"
    except MCPProjectAccessError:
        return MCP_ACCESS_DENIED
    except Exception:
        return MCP_TOOL_ERROR


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
        safe_project = _safe_mcp_project_root(path)
        path = str(safe_project)
        detected_routes = parse_project_routes(path, max_depth=depth)
        seq_code = generate_mermaid_sequence(detected_routes)

        if not seq_code:
            return "No API routes detected. Supported frameworks: Flask, FastAPI, Express, NestJS, Next.js."

        return f"```mermaid\n{seq_code}\n```"
    except MCPProjectAccessError:
        return MCP_ACCESS_DENIED
    except Exception:
        return MCP_TOOL_ERROR


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
        safe_project = _safe_mcp_project_root(path)
        path = str(safe_project)
        compose_file = parse_infra(path)
        if not compose_file:
            return "No docker-compose.yml file found. This tool only works with Docker Compose projects."

        services = parse_docker_compose(compose_file)
        if not services:
            return "docker-compose.yml found but contains no service definitions."

        return f"```mermaid\n{generate_mermaid_infra(services)}\n```"
    except MCPProjectAccessError:
        return MCP_ACCESS_DENIED
    except Exception:
        return MCP_TOOL_ERROR


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
        safe_project = _safe_mcp_project_root(path)
        path = str(safe_project)
        todos = scan_for_todos(path, max_depth=depth)
        if not todos:
            return "No technical debt comments (TODO/FIXME/HACK/XXX/BUG) found. Clean codebase!"

        return get_todos_table_string(todos, plain=True)
    except MCPProjectAccessError:
        return MCP_ACCESS_DENIED
    except Exception:
        return MCP_TOOL_ERROR


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
        safe_project = _safe_mcp_project_root(path)
        path = str(safe_project)
        risks = scan_security_risks(path, max_depth=depth)
        return sanitize_text(get_security_report_string(risks, plain=True))
    except MCPProjectAccessError:
        return MCP_ACCESS_DENIED
    except Exception:
        return MCP_TOOL_ERROR


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
        safe_project = _safe_mcp_project_root(path)
        path = str(safe_project)
        from bck_nd_hlpr.core.dependency_tracker import analyze_impact as _analyze_impact
        usage_map = _analyze_impact(path)
        return get_impact_report_string(usage_map, plain=True)
    except MCPProjectAccessError:
        return MCP_ACCESS_DENIED
    except Exception:
        return MCP_TOOL_ERROR


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
        safe_project = _safe_mcp_project_root(path)
        safe_output = _safe_context_artifact_target(safe_project, output)
        ensure_existing_artifact_allowed(
            safe_project,
            safe_output,
            lambda content: content.startswith(_AI_CONTEXT_PREFIX),
        )
        dumper = ContextDumper(path=str(safe_project), depth=depth)
        context = dumper.build()
        rendered = _AI_CONTEXT_MARKER + context.encode("utf-8")
        atomic_write_artifact(
            safe_project,
            safe_output,
            rendered,
            existing_validator=lambda content: content.startswith(
                _AI_CONTEXT_PREFIX
            ),
        )

        uml = dumper.get_uml_diagram()
        er = dumper.get_er_diagram()
        file_size_kb = round(safe_output.stat().st_size / 1024, 1)
        relative_output = _relative_mcp_path(safe_project, safe_output)

        return (
            f"AI context file successfully generated!\n\n"
            f"File: {relative_output}\n"
            f"Size: {file_size_kb} KB\n"
            f"UML Diagram:  {'Generated' if uml else 'Not detected'}\n"
            f"ER Diagram:   {'Generated' if er else 'Not detected'}\n\n"
            f"The user can now open '{relative_output}', Select All, Copy, and paste it into ChatGPT or Claude."
        )
    except MCPProjectAccessError:
        return MCP_ACCESS_DENIED
    except SecureWriteError:
        return MCP_ARTIFACT_WRITE_DENIED
    except Exception:
        return MCP_TOOL_ERROR


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
        safe_project = _safe_mcp_project_root(path)
        safe_output = _safe_docs_artifact_target(
            safe_project,
            output,
        )
        ensure_existing_artifact_allowed(
            safe_project,
            safe_output,
            lambda content: content.startswith(_HTML_DOCS_PREFIX),
        )
        with tempfile.TemporaryDirectory(prefix="bck-nd-docs-") as staging:
            staging_root = Path(staging).resolve(strict=True)
            generator = DocGenerator()
            out_file = generator.generate(str(safe_project), str(staging_root))
            if out_file is None:
                raise SecureWriteError("Artifact publication was denied safely.")
            generated = Path(out_file).resolve(strict=True)
            try:
                generated.relative_to(staging_root)
            except ValueError as exc:
                raise SecureWriteError(
                    "Artifact publication was denied safely."
                ) from exc
            generated_content = read_verified_artifact(staging_root, generated)
            if generated_content is None:
                raise SecureWriteError("Artifact publication was denied safely.")
            if not generated_content.startswith(_HTML_DOCS_MARKER):
                generated_content = _HTML_DOCS_MARKER + generated_content
            atomic_write_artifact(
                safe_project,
                safe_output,
                generated_content,
                existing_validator=lambda content: content.startswith(
                    _HTML_DOCS_PREFIX
                ),
            )
        relative_output = _relative_mcp_path(safe_project, safe_output)
        return (
            f"Static HTML documentation portal generated successfully.\n"
            f"File: {relative_output}\n"
            f"Open this file in a browser to view the interactive architecture diagrams."
        )
    except MCPProjectAccessError:
        return MCP_ACCESS_DENIED
    except SecureWriteError:
        return MCP_ARTIFACT_WRITE_DENIED
    except Exception:
        return MCP_TOOL_ERROR


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
    except Exception:
        return MCP_TOOL_ERROR


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
        safe_project = _safe_mcp_project_root(path)
        path = str(safe_project)
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
    except MCPProjectAccessError:
        return MCP_ACCESS_DENIED
    except Exception:
        return MCP_TOOL_ERROR


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
        safe_project = _safe_mcp_project_root(path)
        path = str(safe_project)
        traces = parse_project_traceability(path, max_depth=depth)
        if not traces:
            return "No routes or calls detected to trace. Traceability is currently supported for Python (Flask/FastAPI)."
        
        trace_code = generate_mermaid_traceability(traces)
        if not trace_code:
            return "Could not generate the traceability graph."
            
        return f"```mermaid\n{trace_code}\n```"
    except MCPProjectAccessError:
        return MCP_ACCESS_DENIED
    except Exception:
        return MCP_TOOL_ERROR


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
        safe_project = _safe_mcp_project_root(path)
        workflow_path = generate_ci_workflow(str(safe_project))
        verified_workflow = _safe_mcp_child_path(
            safe_project,
            str(workflow_path),
            must_exist=True,
            expected_type="file",
        )
        relative_workflow = _relative_mcp_path(safe_project, verified_workflow)
        return (
            f"GitHub Actions workflow for auto-documentation successfully initialized!\n"
            f"Created workflow file: {relative_workflow}\n\n"
            f"Next steps for the user:\n"
            f"1. Push the changes to GitHub: git add . && git commit -m 'ci: add auto-docs' && git push origin main\n"
            f"2. Go to repository settings on GitHub > Pages.\n"
            f"3. Under 'Build and deployment', choose 'GitHub Actions' as the source."
        )
    except MCPProjectAccessError:
        return MCP_ACCESS_DENIED
    except SecureWriteError:
        return MCP_ARTIFACT_WRITE_DENIED
    except Exception:
        return MCP_TOOL_ERROR


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
        safe_project = _safe_mcp_project_root(root_path)
        root_path = str(safe_project)
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
    except MCPProjectAccessError:
        return MCP_ACCESS_DENIED
    except Exception:
        return MCP_TOOL_ERROR


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
        safe_project = _safe_mcp_project_root(root_path)
        root_path = str(safe_project)
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
    except MCPProjectAccessError:
        return MCP_ACCESS_DENIED
    except Exception:
        return MCP_TOOL_ERROR


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
        safe_project = _safe_mcp_project_root(root_path)
        root_path = str(safe_project)
        from bck_nd_hlpr.core.er_parser import export_entities_as_dict
        return export_entities_as_dict(root_path, format)
    except MCPProjectAccessError:
        return MCP_ACCESS_DENIED
    except Exception:
        return MCP_TOOL_ERROR


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
        safe_project = _safe_mcp_project_root(root_path)
        safe_changed_file = _safe_mcp_child_path(
            safe_project,
            changed_file,
            must_exist=True,
            expected_type="file",
        )

        report_data = get_routes_affected_by_file(
            str(safe_project),
            str(safe_changed_file),
            max_depth=depth,
        )

        relative_changed_file = _relative_mcp_path(
            safe_project,
            safe_changed_file,
        )
        report = [f"Impact Radius for: {relative_changed_file}\n"]
        
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
    except MCPProjectAccessError:
        return MCP_ACCESS_DENIED
    except Exception:
        return MCP_TOOL_ERROR


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
        safe_project = _safe_mcp_project_root(root_path)
        root_path = str(safe_project)
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
    except MCPProjectAccessError:
        return MCP_ACCESS_DENIED
    except Exception:
        return MCP_TOOL_ERROR


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
        safe_project = _safe_mcp_project_root(root_path)
        root_path = str(safe_project)
        from bck_nd_hlpr.core.asg import ASGGraph, ASGBuilder
        from bck_nd_hlpr.core.er_parser import parse_project_for_er
        from bck_nd_hlpr.core.route_parser import parse_project_routes
        from bck_nd_hlpr.core.scanner import ProjectScanner
        from bck_nd_hlpr.cli.formatters import format_asg_json

        graph = ASGGraph()

        try:
            uml_classes = ProjectScanner().collect_uml_classes(
                root_path,
                max_depth=depth,
            )
            if uml_classes:
                ASGBuilder.from_uml_classes(uml_classes, graph=graph)
        except Exception:
            pass

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
    except MCPProjectAccessError:
        return MCP_ACCESS_DENIED
    except Exception:
        return MCP_TOOL_ERROR


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
        safe_project = _safe_mcp_project_root(root_path)
        root_path = str(safe_project)
        from pathlib import Path
        from bck_nd_hlpr.core.detector import ArchitectureDetector
        from bck_nd_hlpr.core.providers.registry import ProviderRegistry

        detector = ArchitectureDetector()
        arch_info = detector.detect(root_path)

        summary_lines = []
        summary_lines.append("Architectural Summary of: .")
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
    except MCPProjectAccessError:
        return MCP_ACCESS_DENIED
    except Exception:
        return MCP_TOOL_ERROR


@mcp.tool()
@redirect_stdout_to_stderr
def get_product_context(
    project_path: str = ".",
    target_path: str = ".",
    max_chars: int = DEFAULT_PRODUCT_CONTEXT_CHARS,
) -> str:
    """Return applicable, validated product intent as canonical read-only context.

    AI clients should consult this tool before proposing changes to product scope,
    goals, target users, or release behavior. The result is the same deterministic
    ``<product_context>`` block used by ``bck-nd prompt`` and ContextDumper.

    Args:
        project_path: Selected project root. Default ".".
        target_path: Safe project-relative scope such as "." or "frontend/src".
        max_chars: Total character budget for the complete canonical block.
    """
    try:
        safe_project = _safe_mcp_project_root(project_path)
        return build_product_context(
            safe_project,
            target_path=target_path,
            max_chars=max_chars,
        ) or ""
    except MCPProjectAccessError:
        return MCP_ACCESS_DENIED
    except ProductContextError:
        return "Error building product context: request rejected safely."
    except Exception:
        return MCP_TOOL_ERROR


@mcp.tool()
@redirect_stdout_to_stderr
def get_requirements_summary(project_path: str = ".") -> str:
    """Scan and summarize User Stories, Acceptance Criteria, and Business Rules from .bck-nd/requirements/.

    Use this tool when:
    - The user asks about "requirements", "user stories", "acceptance criteria", "business rules", or "specs".
    - The user asks "what features are planned / in progress / done?" or "show me the user stories".
    - You need to align implementation or tests with functional requirements and business rules.

    Args:
        project_path: Path to the project root containing .bck-nd/requirements/.
            With one configured root, "." and relative paths resolve from that root;
            with multiple configured roots, pass an authorized absolute path. The
            server process working directory never grants filesystem access.
    """
    try:
        safe_project = _safe_mcp_project_root(project_path)
        current_result = RequirementsParser.load_collection(safe_project)
        location_report = discover_requirements_locations(
            safe_project,
            current_result=current_result,
        )
        summary = render_requirements_summary(current_result)
        scope = render_requirements_scope(location_report)
        if scope is None:
            return summary
        return (
            f"{scope}\n\n"
            f"<requirements_context>\n{summary}\n</requirements_context>"
        )
    except MCPProjectAccessError:
        return MCP_ACCESS_DENIED
    except Exception:
        return MCP_TOOL_ERROR


# ──────────────────────────────────────────────
# Claude Desktop, Cursor & Antigravity Auto-Installer
# ──────────────────────────────────────────────

def _get_claude_config_path() -> Path:
    """Return the platform-specific path to claude_desktop_config.json."""
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", ""))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".config"
    return base / "Claude" / "claude_desktop_config.json"


def _get_cursor_config_paths() -> list[Path]:
    """Return candidate platform-specific paths for Cursor's mcp.json."""
    candidates: list[Path] = []

    # Standard User home .cursor/mcp.json across Windows, macOS, Linux
    candidates.append(Path.home() / ".cursor" / "mcp.json")

    # Platform-specific Cursor globalStorage paths
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(Path(appdata) / "Cursor" / "User" / "globalStorage" / "mcp.json")
    elif sys.platform == "darwin":
        candidates.append(Path.home() / "Library" / "Application Support" / "Cursor" / "User" / "globalStorage" / "mcp.json")
    else:
        candidates.append(Path.home() / ".config" / "Cursor" / "User" / "globalStorage" / "mcp.json")

    return candidates


def _get_antigravity_config_path() -> Path:
    """Return the shared global MCP configuration used by Antigravity IDE/CLI."""
    return Path.home() / ".gemini" / "config" / "mcp_config.json"


def _find_antigravity_executable() -> Optional[str]:
    """Find a current or compatible Antigravity launcher on PATH."""
    for command in ("antigravity-ide", "antigravity", "agy"):
        executable = shutil.which(command)
        if executable:
            return executable
    return None


def _get_antigravity_server_definition(allowed_roots: str) -> dict:
    """Build a GUI-safe stdio definition using the active Python interpreter."""
    return {
        "command": str(Path(sys.executable).resolve()),
        "args": ["-m", "bck_nd_hlpr.cli.mcp_server"],
        "env": {"BCK_ND_MCP_ALLOWED_ROOTS": allowed_roots},
    }


def _installed_server_definition(allowed_roots: str) -> dict:
    return {
        "command": "bck-nd-mcp",
        "env": {"BCK_ND_MCP_ALLOWED_ROOTS": allowed_roots},
    }


def _resolve_install_allowed_roots(allowed_roots=None) -> Tuple[Path, ...]:
    try:
        if allowed_roots:
            return _canonical_allowed_roots(allowed_roots)
        return _environment_allowed_roots()
    except ValueError as exc:
        raise MCPConfigError(
            "MCP installation requires explicit valid roots; use --allowed-root <PATH>."
        ) from None


def _is_link_or_reparse(path_stat: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(path_stat.st_mode) or bool(
        getattr(path_stat, "st_file_attributes", 0) & reparse_flag
    )


def _config_state(path_stat: os.stat_result) -> Tuple[int, int, int, int, int, int]:
    return (
        path_stat.st_dev,
        path_stat.st_ino,
        stat.S_IFMT(path_stat.st_mode),
        path_stat.st_size,
        path_stat.st_mtime_ns,
        path_stat.st_ctime_ns,
    )


def _read_stable_config(target: Path) -> Optional[Tuple[bytes, os.stat_result]]:
    """Read one regular config without following links or accepting races."""
    try:
        initial_stat = target.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise MCPConfigError("Unable to inspect the MCP configuration safely.") from exc

    if _is_link_or_reparse(initial_stat) or not stat.S_ISREG(initial_stat.st_mode):
        raise MCPConfigError("MCP configuration target must be a regular local file.")

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(str(target), flags)
    except OSError as exc:
        raise MCPConfigError("Unable to open the MCP configuration safely.") from exc

    try:
        opened_stat = os.fstat(descriptor)
        opened_identity = (
            opened_stat.st_dev,
            opened_stat.st_ino,
            stat.S_IFMT(opened_stat.st_mode),
            opened_stat.st_size,
            opened_stat.st_mtime_ns,
        )
        expected_identity = (
            initial_stat.st_dev,
            initial_stat.st_ino,
            stat.S_IFMT(initial_stat.st_mode),
            initial_stat.st_size,
            initial_stat.st_mtime_ns,
        )
        if _is_link_or_reparse(opened_stat) or opened_identity != expected_identity:
            raise MCPConfigError("MCP configuration changed during secure reading.")
        chunks = []
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        content = b"".join(chunks)
        final_descriptor_stat = os.fstat(descriptor)
    except MCPConfigError:
        raise
    except OSError as exc:
        raise MCPConfigError("Unable to read the MCP configuration safely.") from exc
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass

    try:
        final_path_stat = target.lstat()
    except OSError as exc:
        raise MCPConfigError("MCP configuration changed during secure reading.") from exc
    if (
        _is_link_or_reparse(final_path_stat)
        or _config_state(final_descriptor_stat) != _config_state(opened_stat)
        or _config_state(final_path_stat) != _config_state(initial_stat)
    ):
        raise MCPConfigError("MCP configuration changed during secure reading.")
    return content, final_path_stat


def _write_verified_backup(backup_path: Path, original: bytes) -> None:
    temp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=backup_path.parent,
            prefix=f".{backup_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_file.write(original)
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_path = Path(temp_file.name)
        os.replace(temp_path, backup_path)
        temp_path = None
        fsync_directory(backup_path.parent)
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass


def _reject_duplicate_json_pairs(pairs):
    """Build one JSON object while rejecting exact duplicate keys."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise MCPConfigError(
                "MCP configuration contains duplicate JSON keys; no changes were made."
            )
        result[key] = value
    return result


def _mcp_config_lock_path(target: Path) -> Path:
    """Return the persistent cooperative lock beside one MCP config."""
    return target.with_name(f".{target.name}.bck-nd.lock")


def _update_mcp_config_file_locked(
    target: Path,
    server_definition: Optional[dict] = None,
) -> Optional[Path]:
    """
    Safely inject or update the 'bck-nd-mcp' entry in an MCP JSON config file.
    Preserves existing servers, cleans up legacy entries, creates a backup, and
    replaces the file atomically.

    Returns:
        The backup path when an existing file was preserved, otherwise None.
    """
    config: dict
    backup_path: Optional[Path] = None
    verified = _read_stable_config(target)
    original_bytes: Optional[bytes] = None
    original_stat: Optional[os.stat_result] = None
    if verified is not None:
        original_bytes, original_stat = verified
        try:
            config = json.loads(
                original_bytes.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_json_pairs,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MCPConfigError(
                "MCP configuration is not valid UTF-8 JSON; no changes were made."
            ) from exc
        if not isinstance(config, dict):
            raise MCPConfigError(
                "MCP configuration root must be a JSON object; no changes were made."
            )
        if "mcpServers" in config and not isinstance(config["mcpServers"], dict):
            raise MCPConfigError(
                "MCP configuration mcpServers must be a JSON object; no changes were made."
            )
        servers = config.setdefault("mcpServers", {})
    else:
        config = {}
        servers = config.setdefault("mcpServers", {})

    # Automatically clean up legacy server entries
    for legacy_key in ("backend-helper", "bck_nd_hlpr"):
        servers.pop(legacy_key, None)

    servers["bck-nd-mcp"] = server_definition or {"command": "bck-nd-mcp"}

    # Ensure parent directory exists
    target.parent.mkdir(parents=True, exist_ok=True)

    if original_bytes is not None:
        backup_path = target.with_name(f"{target.name}.bak")
        _write_verified_backup(backup_path, original_bytes)

    temp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            rendered = (
                json.dumps(config, indent=2, ensure_ascii=False) + "\n"
            ).encode("utf-8")
            temp_file.write(rendered)
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_path = Path(temp_file.name)
        if original_stat is not None:
            os.chmod(temp_path, stat.S_IMODE(original_stat.st_mode))

        current = _read_stable_config(target)
        if original_bytes is None:
            if current is not None:
                raise MCPConfigError(
                    "MCP configuration was created concurrently; no changes were made."
                )
        elif (
            current is None
            or current[0] != original_bytes
            or _config_state(current[1]) != _config_state(original_stat)
        ):
            raise MCPConfigError(
                "MCP configuration changed concurrently; no changes were made."
            )
        os.replace(temp_path, target)
        temp_path = None
        fsync_directory(target.parent)
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass

    return backup_path


def _update_mcp_config_file(
    target: Path,
    server_definition: Optional[dict] = None,
) -> Optional[Path]:
    """Update one MCP config while serializing cooperative writers."""
    target = Path(target)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_file_lock(
            _mcp_config_lock_path(target),
            timeout=MCP_CONFIG_LOCK_TIMEOUT,
        ):
            return _update_mcp_config_file_locked(target, server_definition)
    except FileLockError as exc:
        raise MCPConfigError(
            "Unable to acquire the MCP configuration writer lock."
        ) from exc


def _generate_manual_ide_settings_box(allowed_roots: str) -> str:
    """Render a styled Rich box showing exact fields for manual IDE settings."""
    manual_config = json.dumps(
        {
            "mcpServers": {
                "bck-nd-mcp": _installed_server_definition(allowed_roots),
            }
        },
        ensure_ascii=False,
        indent=2,
    )
    try:
        import io
        from rich.console import Console
        from rich.panel import Panel
        from rich import box
        from rich.markup import escape

        string_io = io.StringIO()
        console = Console(file=string_io, force_terminal=False, highlight=False, width=80)

        content = (
            "[bold]Manual IDE Settings (Claude / Cursor / Antigravity IDE)[/bold]\n\n"
            "  • [cyan]Server Name[/cyan] : [bold green]bck-nd-mcp[/bold green]\n"
            "  • [cyan]Command[/cyan]     : [bold green]bck-nd-mcp[/bold green]\n"
            "  • [cyan]Transport[/cyan]   : [yellow]stdio[/yellow]\n\n"
            "[dim]JSON snippet for mcpServers:[/dim]\n"
            f"{escape(manual_config)}"
        )

        panel = Panel(
            content,
            title="[bold cyan]🛠️  Manual IDE Configuration[/bold cyan]",
            border_style="bright_blue",
            box=box.ROUNDED,
            padding=(1, 2),
        )
        console.print(panel)
        return string_io.getvalue().rstrip()
    except ImportError:
        return (
            "--------------------------------------------------\n"
            "Manual IDE Settings (Claude / Cursor / Antigravity IDE):\n"
            "  • Server Name: bck-nd-mcp\n"
            "  • Command:     bck-nd-mcp\n"
            "  • Transport:   stdio\n"
            f"  • BCK_ND_MCP_ALLOWED_ROOTS: {allowed_roots}\n"
            "--------------------------------------------------"
        )


def _install_mcp_clients(
    claude_config_path: Optional[Path] = None,
    cursor_config_path: Optional[Path] = None,
    antigravity_config_path: Optional[Path] = None,
    allowed_roots=None,
) -> str:
    """
    Register bck-nd-mcp with Claude Desktop, Cursor, and Antigravity.

    Args:
        claude_config_path: Override the default Claude Desktop path.
        cursor_config_path: Override the default Cursor path (useful for testing).
        antigravity_config_path: Override the Antigravity path (useful for testing).

    Returns:
        A human-readable status message with configuration details and manual IDE setup box.
    """
    canonical_roots = _resolve_install_allowed_roots(allowed_roots)
    allowed_roots_text = os.pathsep.join(str(root) for root in canonical_roots)
    standard_definition = _installed_server_definition(allowed_roots_text)
    antigravity_definition = _get_antigravity_server_definition(
        allowed_roots_text
    )
    messages: list[str] = []
    explicit_paths = any(
        path is not None
        for path in (claude_config_path, cursor_config_path, antigravity_config_path)
    )

    # 1. Claude Desktop configuration
    if claude_config_path is not None or not explicit_paths:
        claude_target = claude_config_path or _get_claude_config_path()
        _update_mcp_config_file(
            claude_target,
            server_definition=standard_definition,
        )
        messages.append(f"✅ Claude Desktop configured successfully.\n   Config written to: {claude_target}")

    # 2. Cursor configuration
    if cursor_config_path is not None:
        _update_mcp_config_file(
            cursor_config_path,
            server_definition=standard_definition,
        )
        messages.append(f"✅ Cursor configured successfully.\n   Config written to: {cursor_config_path}")
    elif not explicit_paths:
        cursor_candidates = _get_cursor_config_paths()
        installed_cursor_paths = []
        for candidate in cursor_candidates:
            if candidate.is_file() or candidate.parent.is_dir():
                _update_mcp_config_file(
                    candidate,
                    server_definition=standard_definition,
                )
                installed_cursor_paths.append(candidate)

        if installed_cursor_paths:
            for p in installed_cursor_paths:
                messages.append(f"✅ Cursor configured successfully.\n   Config written to: {p}")
        else:
            messages.append("ℹ️  Cursor config directory not found (manual setup available below).")

    # 3. Antigravity IDE / CLI shared global configuration
    antigravity_target = antigravity_config_path
    antigravity_executable = _find_antigravity_executable()
    if antigravity_target is not None:
        _update_mcp_config_file(
            antigravity_target,
            server_definition=antigravity_definition,
        )
        messages.append(
            "✅ Antigravity IDE / CLI configured successfully.\n"
            f"   Config written to: {antigravity_target}"
        )
    elif not explicit_paths:
        antigravity_target = _get_antigravity_config_path()
        if (
            antigravity_executable
            or antigravity_target.is_file()
            or antigravity_target.parent.is_dir()
        ):
            _update_mcp_config_file(
                antigravity_target,
                server_definition=antigravity_definition,
            )
            detected_as = f" (detected: {antigravity_executable})" if antigravity_executable else ""
            messages.append(
                f"✅ Antigravity IDE / CLI configured successfully{detected_as}.\n"
                f"   Config written to: {antigravity_target}"
            )
        else:
            messages.append(
                "ℹ️  Antigravity IDE / CLI not detected "
                "(manual setup available below)."
            )

    # 4. Rich box for manual IDE configuration
    messages.append(
        "\n" + _generate_manual_ide_settings_box(allowed_roots_text)
    )

    return "\n".join(messages)


def _install_claude_desktop(
    config_path: Optional[Path] = None,
    cursor_config_path: Optional[Path] = None,
    antigravity_config_path: Optional[Path] = None,
    allowed_roots=None,
) -> str:
    """Backward-compatible wrapper for the original installer helper."""
    return _install_mcp_clients(
        claude_config_path=config_path,
        cursor_config_path=cursor_config_path,
        antigravity_config_path=antigravity_config_path,
        allowed_roots=allowed_roots,
    )


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

def _get_mcp_cli_help() -> str:
    """Return current command-line help without starting the stdio server."""
    return """Usage: bck-nd-mcp [OPTIONS]

Backend Helper MCP server for local product, requirements, and architecture intelligence.

With no options, starts the stdio server for an MCP-compatible client.

Options:
  --install              Register with Claude Desktop, Cursor, and Antigravity.
  --allowed-root PATH    Authorize one absolute project root; may be repeated.
  -v, --version          Show the Backend Helper version and exit.
  -h, --help             Show this message and exit.

Antigravity:
  Detects the current antigravity-ide launcher and safely merges bck-nd-mcp into
  ~/.gemini/config/mcp_config.json without removing GitHub or other MCP servers.
"""


def _parse_install_allowed_roots(args) -> list[str]:
    if not args or args[0] != "--install":
        raise MCPConfigError("Invalid MCP installation arguments.")
    roots: list[str] = []
    index = 1
    while index < len(args):
        argument = args[index]
        if argument == "--allowed-root":
            index += 1
            if index >= len(args):
                raise MCPConfigError(
                    "--allowed-root requires an absolute directory path."
                )
            roots.append(args[index])
        elif argument.startswith("--allowed-root="):
            roots.append(argument.split("=", 1)[1])
        else:
            raise MCPConfigError("Invalid MCP installation arguments.")
        index += 1
    return roots


def main():
    args = sys.argv[1:]

    if "--help" in args or "-h" in args:
        print(_get_mcp_cli_help())
        return

    if "--version" in args or "-v" in args:
        from bck_nd_hlpr.core.constants import VERSION
        print(f"bck-nd-hlpr {VERSION}")
        return

    # Handle --install before entering stdio mode.
    if args and args[0] == "--install":
        try:
            allowed_roots = _parse_install_allowed_roots(args)
            msg = _install_claude_desktop(
                allowed_roots=allowed_roots or None,
            )
        except MCPConfigError:
            print(
                "Error: MCP installation requires explicit valid project roots. "
                "Use --allowed-root <PATH>.",
                file=sys.stderr,
            )
            raise SystemExit(2)
        print(msg)
        return

    if args:
        print(f"Error: unknown option or argument: {' '.join(args)}", file=sys.stderr)
        print(_get_mcp_cli_help(), file=sys.stderr)
        raise SystemExit(2)

    # Interactive TTY helper: if a human runs `bck-nd-mcp` directly in a
    # terminal without piping, show a friendly explanation instead of silently
    # blocking on stdio.
    if sys.stdin.isatty():
        try:
            from rich.console import Console
            from rich.panel import Panel
            from rich import box

            console = Console(stderr=True)
            console.print(Panel(
                "[bold cyan]Backend Helper MCP Server[/bold cyan] is running in [yellow]stdio[/yellow] mode.\n\n"
                "This process communicates over stdin/stdout using the MCP protocol.\n"
                "It is meant to be launched by an MCP-compatible client (e.g. Claude Desktop, Cursor, Antigravity IDE).\n\n"
                "[dim]To auto-register with Claude Desktop, Cursor & Antigravity, run:[/dim]\n"
                "  [bold green]bck-nd-mcp --install --allowed-root <PATH>[/bold green]\n\n"
                "[dim]To exit, press[/dim] [bold red]Ctrl+C[/bold red].",
                title="🔌 MCP Server",
                box=box.ROUNDED,
                border_style="bright_blue",
                padding=(1, 2),
            ))
        except ImportError:
            print(
                "Backend Helper MCP Server is running in stdio mode.\n"
                "To auto-register with Claude Desktop / Cursor / Antigravity, "
                "run: bck-nd-mcp --install --allowed-root <PATH>\n"
                "To exit, press Ctrl+C.",
                file=sys.stderr,
            )

    try:
        mcp.run(transport="stdio")
    except (KeyboardInterrupt, asyncio.CancelledError):
        # A human stopped a stdio server that was waiting for its MCP client.
        return

if __name__ == "__main__":
    main()

