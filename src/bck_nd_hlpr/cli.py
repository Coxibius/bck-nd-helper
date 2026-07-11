import typer
import sys
from pathlib import Path
from typing import Optional

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
from bck_nd_hlpr.router import Router
from bck_nd_hlpr.scanner import ProjectScanner
from bck_nd_hlpr.narrator import Narrator
from bck_nd_hlpr.er_parser import parse_project_for_er, generate_mermaid_er
from bck_nd_hlpr.route_parser import parse_project_routes, generate_mermaid_sequence
from bck_nd_hlpr.infra_parser import parse_infra, parse_docker_compose, generate_mermaid_infra
from bck_nd_hlpr.todo_hunter import scan_for_todos, display_todos_table, get_todos_table_string
from bck_nd_hlpr.doc_generator import DocGenerator
from bck_nd_hlpr.ci_generator import generate_ci_workflow
from bck_nd_hlpr.context_dumper import ContextDumper
from bck_nd_hlpr.tree_generator import generate_project_tree
from bck_nd_hlpr.analysis import (
    ScanContext,
    get_analyzer,
    build_uml_diagram,
    build_er_diagram,
)


app = typer.Typer(
    name="bck-nd",
    help="Backend Helper: Lightweight Architecture CLI",
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    epilog="""
Key commands:
- bck-nd scan .            Full architecture overview
- bck-nd scan . --uml      UML only
- bck-nd scan . --er       ER only
- bck-nd scan . --routes   Routes only
- bck-nd prompt .          AI-ready context dump
- bck-nd flow "A -> B"     Quick ASCII flow
- bck-nd docs .            Static HTML docs
- bck-nd chat .            Interactive AI chat

Tip: Run any command with --help for detailed usage.
"""

)

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
    uml: bool = typer.Option(False, "--uml", "-u", help="Generate UML Class Diagram (Mermaid classDiagram). Supports Python (AST), C#, Java, JS/TS, PHP (Tree-sitter). Shows classes, methods, inheritance, associations. Example: bck-nd scan . --uml -o classes.mmd"),
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
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Save output to file (ANSI codes stripped automatically). Works with any flag. Example: bck-nd scan . --er -o schema.mmd"),
    provider: Optional[str] = typer.Option(None, "--provider", help="Force specific AI provider (requires --ai). Options: openai, anthropic, gemini, groq, deepseek, openrouter, ollama. Example: bck-nd scan . --ai --provider openrouter")
):
    """
    Scan a project and generate architecture outputs.

    What it can produce (depending on flags):
    - Tree, Infra map, Routes (sequence), UML, ER, Technical Debt table.
    - Optional text reports (offline explain) or AI-assisted analysis.

    Exclusive modes (choose one):
    - --uml, --er, --routes, --infra, --tree, --todo, --audit, --impact, --trace

    Notable flags:
    - --depth: recursion depth for scanning
    - --format: ascii or mermaid
    - --explain: offline text report
    - --ai/--style/--provider: AI analysis configuration
    - --impact-radius: show routes/files impacted by a given file
    - --teach, --health, --datascience, --contract, --export-dict (see help)
    - --output: write results to file

    Examples:
    - bck-nd scan .
    - bck-nd scan src --depth 5
    - bck-nd scan . --er -o schema.mmd
    - bck-nd scan . --ai --style hacker
    - bck-nd scan . --impact-radius app/api/users.py
    """
    scanner = ProjectScanner()

    # Helper para manejar salida condicional
    def output_handler(content: str, context_msg: str):
        if output:
            try:
                with open(output, "a", encoding="utf-8") as f:
                    if context_msg:
                        f.write(f"\n{'='*60}\n")
                        f.write(f"  {context_msg}\n")
                        f.write(f"{'='*60}\n\n")
                    f.write(content)
                    f.write("\n")
                typer.secho(f"💾 Result saved to: {output}", fg=typer.colors.GREEN, bold=True)
            except Exception as e:
                typer.secho(f"❌ Error writing file: {e}", fg=typer.colors.RED)
        else:
            # Imprimir en consola con decoraciones si es necesario
            if context_msg:
                # Si es bloque de codigo mermaid
                if content.strip().startswith("classDiagram") or \
                   content.strip().startswith("erDiagram") or \
                   content.strip().startswith("sequenceDiagram") or \
                   content.strip().startswith("graph"):
                    print("```mermaid")
                    print(content)
                    print("```")
                    typer.secho("Copy the above block into Mermaid.live", fg=typer.colors.BRIGHT_BLACK)
                else:
                    print(content)

    # Truncar archivo de salida al inicio para empezar limpio
    if output:
        try:
            with open(output, "w", encoding="utf-8") as f:
                f.write("")  # Truncate
        except Exception as e:
            typer.secho(f"❌ Error creating output file: {e}", fg=typer.colors.RED)

    # DETECTAR ARQUITECTURA PRIMERO para rutear parsers
    typer.secho(f"\n🔍 Analyzing architecture of '{path}'...", fg=typer.colors.CYAN, bold=True)
    arch_info = scanner.detect_architecture(path)

    # ═══════════════════════════════════════════════════════════════════
    # ANALYZER DISPATCH (Strategy Pattern) — see bck_nd_hlpr.analysis
    # Each exclusive mode is a plug-and-play Analyzer. Adding a new mode
    # does NOT require touching this orchestrator: register a new Analyzer
    # class in analysis.py and declare its typer Option above.
    # ═══════════════════════════════════════════════════════════════════
    ctx = ScanContext(path=path, depth=depth, arch_info=arch_info, plain=bool(output))

    def emit_result(result) -> None:
        """Uniform output handling for analyzer results (console vs file)."""
        # Always surface warnings, even when the result is OK (e.g., no routes found)
        warning_text = getattr(result, "warning", None)
        if warning_text:
            warn_color_name = (getattr(result, "warning_color", "yellow") or "yellow").upper()
            warn_color = getattr(typer.colors, warn_color_name, typer.colors.YELLOW)
            typer.secho(warning_text, fg=warn_color, bold=warn_color_name.lower() == "green")

        # If analyzer failed, stop after showing the warning
        if not result.ok:
            return

        content = getattr(result, "content", None)
        # Guard against None/empty content to avoid AttributeError on .strip()
        if not content:
            return

        if output:
            output_handler(content, result.title)
            return

        body = content.strip()
        if not body:
            return

        if body.startswith(("classDiagram", "erDiagram", "sequenceDiagram", "graph")):
            print("```mermaid")
            print(content)
            print("```")
            typer.secho("Copy the above block into Mermaid.live", fg=typer.colors.BRIGHT_BLACK)
        else:
            print(content)

    mode_flags = {
        "tree": tree, "uml": uml, "er": er, "routes": routes, "infra": infra,
        "todo": todo, "audit": audit, "impact": impact, "trace": trace,
    }
    selected_mode = next((name for name, active in mode_flags.items() if active), None)

    if selected_mode:
        analyzer = get_analyzer(selected_mode)
        banner_color = getattr(typer.colors, analyzer.banner_color.upper(), typer.colors.MAGENTA)
        typer.secho(f"\n{analyzer.banner}", fg=banner_color, bold=True)
        if analyzer.intro:
            typer.secho(f"{analyzer.intro}\n", fg=typer.colors.BRIGHT_BLACK)
        emit_result(analyzer.run(ctx))
        return

    # MODO IMPACT RADIUS (NEW)
    if impact_radius:
        typer.secho(f"\n[IMPACT RADIUS] 💥 CALCULATING TRANSITIVE IMPACT FOR: {impact_radius}", fg=typer.colors.MAGENTA, bold=True)
        
        from bck_nd_hlpr.route_parser import get_routes_affected_by_file
        
        try:
            abs_path = str(Path(impact_radius).resolve())
            if not Path(abs_path).exists():
                typer.secho(f"⚠️ Friendly warning: The file '{impact_radius}' does not exist.", fg=typer.colors.YELLOW)
                sys.exit(0)
                
            report = get_routes_affected_by_file(path, abs_path, max_depth=depth)
            
            typer.secho(f"\n🎯 Target File: {report['changed_file']}", fg=typer.colors.CYAN)
            
            if not report["affected_files"]:
                typer.secho("✨ Good news! This file has no dependencies or does not affect any other files in the project.", fg=typer.colors.GREEN)
                sys.exit(0)
                
            typer.secho(f"\n🔗 Transitively Affected Files ({len(report['affected_files'])}):", fg=typer.colors.YELLOW)
            for f in report["affected_files"]:
                typer.secho(f"  - {f}")
                
            typer.secho(f"\n🚨 Affected API Routes ({len(report['affected_routes'])}):", fg=typer.colors.RED, bold=True)
            if not report["affected_routes"]:
                typer.secho("  None. No API endpoints seem to be transitively broken by this change.", fg=typer.colors.GREEN)
            else:
                for r in report["affected_routes"]:
                    typer.secho(f"  - [{r['method']}] {r['path']} (in {r['file']})")
                    
        except Exception as e:
            typer.secho(f"⚠️ Could not calculate impact radius: {e}", fg=typer.colors.YELLOW)
            
        sys.exit(0)

    # MODO CONTRACT MAP (NEW)
    if contract:
        typer.secho(f"\n[CONTRACT] 📜 GENERATING API CONTRACT MAP:", fg=typer.colors.MAGENTA, bold=True)
        
        from bck_nd_hlpr.route_parser import generate_api_contract_map
        
        try:
            contracts = generate_api_contract_map(path, max_depth=depth)
            
            if not contracts:
                typer.secho("⚠️ No routes or models found to generate a contract map.", fg=typer.colors.YELLOW)
                sys.exit(0)
                
            if output:
                import json
                if output.endswith(".json"):
                    output_handler(json.dumps(contracts, indent=2), "")
                else:
                    # Markdown table
                    md_lines = ["| Route | File | Matched Model | Columns |", "|---|---|---|---|"]
                    for c in contracts:
                        cols = ", ".join(c['columns'].keys()) if c['columns'] else "None"
                        model = c['matched_model'] or "None (Pure HTTP)"
                        md_lines.append(f"| {c['route']} | {c['file']} | {model} | {cols} |")
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
                    model = c['matched_model'] or "[italic bright_black]None (Pure HTTP)[/italic bright_black]"
                    cols = ", ".join(c['columns'].keys()) if c['columns'] else "-"
                    table.add_row(c['route'], c['file'], model, cols)
                    
                console.print(table)
                
        except Exception as e:
            typer.secho(f"⚠️ Could not generate contract map: {e}", fg=typer.colors.RED)
            
        sys.exit(0)

    # ═══════════════════════════════════════════════════════════════════
    # FUTURE FLAGS — Stubs inactivos (no rompen ejecución actual)
    # ═══════════════════════════════════════════════════════════════════

    if teach:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text
        
        console = Console()
        scanner = ProjectScanner()
        path_list = scanner.get_onboarding_path(path)
        
        if not path_list:
            console.print(Panel("[bold red]No project structure detected to create an onboarding path.[/bold red]"))
            sys.exit(1)
            
        console.print("\n[bold cyan]🎓 Pedagogical Reading Path Generated![/bold cyan]")
        console.print("[italic]Follow this sequence to quickly understand the project architecture:[/italic]\n")
        
        table = Table(show_header=True, header_style="bold magenta", border_style="bright_black")
        table.add_column("Step", style="bold white", justify="right")
        table.add_column("File Path", style="cyan")
        table.add_column("Calculated Role", style="yellow")
        table.add_column("Hint / Why it matters", style="white")
        
        for i, item in enumerate(path_list, 1):
            tier = item["tier"]
            role_color = "bold cyan" if tier == 1 else "bold magenta" if tier == 2 else "bold yellow"
            
            table.add_row(
                str(i),
                item["file"],
                f"[{role_color}]{item['role']}[/{role_color}]",
                item["hint"]
            )
            
        console.print(table)
        console.print("\n[bold green]Happy Onboarding![/bold green] 🚀")
        sys.exit(0)

    if health:
        typer.secho(f"\n🏥 [HEALTH] CALCULATING PROJECT HEALTH SCORE:", fg=typer.colors.CYAN, bold=True)
        
        result = scanner.calculate_health_score(path, max_depth=depth)
        score = result["score"]
        grade = result["grade"]
        breakdown = result["breakdown"]
        
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
        
        c_risks = breakdown["critical_risks"]
        if c_risks > 0:
            report_text.append(f" -{c_risks * 25} points due to {c_risks} Critical Security risk(s)\n", style="red")
            
        h_risks = breakdown["high_risks"]
        if h_risks > 0:
            report_text.append(f" -{h_risks * 10} points due to {h_risks} High/Warning Security risk(s)\n", style="yellow")
            
        f_bugs = breakdown["fixme_bugs"]
        if f_bugs > 0:
            report_text.append(f" -{f_bugs * 3} points due to {f_bugs} FIXME/BUG/XXX(s)\n", style="magenta")
            
        t_hacks = breakdown["todos_hacks"]
        if t_hacks > 0:
            report_text.append(f" -{t_hacks * 1} points due to {t_hacks} TODO/HACK(s)\n", style="bright_black")
            
        if score == 100:
            report_text.append(" 🎉 Perfect Score! No technical debt or security risks detected.\n", style="green")
            
        panel = Panel(report_text, title="Project Health Report Card", border_style=color)
        
        if output:
            output_handler(report_text.plain, "")
        else:
            console.print(panel)
            
        sys.exit(0)

    if datascience:
        typer.secho("\n📊 [DATA SCIENCE] Data Lineage Map", fg=typer.colors.CYAN)
        scanner = ProjectScanner()
        mermaid_chart = scanner.scan_notebooks(path)
        
        if not mermaid_chart:
            typer.secho("No Jupyter Notebooks (.ipynb) with data lineages found.", fg=typer.colors.YELLOW)
        else:
            if output:
                with open(output, "w", encoding="utf-8") as f:
                    f.write(mermaid_chart)
                typer.secho(f"✅ Data Lineage Map saved to {output}", fg=typer.colors.GREEN)
            else:
                print(mermaid_chart)
                
        sys.exit(0)

    if export_dict:
        from bck_nd_hlpr.er_parser import export_entities_as_dict
        
        fmt = export_dict.lower()
        if fmt not in ["json", "csv"]:
            typer.secho(f"❌ Error: Invalid format '{fmt}' for --export-dict. Use 'json' or 'csv'.", fg=typer.colors.RED)
            sys.exit(1)
            
        result = export_entities_as_dict(path, fmt)
        
        if output:
            with open(output, "w", encoding="utf-8") as f:
                f.write(result)
            typer.secho(f"✅ Data Dictionary exported to {output}", fg=typer.colors.GREEN)
        else:
            print(result)
            
        sys.exit(0)

    if arch_info['framework'] != 'Unknown':
        typer.secho(f"💻 Framework detected: {arch_info['framework']}", fg=typer.colors.GREEN)
    if arch_info.get('architecture'):
        typer.secho(f"🏭 Architecture: {arch_info['architecture']}", fg=typer.colors.BLUE)
    if arch_info.get('features'):
        typer.secho(f"✨ Features: {', '.join(arch_info['features'])}", fg=typer.colors.YELLOW)
    
    # Resumen
    if arch_info.get('summary'):
        typer.secho(f"\n📝 {arch_info['summary']}", fg=typer.colors.WHITE)
    
    # ESCANEO DE ARCHIVOS
    typer.secho(f"\n📂 Scanning files (depth: {depth})...", fg=typer.colors.YELLOW)
    flow_string = scanner.scan(path, max_depth=depth)
    
    if not flow_string:
        typer.secho(f"\n❌ No files found in '{path}' with depth {depth}.", fg=typer.colors.RED)
        typer.secho(f"💡 Try increasing depth: bck-nd scan {path} --depth {depth + 2}", fg=typer.colors.YELLOW)
        return

    # 1. DIBUJO (Solo si está activado y no se seleccionaron reportes locales)
    # Por defecto, mostraremos la arquitectura completa (UML, ER, API, Infra, TODOs)
    if graph and not any([explain, ai]):
        typer.secho("\n📊 PROJECT ARCHITECTURE (COMPLETE):", fg=typer.colors.MAGENTA, bold=True)

        # 0. TREE (Project Structure)
        typer.secho("\n[TREE] 🌳 PROJECT STRUCTURE:", fg=typer.colors.CYAN, bold=True)
        tree_output = generate_project_tree(path, depth=depth)
        if tree_output:
            if output:
                output_handler(tree_output, "[TREE] Project Structure")
            else:
                print(tree_output)
        else:
            typer.secho("⚠️ Could not generate project tree.", fg=typer.colors.YELLOW)

        # 1. INFRA
        typer.secho("\n[INFRA] INFRASTRUCTURE MAP:", fg=typer.colors.CYAN, bold=True)
        compose_file = parse_infra(path)
        if compose_file:
            services = parse_docker_compose(compose_file)
            if services:
                infra_code = generate_mermaid_infra(services)
                output_handler(infra_code, "[INFRA] Infrastructure Map")
            else:
                typer.secho("⚠️ No services found in docker-compose.", fg=typer.colors.YELLOW)
        else:
            typer.secho("⚠️ docker-compose.yml not detected in the directory.", fg=typer.colors.YELLOW)

        # 2. ROUTES
        typer.secho("\n[API] ROUTES MAP:", fg=typer.colors.CYAN, bold=True)
        detected_routes = parse_project_routes(path, max_depth=depth)
        if detected_routes:
            seq_code = generate_mermaid_sequence(detected_routes)
            if seq_code:
                output_handler(seq_code, "[API] Routes Map")
            else:
                typer.secho("⚠️ Could not render the routes.", fg=typer.colors.YELLOW)
        else:
            typer.secho("⚠️ No API routes detected (Flask/FastAPI).", fg=typer.colors.YELLOW)

        # 3. UML
        typer.secho("\n[UML] CLASS DIAGRAM:", fg=typer.colors.CYAN, bold=True)
        uml_code = build_uml_diagram(path, depth, arch_info)
        if uml_code:
            output_handler(uml_code, "[UML] Class Diagram")
        else:
            typer.secho("⚠️ No classes detected for UML.", fg=typer.colors.YELLOW)
            
        # 4. ER
        typer.secho("\n[ER] ENTITY-RELATIONSHIP:", fg=typer.colors.CYAN, bold=True)
        er_code = build_er_diagram(path, depth, arch_info)
        if er_code:
            output_handler(er_code, "[ER] Entity-Relationship")
        else:
            typer.secho("⚠️ No database models detected.", fg=typer.colors.YELLOW)

        # 5. TODOs
        typer.secho("\n[TODO] TECHNICAL DEBT:", fg=typer.colors.CYAN, bold=True)
        todos = scan_for_todos(path, max_depth=depth)
        if todos:
            if output:
                table_str = get_todos_table_string(todos, plain=True)
                output_handler(table_str, "[TODO] Technical Debt")
            else:
                display_todos_table(todos)
        else:
            typer.secho("✨ Awesome! No technical debt found.", fg=typer.colors.GREEN, bold=True)

    narrator = Narrator(force_provider=provider)

    # 2. LOCAL (Reporte de texto)
    if explain:
        typer.secho("\n📄 LOCAL REPORT:", fg=typer.colors.CYAN, bold=True)
        report = narrator.explain(flow_string, use_ai=False)
        if output:
             output_handler(report, "")
        else:
             print(report)

    # 3. IA CON PERSONALIDAD Y CONTEXTO
    if ai:
        from bck_nd_hlpr.ai_providers import NoAPIKeyError

        # Early exit with a styled error if no provider is available
        if narrator.provider is None:
            typer.secho("\n❌ No AI provider configured.", fg=typer.colors.RED, bold=True)
            typer.secho("Set one of the following environment variables and retry:\n", fg=typer.colors.YELLOW)
            typer.secho("  OPENAI_API_KEY       — OpenAI GPT models          https://platform.openai.com/api-keys")
            typer.secho("  ANTHROPIC_API_KEY    — Anthropic Claude            https://console.anthropic.com/")
            typer.secho("  GOOGLE_API_KEY       — Google Gemini               https://aistudio.google.com/app/apikey")
            typer.secho("  OPENROUTER_API_KEY   — 200+ models, free tier      https://openrouter.ai/keys", fg=typer.colors.GREEN)
            typer.secho("  OLLAMA_HOST          — Local Ollama (no key)       https://ollama.com/", fg=typer.colors.GREEN)
            typer.secho("\nExample (Windows):  set OPENROUTER_API_KEY=sk-or-...", fg=typer.colors.BRIGHT_BLACK)
            typer.secho("Example (Mac/Linux): export OPENROUTER_API_KEY=sk-or-...", fg=typer.colors.BRIGHT_BLACK)
            return

        # Recuperamos contexto (Docs) para enviar a la IA
        docs = scanner.get_docs_content(path)

        # Añadir información arquitectónica al contexto
        arch_context = f"\n\n--- DETECTED ARCHITECTURE ---\n"
        arch_context += f"Framework: {arch_info.get('framework', 'Unknown')}\n"
        arch_context += f"Type: {arch_info.get('architecture', 'Unknown')}\n"
        arch_context += f"Features: {', '.join(arch_info.get('features', []))}\n"

        # Generar Diagramas Avanzados para dar más contexto a la IA
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
        if arch_info.get('framework') == '.NET Core / C#':
            from bck_nd_hlpr.csharp_parser import parse_project_for_csharp_er, parse_project_for_csharp_uml
            from bck_nd_hlpr.er_parser import generate_mermaid_er
            from bck_nd_hlpr.uml_parser import generate_mermaid_class_diagram

            entities = parse_project_for_csharp_er(path, max_depth=depth)
            if entities:
                extra_diagrams += "Entity-Relationship:\n```mermaid\n" + generate_mermaid_er(entities) + "\n```\n"

            classes = parse_project_for_csharp_uml(path, max_depth=depth)
            if classes:
                extra_diagrams += "UML Class Diagram:\n```mermaid\n" + generate_mermaid_class_diagram(classes) + "\n```\n"
        else:
            from bck_nd_hlpr.er_parser import parse_project_for_er, generate_mermaid_er
            entities = parse_project_for_er(path, max_depth=depth)
            if entities:
                extra_diagrams += "Entity-Relationship:\n```mermaid\n" + generate_mermaid_er(entities) + "\n```\n"

            uml_code = scanner.scan_uml(path, max_depth=depth)
            if uml_code and "note " not in uml_code.lower():
                extra_diagrams += "UML Class Diagram:\n```mermaid\n" + uml_code + "\n```\n"

        if docs:
            full_context = flow_string + arch_context + extra_diagrams + "\n\n--- PROJECT DOCUMENTATION ---\n" + docs
        else:
            full_context = flow_string + arch_context + extra_diagrams

        typer.secho(f"\n🤖 AI ANALYSIS (Style: {style.upper()}):", fg=typer.colors.MAGENTA, bold=True)
        try:
            ai_response = narrator.explain(full_context, use_ai=True, style=style)
        except NoAPIKeyError as e:
            typer.secho(f"\n❌ {e}", fg=typer.colors.RED, bold=True)
            return

        if output:
            output_handler(ai_response, "")
        else:
            print(ai_response)

@app.command()
def docs(
    path: str = typer.Argument(".", help="Path to the project to document. Use '.' for current dir. Example: bck-nd docs ./my-api"),
    output: str = typer.Option("docs", "--output", "-o", help="Output directory for the HTML portal (created if missing). Example: bck-nd docs . -o site")
):
    """
    Generate a static HTML documentation portal (Mermaid-powered).

    Includes:
    - Infra map (docker-compose)
    - API routes (sequence diagrams)
    - UML class diagram
    - ER diagram (ORM models)
    - Technical debt table

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
        from bck_nd_hlpr.tui_app import ArchitectureExplorer
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
        from bck_nd_hlpr.csharp_parser import parse_project_for_csharp_er, parse_project_for_csharp_uml
        from bck_nd_hlpr.er_parser import generate_mermaid_er
        from bck_nd_hlpr.uml_parser import generate_mermaid_class_diagram
        
        entities = parse_project_for_csharp_er(path, max_depth=depth)
        if entities:
            extra_diagrams += "Entity-Relationship:\n```mermaid\n" + generate_mermaid_er(entities) + "\n```\n"
        
        classes = parse_project_for_csharp_uml(path, max_depth=depth)
        if classes:
            extra_diagrams += "UML Class Diagram:\n```mermaid\n" + generate_mermaid_class_diagram(classes) + "\n```\n"
    else:
        from bck_nd_hlpr.er_parser import parse_project_for_er, generate_mermaid_er
        entities = parse_project_for_er(path, max_depth=depth)
        if entities:
            extra_diagrams += "Entity-Relationship:\n```mermaid\n" + generate_mermaid_er(entities) + "\n```\n"
            
        uml_code = scanner.scan_uml(path, max_depth=depth)
        if uml_code and "class Empty" not in uml_code:
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
    output: str = typer.Option("ai_context.txt", "--output", "-o", help="Output file path/name for the context dump (default: ai_context.txt in current dir). Example: bck-nd prompt . -o context.txt"),
    depth: int = typer.Option(4, "--depth", "-d", help="Directory scan depth (default: 4). Increase for deep project structures. Example: bck-nd prompt . --depth 6"),
    max_core_files: Optional[int] = typer.Option(None, "--max-core-files", help="Maximum number of core files to include in the context dump (default: 8 for mobile, 5 for backend)."),
):
    """
    Export an AI-ready context file (project tree, UML, ER, core files).

    What you get (single .txt):
    - <project_tree>: filtered directory tree
    - <architecture_uml>: Mermaid classDiagram
    - <architecture_er>: Mermaid erDiagram
    - <core_files>: prioritized key files

    Usage:
    1) bck-nd prompt .
    2) Open ai_context.txt (or custom path)
    3) Copy/paste into your LLM as the first message

    Examples:
    - bck-nd prompt .
    - bck-nd prompt /my/project -o ctx.txt
    - bck-nd prompt . --depth 6
    """
    if output == "-":
        dumper = ContextDumper(path=path, depth=depth, max_core_files=max_core_files)
        context = dumper.build()
        print(context)
        return

    from rich.console import Console
    from rich.panel import Panel
    from rich import box

    console = Console(force_terminal=True, highlight=False)

    console.print(
        Panel.fit(
            "[bold cyan]bck-nd Context Dump[/bold cyan]\n"
            "[dim]Generating LLM-optimized context file...[/dim]",
            border_style="cyan",
            box=box.ASCII2,
        )
    )

    dumper = ContextDumper(path=path, depth=depth, max_core_files=max_core_files)

    typer.secho("  [1/4] Building directory tree...", fg=typer.colors.CYAN)
    tree = dumper.get_project_tree()

    typer.secho("  [2/4] Generating UML diagram...", fg=typer.colors.MAGENTA)
    uml = dumper.get_uml_diagram()

    typer.secho("  [3/4] Generating ER diagram...", fg=typer.colors.MAGENTA)
    er = dumper.get_er_diagram()

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
    uml_status  = "[green][OK] Generated[/green]" if uml else "[yellow][--] No classes detected[/yellow]"
    er_status   = "[green][OK] Generated[/green]" if er  else "[yellow][--] No models detected[/yellow]"

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


if __name__ == "__main__":
    app()
