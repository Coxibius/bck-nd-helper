import shutil
import subprocess
import sys
import json
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional

import typer

# Reconfigure stdout/stderr to UTF-8 on Windows to prevent UnicodeEncodeError with emojis
if sys.platform.startswith("win"):
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
from bck_nd_hlpr.core.router import Router
from bck_nd_hlpr.core.scanner import ProjectScanner
from bck_nd_hlpr.core.narrator import Narrator
from bck_nd_hlpr.core.er_parser import parse_project_for_er, generate_mermaid_er
from bck_nd_hlpr.core.route_parser import parse_project_routes, generate_mermaid_sequence
from bck_nd_hlpr.core.infra_parser import parse_infra, parse_docker_compose, generate_mermaid_infra
from bck_nd_hlpr.cli.formatters import display_todos_table, get_todos_table_string, format_uml_diagram
from bck_nd_hlpr.core.uml_parser import is_empty_mermaid_class_diagram
from bck_nd_hlpr.core.doc_generator import DocGenerator
from bck_nd_hlpr.core.ci_generator import generate_ci_workflow
from bck_nd_hlpr.core.context_dumper import (
    ContextDumper,
    format_context_metrics,
)
from bck_nd_hlpr.core.product.renderer import (
    DEFAULT_PRODUCT_CONTEXT_CHARS,
    MIN_PRODUCT_CONTEXT_CHARS,
)
from bck_nd_hlpr.core.tree_generator import generate_project_tree
from bck_nd_hlpr.core.analysis import (
    ScanContext,
    get_analyzer,
    build_uml_diagram,
    build_er_diagram,
)


app = typer.Typer(
    name="bck-nd",
    help="Backend Helper: Architecture, requirements, AI context, and MCP tooling.",
    add_completion=False,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
    epilog="""
[bold]Current workflows[/bold]

• [cyan]bck-nd scan . --json[/cyan] — Four Pillars scan for CI/CD

• [cyan]bck-nd prompt . --copy[/cyan] — AI context, requirements, and metrics

• [cyan]bck-nd req init US-001[/cyan] — scaffold a user story

• [cyan]bck-nd req status US-001 DONE[/cyan] — update story status

• [cyan]bck-nd prd init PRD-AUTH[/cyan] — scaffold local product intent

• [cyan]bck-nd docs .[/cyan] — standalone offline documentation portal

• [cyan]bck-nd-mcp --install[/cyan] — connect Claude, Cursor, and Antigravity

[dim]Tip: Run any command with --help for detailed usage.[/dim]
"""
)

from bck_nd_hlpr.core.constants import VERSION


def version_callback(value: bool):
    if value:
        from rich.console import Console
        console = Console()
        console.print(f"[bold cyan]bck-nd-hlpr[/bold cyan] [green]{VERSION}[/green]")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-v",
        callback=version_callback,
        is_eager=True,
        help="Show the application version and exit.",
    ),
):
    """Backend Helper — Four Pillars architecture and requirements intelligence."""
    pass


def save_or_print(content: str, output_path: Optional[str], title: str = "OUTPUT"):
    """Helper to handle output persistence."""
    if output_path:
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(content)
            typer.secho(f"💾 Output saved to: {output_path}", fg=typer.colors.GREEN, bold=True)
        except Exception as e:
            typer.secho(f"❌ Error saving file: {e}", fg=typer.colors.RED)
    else:
        # Standard stdout behavior
        if "graph" in title or "diagram" in title.lower():
             print(content)
        else:
             print(content)


def copy_to_clipboard(text: str) -> bool:
    """Copy text to the system clipboard using native command-line tools."""
    if sys.platform.startswith("win"):
        commands = [["clip"]]
        encoded = text.encode("utf-16le")
    elif sys.platform == "darwin":
        commands = [["pbcopy"]]
        encoded = text.encode("utf-8")
    else:
        encoded = text.encode("utf-8")
        commands = []
        if shutil.which("wl-copy"):
            commands.append(["wl-copy"])
        if shutil.which("xclip"):
            commands.append(["xclip", "-selection", "clipboard"])

    for command in commands:
        try:
            subprocess.run(command, input=encoded, check=True)
            return True
        except (FileNotFoundError, OSError, subprocess.CalledProcessError):
            continue
    return False


def _copy_context_if_requested(context: str, requested: bool) -> None:
    if not requested:
        return
    if copy_to_clipboard(context):
        typer.secho(
            "📋 Context copied to clipboard! Ready to paste into ChatGPT / Claude.",
            fg=typer.colors.GREEN,
            bold=True,
        )
    else:
        typer.secho(
            "[--] Clipboard utility unavailable (tried clip, pbcopy, wl-copy, and xclip).",
            fg=typer.colors.YELLOW,
            err=True,
        )


def _print_context_metrics(
    dumper: ContextDumper,
    context: str,
    *,
    err: bool = False,
) -> None:
    """Print the standard token and context-savings footer."""
    typer.secho(
        format_context_metrics(dumper.get_context_metrics(context)),
        fg=typer.colors.CYAN,
        bold=True,
        err=err,
    )


def _json_compatible(value: Any) -> Any:
    """Recursively normalize analyzer models into deterministic JSON values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return _json_compatible(value.value)
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _json_compatible(value.to_dict())
    if is_dataclass(value):
        return _json_compatible(asdict(value))
    if isinstance(value, Mapping):
        return {
            str(key): _json_compatible(item)
            for key, item in value.items()
        }
    if isinstance(value, (set, frozenset)):
        normalized = [_json_compatible(item) for item in value]
        return sorted(normalized, key=lambda item: str(item))
    if isinstance(value, (list, tuple)):
        return [_json_compatible(item) for item in value]
    return str(value)


def _asg_to_dict(asg_graph: Any) -> dict[str, Any]:
    if asg_graph is None:
        return {"nodes": [], "edges": []}
    from bck_nd_hlpr.core.asg import ASGToJsonExporter

    return _json_compatible(ASGToJsonExporter.to_dict(asg_graph))


def _full_scan_json_payload(result: Any) -> dict[str, Any]:
    """Build the stable consolidated schema emitted by ``scan --json``."""
    return {
        "framework": result.framework,
        "architecture": result.architecture,
        "summary": result.summary,
        "features": _json_compatible(result.features or []),
        "asg": _asg_to_dict(result.asg_graph),
        "requirements": _json_compatible(result.requirements or []),
        "health": _json_compatible(result.health_score or {}),
        "todos": _json_compatible(result.todos or []),
        "security_risks": _json_compatible(result.security_risks or []),
    }


def _emit_scan_json(payload: Any, output: Optional[str]) -> None:
    serialized = json.dumps(
        _json_compatible(payload),
        ensure_ascii=False,
        indent=2,
    )
    if output:
        Path(output).write_text(serialized + "\n", encoding="utf-8")
    else:
        typer.echo(serialized)

@app.command()
def flow(
    layout: str = typer.Argument(..., help="Manual flow string.")
):
    """
    Generate an ASCII flow diagram from a compact string.

    Syntax hints:
    - "A -> B" connects A to B horizontally.
    - "[X, Y, Z]" keeps multiple nodes in the same column.
    - ";" starts a new row.
    - "[DB]" renders as a cylinder, "[Service]" as a soft box, "[?]/[IF]" as a decision diamond.

    Examples:
    - bck-nd flow "Client -> API -> Database"
    - bck-nd flow "Client -> LB -> [API_v1, API_v2] ; API_v1 -> Redis"
    - bck-nd flow "User -> Auth [Service] -> JWT [Token] -> API"
    """
    try:
        typer.secho("\n📐 GENERATING MANUAL DIAGRAM:", fg=typer.colors.CYAN, bold=True)
        router = Router()
        router.process(layout)
    except Exception as e:
        typer.secho(f"❌ Error: {e}", fg=typer.colors.RED)

@app.command()
def scan(
    path: str = typer.Argument(".", help="Path to the project directory. Use '.' for current dir or provide a relative/absolute path. Example: bck-nd scan src"),
    depth: int = typer.Option(3, "--depth", "-d", help="Max directory recursion depth (default: 3). Increase if files are nested deep. Example: bck-nd scan . --depth 5"),
    graph: bool = typer.Option(True, "--graph/--no-graph", help="Toggle diagram generation. Use --no-graph for text-only output (faster, good for CI logs). Example: bck-nd scan . --no-graph --ai"),
    explain: bool = typer.Option(False, "--explain", "-e", help="Generate an offline text report listing Controllers, Models, and Services. No AI required. Example: bck-nd scan . --explain"),
    ai: bool = typer.Option(False, "--ai", help="Run AI-powered analysis. Auto-detects API keys (OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY, OPENROUTER_API_KEY) or a local Ollama server. Example: bck-nd scan . --ai --style hacker"),
    style: str = typer.Option("pro", "--style", "-s", help="AI personality (requires --ai). Options: pro (architect), hacker (security), soviet (efficiency), eli5 (simple), ramsay (critical), jarvis (elegant), corporate (buzzwords), medieval (wizard), doom (bug hunter). Example: bck-nd scan . --ai --style ramsay"),
    format: str = typer.Option("ascii", "--format", "-f", help="Output format: 'ascii' (terminal boxes) or 'mermaid' (graph TD code for Notion/GitHub/Obsidian + terminal preview). Example: bck-nd scan . --format mermaid"),
    uml: bool = typer.Option(False, "--uml", "-u", help="Generate a Mermaid UML class diagram. Supports Python, C#, Java, JS/TS/React, PHP, Go, and Rust classes/interfaces. Example: bck-nd scan . --uml -o classes.mmd"),
    er: bool = typer.Option(False, "--er", help="Generate Entity-Relationship Diagram (Mermaid erDiagram). Scans ORMs: SQLAlchemy, Django, Entity Framework, Prisma, Drizzle, Sequelize, Mongoose, Laravel/Eloquent, JPA, and raw SQL. Example: bck-nd scan . --er -o schema.mmd"),
    routes: bool = typer.Option(False, "--routes", help="Generate API Routes Sequence Diagram (Mermaid sequenceDiagram). Scans Flask, FastAPI, Express, NestJS endpoints. Shows Client -> API interactions. Example: bck-nd scan . --routes"),
    infra: bool = typer.Option(False, "--infra", help="Generate Infrastructure Diagram from docker-compose.yml (Mermaid graph LR). Shows services, images, dependencies. DB services as cylinders. Example: bck-nd scan . --infra"),
    todo: bool = typer.Option(False, "--todo", help="Scan for technical debt: TODO, FIXME, HACK, XXX, BUG comments. Color-coded Rich table with file, line, type, message. Example: bck-nd scan . --todo -o debt.txt"),
    audit: bool = typer.Option(False, "--audit", help="Security audit: detects hardcoded AWS keys, private PEMs, DB passwords, API tokens, IPs. Reports Critical/High/Warning risks. Example: bck-nd scan . --audit"),
    impact: bool = typer.Option(False, "--impact", help="Dependency heatmap: ranks files by import count. Risk categories: CORE, SHARED, PERIPHERAL. Example: bck-nd scan . --impact"),
    impact_radius: Optional[str] = typer.Option(None, "--impact-radius", help="Path of the modified file to calculate its transitive impact radius on API routes."),
    contract: bool = typer.Option(False, "--contract", help="Generate an API Contract Map matching HTTP routes to database models and columns."),
    trace: bool = typer.Option(False, "--trace", help="Route-to-DB traceability graph (Mermaid graph LR). Traces routes -> services -> models via AST. Supports Python (FastAPI/Flask). Example: bck-nd scan . --trace"),
    tree: bool = typer.Option(False, "--tree", help="ASCII directory tree with Unicode box-drawing. Auto-filters noise (node_modules, venv, .git, __pycache__). Example: bck-nd scan . --tree --depth 5"),
    teach: bool = typer.Option(False, "--teach", help="Guided onboarding walkthrough using the dependency heatmap. Example: bck-nd scan . --teach"),
    health: bool = typer.Option(False, "--health", help="Calculate and print a consolidated Project Health Score report card."),
    export_dict: Optional[str] = typer.Option(None, "--export-dict", help="Export Data Dictionary (JSON/CSV from ORM models). Example: bck-nd scan . --export-dict json"),
    datascience: bool = typer.Option(False, "--datascience", help="Generate Data Lineage Map (Mermaid graph LR) from Jupyter Notebooks. Example: bck-nd scan . --datascience"),
    req: bool = typer.Option(False, "--req", help="Display Project Requirements summary table from .bck-nd/requirements/."),
    json_output: bool = typer.Option(False, "--json", help="Output results in machine-readable JSON format for CI/CD and scripts."),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Save output to file (ANSI codes stripped automatically). Works with any flag. Example: bck-nd scan . --er -o schema.mmd"),
    export_mermaid: bool = typer.Option(False, "--export-mermaid", help="Automatically save diagrams as .mmd files. Example: bck-nd scan . --uml --export-mermaid"),
    provider: Optional[str] = typer.Option(None, "--provider", help="Force specific AI provider (requires --ai). Options: openai, anthropic, gemini, groq, deepseek, openrouter, ollama. Example: bck-nd scan . --ai --provider openrouter"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Bypass incremental delta cache and force a complete full re-scan.")
):

    """
    Scan a project and generate architecture outputs.

    What it can produce (depending on flags):
    - Tree, Infra map, Routes (sequence), UML, ER, Technical Debt table, Requirements table.
    - Optional text reports (offline explain) or AI-assisted analysis.

    Exclusive modes (choose one):
    - --uml, --er, --routes, --infra, --tree, --todo, --audit, --impact, --trace, --req

    Notable flags:
    - --depth: recursion depth for scanning
    - --format: ascii or mermaid
    - --explain: offline text report
    - --ai/--style/--provider: AI analysis configuration
    - --impact-radius: show routes/files impacted by a given file
    - --teach, --health, --datascience, --contract, --export-dict (see help)
    - --json: emit machine-readable JSON, optionally with --output
    - --output: write results to file
    - --no-cache: disable delta cache engine

    Examples:
    - bck-nd scan .
    - bck-nd scan src --depth 5
    - bck-nd scan . --er -o schema.mmd
    - bck-nd scan . --ai --style hacker
    - bck-nd scan . --impact-radius app/api/users.py
    """
    from bck_nd_hlpr.core.orchestrator import ScannerOrchestrator, OrchestratorConfig
    from bck_nd_hlpr.cli.formatters import (
        get_security_report_string,
        get_impact_report_string,
        get_requirements_table_string,
        display_requirements_table,
    )

    requested_json_reports: list[tuple[str, str]] = []
    for requested, output_key, result_attr in (
        (tree, "tree", "tree"),
        (infra, "infra", "infra"),
        (routes, "routes", "routes"),
        (uml, "uml", "uml"),
        (er, "er", "er"),
        (todo, "todos", "todos"),
        (req, "requirements", "requirements"),
        (audit, "security_risks", "security_risks"),
        (impact, "dependency_heatmap", "dependency_heatmap"),
        (bool(impact_radius), "impact_radius", "impact_radius_report"),
        (contract, "api_contracts", "api_contracts"),
        (trace, "trace", "trace"),
        (datascience, "datascience", "datascience"),
        (teach, "onboarding", "onboarding_path"),
        (health, "health", "health_score"),
        (bool(export_dict), "data_dictionary", "data_dictionary"),
        (ai, "ai_narrative", "ai_narrative"),
        (explain, "explain", "explain"),
    ):
        if requested:
            requested_json_reports.append((output_key, result_attr))

    full_json_scan = json_output and not requested_json_reports

    initialized_files = set()
    if output and not json_output:
        try:
            with open(output, "w", encoding="utf-8") as f:
                f.write("")
            initialized_files.add(output)
        except Exception as e:
            typer.secho(f"❌ Error creating output file: {e}", fg=typer.colors.RED)

    def output_handler(content: str, context_msg: str):
        is_diagram = content.strip().startswith(("classDiagram", "erDiagram", "sequenceDiagram", "graph"))
        target_output = output
        
        if export_mermaid and is_diagram and not target_output:
            # Auto-generate filename
            clean_name = "".join(c for c in context_msg.lower() if c.isalnum() or c.isspace()).replace(" ", "_")
            target_output = f"{clean_name}.mmd"

        if target_output:
            is_mmd_file = target_output.endswith(".mmd")
            
            # Truncate if it's an auto-generated file we haven't written to yet
            if target_output not in initialized_files:
                try:
                    with open(target_output, "w", encoding="utf-8") as f:
                        f.write("")
                    initialized_files.add(target_output)
                except Exception as e:
                    typer.secho(f"❌ Error creating output file: {e}", fg=typer.colors.RED)

            try:
                with open(target_output, "a", encoding="utf-8") as f:
                    if context_msg and not is_mmd_file:
                        f.write(f"\n{'='*60}\n")
                        f.write(f"  {context_msg}\n")
                        f.write(f"{'='*60}\n\n")
                        
                    if is_mmd_file:
                        f.write(content.strip())
                        f.write("\n")
                    else:
                        f.write(content)
                        f.write("\n")
                typer.secho(f"💾 Result saved to: {target_output}", fg=typer.colors.GREEN, bold=True)
            except Exception as e:
                typer.secho(f"❌ Error writing file: {e}", fg=typer.colors.RED)
        else:
            if context_msg:
                if is_diagram:
                    print("```mermaid")
                    print(content.strip())
                    print("```")
                    typer.secho("Copy the above block into Mermaid.live", fg=typer.colors.BRIGHT_BLACK)
                else:
                    print(content)

    if not json_output:
        typer.secho(f"\n🔍 Analyzing architecture of '{path}'...", fg=typer.colors.CYAN, bold=True)

    config = OrchestratorConfig(
        path=path,
        depth=depth,
        uml=uml,
        er=er,
        routes=routes,
        infra=infra,
        todo=todo or full_json_scan,
        audit=audit or full_json_scan,
        impact=impact,
        trace=trace,
        tree=tree,
        datascience=datascience,
        contract=contract,
        health=health or full_json_scan,
        teach=teach,
        export_dict=export_dict,
        impact_radius=impact_radius,
        ai=ai,
        style=style,
        provider=provider,
        plain=bool(output) or json_output,
        use_cache=not no_cache,
        requirements=req or full_json_scan,
        asg=full_json_scan,
    )

    try:
        result = ScannerOrchestrator.run(config)
    except Exception as e:
        if json_output:
            try:
                _emit_scan_json({"error": str(e)}, output)
            except OSError:
                typer.echo(json.dumps({"error": str(e)}), err=True)
            raise typer.Exit(code=1)
        typer.secho(f"❌ Error during orchestrator execution: {e}", fg=typer.colors.RED)
        return

    if json_output:
        try:
            if full_json_scan:
                payload: Any = _full_scan_json_payload(result)
            else:
                report_values: dict[str, Any] = {}
                for output_key, result_attr in requested_json_reports:
                    if result_attr == "explain":
                        narrator = Narrator()
                        scanner = ProjectScanner()
                        flow_string = scanner.scan(path, max_depth=depth)
                        report_values[output_key] = narrator.explain(
                            flow_string,
                            use_ai=False,
                        )
                    else:
                        report_values[output_key] = getattr(result, result_attr, None)
                payload = (
                    next(iter(report_values.values()))
                    if len(report_values) == 1
                    else report_values
                )
            _emit_scan_json(payload, output)
        except OSError as e:
            typer.echo(
                json.dumps({"error": f"Could not write JSON output: {e}"}),
                err=True,
            )
            raise typer.Exit(code=1)
        return

    if result.framework != 'Unknown':
        typer.secho(f"💻 Framework detected: {result.framework}", fg=typer.colors.GREEN)
    if result.architecture:
        typer.secho(f"🏭 Architecture: {result.architecture}", fg=typer.colors.BLUE)
    if result.features:
        typer.secho(f"✨ Features: {', '.join(result.features)}", fg=typer.colors.YELLOW)
    if result.summary:
        typer.secho(f"\n📝 {result.summary}", fg=typer.colors.WHITE)

    if config.tree and result.tree:
        typer.secho("\n[TREE] 🌳 PROJECT STRUCTURE:", fg=typer.colors.CYAN, bold=True)
        if output:
            output_handler(result.tree, "[TREE] Project Structure")
        else:
            print(result.tree)

    if config.infra and result.infra:
        typer.secho("\n[INFRA] INFRASTRUCTURE MAP:", fg=typer.colors.CYAN, bold=True)
        output_handler(result.infra, "[INFRA] Infrastructure Map")

    if config.routes and result.routes:
        typer.secho("\n[API] ROUTES MAP:", fg=typer.colors.CYAN, bold=True)
        output_handler(result.routes, "[API] Routes Map")

    if config.uml:
        typer.secho("\n[UML] CLASS DIAGRAM:", fg=typer.colors.CYAN, bold=True)
        if not is_empty_mermaid_class_diagram(result.uml):
            output_handler(format_uml_diagram(result.uml), "[UML] Class Diagram")
        else:
            if output:
                output_handler(format_uml_diagram(result.uml), "[UML] Class Diagram")
            else:
                typer.secho(format_uml_diagram(result.uml), fg=typer.colors.YELLOW)

    if config.er and result.er:
        typer.secho("\n[ER] ENTITY-RELATIONSHIP:", fg=typer.colors.CYAN, bold=True)
        output_handler(result.er, "[ER] Entity-Relationship")

    if config.trace and result.trace:
        typer.secho("\n[TRACE] ROUTE-TO-DB TRACEABILITY:", fg=typer.colors.CYAN, bold=True)
        output_handler(result.trace, "[TRACE] Traceability Map")

    if config.datascience and result.datascience:
        typer.secho("\n📊 [DATA SCIENCE] Data Lineage Map", fg=typer.colors.CYAN)
        output_handler(result.datascience, "[DATA SCIENCE] Data Lineage Map")

    if config.todo and result.todos is not None:
        typer.secho("\n[TODO] TECHNICAL DEBT:", fg=typer.colors.CYAN, bold=True)
        if not result.todos:
            typer.secho("✨ Awesome! No technical debt found.", fg=typer.colors.GREEN, bold=True)
        else:
            if output:
                table_str = get_todos_table_string(result.todos, plain=True)
                output_handler(table_str, "[TODO] Technical Debt")
            else:
                display_todos_table(result.todos)

    if req:
        specs = result.requirements or []
        if specs:
            typer.secho("\n[REQ] 📋 PROJECT REQUIREMENTS:", fg=typer.colors.CYAN, bold=True)
            if output:
                table_str = get_requirements_table_string(specs, plain=True)
                output_handler(table_str, "[REQ] Project Requirements")
            else:
                display_requirements_table(specs)

    if config.audit and result.security_risks is not None:
        typer.secho("\n🚨 SECURITY AUDIT:", fg=typer.colors.CYAN, bold=True)
        report_str = get_security_report_string(result.security_risks, plain=bool(output))
        if output:
            output_handler(report_str, "[AUDIT] Security Audit")
        else:
            print(report_str)

    if config.impact and result.dependency_heatmap is not None:
        typer.secho("\n[IMPACT] DEPENDENCY HEATMAP:", fg=typer.colors.CYAN, bold=True)
        report_str = get_impact_report_string(result.dependency_heatmap, plain=bool(output))
        if output:
            output_handler(report_str, "[IMPACT] Dependency Heatmap")
        else:
            print(report_str)

    if config.impact_radius and result.impact_radius_report is not None:
        report = result.impact_radius_report
        typer.secho(f"\n[IMPACT RADIUS] 💥 CALCULATING TRANSITIVE IMPACT FOR: {impact_radius}", fg=typer.colors.MAGENTA, bold=True)
        typer.secho(f"\n🎯 Target File: {report.get('changed_file')}", fg=typer.colors.CYAN)
        
        if not report.get("affected_files"):
            typer.secho("✨ Good news! This file has no dependencies or does not affect any other files in the project.", fg=typer.colors.GREEN)
        else:
            typer.secho(f"\n🔗 Transitively Affected Files ({len(report['affected_files'])}):", fg=typer.colors.YELLOW)
            for f in report["affected_files"]:
                typer.secho(f"  - {f}")
            
            typer.secho(f"\n🚨 Affected API Routes ({len(report.get('affected_routes', []))}):", fg=typer.colors.RED, bold=True)
            if not report.get("affected_routes"):
                typer.secho("  None. No API endpoints seem to be transitively broken by this change.", fg=typer.colors.GREEN)
            else:
                for r in report["affected_routes"]:
                    typer.secho(f"  - [{r.get('method')}] {r.get('path')} (in {r.get('file')})")

    if config.contract and result.api_contracts is not None:
        typer.secho(f"\n[CONTRACT] 📜 GENERATING API CONTRACT MAP:", fg=typer.colors.MAGENTA, bold=True)
        contracts = result.api_contracts
        if not contracts:
            typer.secho("⚠️ No routes or models found to generate a contract map.", fg=typer.colors.YELLOW)
        else:
            if output:
                import json
                if output.endswith(".json"):
                    output_handler(json.dumps(contracts, indent=2), "")
                else:
                    md_lines = ["| Route | File | Matched Model | Columns |", "|---|---|---|---|"]
                    for c in contracts:
                        cols = ", ".join(c.get('columns', {}).keys()) if c.get('columns') else "None"
                        model = c.get('matched_model') or "None (Pure HTTP)"
                        md_lines.append(f"| {c.get('route')} | {c.get('file')} | {model} | {cols} |")
                    output_handler("\n".join(md_lines), "")
            else:
                from rich.console import Console
                from rich.table import Table
                console = Console()
                table = Table(show_header=True, header_style="bold magenta", title="API Contract Map")
                table.add_column("Route", style="cyan")
                table.add_column("File", style="yellow")
                table.add_column("Matched Model", style="bold green")
                table.add_column("Exposed Columns", style="white")
                for c in contracts:
                    model = c.get('matched_model') or "[italic bright_black]None (Pure HTTP)[/italic bright_black]"
                    cols = ", ".join(c.get('columns', {}).keys()) if c.get('columns') else "-"
                    table.add_row(c.get('route'), c.get('file'), model, cols)
                console.print(table)

    if config.teach and result.onboarding_path is not None:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
        
        path_list = result.onboarding_path
        console = Console()
        if not path_list:
            console.print(Panel("[bold red]No project structure detected to create an onboarding path.[/bold red]"))
        else:
            console.print("\n[bold cyan]🎓 Pedagogical Reading Path Generated![/bold cyan]")
            console.print("[italic]Follow this sequence to quickly understand the project architecture:[/italic]\n")
            table = Table(show_header=True, header_style="bold magenta", border_style="bright_black")
            table.add_column("Step", style="bold white", justify="right")
            table.add_column("File Path", style="cyan")
            table.add_column("Calculated Role", style="yellow")
            table.add_column("Hint / Why it matters", style="white")
            for i, item in enumerate(path_list, 1):
                tier = item.get("tier", 3)
                role_color = "bold cyan" if tier == 1 else "bold magenta" if tier == 2 else "bold yellow"
                table.add_row(
                    str(i),
                    item.get("file", ""),
                    f"[{role_color}]{item.get('role', '')}[/{role_color}]",
                    item.get("hint", "")
                )
            console.print(table)
            console.print("\n[bold green]Happy Onboarding![/bold green] 🚀")

    if config.health and result.health_score is not None:
        typer.secho(f"\n🏥 [HEALTH] CALCULATING PROJECT HEALTH SCORE:", fg=typer.colors.CYAN, bold=True)
        score_data = result.health_score
        score = score_data.get("score", 0)
        grade = score_data.get("grade", "F")
        breakdown = score_data.get("breakdown", {})
        
        from rich.console import Console
        from rich.panel import Panel
        from rich.text import Text
        console = Console()
        
        if grade in ["A", "B"]:
            color = "green"
        elif grade in ["C", "D"]:
            color = "yellow"
        else:
            color = "red bold"
            
        report_text = Text()
        report_text.append(f"Score: {score}/100\n", style=f"{color}")
        report_text.append(f"Grade: {grade}\n\n", style=f"{color}")
        
        c_risks = breakdown.get("critical_risks", 0)
        if c_risks > 0:
            report_text.append(f" -{c_risks * 25} points due to {c_risks} Critical Security risk(s)\n", style="red")
            
        h_risks = breakdown.get("high_risks", 0)
        if h_risks > 0:
            report_text.append(f" -{h_risks * 10} points due to {h_risks} High/Warning Security risk(s)\n", style="yellow")
            
        f_bugs = breakdown.get("fixme_bugs", 0)
        if f_bugs > 0:
            report_text.append(f" -{f_bugs * 3} points due to {f_bugs} FIXME/BUG/XXX(s)\n", style="magenta")
            
        t_hacks = breakdown.get("todos_hacks", 0)
        if t_hacks > 0:
            report_text.append(f" -{t_hacks * 1} points due to {t_hacks} TODO/HACK(s)\n", style="bright_black")
            
        if score == 100:
            report_text.append(" 🎉 Perfect Score! No technical debt or security risks detected.\n", style="green")
            
        panel = Panel(report_text, title="Project Health Report Card", border_style=color)
        if output:
            output_handler(report_text.plain, "")
        else:
            console.print(panel)

    if config.export_dict and result.data_dictionary is not None:
        if output:
            with open(output, "w", encoding="utf-8") as f:
                f.write(result.data_dictionary)
            typer.secho(f"✅ Data Dictionary exported to {output}", fg=typer.colors.GREEN)
        else:
            print(result.data_dictionary)

    if config.ai and result.ai_narrative:
        typer.secho(f"\n🤖 AI ANALYSIS (Style: {style.upper()}):", fg=typer.colors.MAGENTA, bold=True)
        if output:
            output_handler(result.ai_narrative, "")
        else:
            print(result.ai_narrative)

    if explain:
        typer.secho("\n📄 LOCAL REPORT:", fg=typer.colors.CYAN, bold=True)
        from bck_nd_hlpr.core.narrator import Narrator
        from bck_nd_hlpr.core.scanner import ProjectScanner
        narrator = Narrator()
        scanner = ProjectScanner()
        flow_string = scanner.scan(path, max_depth=depth)
        report = narrator.explain(flow_string, use_ai=False)
        if output:
             output_handler(report, "")
        else:
             print(report)

    # General graph mode fallback if none of the above are specified 
    # and graph=True and no single specific diagram requested
    if graph and not any([uml, er, routes, infra, todo, audit, impact, trace, tree, datascience, contract, teach, health, export_dict, ai, explain, impact_radius, req]):
        typer.secho("\n📊 PROJECT ARCHITECTURE (COMPLETE):", fg=typer.colors.MAGENTA, bold=True)
        
        config_full = OrchestratorConfig(
            path=path, depth=depth,
            tree=True, infra=True, routes=True, uml=True, er=True, todo=True, requirements=True
        )
        result_full = ScannerOrchestrator.run(config_full)
        
        if result_full.tree:
            typer.secho("\n[TREE] 🌳 PROJECT STRUCTURE:", fg=typer.colors.CYAN, bold=True)
            if output:
                output_handler(result_full.tree, "[TREE] Project Structure")
            else:
                print(result_full.tree)
        if result_full.infra:
            typer.secho("\n[INFRA] INFRASTRUCTURE MAP:", fg=typer.colors.CYAN, bold=True)
            output_handler(result_full.infra, "[INFRA] Infrastructure Map")
        if result_full.routes:
            typer.secho("\n[API] ROUTES MAP:", fg=typer.colors.CYAN, bold=True)
            output_handler(result_full.routes, "[API] Routes Map")
        if not is_empty_mermaid_class_diagram(result_full.uml):
            typer.secho("\n[UML] CLASS DIAGRAM:", fg=typer.colors.CYAN, bold=True)
            output_handler(format_uml_diagram(result_full.uml), "[UML] Class Diagram")
        if result_full.er:
            typer.secho("\n[ER] ENTITY-RELATIONSHIP:", fg=typer.colors.CYAN, bold=True)
            output_handler(result_full.er, "[ER] Entity-Relationship")
        if result_full.todos is not None:
            typer.secho("\n[TODO] TECHNICAL DEBT:", fg=typer.colors.CYAN, bold=True)
            if not result_full.todos:
                typer.secho("✨ Awesome! No technical debt found.", fg=typer.colors.GREEN, bold=True)
            else:
                if output:
                    table_str = get_todos_table_string(result_full.todos, plain=True)
                    output_handler(table_str, "[TODO] Technical Debt")
                else:
                    display_todos_table(result_full.todos)

        # Requirements
        specs = result_full.requirements or []
        if specs:
            typer.secho("\n[REQ] 📋 PROJECT REQUIREMENTS:", fg=typer.colors.CYAN, bold=True)
            if output:
                req_table_str = get_requirements_table_string(specs, plain=True)
                output_handler(req_table_str, "[REQ] Project Requirements")
            else:
                display_requirements_table(specs)

@app.command()
def docs(
    path: str = typer.Argument(".", help="Path to the project to document. Use '.' for current dir. Example: bck-nd docs ./my-api"),
    output: str = typer.Option("docs", "--output", "-o", help="Output directory for the HTML portal (created if missing). Example: bck-nd docs . -o site")
):
    """
    Generate a standalone, responsive HTML documentation portal.

    Includes:
    - Infra map (docker-compose)
    - API routes (sequence diagrams)
    - UML class diagram
    - ER diagram (ORM models)
    - Technical debt table
    - Project requirements (when .bck-nd/requirements/ exists)
    - Embedded offline SVG diagram previews (no CDN required)

    Examples:
    - bck-nd docs .
    - bck-nd docs . --output site

    Tip: Pair with `bck-nd init-ci` to publish on GitHub Pages.
    """
    typer.secho(f"\n[WEB] GENERATING WEB DOCUMENTATION IN '{output}':", fg=typer.colors.CYAN, bold=True)
    generator = DocGenerator()
    try:
        out_file = generator.generate(path, output)
        typer.secho(f"[OK] Documentation successfully generated at: {out_file}", fg=typer.colors.GREEN, bold=True)
    except Exception as e:
        typer.secho(f"[ERROR] Error generating documentation: {e}", fg=typer.colors.RED)


@app.command()
def explore():
    """
    Launch the TUI explorer.

    Features:
    - Sidebar directory tree
    - File view: instant ASCII + Mermaid routes for code files
    - Folder view: high-level architecture summary

    Shortcuts:
    - D: toggle dark/light
    - Q: quit

    Requires: textual (pip install textual)
    """
    try:
        from bck_nd_hlpr.cli.tui_app import ArchitectureExplorer
        explorer_app = ArchitectureExplorer()
        explorer_app.run()
    except ImportError as e:
        typer.secho(f"❌ Error starting TUI: {e}", fg=typer.colors.RED)
        typer.secho("Make sure 'textual' is installed (pip install textual).", fg=typer.colors.YELLOW)

@app.command()
def chat(
    path: str = typer.Argument(".", help="Path to the project. Scans architecture to build AI context. Example: bck-nd chat ./my-api"),
    depth: int = typer.Option(3, "--depth", "-d", help="Scan depth for context building (default: 3). Increase for deeply nested projects. Example: bck-nd chat . -d 5"),
    style: str = typer.Option("pro", "--style", "-s", help="AI personality: pro, hacker, soviet, eli5, ramsay, jarvis, corporate, medieval, doom. Example: bck-nd chat . --style jarvis"),
    provider: Optional[str] = typer.Option(None, "--provider", help="Force AI provider: openai, anthropic, gemini, groq, deepseek, openrouter, ollama. Example: bck-nd chat . --provider openrouter")
):
    """
    Interactive AI chat about your codebase (requires API key or Ollama).

    The command scans architecture and docs, then opens a chat loop with context loaded.

    Exit commands: exit, quit, q

    Examples:
    - bck-nd chat .
    - bck-nd chat . --style hacker
    - bck-nd chat . --provider ollama
    """
    scanner = ProjectScanner()
    
    typer.secho(f"🔍 Scanning architecture to initialize context (depth: {depth})...", fg=typer.colors.CYAN, bold=True)
    arch_info = scanner.detect_architecture(path)
    flow_string = scanner.scan(path, max_depth=depth)
    
    if not flow_string:
        typer.secho(f"❌ Could not build initial context. Empty folder or missing key files.", fg=typer.colors.RED)
        return
        
    # Construir mega-contexto arquitectónico
    arch_context = f"\n\n--- DETECTED ARCHITECTURE ---\n"
    arch_context += f"Framework: {arch_info.get('framework', 'Unknown')}\n"
    arch_context += f"Type: {arch_info.get('architecture', 'Unknown')}\n"
    arch_context += f"Features: {', '.join(arch_info.get('features', []))}\n"
    
    extra_diagrams = "\n\n--- ADVANCED DIAGRAMS (MERMAID) ---\n"
    
    # 1. Infra
    compose_file = parse_infra(path)
    if compose_file:
        services = parse_docker_compose(compose_file)
        if services:
            extra_diagrams += "Infrastructure (docker-compose):\n```mermaid\n" + generate_mermaid_infra(services) + "\n```\n"

    # 2. Rutas API
    detected_routes = parse_project_routes(path, max_depth=depth)
    if detected_routes:
        extra_diagrams += "API Routes (Sequence):\n```mermaid\n" + generate_mermaid_sequence(detected_routes) + "\n```\n"

    # 3. ER y UML
    entities = None
    if arch_info.get('framework') == '.NET Core / C#':
        from bck_nd_hlpr.core.csharp_parser import parse_project_for_csharp_er, parse_project_for_csharp_uml
        from bck_nd_hlpr.core.er_parser import generate_mermaid_er
        from bck_nd_hlpr.core.uml_parser import generate_mermaid_class_diagram
        
        entities = parse_project_for_csharp_er(path, max_depth=depth)
        if entities:
            extra_diagrams += "Entity-Relationship:\n```mermaid\n" + generate_mermaid_er(entities) + "\n```\n"
        
        classes = parse_project_for_csharp_uml(path, max_depth=depth)
        if classes:
            extra_diagrams += "UML Class Diagram:\n```mermaid\n" + generate_mermaid_class_diagram(classes) + "\n```\n"
    else:
        from bck_nd_hlpr.core.er_parser import parse_project_for_er, generate_mermaid_er
        entities = parse_project_for_er(path, max_depth=depth)
        if entities:
            extra_diagrams += "Entity-Relationship:\n```mermaid\n" + generate_mermaid_er(entities) + "\n```\n"
            
        uml_code = scanner.scan_uml(path, max_depth=depth)
        if not is_empty_mermaid_class_diagram(uml_code):
            extra_diagrams += "UML Class Diagram:\n```mermaid\n" + uml_code + "\n```\n"

    docs = scanner.get_docs_content(path)
    
    if docs:
        full_context = flow_string + arch_context + extra_diagrams + "\n\n--- PROJECT DOCUMENTATION ---\n" + docs
    else:
        full_context = flow_string + arch_context + extra_diagrams
        
    narrator = Narrator(force_provider=provider)
    if narrator.provider is None:
        typer.secho("\n❌ No AI provider configured. Interactive chat requires an active provider.", fg=typer.colors.RED, bold=True)
        typer.secho("Set one of the following environment variables:\n", fg=typer.colors.YELLOW)
        typer.secho("  OPENAI_API_KEY       — OpenAI GPT models          https://platform.openai.com/api-keys")
        typer.secho("  ANTHROPIC_API_KEY    — Anthropic Claude            https://console.anthropic.com/")
        typer.secho("  GOOGLE_API_KEY       — Google Gemini               https://aistudio.google.com/app/apikey")
        typer.secho("  OPENROUTER_API_KEY   — 200+ models, free tier      https://openrouter.ai/keys", fg=typer.colors.GREEN)
        typer.secho("  OLLAMA_HOST          — Local Ollama (no key)       https://ollama.com/", fg=typer.colors.GREEN)
        return
    
    typer.secho("\n✅ Contexto cargado con éxito.", fg=typer.colors.GREEN)
    typer.secho(f"💬 STARTING INTERACTIVE CHAT (Style: {style.upper()}). Type 'exit' to quit.\n", fg=typer.colors.MAGENTA, bold=True)
    
    history_text = ""
    while True:
        user_input = typer.prompt("You", type=str)
        if user_input.strip().lower() in ["salir", "exit", "quit", "q"]:
            typer.secho("👋 See you later!", fg=typer.colors.CYAN)
            break
            
        history_text += f"\nUser: {user_input}\n"
        
        response = narrator.chat_turn(system_context=full_context, history_text=history_text, style=style)
        
        typer.secho(f"\n🤖 bck-nd: {response}\n", fg=typer.colors.YELLOW)
        
        history_text += f"\nbck-nd: {response}\n"

@app.command()
def init_ci(
    path: str = typer.Argument(".", help="Project root where .github/workflows/ will be created. Example: bck-nd init-ci .")
):
    """
    Generate a GitHub Actions workflow for auto-docs + Pages publish.

    It creates .github/workflows/bck-nd-docs.yml to build the docs portal on push.

    After running:
    1) git add . && git commit -m "ci: add auto-docs" && git push
    2) In GitHub > Settings > Pages, set source to GitHub Actions
    3) Done — docs update on every push to main

    Example: bck-nd init-ci
    """
    typer.secho("\n[CI/CD] INITIALIZING FOR AUTO-DOCUMENTATION:", fg=typer.colors.CYAN, bold=True)
    
    try:
        workflow_path = generate_ci_workflow(path)
        typer.secho(f"[OK] File created: {workflow_path}", fg=typer.colors.GREEN)
        
        typer.secho("\n[STEPS] NEXT STEPS:", fg=typer.colors.YELLOW, bold=True)
        typer.secho("1. Push the changes to GitHub: git add . && git commit -m 'ci: add auto-docs' && git push origin main")
        typer.secho("2. Go to your repo on GitHub > Settings > Pages.")
        typer.secho("3. Under 'Build and deployment', choose 'GitHub Actions' as the source.")
        typer.secho("4. Done! Your documentation will update on push to main.", fg=typer.colors.CYAN)
    except Exception as e:
        typer.secho(f"❌ Error configuring CI: {e}", fg=typer.colors.RED)

@app.command(name="prompt")
def prompt_cmd(
    path: str = typer.Argument(".", help="Path to the project to analyze. Use '.' for current directory or provide an absolute/relative path. Example: bck-nd prompt /home/user/my-api"),
    output: str = typer.Option("ai_context.txt", "--output", "-o", help="Output file path/name for the context dump (default adapts to flags). Example: bck-nd prompt . -o context.txt"),
    depth: Optional[int] = typer.Option(None, "--depth", "-d", help="Directory scan depth (default: unlimited). Set a value to cap recursion. Example: bck-nd prompt . --depth 6"),
    max_core_files: Optional[int] = typer.Option(None, "--max-core-files", help="Maximum number of core files to include in the context dump (default: 8 for mobile, 5 for backend)."),
    uml: bool = typer.Option(False, "--uml", help="Generate product-aware focused context with UML (use --no-prd for strictly technical output)."),
    er: bool = typer.Option(False, "--er", help="Generate product-aware focused context with ER (use --no-prd for strictly technical output)."),
    tree: bool = typer.Option(False, "--tree", help="Generate product-aware focused context with project tree (use --no-prd for strictly technical output)."),
    copy_to_clipboard: bool = typer.Option(False, "--copy", "-c", help="Automatically copy generated context to system clipboard."),
    no_prd: bool = typer.Option(False, "--no-prd", help="Exclude local PRD product context without modifying its source files."),
    max_product_chars: int = typer.Option(
        DEFAULT_PRODUCT_CONTEXT_CHARS,
        "--max-product-chars",
        min=MIN_PRODUCT_CONTEXT_CHARS,
        help="Maximum characters for the complete product context block.",
    ),
):
    """
    Export AI-ready context with requirements, diagrams, core files, and metrics.

    Default (no flags) — full context dump:
    - <product_context>: applicable product intent, provenance, and trust status
    - <project_tree>: filtered directory tree
    - <architecture_uml>: Mermaid classDiagram
    - <architecture_er>: Mermaid erDiagram
    - <requirements_context>: stories, statuses, criteria, and business rules
    - <core_files>: prioritized key files
    - Metrics: estimated tokens, context size, and savings vs raw source

    Focused mode (--uml, --er, --tree):
    - Includes applicable product context plus the requested technical sections.
    - Use --no-prd for strictly technical requested sections only.
    - Default filename adapts: ai_context_uml.txt, ai_context_er.txt, etc.
    - Flags can be combined: --uml --er → ai_context_diagrams.txt

    Usage:
    1) bck-nd prompt .
    2) Open ai_context.txt (or use --copy / -c)
    3) Paste it into your AI client as the first message

    Examples:
    - bck-nd prompt .
    - bck-nd prompt /my/project -o ctx.txt
    - bck-nd prompt . --depth 6
    - bck-nd prompt . --uml
    - bck-nd prompt . --er
    - bck-nd prompt . --tree
    - bck-nd prompt . --uml --er
    - bck-nd prompt . --copy
    - bck-nd prompt . --no-prd
    - bck-nd prompt . --max-product-chars 4000
    """
    # ── Detect focused mode ──────────────────────────────────────────────
    focused_mode = uml or er or tree

    # ── Dynamic default filename ─────────────────────────────────────────
    user_set_output = output != "ai_context.txt"
    if focused_mode and not user_set_output:
        active_flags = []
        if uml:
            active_flags.append("uml")
        if er:
            active_flags.append("er")
        if tree:
            active_flags.append("tree")

        if len(active_flags) == 1:
            output = f"ai_context_{active_flags[0]}.txt"
        else:
            output = "ai_context_diagrams.txt"

    # ── Stdout piping mode ───────────────────────────────────────────────
    if output == "-":
        dumper = ContextDumper(
            path=path,
            depth=depth,
            output_file=output,
            max_core_files=max_core_files,
            include_prd=not no_prd,
            max_product_chars=max_product_chars,
        )
        if focused_mode:
            context = dumper.build_focused(include_tree=tree, include_uml=uml, include_er=er)
        else:
            context = dumper.build()
        print(context)
        _copy_context_if_requested(context, copy_to_clipboard)
        _print_context_metrics(dumper, context, err=True)
        return

    from rich.console import Console
    from rich.panel import Panel
    from rich import box

    console = Console(force_terminal=True, highlight=False)

    # ── FOCUSED MODE ─────────────────────────────────────────────────────
    if focused_mode:
        focus_parts = []
        if tree:
            focus_parts.append("Tree")
        if uml:
            focus_parts.append("UML")
        if er:
            focus_parts.append("ER")
        focus_label = " + ".join(focus_parts)

        console.print(
            Panel.fit(
                f"[bold cyan]bck-nd Focused Context ({focus_label})[/bold cyan]\n"
                "[dim]Generating lightweight diagram file...[/dim]",
                border_style="cyan",
                box=box.ASCII2,
            )
        )

        dumper = ContextDumper(
            path=path,
            depth=depth,
            output_file=Path(output).name,
            max_core_files=max_core_files,
            include_prd=not no_prd,
            max_product_chars=max_product_chars,
        )

        total_steps = sum([tree, uml, er])
        step = 0

        if tree:
            step += 1
            typer.secho(f"  [{step}/{total_steps}] Building directory tree...", fg=typer.colors.CYAN)
            dumper.get_project_tree()

        uml_result = None
        if uml:
            step += 1
            typer.secho(f"  [{step}/{total_steps}] Generating UML diagram...", fg=typer.colors.MAGENTA)
            uml_result = dumper.get_uml_diagram()

        er_result = None
        if er:
            step += 1
            typer.secho(f"  [{step}/{total_steps}] Generating ER diagram...", fg=typer.colors.MAGENTA)
            er_result = dumper.get_er_diagram()

        context = dumper.build_focused(include_tree=tree, include_uml=uml, include_er=er)

        try:
            output_path = Path(output)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(context)
        except Exception as e:
            typer.secho(f"[ERROR] Could not save file: {e}", fg=typer.colors.RED)
            raise typer.Exit(code=1)

        # Summary
        status_lines = []
        if tree:
            status_lines.append("[bold]Tree:[/bold]      [green][OK] Generated[/green]")
        if uml:
            uml_status = "[green][OK] Generated[/green]" if uml_result else "[yellow][--] No classes detected[/yellow]"
            status_lines.append(f"[bold]UML:[/bold]       {uml_status}")
        if er:
            er_status = "[green][OK] Generated[/green]" if er_result else "[yellow][--] No models detected[/yellow]"
            status_lines.append(f"[bold]ER:[/bold]        {er_status}")

        console.print()
        console.print(
            Panel(
                f"[bold]Project:[/bold]   [cyan]{Path(path).resolve().name}[/cyan]\n"
                + "\n".join(status_lines) + "\n\n"
                f"[bold green]Focused context saved to [underline]{output}[/underline].[/bold green]\n"
                f"[italic]Lightweight file — ready to paste into your AI![/italic]",
                title=f"[bold cyan]Focused Context Complete ({focus_label})[/bold cyan]",
                border_style="green",
                box=box.ASCII2,
            )
        )
        _copy_context_if_requested(context, copy_to_clipboard)
        _print_context_metrics(dumper, context)
        return

    # ── FULL MODE (default — unchanged) ──────────────────────────────────
    console.print(
        Panel.fit(
            "[bold cyan]bck-nd Context Dump[/bold cyan]\n"
            "[dim]Generating LLM-optimized context file...[/dim]",
            border_style="cyan",
            box=box.ASCII2,
        )
    )

    dumper = ContextDumper(
        path=path,
        depth=depth,
        output_file=Path(output).name,
        max_core_files=max_core_files,
        include_prd=not no_prd,
        max_product_chars=max_product_chars,
    )

    typer.secho("  [1/4] Building directory tree...", fg=typer.colors.CYAN)
    tree_out = dumper.get_project_tree()

    typer.secho("  [2/4] Generating UML diagram...", fg=typer.colors.MAGENTA)
    uml_out = dumper.get_uml_diagram()

    typer.secho("  [3/4] Generating ER diagram...", fg=typer.colors.MAGENTA)
    er_out = dumper.get_er_diagram()

    typer.secho("  [4/4] Assembling context file...", fg=typer.colors.GREEN)
    context = dumper.build()

    # Write to disk
    try:
        output_path = Path(output)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(context)
    except Exception as e:
        typer.secho(f"[ERROR] Could not save file: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    # -- Summary report -------------------------------------------------------
    uml_status  = "[green][OK] Generated[/green]" if uml_out else "[yellow][--] No classes detected[/yellow]"
    er_status   = "[green][OK] Generated[/green]" if er_out  else "[yellow][--] No models detected[/yellow]"

    console.print()
    console.print(
        Panel(
            f"[bold]Project:[/bold]   [cyan]{Path(path).resolve().name}[/cyan]\n"
            f"[bold]UML:[/bold]       {uml_status}\n"
            f"[bold]ER:[/bold]        {er_status}\n\n"
            f"[bold green]Contexto generado en [underline]{output}[/underline].[/bold green]\n"
            f"[italic]Listo para copiar y pegar en tu IA![/italic]",
            title="[bold cyan]Context Dump Complete[/bold cyan]",
            border_style="green",
            box=box.ASCII2,
        )
    )
    _copy_context_if_requested(context, copy_to_clipboard)
    _print_context_metrics(dumper, context)


# ──────────────────────────────────────────────
# PRODUCT REQUIREMENTS DOCUMENTS (bck-nd prd)
# ──────────────────────────────────────────────

prd_app = typer.Typer(
    name="prd",
    help="Create, inspect, validate, and update local Product Requirements Documents.",
    no_args_is_help=True,
)
app.add_typer(prd_app, name="prd")


def _prd_operation_json(message: str, diagnostics: Optional[list] = None) -> dict:
    """Build a pure JSON failure payload for the PRD CLI adapter."""
    serialized = [item.to_dict() for item in (diagnostics or [])]
    if not any(item.get("severity") == "ERROR" for item in serialized):
        serialized.append(
            {
                "code": "PRD_OPERATION_ERROR",
                "severity": "ERROR",
                "message": message,
                "source_path": "",
                "field": None,
                "section": None,
                "reference": None,
            }
        )
    return {
        "schema_version": 1,
        "valid": False,
        "summary": {
            "documents": 0,
            "errors": sum(item["severity"] == "ERROR" for item in serialized),
            "warnings": sum(item["severity"] == "WARNING" for item in serialized),
            "info": sum(item["severity"] == "INFO" for item in serialized),
        },
        "documents": [],
        "diagnostics": serialized,
    }


def _print_prd_diagnostics(diagnostics: list) -> None:
    """Render structured product diagnostics without domain logic in Typer."""
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text

    table = Table(header_style="bold cyan", expand=False)
    table.add_column("Document")
    table.add_column("Code")
    table.add_column("Severity")
    table.add_column("Field / Section")
    table.add_column("Message")
    severity_styles = {"ERROR": "red", "WARNING": "yellow", "INFO": "cyan"}
    for diagnostic in diagnostics:
        severity = diagnostic.severity.value
        code = diagnostic.code.value if isinstance(diagnostic.code, Enum) else str(diagnostic.code)
        table.add_row(
            Text(diagnostic.source_path or "-"),
            Text(code),
            Text(severity, style=severity_styles.get(severity, "white")),
            Text(diagnostic.field or diagnostic.section or "-"),
            Text(diagnostic.message),
        )
    Console(width=180).print(table)


@prd_app.command("init")
def prd_init(
    product_id: Optional[str] = typer.Argument(
        None,
        help="Optional PRD identifier, for example PRD-AUTH. Defaults to PRD.",
    ),
    project_path: str = typer.Option(
        ".",
        "--path",
        "-p",
        help="Project root where .bck-nd/product/ will be created.",
    ),
):
    """Create a canonical Markdown PRD template without overwriting files."""
    from bck_nd_hlpr.core.product import (
        ProductInvalidIdError,
        ProductService,
        ProductServiceError,
    )

    try:
        service = ProductService(project_path)
        result = service.create_document(product_id)
        relative_path = result.path.relative_to(service.project_root).as_posix()
    except ProductInvalidIdError as exc:
        typer.secho(f"[ERROR] {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=2)
    except ProductServiceError as exc:
        typer.secho(f"[ERROR] {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    typer.secho(
        f"[OK] Product requirements document created: {relative_path}",
        fg=typer.colors.GREEN,
        bold=True,
    )


@prd_app.command("list")
def prd_list(
    project_path: str = typer.Option(
        ".",
        "--path",
        "-p",
        help="Project root containing .bck-nd/product/.",
    ),
):
    """List local PRDs with lifecycle and validation summaries."""
    from bck_nd_hlpr.core.product import DiagnosticSeverity, ProductService, ProductServiceError
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text

    console = Console(width=160)
    try:
        service = ProductService(project_path)
        collection = service.load_documents()
        report = service.validate_documents(collection=collection)
    except ProductServiceError as exc:
        typer.secho(f"[ERROR] {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    if not report.documents:
        if report.diagnostics:
            _print_prd_diagnostics(report.diagnostics)
        else:
            typer.secho(
                "[--] No product requirements documents found.",
                fg=typer.colors.YELLOW,
            )
        return

    table = Table(
        title=f"Product Requirements Documents ({len(report.documents)} found)",
        header_style="bold cyan",
    )
    for column in ("ID", "Title", "Status", "Applies To", "Requirements", "Diagnostics"):
        table.add_column(column)

    for document in report.documents:
        related = [
            item
            for item in report.diagnostics
            if item.source_path == document.source_path
        ]
        errors = sum(item.severity is DiagnosticSeverity.ERROR for item in related)
        warnings = sum(item.severity is DiagnosticSeverity.WARNING for item in related)
        status_style = {
            "DRAFT": "yellow",
            "REVIEW": "blue",
            "APPROVED": "green",
            "SHIPPED": "bold green",
            "ARCHIVED": "dim",
        }.get(document.status_value, "white")
        table.add_row(
            Text(document.id or "-"),
            Text(document.title or "Untitled"),
            Text(document.status_value or "-", style=status_style),
            Text(", ".join(document.applies_to) or "-"),
            str(len(document.requirement_ids)),
            f"{errors}E / {warnings}W",
        )

    console.print(table)
    global_diagnostics = [
        item
        for item in report.diagnostics
        if item.source_path not in {document.source_path for document in report.documents}
    ]
    if global_diagnostics:
        _print_prd_diagnostics(global_diagnostics)


@prd_app.command("validate")
def prd_validate(
    product_id: Optional[str] = typer.Argument(
        None,
        help="Optional PRD identifier; omit it to validate the complete collection.",
    ),
    project_path: str = typer.Option(
        ".",
        "--path",
        "-p",
        help="Project root containing .bck-nd/product/.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit only deterministic machine-readable JSON.",
    ),
):
    """Validate product intent and its linked requirement identifiers."""
    from bck_nd_hlpr.core.product import (
        ProductInvalidIdError,
        ProductSerializationError,
        ProductService,
        ProductServiceError,
    )

    try:
        service = ProductService(project_path)
        report = service.validate_documents(product_id)
        if json_output:
            try:
                payload = report.to_dict()
            except ProductSerializationError:
                payload = _prd_operation_json(
                    "Product data could not be serialized safely."
                )
                typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
                raise typer.Exit(code=1)
            typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            if not report.documents and not report.diagnostics:
                typer.secho(
                    "[--] No product requirements documents found.",
                    fg=typer.colors.YELLOW,
                )
            elif report.diagnostics:
                _print_prd_diagnostics(report.diagnostics)
            else:
                typer.secho(
                    "[OK] All selected product requirements documents are valid.",
                    fg=typer.colors.GREEN,
                    bold=True,
                )
            typer.echo(
                "Summary: "
                f"{len(report.documents)} document(s), "
                f"{report.error_count} error(s), "
                f"{report.warning_count} warning(s), "
                f"{report.info_count} info."
            )
        if not report.valid:
            raise typer.Exit(code=1)
    except ProductInvalidIdError as exc:
        if json_output:
            typer.echo(json.dumps(_prd_operation_json(str(exc)), ensure_ascii=False, indent=2))
        else:
            typer.secho(f"[ERROR] {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=2)
    except ProductServiceError as exc:
        if json_output:
            typer.echo(
                json.dumps(
                    _prd_operation_json(str(exc), exc.diagnostics),
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            typer.secho(f"[ERROR] {exc}", fg=typer.colors.RED)
            if exc.diagnostics:
                _print_prd_diagnostics(exc.diagnostics)
        raise typer.Exit(code=1)


@prd_app.command("status")
def prd_status(
    product_id: str = typer.Argument(..., help="PRD identifier, for example PRD-AUTH."),
    new_status: str = typer.Argument(
        ...,
        help="New status: DRAFT, REVIEW, APPROVED, SHIPPED, or ARCHIVED.",
    ),
    project_path: str = typer.Option(
        ".",
        "--path",
        "-p",
        help="Project root containing .bck-nd/product/.",
    ),
):
    """Apply a validated PRD lifecycle transition with a minimal atomic edit."""
    from bck_nd_hlpr.core.product import (
        ProductInvalidIdError,
        ProductInvalidStatusError,
        ProductService,
        ProductServiceError,
        ProductTransitionBlockedError,
    )

    try:
        result = ProductService(project_path).update_status(product_id, new_status)
    except (ProductInvalidIdError, ProductInvalidStatusError) as exc:
        typer.secho(f"[ERROR] {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=2)
    except ProductTransitionBlockedError as exc:
        typer.secho(f"[ERROR] {exc}", fg=typer.colors.RED)
        if exc.diagnostics:
            _print_prd_diagnostics(exc.diagnostics)
        raise typer.Exit(code=1)
    except ProductServiceError as exc:
        typer.secho(f"[ERROR] {exc}", fg=typer.colors.RED)
        if exc.diagnostics:
            _print_prd_diagnostics(exc.diagnostics)
        raise typer.Exit(code=1)

    if result.changed:
        typer.secho(
            f"[OK] PRD {result.document.id} status updated: "
            f"{result.previous_status or '<missing>'} -> {result.new_status}",
            fg=typer.colors.GREEN,
            bold=True,
        )
    else:
        typer.secho(
            f"[OK] PRD {result.document.id} is already {result.new_status}.",
            fg=typer.colors.GREEN,
        )


# ──────────────────────────────────────────────
# SUBCOMANDOS DE REQUERIMIENTOS (bck-nd req)
# ──────────────────────────────────────────────

req_app = typer.Typer(
    name="req",
    help="Scaffold, list, update, and discover User Stories and requirements.",
    no_args_is_help=True,
)
app.add_typer(req_app, name="req")


@req_app.command("init")
def req_init(
    story_id: str = typer.Argument(..., help="Story identifier, for example US-001 or HU01."),
    file_format: str = typer.Option("md", "--format", "-f", help="Template format: md or json."),
    project_path: str = typer.Option(".", "--path", "-p", help="Project root where .bck-nd/requirements/ will be created."),
):
    """Create a requirement specification template for a new User Story."""
    import json
    import re

    normalized_id = story_id.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]*", normalized_id):
        typer.secho(
            "[ERROR] STORY_ID may contain only letters, numbers, hyphens, and underscores.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2)

    normalized_format = file_format.strip().lower().lstrip(".")
    if normalized_format not in {"md", "json"}:
        typer.secho("[ERROR] --format must be either 'md' or 'json'.", fg=typer.colors.RED)
        raise typer.Exit(code=2)

    requirements_dir = Path(project_path) / ".bck-nd" / "requirements"
    requirements_dir.mkdir(parents=True, exist_ok=True)
    target = requirements_dir / f"{normalized_id}.{normalized_format}"

    if target.exists():
        typer.secho(f"[ERROR] Requirement file already exists: {target}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    if normalized_format == "md":
        content = f"""# {normalized_id} [TODO] - Story title

- **Role**: Describe the user or stakeholder
- **Want**: Describe the desired capability
- **Benefit**: Describe the expected business value

## Business Rules
- BR01: Describe the business rule

## Acceptance Criteria
- AC01: Given a starting context When an action occurs Then describe the expected outcome

## Required Data
- field_name: data type and whether it is required

## Validations
- field_name: validation rule

## Exceptions
- ERR_EXAMPLE: Describe the exceptional condition

## Open Questions
- Add unresolved stakeholder questions here
"""
    else:
        content = json.dumps(
            {
                "story": {
                    "id": normalized_id,
                    "title": "Story title",
                    "role": "Describe the user or stakeholder",
                    "want": "Describe the desired capability",
                    "benefit": "Describe the expected business value",
                    "status": "TODO",
                },
                "business_rules": [
                    {"id": "BR01", "description": "Describe the business rule"}
                ],
                "acceptance_criteria": [
                    {
                        "id": "AC01",
                        "given": "a starting context",
                        "when": "an action occurs",
                        "then": "describe the expected outcome",
                    }
                ],
                "required_data": [
                    {"field": "field_name", "type": "data type and requirement"}
                ],
                "validations": [
                    {"field": "field_name", "rule": "validation rule"}
                ],
                "exceptions": [
                    {"code": "ERR_EXAMPLE", "description": "Describe the exceptional condition"}
                ],
                "open_questions": ["Add unresolved stakeholder questions here"],
            },
            indent=2,
        ) + "\n"

    target.write_text(content, encoding="utf-8")
    typer.secho(f"[OK] Requirement template created: {target}", fg=typer.colors.GREEN, bold=True)


@req_app.command("status")
@req_app.command("set-status")
def req_status(
    story_id: str = typer.Argument(..., help="Story identifier, for example US-001."),
    new_status: str = typer.Argument(
        ...,
        help="New status: TODO, IN_PROGRESS, TESTING, DONE, or BLOCKED.",
    ),
    project_path: str = typer.Option(
        ".",
        "--path",
        "-p",
        help="Project root containing .bck-nd/requirements/.",
    ),
):
    """Update a requirement story status in its JSON or Markdown source file."""
    import re

    from bck_nd_hlpr.core.requirements import RequirementsParser
    from rich.console import Console

    normalized_id = story_id.strip().upper()
    normalized_status = new_status.strip().upper()

    if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]*", normalized_id):
        typer.secho(
            "[ERROR] STORY_ID may contain only letters, numbers, hyphens, and underscores.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2)

    if normalized_status not in RequirementsParser.VALID_STATUSES:
        accepted = ", ".join(sorted(RequirementsParser.VALID_STATUSES))
        typer.secho(
            f"[ERROR] Invalid status '{new_status}'. Accepted statuses: {accepted}.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2)

    old_status = RequirementsParser.get_story_status(project_path, normalized_id)
    if old_status is None:
        typer.secho(
            f"[ERROR] Requirement story not found: {normalized_id}",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    if not RequirementsParser.update_story_status(
        project_path,
        normalized_id,
        normalized_status,
    ):
        typer.secho(
            f"[ERROR] Could not update requirement story: {normalized_id}",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    Console().print(
        f"✨ Story [bold]{normalized_id}[/bold] status updated: "
        f"[yellow]{old_status}[/yellow] ➔ [green]{normalized_status}[/green]"
    )


@req_app.command("list")
def req_list(
    project_path: str = typer.Argument(".", help="Path to the project root directory."),
):
    """
    List all User Stories and specifications found under .bck-nd/requirements/.
    """
    from bck_nd_hlpr.core.requirements import RequirementsParser
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich import box

    console = Console()
    specs = RequirementsParser.load_from_directory(project_path)

    if not specs:
        console.print(
            Panel(
                f"[yellow]No requirements found in [bold]{project_path}/.bck-nd/requirements/[/bold][/yellow]\n\n"
                "[dim]Create JSON specifications under .bck-nd/requirements/ (e.g. HU01.json) to define User Stories.[/dim]",
                title="[bold yellow]Requirements Not Found[/bold yellow]",
                border_style="yellow",
                box=box.ASCII2,
            )
        )
        return

    table = Table(
        title=f"Project Requirements & User Stories ({len(specs)} found)",
        box=box.ROUNDED,
        header_style="bold cyan",
    )
    table.add_column("Story ID", style="cyan bold", justify="center")
    table.add_column("Status", justify="center")
    table.add_column("Title", style="bold")
    table.add_column("Role", style="dim")
    table.add_column("Criteria", justify="right", style="green")
    table.add_column("Rules", justify="right", style="magenta")

    status_styles = {
        "TODO": "[bold yellow]TODO[/bold yellow]",
        "IN_PROGRESS": "[bold blue]IN_PROGRESS[/bold blue]",
        "TESTING": "[bold magenta]TESTING[/bold magenta]",
        "DONE": "[bold green]DONE[/bold green]",
        "BLOCKED": "[bold red]BLOCKED[/bold red]",
    }

    for spec in specs:
        story = spec.story
        raw_status = story.status.upper() if story.status else "TODO"
        status_display = status_styles.get(raw_status, f"[white]{raw_status}[/white]")

        table.add_row(
            story.id or "N/A",
            status_display,
            story.title or "Untitled",
            story.role or "-",
            str(len(spec.acceptance_criteria)),
            str(len(spec.business_rules)),
        )

    console.print()
    console.print(table)
    console.print(
        f"[dim]Tip: Run [bold cyan]bck-nd req discover <story_id>[/bold cyan] for discovery guides.[/dim]\n"
    )


@req_app.command("discover")
def req_discover(
    story_id: Optional[str] = typer.Argument(
        None, help="User Story ID to discover (e.g. HU01), or omit to list available stories."
    ),
    project_path: str = typer.Argument(
        ".", help="Path to project root directory."
    ),
):
    """
    Generate a Stakeholder Interview & Discovery Guide for a User Story.
    """
    from bck_nd_hlpr.core.requirements import RequirementsParser
    from rich.console import Console
    from rich.panel import Panel
    from rich import box

    console = Console()

    # Handle case where user runs `bck-nd req discover .`
    if story_id and (story_id == "." or (Path(story_id).is_dir() and not story_id.upper().startswith("HU"))):
        project_path = story_id
        story_id = None

    specs = RequirementsParser.load_from_directory(project_path)

    if not specs:
        console.print(
            Panel(
                f"[yellow]No requirements found in [bold]{project_path}/.bck-nd/requirements/[/bold][/yellow]\n\n"
                "[dim]Create JSON specifications under .bck-nd/requirements/ (e.g. HU01.json).[/dim]",
                title="[bold yellow]Requirements Not Found[/bold yellow]",
                border_style="yellow",
                box=box.ASCII2,
            )
        )
        return

    # If no story_id is provided, list available stories
    if not story_id:
        console.print(
            Panel(
                "[bold cyan]Available User Stories for Discovery:[/bold cyan]\n\n"
                + "\n".join(
                    f"  • [cyan bold]{spec.story.id}[/cyan bold] [{spec.story.status}] - {spec.story.title}"
                    for spec in specs
                )
                + "\n\n[dim]Usage: [bold]bck-nd req discover <story_id>[/bold][/dim]",
                title="[bold cyan]Requirements Discovery[/bold cyan]",
                border_style="cyan",
                box=box.ASCII2,
            )
        )
        return

    # Find matching story
    target_spec = None
    for spec in specs:
        if spec.story.id.upper() == story_id.upper():
            target_spec = spec
            break

    if not target_spec:
        avail = ", ".join(s.story.id for s in specs if s.story.id) or "None"
        console.print(
            f"[bold red]Error:[/bold red] Story ID '[bold]{story_id}[/bold]' not found. Available stories: {avail}"
        )
        raise typer.Exit(code=1)

    story = target_spec.story

    # Build Structured Discovery Guide
    lines = []
    lines.append("[bold white on blue] DISCOVERY & STAKEHOLDER INTERVIEW GUIDE [/bold white on blue]\n")
    lines.append(f"[bold cyan]User Story:[/bold cyan] [bold]{story.id}[/bold] [{story.status}] - {story.title}")
    if story.role:
        lines.append(f"  [bold]As a:[/bold] {story.role}")
    if story.want:
        lines.append(f"  [bold]I want:[/bold] {story.want}")
    if story.benefit:
        lines.append(f"  [bold]So that:[/bold] {story.benefit}")
    lines.append("")

    # 1. Mandatory Data Questions
    lines.append("[bold green]1. Mandatory Data & Field Specifications:[/bold green]")
    lines.append("  • What fields are strictly required vs optional?")
    lines.append("  • What are the allowed data types, formats, character limits, or regex patterns?")
    lines.append("  • Are there default values or auto-generated fields (e.g. UUID, timestamps)?")
    if target_spec.required_data:
        lines.append("  [dim]Existing Required Data Fields:[/dim]")
        for item in target_spec.required_data:
            lines.append(f"    - {item}")
    else:
        lines.append("  [dim]Existing Required Data: (None defined yet)[/dim]")
    lines.append("")

    # 2. Business Rules & Validation Questions
    lines.append("[bold magenta]2. Business Rules & Domain Validations:[/bold magenta]")
    lines.append("  • What domain constraints must be enforced before saving (e.g. uniqueness, age limits)?")
    lines.append("  • Who has permissions / authorization roles to execute this action?")
    lines.append("  • Are there state transitions or dependent records affected?")
    if target_spec.business_rules:
        lines.append("  [dim]Existing Business Rules:[/dim]")
        for br in target_spec.business_rules:
            lines.append(f"    - [magenta]{br.id}[/magenta]: {br.description}")
    else:
        lines.append("  [dim]Existing Business Rules: (None defined yet)[/dim]")
    if target_spec.validations:
        lines.append("  [dim]Existing Validations:[/dim]")
        for val in target_spec.validations:
            lines.append(f"    - {val}")
    lines.append("")

    # 3. Exception Handling Questions
    lines.append("[bold red]3. Exception Handling & Edge Cases:[/bold red]")
    lines.append("  • What should happen if invalid or duplicate data is submitted?")
    lines.append("  • What error codes and localized error messages must be returned to the client?")
    lines.append("  • How should network timeouts or external service failures be handled?")
    if target_spec.exceptions:
        lines.append("  [dim]Existing Exceptions:[/dim]")
        for exc in target_spec.exceptions:
            lines.append(f"    - {exc}")
    else:
        lines.append("  [dim]Existing Exceptions: (None defined yet)[/dim]")
    lines.append("")

    # 4. Acceptance Criteria Verification Questions
    lines.append("[bold yellow]4. Acceptance Criteria Verification Scenarios:[/bold yellow]")
    lines.append("  • What exact scenarios demonstrate that this story is DONE and verified?")
    lines.append("  • Given-When-Then criteria:")
    if target_spec.acceptance_criteria:
        for ac in target_spec.acceptance_criteria:
            lines.append(f"    - [yellow]{ac.id}[/yellow]: Given {ac.given} When {ac.when} Then {ac.then}")
    else:
        lines.append("    (No acceptance criteria defined yet)")
    lines.append("")

    # 5. Open Questions
    if target_spec.open_questions:
        lines.append("[bold cyan]5. Open Stakeholder Questions:[/bold cyan]")
        for q in target_spec.open_questions:
            lines.append(f"  • {q}")
        lines.append("")

    console.print(
        Panel(
            "\n".join(lines),
            title=f"[bold cyan]Discovery Guide — {story.id}[/bold cyan]",
            border_style="cyan",
            box=box.ASCII2,
        )
    )


if __name__ == "__main__":
    app()


