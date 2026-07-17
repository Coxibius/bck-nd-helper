"""
Analysis Framework — Strategy/Command pattern for `bck-nd scan`.

Each exclusive scan mode (``--uml``, ``--er``, ``--todo``, ...) is a
self-contained :class:`Analyzer` registered via the :func:`register`
decorator. The CLI orchestrator (``cli.scan``) and the MCP server dispatch
generically through the registry, so **adding a new analysis never requires
touching the orchestrator**: just drop a new Analyzer class here (or in any
imported module) and declare its CLI flag.

Design:
    ScanContext      -> immutable input snapshot (path, depth, arch_info, ...)
    AnalyzerResult   -> uniform output envelope (content / warning / raw data)
    Analyzer (ABC)   -> the Strategy interface (one `run()` per analysis)
    register()       -> plug-and-play registry (flag -> Analyzer class)
    run_analyzer()   -> programmatic entry point (MCP / docs / tests)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# Single source of truth for the Strategy/Registry contract. `analysis` keeps
# its historical public names (Analyzer, register, ScanContext, ...) as thin
# re-exports so the CLI/MCP imports keep working unchanged.
from bck_nd_hlpr.core.base_analyzer import (
    AnalyzerResult,
    BaseAnalyzer as Analyzer,
    ScanContext,
    available_flags,
    get_analyzer,
    register,
)


def run_analyzer(

    flag: str,
    path: str,
    depth: int = 3,
    arch_info: Optional[Dict[str, Any]] = None,
    plain: bool = True,
) -> AnalyzerResult:
    """Programmatic entry point (MCP server, doc generator, tests).

    Detects the architecture automatically when ``arch_info`` is omitted.
    """
    analyzer = get_analyzer(flag)
    if analyzer is None:
        raise KeyError(
            f"Unknown analyzer '{flag}'. Available: {', '.join(available_flags())}"
        )
    if arch_info is None:
        from bck_nd_hlpr.core.scanner import ProjectScanner
        arch_info = ProjectScanner().detect_architecture(path)
    ctx = ScanContext(path=path, depth=depth, arch_info=arch_info, plain=plain)
    return analyzer.run(ctx)


# ---------------------------------------------------------------------------
# Polyglot diagram builders (shared by analyzers, CLI overview, chat, MCP)
# ---------------------------------------------------------------------------

_CSHARP = ".NET Core / C#"
_JS_FRAMEWORKS = ("Express.js", "Next.js")
_JAVA_FRAMEWORKS = ("Spring Boot", "Java (Maven)", "Java (Gradle)")
_PHP_FRAMEWORKS = ("Laravel", "PHP")


def build_uml_diagram(path: str, depth: int, arch_info: Dict[str, Any]) -> Optional[str]:
    """Route to the correct language parser and return Mermaid UML (or None)."""
    framework = str(arch_info.get("framework", ""))

    classes = None
    if framework == _CSHARP:
        from bck_nd_hlpr.core.csharp_parser import parse_project_for_csharp_uml
        classes = parse_project_for_csharp_uml(path, max_depth=depth)
    elif framework in _JS_FRAMEWORKS:
        from bck_nd_hlpr.core.js_parser import parse_project_for_js_uml
        classes = parse_project_for_js_uml(path, max_depth=depth)
    elif framework == "Django":
        from bck_nd_hlpr.core.django_parser import parse_project_for_django_uml
        classes = parse_project_for_django_uml(path, max_depth=depth)
    elif framework in _JAVA_FRAMEWORKS:
        from bck_nd_hlpr.core.java_parser import parse_project_for_java_uml
        classes = parse_project_for_java_uml(path, max_depth=depth)
    elif framework in _PHP_FRAMEWORKS:
        from bck_nd_hlpr.core.php_parser import parse_project_for_php_uml
        classes = parse_project_for_php_uml(path, max_depth=depth)
    else:
        from bck_nd_hlpr.core.scanner import ProjectScanner
        uml_code = ProjectScanner().scan_uml(path, max_depth=depth)
        if uml_code and "class Empty" not in uml_code:
            return uml_code
        return None

    if classes:
        from bck_nd_hlpr.core.uml_parser import generate_mermaid_class_diagram
        return generate_mermaid_class_diagram(classes)
    return None


def build_er_diagram(path: str, depth: int, arch_info: Dict[str, Any]) -> Optional[str]:
    """Route to the correct language parser and return Mermaid ER (or None)."""
    framework = str(arch_info.get("framework", ""))

    if framework == _CSHARP:
        from bck_nd_hlpr.core.csharp_parser import parse_project_for_csharp_er
        entities = parse_project_for_csharp_er(path, max_depth=depth)
    elif framework in _JS_FRAMEWORKS:
        from bck_nd_hlpr.core.js_parser import parse_project_for_js_er
        entities = parse_project_for_js_er(path, max_depth=depth)
    elif framework == "Django":
        from bck_nd_hlpr.core.django_parser import parse_project_for_django_er
        entities = parse_project_for_django_er(path, max_depth=depth)
    elif framework in _JAVA_FRAMEWORKS:
        from bck_nd_hlpr.core.java_parser import parse_project_for_java_er
        entities = parse_project_for_java_er(path, max_depth=depth)
    elif framework in _PHP_FRAMEWORKS:
        from bck_nd_hlpr.core.php_parser import parse_project_for_php_er
        entities = parse_project_for_php_er(path, max_depth=depth)
    else:
        from bck_nd_hlpr.core.er_parser import parse_project_for_er
        entities = parse_project_for_er(path, max_depth=depth)

    if entities:
        from bck_nd_hlpr.core.er_parser import generate_mermaid_er
        return generate_mermaid_er(entities) or None
    return None


# ---------------------------------------------------------------------------
# Built-in analyzers (one class per `bck-nd scan` exclusive mode)
# ---------------------------------------------------------------------------

@register
class TreeAnalyzer(Analyzer):
    flag = "tree"
    banner = "[TREE] 🌳 PROJECT STRUCTURE:"
    banner_color = "cyan"

    def run(self, ctx: ScanContext) -> AnalyzerResult:
        from bck_nd_hlpr.core.tree_generator import generate_project_tree
        tree = generate_project_tree(ctx.path, depth=ctx.depth)
        return AnalyzerResult(
            content=tree or None,
            title="Project Structure",
            warning="⚠️ Could not generate project tree.",
        )


@register
class UmlAnalyzer(Analyzer):
    flag = "uml"
    banner = "[UML] GENERATING CLASS DIAGRAM (Mermaid):"

    def run(self, ctx: ScanContext) -> AnalyzerResult:
        return AnalyzerResult(
            content=build_uml_diagram(ctx.path, ctx.depth, ctx.arch_info),
            warning="⚠️ No classes detected for UML.",
        )


@register
class ErAnalyzer(Analyzer):
    flag = "er"
    banner = "[ER] GENERATING ER DIAGRAM (Mermaid):"

    def run(self, ctx: ScanContext) -> AnalyzerResult:
        return AnalyzerResult(
            content=build_er_diagram(ctx.path, ctx.depth, ctx.arch_info),
            warning="⚠️ No database models detected.",
        )


@register
class RoutesAnalyzer(Analyzer):
    flag = "routes"
    banner = "[API] GENERATING ROUTES MAP (Mermaid Sequence):"

    def run(self, ctx: ScanContext) -> AnalyzerResult:
        from bck_nd_hlpr.core.route_parser import parse_project_routes, generate_mermaid_sequence
        routes = parse_project_routes(ctx.path, max_depth=ctx.depth)
        code = generate_mermaid_sequence(routes) if routes else None
        return AnalyzerResult(
            content=code or None,
            warning="⚠️ No API routes detected (Flask/FastAPI).",
            raw=routes,
        )


@register
class InfraAnalyzer(Analyzer):
    flag = "infra"
    banner = "[INFRA] GENERATING INFRASTRUCTURE DIAGRAM (Mermaid):"

    def run(self, ctx: ScanContext) -> AnalyzerResult:
        from bck_nd_hlpr.core.infra_parser import parse_infra, parse_docker_compose, generate_mermaid_infra
        compose_file = parse_infra(ctx.path)
        if not compose_file:
            return AnalyzerResult(warning="⚠️ docker-compose.yml not detected in the directory.")
        services = parse_docker_compose(compose_file)
        if not services:
            return AnalyzerResult(warning="⚠️ No services found in docker-compose.")
        return AnalyzerResult(content=generate_mermaid_infra(services), raw=services)


@register
class TodoAnalyzer(Analyzer):
    flag = "todo"
    banner = "[TODO] 🧹 SCANNING TECHNICAL DEBT:"
    banner_color = "cyan"
    intro = "Searching for: TODO, FIXME, HACK, XXX, BUG..."

    def run(self, ctx: ScanContext) -> AnalyzerResult:
        from bck_nd_hlpr.core.todo_hunter import scan_for_todos
        from bck_nd_hlpr.cli.formatters import get_todos_table_string
        todos = scan_for_todos(ctx.path, max_depth=ctx.depth)
        if not todos:
            return AnalyzerResult(
                warning="✨ Awesome! No technical debt found.",
                warning_color="green",
            )
        return AnalyzerResult(
            content=get_todos_table_string(todos, plain=ctx.plain),
            title="",
            raw=todos,
        )


@register
class AuditAnalyzer(Analyzer):
    flag = "audit"
    banner = "[AUDIT] 🚨 SCANNING SECURITY RISKS:"
    banner_color = "red"
    intro = "Searching for: Credentials, Keys, IPs, Secrets..."

    def run(self, ctx: ScanContext) -> AnalyzerResult:
        from bck_nd_hlpr.core.security_auditor import scan_security_risks
        from bck_nd_hlpr.cli.formatters import get_security_report_string
        risks = scan_security_risks(ctx.path, max_depth=ctx.depth)
        return AnalyzerResult(
            content=get_security_report_string(risks, plain=ctx.plain),
            title="",
            raw=risks,
        )


@register
class ImpactAnalyzer(Analyzer):
    flag = "impact"
    banner = "[IMPACT] 🕸️ ANALYZING DEPENDENCY AND CHANGE RISK:"

    def run(self, ctx: ScanContext) -> AnalyzerResult:
        from bck_nd_hlpr.core.dependency_tracker import analyze_impact
        from bck_nd_hlpr.cli.formatters import get_impact_report_string
        usage_map = analyze_impact(ctx.path)
        return AnalyzerResult(
            content=get_impact_report_string(usage_map, plain=ctx.plain),
            title="",
            raw=usage_map,
        )


@register
class TraceAnalyzer(Analyzer):
    flag = "trace"
    banner = "[TRACE] 🔗 GENERATING ROUTE-TO-DB TRACEABILITY MAP (Mermaid):"

    def run(self, ctx: ScanContext) -> AnalyzerResult:
        from bck_nd_hlpr.core.traceability import parse_project_traceability, generate_mermaid_traceability
        traces = parse_project_traceability(ctx.path, max_depth=ctx.depth)
        if not traces:
            return AnalyzerResult(warning="⚠️ No Python routes detected to trace.")
        code = generate_mermaid_traceability(traces)
        return AnalyzerResult(
            content=code or None,
            warning="⚠️ Could not generate the traceability graph.",
            raw=traces,
        )