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
from bck_nd_hlpr.traceability import parse_project_traceability, generate_mermaid_traceability
from bck_nd_hlpr.tree_generator import generate_project_tree


app = typer.Typer(
    name="bck-nd",
    help="Backend Helper: Lightweight Architecture CLI",
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    epilog="""
\b
QUICK REFERENCE:

  Scanning & Diagrams:
    bck-nd scan .              Full architecture overview (Tree+UML+ER+Routes+Infra+TODOs)
    bck-nd scan . --uml        UML Class Diagram only
    bck-nd scan . --er         Entity-Relationship Diagram only
    bck-nd scan . --routes     API Routes Sequence Diagram only
    bck-nd scan . --infra      Docker Compose Infrastructure Map only
    bck-nd scan . --tree       Project directory tree only

  Analysis & Reports:
    bck-nd scan . --todo       Technical Debt Scanner (TODO/FIXME/HACK/BUG)
    bck-nd scan . --audit      Security Audit (secrets, keys, IPs)
    bck-nd scan . --impact     Dependency Heatmap (change risk)
    bck-nd scan . --trace      Route-to-DB traceability graph
    bck-nd scan . --explain    Offline text report (Controllers/Models/Services)
    bck-nd scan . --ai         AI-powered analysis (BYO-Key: OpenAI/Anthropic/Gemini/Ollama)

  Other Commands:
    bck-nd prompt .            Export LLM-optimized context file for ChatGPT/Claude
    bck-nd flow "A -> B -> C"  Generate quick ASCII flow diagram from string
    bck-nd docs .              Generate static HTML documentation portal
    bck-nd chat .              Interactive AI chat about your codebase
    bck-nd explore             Launch interactive TUI explorer
    bck-nd init-ci             Setup GitHub Actions for auto-docs on Pages

  Saving Output:
    bck-nd scan . --er -o schema.mmd    Save any diagram/report to file
    bck-nd prompt . -o context.txt      Custom output file name

  Tip: Run any command with --help for detailed usage and examples.
       Example: bck-nd scan --help
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
    📐 Generate an ASCII diagram from a manual string.

    \b
    Syntax:
      A -> B            Connection from A to B
      [X, Y, Z]         Multiple nodes in same position
      ;                 New row / line break
      A [DB]            Rendered as database cylinder
      A [Service]       Rendered as soft box
      A [?] or A [IF]   Rendered as decision diamond

    \b
    Examples:
      bck-nd flow "Client -> API -> Database"
      bck-nd flow "Client -> LoadBalancer -> [API_v1, API_v2] ; API_v1 -> Redis"
      bck-nd flow "User -> Auth [Service] -> JWT [Token] -> API"
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
    ai: bool = typer.Option(False, "--ai", help="Run AI-powered analysis. Auto-detects API keys (OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY, OLLAMA_HOST) or falls back to webhook. Example: bck-nd scan . --ai --style hacker"),
    style: str = typer.Option("pro", "--style", "-s", help="AI personality (requires --ai). Options: pro (architect), hacker (security), soviet (efficiency), eli5 (simple), ramsay (critical), jarvis (elegant), corporate (buzzwords), medieval (wizard), doom (bug hunter). Example: bck-nd scan . --ai --style ramsay"),
    format: str = typer.Option("ascii", "--format", "-f", help="Output format: 'ascii' (terminal boxes) or 'mermaid' (graph TD code for Notion/GitHub/Obsidian + terminal preview). Example: bck-nd scan . --format mermaid"),
    uml: bool = typer.Option(False, "--uml", "-u", help="Generate UML Class Diagram (Mermaid classDiagram). Supports Python (AST), C#, Java, JS/TS, PHP (Tree-sitter). Shows classes, methods, inheritance, associations. Example: bck-nd scan . --uml -o classes.mmd"),
    er: bool = typer.Option(False, "--er", help="Generate Entity-Relationship Diagram (Mermaid erDiagram). Scans ORMs: SQLAlchemy, Django, Entity Framework, Prisma, Drizzle, Sequelize, Mongoose, Laravel/Eloquent, JPA, and raw SQL. Example: bck-nd scan . --er -o schema.mmd"),
    routes: bool = typer.Option(False, "--routes", help="Generate API Routes Sequence Diagram (Mermaid sequenceDiagram). Scans Flask, FastAPI, Express, NestJS endpoints. Shows Client -> API interactions. Example: bck-nd scan . --routes"),
    infra: bool = typer.Option(False, "--infra", help="Generate Infrastructure Diagram from docker-compose.yml (Mermaid graph LR). Shows services, images, dependencies. DB services as cylinders. Example: bck-nd scan . --infra"),
    todo: bool = typer.Option(False, "--todo", help="Scan for technical debt: TODO, FIXME, HACK, XXX, BUG comments. Color-coded Rich table with file, line, type, message. Example: bck-nd scan . --todo -o debt.txt"),
    audit: bool = typer.Option(False, "--audit", help="Security audit: detects hardcoded AWS keys, private PEMs, DB passwords, API tokens, IPs. Reports Critical/High/Warning risks. Example: bck-nd scan . --audit"),
    impact: bool = typer.Option(False, "--impact", help="Dependency heatmap: ranks files by import count. Risk categories: CORE, SHARED, PERIPHERAL. Example: bck-nd scan . --impact"),
    trace: bool = typer.Option(False, "--trace", help="Route-to-DB traceability graph (Mermaid graph LR). Traces routes -> services -> models via AST. Supports Python (FastAPI/Flask). Example: bck-nd scan . --trace"),
    tree: bool = typer.Option(False, "--tree", help="ASCII directory tree with Unicode box-drawing. Auto-filters noise (node_modules, venv, .git, __pycache__). Example: bck-nd scan . --tree --depth 5"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Save output to file (ANSI codes stripped automatically). Works with any flag. Example: bck-nd scan . --er -o schema.mmd"),
    provider: Optional[str] = typer.Option(None, "--provider", help="Force specific AI provider (requires --ai). Options: openai, anthropic, gemini, groq, deepseek, openrouter, ollama, webhook. Example: bck-nd scan . --ai --provider ollama")
):
    """
    🕵️ Scans a project and automatically detects its architecture.

    \b
    DEFAULT MODE (no flags):
      Runs a full architecture overview generating:
      Tree + Infra Map + API Routes + UML + ER + Technical Debt

    \b
    EXCLUSIVE MODES (use one at a time):
      --uml        UML Class Diagram only
      --er         Entity-Relationship Diagram only
      --routes     API Routes Sequence Diagram only
      --infra      Docker Compose Infrastructure Map only
      --tree       Project directory tree only
      --todo       Technical Debt report only
      --audit      Security Audit report only
      --impact     Dependency Heatmap only
      --trace      Route-to-DB Traceability only

    \b
    COMBINABLE FLAGS:
      --explain    Add offline text report (Controllers/Models/Services)
      --ai         Add AI-powered analysis (auto-detects API keys)
      --no-graph   Skip diagrams (useful with --ai for text-only)
      -o FILE      Save output to file

    \b
    EXAMPLES:
      bck-nd scan .                          Full overview
      bck-nd scan src --depth 5              Deep scan of src/
      bck-nd scan . --er -o schema.mmd       Export ER to file
      bck-nd scan . --ai --style hacker      AI security review
      bck-nd scan . --ai --provider ollama   Force local Ollama
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

    # Funciones de apoyo para UML y ER
    def get_uml_code():
        framework = arch_info.get('framework', '')
        is_csharp = framework == '.NET Core / C#'
        is_express = framework == 'Express.js'
        is_nextjs = framework == 'Next.js'
        is_django = framework == 'Django'
        is_spring = framework in ['Spring Boot', 'Java (Maven)', 'Java (Gradle)']
        is_laravel = framework in ['Laravel', 'PHP']
        
        uml_diagram = None
        if is_csharp:
            from bck_nd_hlpr.csharp_parser import parse_project_for_csharp_uml
            from bck_nd_hlpr.uml_parser import generate_mermaid_class_diagram
            classes = parse_project_for_csharp_uml(path, max_depth=depth)
            if classes:
                uml_diagram = generate_mermaid_class_diagram(classes)
        elif is_express or is_nextjs:
            from bck_nd_hlpr.js_parser import parse_project_for_js_uml
            from bck_nd_hlpr.uml_parser import generate_mermaid_class_diagram
            classes = parse_project_for_js_uml(path, max_depth=depth)
            if classes:
                uml_diagram = generate_mermaid_class_diagram(classes)
        elif is_django:
            from bck_nd_hlpr.django_parser import parse_project_for_django_uml
            from bck_nd_hlpr.uml_parser import generate_mermaid_class_diagram
            classes = parse_project_for_django_uml(path, max_depth=depth)
            if classes:
                uml_diagram = generate_mermaid_class_diagram(classes)
        elif is_spring:
            from bck_nd_hlpr.java_parser import parse_project_for_java_uml
            from bck_nd_hlpr.uml_parser import generate_mermaid_class_diagram
            classes = parse_project_for_java_uml(path, max_depth=depth)
            if classes:
                uml_diagram = generate_mermaid_class_diagram(classes)
        elif is_laravel:
            from bck_nd_hlpr.php_parser import parse_project_for_php_uml
            from bck_nd_hlpr.uml_parser import generate_mermaid_class_diagram
            classes = parse_project_for_php_uml(path, max_depth=depth)
            if classes:
                uml_diagram = generate_mermaid_class_diagram(classes)
        else:
            uml_code = scanner.scan_uml(path, max_depth=depth)
            if uml_code and "class Empty" not in uml_code:
                uml_diagram = uml_code
        return uml_diagram

    def get_er_code():
        framework = arch_info.get('framework', '')
        is_csharp = framework == '.NET Core / C#'
        is_express = framework == 'Express.js'
        is_nextjs = framework == 'Next.js'
        is_django = framework == 'Django'
        is_spring = framework in ['Spring Boot', 'Java (Maven)', 'Java (Gradle)']
        is_laravel = framework in ['Laravel', 'PHP']
        
        from bck_nd_hlpr.er_parser import parse_project_for_er, generate_mermaid_er
        
        entities = None
        if is_csharp:
            from bck_nd_hlpr.csharp_parser import parse_project_for_csharp_er
            entities = parse_project_for_csharp_er(path, max_depth=depth)
        elif is_express or is_nextjs:
            from bck_nd_hlpr.js_parser import parse_project_for_js_er
            entities = parse_project_for_js_er(path, max_depth=depth)
        elif is_django:
            from bck_nd_hlpr.django_parser import parse_project_for_django_er
            entities = parse_project_for_django_er(path, max_depth=depth)
        elif is_spring:
            from bck_nd_hlpr.java_parser import parse_project_for_java_er
            entities = parse_project_for_java_er(path, max_depth=depth)
        elif is_laravel:
            from bck_nd_hlpr.php_parser import parse_project_for_php_er
            entities = parse_project_for_php_er(path, max_depth=depth)
        else:
            entities = parse_project_for_er(path, max_depth=depth)
            
        er_diagram = None
        if entities:
            gen_er = generate_mermaid_er(entities)
            if gen_er:
                er_diagram = gen_er
        return er_diagram

    # MODO TREE EXCLUSIVO
    if tree:
        typer.secho(f"\n[TREE] 🌳 PROJECT STRUCTURE:", fg=typer.colors.CYAN, bold=True)
        tree_output = generate_project_tree(path, depth=depth)
        if tree_output:
            output_handler(tree_output, "Project Structure")
        else:
            typer.secho("⚠️ Could not generate project tree.", fg=typer.colors.YELLOW)
        return

    # MODO UML EXCLUSIVO
    if uml:
        typer.secho(f"\n[UML] GENERATING CLASS DIAGRAM (Mermaid):", fg=typer.colors.MAGENTA, bold=True)
        uml_code = get_uml_code()
        if uml_code:
            output_handler(uml_code, "Mermaid Code")
        else:
            typer.secho("⚠️ No classes detected for UML.", fg=typer.colors.YELLOW)
        return

    # MODO ER (ENTITY-RELATIONSHIP)
    if er:
        typer.secho(f"\n[ER] GENERATING ER DIAGRAM (Mermaid):", fg=typer.colors.MAGENTA, bold=True)
        er_code = get_er_code()
        if er_code:
            output_handler(er_code, "Mermaid Code")
        else:
            typer.secho("⚠️ No database models detected.", fg=typer.colors.YELLOW)
        return
    
    # MODO ROUTES (API MAP)
    if routes:
        typer.secho(f"\n[API] GENERATING ROUTES MAP (Mermaid Sequence):", fg=typer.colors.MAGENTA, bold=True)
        detected_routes = parse_project_routes(path, max_depth=depth)
        seq_code = generate_mermaid_sequence(detected_routes)
        
        if not seq_code:
            typer.secho("⚠️ No API routes detected (Flask/FastAPI).", fg=typer.colors.YELLOW)
        else:
            output_handler(seq_code, "Mermaid Code")
        return
    
    # MODO INFRA (DOCKER COMPOSE)
    if infra:
        typer.secho(f"\n[INFRA] GENERATING INFRASTRUCTURE DIAGRAM (Mermaid):", fg=typer.colors.MAGENTA, bold=True)
        compose_file = parse_infra(path)
        
        if not compose_file:
            typer.secho("⚠️ docker-compose.yml not detected in the directory.", fg=typer.colors.YELLOW)
            return
        
        typer.secho(f"📦 Found: {compose_file}", fg=typer.colors.GREEN)
        services = parse_docker_compose(compose_file)
        
        if not services:
            typer.secho("⚠️ No services found in docker-compose.", fg=typer.colors.YELLOW)
            return
        
        infra_code = generate_mermaid_infra(services)
        output_handler(infra_code, "Mermaid Code")
        return
    
    # MODO TODO HUNTER (TECHNICAL DEBT)
    if todo:
        typer.secho(f"\n[TODO] 🧹 SCANNING TECHNICAL DEBT:", fg=typer.colors.CYAN, bold=True)
        typer.secho(f"Searching for: TODO, FIXME, HACK, XXX, BUG...\n", fg=typer.colors.BRIGHT_BLACK)
        
        todos = scan_for_todos(path, max_depth=depth)
        
        if not todos:
            typer.secho("✨ Awesome! No technical debt found.", fg=typer.colors.GREEN, bold=True)
            return

        if output:
            # User request: NO ANSI CODES in file output
            table_str = get_todos_table_string(todos, plain=True)
            output_handler(table_str, "")
        else:
            display_todos_table(todos)
        return

    # MODO AUDITOR SEGURIDAD (NEW)
    if audit:
        typer.secho(f"\n[AUDIT] 🚨 SCANNING SECURITY RISKS:", fg=typer.colors.RED, bold=True)
        typer.secho(f"Searching for: Credentials, Keys, IPs, Secrets...\n", fg=typer.colors.BRIGHT_BLACK)
        
        from bck_nd_hlpr.security_auditor import scan_security_risks, get_security_report_string
        risks = scan_security_risks(path, max_depth=depth)
        
        report_str = get_security_report_string(risks, plain=(output is not None))
        
        if output:
            output_handler(report_str, "")
        else:
            print(report_str)
        return

    # MODO IMPACTO (NEW)
    if impact:
        typer.secho(f"\n[IMPACT] 🕸️ ANALYZING DEPENDENCY AND CHANGE RISK:", fg=typer.colors.MAGENTA, bold=True)
        
        from bck_nd_hlpr.dependency_tracker import analyze_impact, get_impact_report_string
        usage_map = analyze_impact(path)
        report_str = get_impact_report_string(usage_map, plain=(output is not None))
        
        if output:
            output_handler(report_str, "")
        else:
            print(report_str)
        return

    # MODO TRACE (NEW)
    if trace:
        typer.secho(f"\n[TRACE] 🔗 GENERATING ROUTE-TO-DB TRACEABILITY MAP (Mermaid):", fg=typer.colors.MAGENTA, bold=True)
        traces = parse_project_traceability(path, max_depth=depth)
        
        if not traces:
            typer.secho("⚠️ No Python routes detected to trace.", fg=typer.colors.YELLOW)
            return
            
        trace_code = generate_mermaid_traceability(traces)
        if trace_code:
            output_handler(trace_code, "Mermaid Code")
        else:
            typer.secho("⚠️ Could not generate the traceability graph.", fg=typer.colors.YELLOW)
        return

    
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
        uml_code = get_uml_code()
        if uml_code:
            output_handler(uml_code, "[UML] Class Diagram")
        else:
            typer.secho("⚠️ No classes detected for UML.", fg=typer.colors.YELLOW)
            
        # 4. ER
        typer.secho("\n[ER] ENTITY-RELATIONSHIP:", fg=typer.colors.CYAN, bold=True)
        er_code = get_er_code()
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
             # Si ya guardamos el graph, tal vez queramos append?
             # El flag -o sobrescribe. Si el usuario usa --explain Y --output, debería guardar el reporte.
             # Si usa --graph Y --explain Y --output, ¿qué guardamos?
             # Asumamos que si hay output, guardamos el reporte EXPLICATIVO si se pide explain.
             output_handler(report, "")
        else:
             print(report)

    # 3. IA CON PERSONALIDAD Y CONTEXTO
    if ai:
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
        
        if narrator.provider is None:
            typer.secho("[INFO] No API Key detected. Generating static documentation without AI analysis...", fg=typer.colors.YELLOW)
        
        typer.secho(f"\n🤖 AI ANALYSIS (Style: {style.upper()}):", fg=typer.colors.MAGENTA, bold=True)
        ai_response = narrator.explain(full_context, use_ai=True, style=style)
        
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
    🌐 Generate a self-contained static HTML documentation portal.

    \b
    Creates docs/index.html with:
      - Infrastructure Map (docker-compose.yml visualization)
      - API Routes (HTTP endpoint sequence diagrams)
      - UML Class Diagram (auto-generated class hierarchy)
      - Entity-Relationship Diagram (ORM models)
      - Technical Debt table (TODOs/FIXMEs)
      - Rendered via MermaidJS CDN — no build tools needed.

    \b
    Examples:
      bck-nd docs .                  Generate in ./docs/
      bck-nd docs . --output site    Generate in ./site/
    
    \b
    CI/CD Tip:
      Combine with 'bck-nd init-ci' to auto-publish on GitHub Pages.
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
    🖥️ Launch the interactive Terminal User Interface (TUI) explorer.

    \b
    What you get:
      - Sidebar: Directory tree to navigate your codebase
      - Main View: Click a .py file for instant ASCII diagram + Mermaid routes
      - Folder View: Click a folder to see its high-level architecture

    \b
    Keyboard Shortcuts:
      D    Toggle dark/light mode
      Q    Quit the TUI

    \b
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
    provider: Optional[str] = typer.Option(None, "--provider", help="Force AI provider: openai, anthropic, gemini, groq, deepseek, openrouter, ollama, webhook. Example: bck-nd chat . --provider ollama")
):
    """
    💬 Start an interactive chat with your codebase using AI (BYO-Key).

    \b
    Requires an active AI provider (API key or Ollama running).
    Automatically loads full project context (architecture, diagrams, docs)
    so you can ask questions about your codebase immediately.

    \b
    Type 'exit', 'quit', or 'q' to end the session.

    \b
    Examples:
      bck-nd chat .                          Default (pro style)
      bck-nd chat . --style hacker           Security-focused chat
      bck-nd chat . --provider ollama        Use local Ollama
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
        typer.secho("\n❌ Error: No API Key detected. Interactive chat requires an active AI provider.", fg=typer.colors.RED, bold=True)
        typer.secho("Please configure OPENAI_API_KEY or similar to use this feature.", fg=typer.colors.YELLOW)
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
    🤖 Setup "Living Documentation" via GitHub Actions + GitHub Pages.

    \b
    Creates .github/workflows/documentation.yml that:
      - Triggers on every push to any branch
      - Installs bck-nd-hlpr in the CI runner
      - Generates the full HTML documentation portal
      - Deploys to GitHub Pages (branches as subdirectories: /main/, /developer/)

    \b
    After running:
      1. git add . && git commit -m 'ci: add auto-docs' && git push
      2. Go to GitHub > Settings > Pages
      3. Set source to 'GitHub Actions'
      4. Done! Docs update on every push.

    \b
    Example:
      bck-nd init-ci
    """
    typer.secho("\n[CI/CD] INITIALIZING FOR AUTO-DOCUMENTATION:", fg=typer.colors.CYAN, bold=True)
    
    try:
        workflow_path = generate_ci_workflow(path)
        typer.secho(f"[OK] File created: {workflow_path}", fg=typer.colors.GREEN)
        
        typer.secho("\n[STEPS] NEXT STEPS:", fg=typer.colors.YELLOW, bold=True)
        typer.secho("1. Push the changes to GitHub: git add . && git commit -m 'ci: add auto-docs' && git push origin main")
        typer.secho("2. Go to your repo on GitHub > Settings > Pages.")
        typer.secho("3. Under 'Build and deployment', choose 'GitHub Actions' as the source.")
        typer.secho("4. Done! Your documentation will update on every push.", fg=typer.colors.CYAN)
    except Exception as e:
        typer.secho(f"❌ Error configuring CI: {e}", fg=typer.colors.RED)

@app.command(name="prompt")
def prompt_cmd(
    path: str = typer.Argument(".", help="Path to the project to analyze. Use '.' for current directory or provide an absolute/relative path. Example: bck-nd prompt /home/user/my-api"),
    output: str = typer.Option("ai_context.txt", "--output", "-o", help="Output file path/name for the context dump (default: ai_context.txt in current dir). Example: bck-nd prompt . -o context.txt"),
    depth: int = typer.Option(4, "--depth", "-d", help="Directory scan depth (default: 4). Increase for deep project structures. Example: bck-nd prompt . --depth 6"),
):
    """
    🧠 AI Context Dump: Export full project context for ChatGPT / Claude.

    \b
    Generates a single LLM-optimized .txt file with XML-like tags:
      <project_tree>       Clean ASCII directory tree (no venv/node_modules)
      <architecture_uml>   UML Class Diagram in Mermaid format
      <architecture_er>    Entity-Relationship Diagram in Mermaid format
      <core_files>         Content of the 3-5 most important backend files

    \b
    How to use:
      1. Run: bck-nd prompt .
      2. Open ai_context.txt
      3. Select All -> Copy
      4. Paste into ChatGPT / Claude as the first message
      5. Start asking questions about your codebase!

    \b
    Examples:
      bck-nd prompt .                      Generates ai_context.txt
      bck-nd prompt /my/project -o ctx.txt Custom output file
      bck-nd prompt . --depth 6            Deeper scan for nested projects
    """
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

    dumper = ContextDumper(path=path, depth=depth)

    typer.secho("  [1/5] Building directory tree...", fg=typer.colors.CYAN)
    tree = dumper.get_project_tree()

    typer.secho("  [2/5] Generating UML diagram...", fg=typer.colors.MAGENTA)
    uml = dumper.get_uml_diagram()

    typer.secho("  [3/5] Generating ER diagram...", fg=typer.colors.MAGENTA)
    er = dumper.get_er_diagram()

    typer.secho("  [4/5] Reading core backend files...", fg=typer.colors.YELLOW)
    core_files = dumper.get_core_files()

    typer.secho("  [5/5] Assembling context file...", fg=typer.colors.GREEN)
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
    files_count = len(core_files)

    console.print()
    console.print(
        Panel(
            f"[bold]Project:[/bold]   [cyan]{Path(path).resolve().name}[/cyan]\n"
            f"[bold]UML:[/bold]       {uml_status}\n"
            f"[bold]ER:[/bold]        {er_status}\n"
            f"[bold]Core files:[/bold] [green]{files_count} file(s) included[/green]\n\n"
            f"[bold green]Contexto generado en [underline]{output}[/underline].[/bold green]\n"
            f"[italic]Listo para copiar y pegar en tu IA![/italic]",
            title="[bold cyan]Context Dump Complete[/bold cyan]",
            border_style="green",
            box=box.ASCII2,
        )
    )


if __name__ == "__main__":
    app()
