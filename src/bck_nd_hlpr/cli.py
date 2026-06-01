import typer
import sys
from typing import Optional
from bck_nd_hlpr.router import Router
from bck_nd_hlpr.scanner import ProjectScanner
from bck_nd_hlpr.narrator import Narrator
from bck_nd_hlpr.er_parser import parse_project_for_er, generate_mermaid_er
from bck_nd_hlpr.route_parser import parse_project_routes, generate_mermaid_sequence
from bck_nd_hlpr.infra_parser import parse_infra, parse_docker_compose, generate_mermaid_infra
from bck_nd_hlpr.todo_hunter import scan_for_todos, display_todos_table, get_todos_table_string
from bck_nd_hlpr.doc_generator import DocGenerator
from bck_nd_hlpr.ci_generator import generate_ci_workflow


app = typer.Typer(
    name="bck-nd",
    help="Backend Helper: Lightweight Architecture CLI",
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    epilog="""
COMMAND MANUAL:

Basic Scanning:
  bck-nd scan .                       # Scan current directory and generate UML & ER diagrams
  bck-nd scan src --depth 5           # Scan specific folder with increased depth

Output Formats:
  bck-nd scan . --format ascii        # Default ASCII output
  bck-nd scan . --format mermaid      # Mermaid.js output (+ Visual Preview)
  bck-nd scan . --uml                 # UML Class Diagram (uses AST for class/inheritance)
  bck-nd scan . --er                  # Entity-Relationship Diagram (SQLAlchemy/Django)
  bck-nd scan . --routes              # API Route Map (Flask/FastAPI Sequence Diagram)
  bck-nd scan . --infra               # Infrastructure Diagram (Docker Compose)
  bck-nd scan . --todo                # Technical Debt Scanner (TODO, FIXME, HACK, XXX, BUG)
  bck-nd scan . --audit               # Security Audit (Detect Secrets, Keys, Hardcoded IPs) [NEW]
  bck-nd scan . --impact              # Dependency Heatmap (What breaks if I code?) [NEW]

Persistence:
  bck-nd scan . --output report.txt   # Save output to file instead of stdout
  bck-nd scan . --er -o schema.mmd    # Save Mermaid diagram to file

Reporting & AI:
  bck-nd scan . --explain             # Diagram + Local Text Report (Offline)
  bck-nd scan . --ai                  # Diagram + AI Analysis (requires n8n)
  
Manual Diagrams:
  bck-nd flow "User -> API -> DB"     # Generate quick ASCII flow from string

DevOps & CI/CD:
  bck-nd init-ci                      # Setup GitHub Actions for Auto-Docs [NEW]
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
    layout: str = typer.Argument(..., help="String de flujo manual.")
):
    """
    📐 Genera un diagrama ASCII desde un string manual.
    
    Ejemplo: bck-nd flow "Client -> API -> Database"
    """
    try:
        typer.secho("\n📐 GENERANDO DIAGRAMA MANUAL:", fg=typer.colors.CYAN, bold=True)
        router = Router()
        router.process(layout)
    except Exception as e:
        typer.secho(f"❌ Error: {e}", fg=typer.colors.RED)

@app.command()
def scan(
    path: str = typer.Argument(".", help="Ruta a analizar"),
    depth: int = typer.Option(3, "--depth", "-d", help="Profundidad de escaneo."),
    graph: bool = typer.Option(True, "--graph/--no-graph", help="Mostrar diagramas UML y ER por defecto."),
    explain: bool = typer.Option(False, "--explain", "-e", help="Reporte de texto local."),
    ai: bool = typer.Option(False, "--ai", help="Análisis IA (n8n)."),
    style: str = typer.Option("pro", "--style", "-s", help="Personalidad: pro, hacker, soviet, ramsay, jarvis, eli5, doom."),
    format: str = typer.Option("ascii", "--format", "-f", help="Formato de salida: ascii, mermaid."),
    uml: bool = typer.Option(False, "--uml", "-u", help="Generar diagrama de clases UML."),
    er: bool = typer.Option(False, "--er", help="Generar diagrama ER de base de datos (Mermaid)."),
    routes: bool = typer.Option(False, "--routes", help="Generar mapa de rutas API (Mermaid Sequence)."),
    infra: bool = typer.Option(False, "--infra", help="Generar diagrama de infraestructura (Docker Compose)."),
    todo: bool = typer.Option(False, "--todo", help="Buscar deuda técnica (TODO, FIXME, HACK, XXX, BUG)."),
    audit: bool = typer.Option(False, "--audit", help="Auditoría de Seguridad (Busca credenciales hardcodeadas)."),
    impact: bool = typer.Option(False, "--impact", help="Mapa de calor de dependencias (High Impact Files)."),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Guardar resultado en archivo (desactiva stdout)."),
    provider: Optional[str] = typer.Option(None, "--provider", help="Forzar proveedor IA (openai, anthropic, gemini, groq, deepseek, openrouter, ollama, webhook).")
):
    """
    🕵️ Escanea un proyecto y detecta su arquitectura automáticamente.
    
    \b
    Modos de uso:
    • bck-nd scan .                    - Diagramas UML y ER (Mermaid)
    • bck-nd scan . -o report.txt      - Guardar en archivo
    • bck-nd scan . --uml              - Diagrama de Clases UML (Mermaid)
    • bck-nd scan . --format mermaid   - Salida Mermaid.js
    """
    scanner = ProjectScanner()

    # Helper para manejar salida condicional
    def output_handler(content: str, context_msg: str):
        if output:
            try:
                with open(output, "w", encoding="utf-8") as f:
                    f.write(content)
                typer.secho(f"💾 Resultado guardado en: {output}", fg=typer.colors.GREEN, bold=True)
            except Exception as e:
                typer.secho(f"❌ Error escribiendo archivo: {e}", fg=typer.colors.RED)
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
                    typer.secho("Copia el bloque anterior en Mermaid.live", fg=typer.colors.BRIGHT_BLACK)
                else:
                    print(content)

    # DETECTAR ARQUITECTURA PRIMERO para rutear parsers
    typer.secho(f"\n🔍 Analizando arquitectura de '{path}'...", fg=typer.colors.CYAN, bold=True)
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

    # MODO UML EXCLUSIVO
    if uml:
        typer.secho(f"\n[UML] GENERANDO DIAGRAMA DE CLASES (Mermaid):", fg=typer.colors.MAGENTA, bold=True)
        uml_code = get_uml_code()
        if uml_code:
            output_handler(uml_code, "Mermaid Code")
        else:
            typer.secho("⚠️ No se detectaron clases para UML.", fg=typer.colors.YELLOW)
        return

    # MODO ER (ENTITY-RELATIONSHIP)
    if er:
        typer.secho(f"\n[ER] GENERANDO DIAGRAMA ER (Mermaid):", fg=typer.colors.MAGENTA, bold=True)
        er_code = get_er_code()
        if er_code:
            output_handler(er_code, "Mermaid Code")
        else:
            typer.secho("⚠️ No se detectaron modelos de base de datos.", fg=typer.colors.YELLOW)
        return
    
    # MODO ROUTES (API MAP)
    if routes:
        typer.secho(f"\n[API] GENERANDO MAPA DE RUTAS (Mermaid Sequence):", fg=typer.colors.MAGENTA, bold=True)
        detected_routes = parse_project_routes(path, max_depth=depth)
        seq_code = generate_mermaid_sequence(detected_routes)
        
        if not seq_code:
            typer.secho("⚠️ No se detectaron rutas API (Flask/FastAPI).", fg=typer.colors.YELLOW)
        else:
            output_handler(seq_code, "Mermaid Code")
        return
    
    # MODO INFRA (DOCKER COMPOSE)
    if infra:
        typer.secho(f"\n[INFRA] GENERANDO DIAGRAMA DE INFRAESTRUCTURA (Mermaid):", fg=typer.colors.MAGENTA, bold=True)
        compose_file = parse_infra(path)
        
        if not compose_file:
            typer.secho("⚠️ No se detectó docker-compose.yml en el directorio.", fg=typer.colors.YELLOW)
            return
        
        typer.secho(f"📦 Encontrado: {compose_file}", fg=typer.colors.GREEN)
        services = parse_docker_compose(compose_file)
        
        if not services:
            typer.secho("⚠️ No se encontraron servicios en docker-compose.", fg=typer.colors.YELLOW)
            return
        
        infra_code = generate_mermaid_infra(services)
        output_handler(infra_code, "Mermaid Code")
        return
    
    # MODO TODO HUNTER (TECHNICAL DEBT)
    if todo:
        typer.secho(f"\n[TODO] 🧹 ESCANEANDO DEUDA TÉCNICA:", fg=typer.colors.CYAN, bold=True)
        typer.secho(f"Buscando: TODO, FIXME, HACK, XXX, BUG...\n", fg=typer.colors.BRIGHT_BLACK)
        
        todos = scan_for_todos(path, max_depth=depth)
        
        if not todos:
            typer.secho("✨ ¡Increíble! No se encontró deuda técnica.", fg=typer.colors.GREEN, bold=True)
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
        typer.secho(f"\n[AUDIT] 🚨 ESCANEANDO RIESGOS DE SEGURIDAD:", fg=typer.colors.RED, bold=True)
        typer.secho(f"Buscando: Credenciales, Keys, IPs, Secrets...\n", fg=typer.colors.BRIGHT_BLACK)
        
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
        typer.secho(f"\n[IMPACT] 🕸️ ANALIZANDO DEPENDENCIA Y RIESGO DE CAMBIO:", fg=typer.colors.MAGENTA, bold=True)
        
        from bck_nd_hlpr.dependency_tracker import analyze_impact, get_impact_report_string
        usage_map = analyze_impact(path)
        report_str = get_impact_report_string(usage_map, plain=(output is not None))
        
        if output:
            output_handler(report_str, "")
        else:
            print(report_str)
        return


    
    if arch_info['framework'] != 'Unknown':
        typer.secho(f"💻 Framework detectado: {arch_info['framework']}", fg=typer.colors.GREEN)
    if arch_info.get('architecture'):
        typer.secho(f"🏭 Arquitectura: {arch_info['architecture']}", fg=typer.colors.BLUE)
    if arch_info.get('features'):
        typer.secho(f"✨ Características: {', '.join(arch_info['features'])}", fg=typer.colors.YELLOW)
    
    # Resumen
    if arch_info.get('summary'):
        typer.secho(f"\n📝 {arch_info['summary']}", fg=typer.colors.WHITE)
    
    # ESCANEO DE ARCHIVOS
    typer.secho(f"\n📂 Escaneando archivos (profundidad: {depth})...", fg=typer.colors.YELLOW)
    flow_string = scanner.scan(path, max_depth=depth)
    
    if not flow_string:
        typer.secho(f"\n❌ No se encontraron archivos en '{path}' con profundidad {depth}.", fg=typer.colors.RED)
        typer.secho(f"💡 Intenta aumentar la profundidad: bck-nd scan {path} --depth {depth + 2}", fg=typer.colors.YELLOW)
        return

    # 1. DIBUJO (Solo si está activado y no se seleccionaron reportes locales)
    # Por defecto, mostraremos la arquitectura completa (UML, ER, API, Infra, TODOs)
    if graph and not any([explain, ai]):
        typer.secho("\n📊 ARQUITECTURA DEL PROYECTO (COMPLETA):", fg=typer.colors.MAGENTA, bold=True)
        
        # 1. INFRA
        typer.secho("\n[INFRA] MAPA DE INFRAESTRUCTURA:", fg=typer.colors.CYAN, bold=True)
        compose_file = parse_infra(path)
        if compose_file:
            services = parse_docker_compose(compose_file)
            if services:
                infra_code = generate_mermaid_infra(services)
                output_handler(infra_code, "Mermaid Code")
            else:
                typer.secho("⚠️ No se encontraron servicios en docker-compose.", fg=typer.colors.YELLOW)
        else:
            typer.secho("⚠️ No se detectó docker-compose.yml en el directorio.", fg=typer.colors.YELLOW)

        # 2. ROUTES
        typer.secho("\n[API] MAPA DE RUTAS:", fg=typer.colors.CYAN, bold=True)
        detected_routes = parse_project_routes(path, max_depth=depth)
        if detected_routes:
            seq_code = generate_mermaid_sequence(detected_routes)
            if seq_code:
                output_handler(seq_code, "Mermaid Code")
            else:
                typer.secho("⚠️ No se pudieron renderizar las rutas.", fg=typer.colors.YELLOW)
        else:
            typer.secho("⚠️ No se detectaron rutas API (Flask/FastAPI).", fg=typer.colors.YELLOW)

        # 3. UML
        typer.secho("\n[UML] DIAGRAMA DE CLASES:", fg=typer.colors.CYAN, bold=True)
        uml_code = get_uml_code()
        if uml_code:
            output_handler(uml_code, "Mermaid Code")
        else:
            typer.secho("⚠️ No se detectaron clases para UML.", fg=typer.colors.YELLOW)
            
        # 4. ER
        typer.secho("\n[ER] ENTITY-RELATIONSHIP:", fg=typer.colors.CYAN, bold=True)
        er_code = get_er_code()
        if er_code:
            output_handler(er_code, "Mermaid Code")
        else:
            typer.secho("⚠️ No se detectaron modelos de base de datos.", fg=typer.colors.YELLOW)

        # 5. TODOs
        typer.secho("\n[TODO] DEUDA TÉCNICA:", fg=typer.colors.CYAN, bold=True)
        todos = scan_for_todos(path, max_depth=depth)
        if todos:
            if output:
                table_str = get_todos_table_string(todos, plain=True)
                output_handler(table_str, "")
            else:
                display_todos_table(todos)
        else:
            typer.secho("✨ ¡Increíble! No se encontró deuda técnica.", fg=typer.colors.GREEN, bold=True)

    narrator = Narrator(force_provider=provider)

    # 2. LOCAL (Reporte de texto)
    if explain:
        typer.secho("\n📄 REPORTE LOCAL:", fg=typer.colors.CYAN, bold=True)
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
        arch_context = f"\n\n--- ARQUITECTURA DETECTADA ---\n"
        arch_context += f"Framework: {arch_info.get('framework', 'Unknown')}\n"
        arch_context += f"Tipo: {arch_info.get('architecture', 'Unknown')}\n"
        arch_context += f"Features: {', '.join(arch_info.get('features', []))}\n"
        
        # Generar Diagramas Avanzados para dar más contexto a la IA
        extra_diagrams = "\n\n--- DIAGRAMAS AVANZADOS (MERMAID) ---\n"
        
        # 1. Infra
        compose_file = parse_infra(path)
        if compose_file:
            services = parse_docker_compose(compose_file)
            if services:
                extra_diagrams += "Infraestructura (docker-compose):\n```mermaid\n" + generate_mermaid_infra(services) + "\n```\n"

        # 2. Rutas API
        detected_routes = parse_project_routes(path, max_depth=depth)
        if detected_routes:
            extra_diagrams += "Rutas API (Sequence):\n```mermaid\n" + generate_mermaid_sequence(detected_routes) + "\n```\n"

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
            full_context = flow_string + arch_context + extra_diagrams + "\n\n--- DOCUMENTACIÓN DEL PROYECTO ---\n" + docs
        else:
            full_context = flow_string + arch_context + extra_diagrams
        
        typer.secho(f"\n🤖 ANÁLISIS IA (Estilo: {style.upper()}):", fg=typer.colors.MAGENTA, bold=True)
        ai_response = narrator.explain(full_context, use_ai=True, style=style)
        
        if output:
            output_handler(ai_response, "")
        else:
            print(ai_response)

@app.command()
def docs(
    path: str = typer.Argument(".", help="Ruta a analizar"),
    output: str = typer.Option("docs", "--output", "-o", help="Directorio de salida para la documentación HTML")
):
    """
    [WEB] Genera documentación web estática del proyecto con diagramas (index.html).
    """
    typer.secho(f"\n[WEB] GENERANDO DOCUMENTACIÓN WEB EN '{output}':", fg=typer.colors.CYAN, bold=True)
    generator = DocGenerator()
    try:
        out_file = generator.generate(path, output)
        typer.secho(f"[OK] Documentación generada con éxito en: {out_file}", fg=typer.colors.GREEN, bold=True)
    except Exception as e:
        typer.secho(f"[ERROR] Error al generar documentación: {e}", fg=typer.colors.RED)


@app.command()
def explore():
    """🖥️ TUI: Lanza la interfaz gráfica de terminal."""
    try:
        from bck_nd_hlpr.tui_app import ArchitectureExplorer
        explorer_app = ArchitectureExplorer()
        explorer_app.run()
    except ImportError as e:
        typer.secho(f"❌ Error al iniciar TUI: {e}", fg=typer.colors.RED)
        typer.secho("Asegúrate de haber instalado 'textual' (pip install textual).", fg=typer.colors.YELLOW)

@app.command()
def chat(
    path: str = typer.Argument(".", help="Ruta a analizar para dar contexto"),
    depth: int = typer.Option(3, "--depth", "-d", help="Profundidad de escaneo."),
    style: str = typer.Option("pro", "--style", "-s", help="Personalidad del bot (pro, hacker, ramsay, etc.)."),
    provider: Optional[str] = typer.Option(None, "--provider", help="Forzar proveedor IA (openai, anthropic, gemini, groq, deepseek, openrouter, ollama, webhook).")
):
    """
    💬 Inicia un chat interactivo con tu base de código usando IA (BYO-Key).
    """
    scanner = ProjectScanner()
    
    typer.secho(f"🔍 Escaneando arquitectura para inicializar el contexto (profundidad: {depth})...", fg=typer.colors.CYAN, bold=True)
    arch_info = scanner.detect_architecture(path)
    flow_string = scanner.scan(path, max_depth=depth)
    
    if not flow_string:
        typer.secho(f"❌ No se pudo construir el contexto inicial. Carpeta vacía o faltan archivos clave.", fg=typer.colors.RED)
        return
        
    # Construir mega-contexto arquitectónico
    arch_context = f"\n\n--- ARQUITECTURA DETECTADA ---\n"
    arch_context += f"Framework: {arch_info.get('framework', 'Unknown')}\n"
    arch_context += f"Tipo: {arch_info.get('architecture', 'Unknown')}\n"
    arch_context += f"Features: {', '.join(arch_info.get('features', []))}\n"
    
    extra_diagrams = "\n\n--- DIAGRAMAS AVANZADOS (MERMAID) ---\n"
    
    # 1. Infra
    compose_file = parse_infra(path)
    if compose_file:
        services = parse_docker_compose(compose_file)
        if services:
            extra_diagrams += "Infraestructura (docker-compose):\n```mermaid\n" + generate_mermaid_infra(services) + "\n```\n"

    # 2. Rutas API
    detected_routes = parse_project_routes(path, max_depth=depth)
    if detected_routes:
        extra_diagrams += "Rutas API (Sequence):\n```mermaid\n" + generate_mermaid_sequence(detected_routes) + "\n```\n"

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
        full_context = flow_string + arch_context + extra_diagrams + "\n\n--- DOCUMENTACIÓN DEL PROYECTO ---\n" + docs
    else:
        full_context = flow_string + arch_context + extra_diagrams
        
    narrator = Narrator(force_provider=provider)
    
    typer.secho("\n✅ Contexto cargado con éxito.", fg=typer.colors.GREEN)
    typer.secho(f"💬 INICIANDO CHAT INTERACTIVO (Estilo: {style.upper()}). Escribe 'salir' para terminar.\n", fg=typer.colors.MAGENTA, bold=True)
    
    history_text = ""
    while True:
        user_input = typer.prompt("Tú", type=str)
        if user_input.strip().lower() in ["salir", "exit", "quit", "q"]:
            typer.secho("👋 ¡Hasta luego!", fg=typer.colors.CYAN)
            break
            
        history_text += f"\nUsuario: {user_input}\n"
        
        response = narrator.chat_turn(system_context=full_context, history_text=history_text, style=style)
        
        typer.secho(f"\n🤖 bck-nd: {response}\n", fg=typer.colors.YELLOW)
        
        history_text += f"\nbck-nd: {response}\n"

@app.command()
def init_ci(
    path: str = typer.Argument(".", help="Ruta del proyecto para inicializar CI.")
):
    """
    🤖 Configura GitHub Actions para auto-documentación en GitHub Pages.
    """
    typer.secho("\n[CI/CD] INICIALIZANDO PARA AUTO-DOCUMENTACIÓN:", fg=typer.colors.CYAN, bold=True)
    
    try:
        workflow_path = generate_ci_workflow(path)
        typer.secho(f"[OK] Archivo creado: {workflow_path}", fg=typer.colors.GREEN)
        
        typer.secho("\n[PASOS] PRÓXIMOS PASOS:", fg=typer.colors.YELLOW, bold=True)
        typer.secho("1. Sube los cambios a GitHub: git add . && git commit -m 'ci: add auto-docs' && git push origin main")
        typer.secho("2. Ve a tu repo en GitHub > Settings > Pages.")
        typer.secho("3. En 'Build and deployment', elige 'GitHub Actions' como fuente.")
        typer.secho("4. ¡Listo! Tu documentación se actualizará en cada push.", fg=typer.colors.CYAN)
    except Exception as e:
        typer.secho(f"❌ Error al configurar CI: {e}", fg=typer.colors.RED)

if __name__ == "__main__":
    app()
