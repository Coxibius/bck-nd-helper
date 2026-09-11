"""
Formatters module for CLI and Textual UI outputs.
Decouples terminal presentation libraries (Rich, Typer) from the core logic.
"""

from typing import List, Dict, Optional, Set, Any
import io
from rich.console import Console
from rich.table import Table
from rich.text import Text

# Color scheme for each debt type (moved from todo_hunter)
DEBT_MARKERS = ['TODO', 'FIXME', 'HACK', 'XXX', 'BUG']
TYPE_COLORS = {
    'TODO': 'blue',
    'FIXME': 'yellow',
    'HACK': 'magenta',
    'XXX': 'red',
    'BUG': 'bright_red',
}


def display_todos_table(todos: List[Dict]) -> None:
    """
    Displays technical debt items in a beautiful Rich table.
    Supports scoped tags: TODO(audit), FIXME(security), HACK(perf), etc.
    """
    console = Console()
    
    # Create table
    table = Table(
        title="🧹 Technical Debt Report",
        show_header=True,
        header_style="bold cyan",
        border_style="bright_black",
        title_style="bold magenta"
    )
    
    # Add columns — Type column widened to 18 to hold scoped forms e.g. "TODO(audit)"
    table.add_column("File", style="cyan", no_wrap=False, width=30)
    table.add_column("Line", style="white", justify="right", width=6)
    table.add_column("Type", style="bold", width=18)
    table.add_column("Message", style="white", no_wrap=False)
    
    # Sort todos by file, then line number
    sorted_todos = sorted(todos, key=lambda x: (x['file'], x['line']))
    
    # Add rows
    for todo in sorted_todos:
        type_color = TYPE_COLORS.get(todo['type'], 'white')
        scope = todo.get('scope', '') or ''
        display_type = f"{todo['type']}({scope})" if scope else todo['type']
        type_text = Text(display_type, style=type_color)
        
        message = todo['message']
        if len(message) > 60:
            message = message[:57] + "..."
        
        table.add_row(
            todo['file'],
            str(todo['line']),
            type_text,
            message
        )
    
    # Display table
    console.print()
    console.print(table)
    console.print()
    
    # Display statistics
    display_todo_statistics(todos, console)


def get_todos_table_string(todos: List[Dict], plain: bool = False) -> str:
    """
    Returns the technical debt table as a string.
    Supports scoped tags: TODO(audit), FIXME(security), HACK(perf), etc.
    """
    output = io.StringIO()
    
    if plain:
        console = Console(file=output, force_terminal=False, no_color=True, width=120)
    else:
        console = Console(file=output, force_terminal=True, width=120)
    
    # Create table
    table = Table(
        title="🧹 Technical Debt Report" if not plain else "Technical Debt Report",
        show_header=True,
        header_style="bold cyan" if not plain else None,
        border_style="bright_black" if not plain else None,
        title_style="bold magenta" if not plain else None,
    )
    
    # Add columns — Type column widened to 18 to hold scoped forms e.g. "TODO(audit)"
    table.add_column("File", style="cyan" if not plain else None, no_wrap=False, width=30)
    table.add_column("Line", style="white" if not plain else None, justify="right", width=6)
    table.add_column("Type", style="bold" if not plain else None, width=18)
    table.add_column("Message", style="white" if not plain else None, no_wrap=False)
    
    # Sort todos
    sorted_todos = sorted(todos, key=lambda x: (x['file'], x['line']))
    
    # Add rows
    for todo in sorted_todos:
        type_color = TYPE_COLORS.get(todo['type'], 'white')
        scope = todo.get('scope', '') or ''
        display_type = f"{todo['type']}({scope})" if scope else todo['type']
        type_text = Text(display_type, style=type_color if not plain else None)
        message = todo['message']
        if len(message) > 60:
            message = message[:57] + "..."
        
        table.add_row(todo['file'], str(todo['line']), type_text, message)
    
    console.print(table)
    console.print()
    display_todo_statistics(todos, console)
    
    return output.getvalue()


def display_todo_statistics(todos: List[Dict], console: Console) -> None:
    """
    Displays summary statistics of technical debt.
    Also includes a scope breakdown when scoped tags (e.g. TODO(audit)) are present.
    """
    # Count by base type (TODO, FIXME, HACK, XXX, BUG)
    type_counts = {}
    # Count by scoped type (TODO(audit), FIXME(security), ...) for detailed breakdown
    scoped_counts = {}
    for todo in todos:
        debt_type = todo['type']
        scope = todo.get('scope', '') or ''
        type_counts[debt_type] = type_counts.get(debt_type, 0) + 1
        scoped_key = f"{debt_type}({scope})" if scope else debt_type
        scoped_counts[scoped_key] = scoped_counts.get(scoped_key, 0) + 1

    # Display summary
    console.print("📊 [bold cyan]Summary by Type:[/bold cyan]")

    for marker in DEBT_MARKERS:
        count = type_counts.get(marker, 0)
        color = TYPE_COLORS.get(marker, 'white')

        if count > 0:
            console.print(f"  [{color}]●[/{color}] {marker}: [bold]{count}[/bold] items")
        else:
            console.print(f"  [dim]○[/dim] {marker}: [dim]0[/dim] items")

    # Scope breakdown (only if any scoped tags exist)
    has_scopes = any((t.get('scope', '') or '') for t in todos)
    if has_scopes:
        console.print()
        console.print("🔖 [bold cyan]Scoped Breakdown:[/bold cyan]")
        for scoped_key in sorted(scoped_counts.keys()):
            if '(' in scoped_key:
                base_marker = scoped_key.split('(')[0]
                color = TYPE_COLORS.get(base_marker, 'white')
                console.print(f"  [{color}]◆[/{color}] {scoped_key}: [bold]{scoped_counts[scoped_key]}[/bold] items")

    console.print()
    console.print(f"[bold yellow]Total Technical Debt:[/bold yellow] [bold]{len(todos)}[/bold] items")

    # Calculate debt level
    if len(todos) == 0:
        console.print("[bold green]✨ Debt Level: EXCELLENT[/bold green]")
    elif len(todos) <= 5:
        console.print("[bold green]👍 Debt Level: LOW[/bold green]")
    elif len(todos) <= 15:
        console.print("[bold yellow]⚠️  Debt Level: MODERATE[/bold yellow]")
    elif len(todos) <= 30:
        console.print("[bold red]🔥 Debt Level: HIGH[/bold red]")
    else:
        console.print("[bold bright_red]💀 Debt Level: CRITICAL[/bold bright_red]")


def get_security_report_string(risks: List[Dict], plain: bool = False) -> str:
    """Generates the security report table string."""
    output = io.StringIO()
    
    if plain:
        console = Console(file=output, force_terminal=False, no_color=True, width=120)
    else:
        console = Console(file=output, force_terminal=True, width=120)
        
    severity_order = {'CRITICAL': 0, 'HIGH': 1, 'WARNING': 2}
    sorted_risks = sorted(risks, key=lambda x: (severity_order.get(x['severity'], 99), x['file'], x['line']))
    
    crit_count = sum(1 for r in risks if r['severity'] == 'CRITICAL')
    high_count = sum(1 for r in risks if r['severity'] == 'HIGH')
    warn_count = sum(1 for r in risks if r['severity'] == 'WARNING')
    
    if crit_count > 0:
        global_score = "CRITICAL"
    elif high_count > 0:
        global_score = "HIGH"
    elif warn_count > 3:
        global_score = "MEDIUM"
    elif warn_count > 0:
        global_score = "LOW"
    else:
        global_score = "CLEAN"
        
    if plain:
        # Group by file in plain text output
        grouped = {}
        for risk in sorted_risks:
            f = risk['file']
            if f not in grouped:
                grouped[f] = []
            grouped[f].append(risk)
            
        console.print("🚨 SECURITY AUDIT REPORT 🚨\n")
        for f, file_risks in grouped.items():
            console.print(f"File: {f}")
            for risk in file_risks:
                cat = risk.get('category', 'Secrets')
                console.print(f"  [{risk['severity']}] Line {risk['line']}: {risk['type']} - {risk['message']} (Category: {cat})")
            console.print("")
    else:
        table = Table(
            title="🚨 SECURITY AUDIT REPORT 🚨",
            show_header=True,
            header_style="bold red",
            border_style="red",
            title_style="bold red"
        )
        
        table.add_column("Severity", style="bold red", width=10)
        table.add_column("Category", style="magenta", width=15)
        table.add_column("File", style="cyan")
        table.add_column("Line", justify="right")
        table.add_column("Risk Type", style="yellow")
        table.add_column("Message")
        
        for risk in sorted_risks:
            sev = risk['severity']
            style = "bold red" if sev == 'CRITICAL' else ("bold orange3" if sev == 'HIGH' else "yellow")
            
            table.add_row(
                Text(sev, style=style),
                risk.get('category', 'Secrets'),
                risk['file'],
                str(risk['line']),
                risk['type'],
                risk['message']
            )
            
        console.print(table)
        
    # Print summary block and risk score
    score_style = "bold red" if global_score in ["CRITICAL", "HIGH"] else ("yellow" if global_score == "MEDIUM" else "bold green")
    summary_text = f"{crit_count} Critical · {high_count} High · {warn_count} Warning"
    
    if not plain:
        if not risks:
            console.print("\n[bold green]✅ No obvious security risks found.[/bold green]")
        else:
            console.print(f"\n[bold red]Found {len(risks)} potential security risks.[/bold red]")
            console.print(f"[bold]Risk Score: [/bold][{score_style}]{global_score}[/{score_style}]")
            console.print(f"[bold]Summary:[/bold] {summary_text}")
    else:
        if not risks:
            console.print("\n✅ No obvious security risks found.")
        else:
            console.print(f"\nFound {len(risks)} potential security risks.")
            console.print(f"Risk Score: {global_score}")
            console.print(f"Summary: {summary_text}")
        
    return output.getvalue()


def get_impact_report_string(usage_map: Dict[str, Set[str]], plain: bool = False) -> str:
    """Generates the dependency heatmap report string."""
    output = io.StringIO()
    
    if plain:
        console = Console(file=output, force_terminal=False, no_color=True, width=120)
    else:
        console = Console(file=output, force_terminal=True, width=120)
        
    table = Table(
        title="🔥 DEPENDENCY IMPACT HEATMAP (What breaks if I touch this?)",
        show_header=True,
        header_style="bold red" if not plain else None,
        border_style="red" if not plain else None,
        title_style="bold red" if not plain else None
    )
    
    table.add_column("File (The Dependency)", style="cyan" if not plain else None)
    table.add_column("Impact Score", justify="right", style="bold white" if not plain else None)
    table.add_column("Risk Category", justify="center", style="bold" if not plain else None)
    table.add_column("Imported By (Dependents)", style="white" if not plain else None)

    # Sort by number of dependents (High impact first)
    sorted_files = sorted(usage_map.items(), key=lambda item: len(item[1]), reverse=True)
    
    for file, dependents in sorted_files:
        score = len(dependents)
        deps_list = ", ".join(sorted(list(dependents))[:3]) # Show first 3
        if len(dependents) > 3:
            deps_list += f" (+{len(dependents)-3} more)"
            
        color = "white"
        risk_category = "🟢 PERIPHERAL"
        risk_color = "green"

        if score > 5:
            color = "bold red"
            risk_category = "🔥 CORE"
            risk_color = "bold red"
        elif score >= 2:
            color = "bold yellow"
            risk_category = "🟡 SHARED"
            risk_color = "bold yellow"
        
        count_styled = Text(str(score), style=color if not plain else None)
        risk_styled = Text(risk_category, style=risk_color if not plain else None)
        
        table.add_row(file, count_styled, risk_styled, deps_list)
        
    console.print(table)
    
    if not usage_map:
        console.print("\n[yellow]No internal dependencies detected (or project is flat).[/yellow]" if not plain else "\nNo internal dependencies detected.")
        
    return output.getvalue()


def format_asg_json(asg_graph: Any, indent: int = 2) -> str:
    """
    Format ASGGraph object into a clean JSON string representation.
    """
    import json
    if asg_graph is None:
        return json.dumps({"nodes": [], "edges": []}, indent=indent)

    if hasattr(asg_graph, "to_dict"):
        data = asg_graph.to_dict()
    elif isinstance(asg_graph, dict):
        data = asg_graph
    else:
        data = {"nodes": [], "edges": []}

    return json.dumps(data, indent=indent)


def format_uml_diagram(uml_content: Any, plain: bool = False) -> str:
    """
    Format UML class diagram for presentation or return fallback text when empty.
    """
    from bck_nd_hlpr.core.uml_parser import is_empty_mermaid_class_diagram

    if not is_empty_mermaid_class_diagram(uml_content):
        return uml_content.strip()
    return "[--] No classes or TypeScript interfaces detected."


def _requirements_briefs_table(specs: List[Any], *, plain: bool = False) -> Table:
    """Build the one canonical, compact story-brief presentation."""
    from rich import box
    from rich.markup import escape

    table = Table(
        title="Project Requirements" if plain else f"Project Requirements & User Stories ({len(specs)} found)",
        show_header=True,
        header_style="bold cyan" if not plain else None,
        border_style="bright_black" if not plain else None,
        box=box.ASCII if plain else box.ROUNDED,
    )
    table.add_column("Story", style="cyan bold" if not plain else None, min_width=14)
    table.add_column("Story Brief", no_wrap=False, ratio=1)

    status_styles = {
        "TODO": "bold yellow",
        "IN_PROGRESS": "bold blue",
        "TESTING": "bold magenta",
        "DONE": "bold green",
    }

    for spec in specs:
        story = getattr(spec, "story", None)
        story_id = getattr(story, "id", "") if story else ""
        raw_status = (getattr(story, "status", "TODO") or "TODO").upper() if story else "TODO"
        status_style = status_styles.get(raw_status, "white") if not plain else None
        title = getattr(story, "title", "Untitled") if story else "Untitled"
        role = getattr(story, "role", "") if story else ""
        want = getattr(story, "want", "") if story else ""
        benefit = getattr(story, "benefit", "") if story else ""
        crit_count = len(getattr(spec, "acceptance_criteria", []) or [])
        rules_count = len(getattr(spec, "business_rules", []) or [])
        criteria_label = "criterio" if crit_count == 1 else "criterios"
        rules_label = "regla" if rules_count == 1 else "reglas"

        story_cell = Text(str(story_id or "N/A"))
        story_cell.append(f" [{raw_status}]", style=status_style)
        brief_lines = [
            escape(str(title or "Untitled")),
            f"Como {escape(str(role or '(none)'))},",
            f"quiero {escape(str(want or '(none)'))},",
            f"para {escape(str(benefit or '(none)'))}.",
            f"{crit_count} {criteria_label} · {rules_count} {rules_label}",
        ]

        table.add_row(
            story_cell,
            "\n".join(brief_lines),
        )
    return table


def display_requirements_table(specs: List[Any], console: Optional[Console] = None) -> None:
    """Display the canonical story briefs for a Requirements collection."""
    if console is None:
        console = Console()

    console.print()
    console.print(_requirements_briefs_table(specs))


def get_requirements_table_string(specs: List[Any], plain: bool = False) -> str:
    """Return the same canonical story briefs as a formatted string."""
    output = io.StringIO()
    if plain:
        console = Console(file=output, force_terminal=False, no_color=True, width=120)
    else:
        console = Console(file=output, force_terminal=True, width=120)

    console.print(_requirements_briefs_table(specs, plain=plain))
    return output.getvalue()


def _requirement_value_text(value: Any) -> str:
    """Return compact deterministic text without Python/JSON container syntax."""
    if value is None:
        return "(none)"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict):
        return " · ".join(
            f"{key}: {_requirement_value_text(value[key])}"
            for key in sorted(value, key=lambda item: (str(item).casefold(), str(item)))
        ) or "(none)"
    if isinstance(value, (list, tuple)):
        return ", ".join(_requirement_value_text(item) for item in value) or "(none)"
    return str(value)


def _requirement_item_text(
    value: Any,
    *,
    identifier_key: str,
    description_key: str,
) -> str:
    """Format a structured requirement item as a friendly, stable sentence."""
    if not isinstance(value, dict):
        return _requirement_value_text(value)

    identifier = _requirement_value_text(value.get(identifier_key)) \
        if identifier_key in value else ""
    description = _requirement_value_text(value.get(description_key)) \
        if description_key in value else ""
    if identifier and description:
        leading = f"{identifier} — {description}"
    else:
        leading = identifier or description

    excluded = {identifier_key, description_key}
    extras = [
        f"{key}: {_requirement_value_text(value[key])}"
        for key in sorted(value, key=lambda item: (str(item).casefold(), str(item)))
        if key not in excluded
    ]
    parts = [part for part in (leading, *extras) if part]
    return " · ".join(parts) or "(none)"


def display_requirement_detail(spec: Any, console: Optional[Console] = None) -> None:
    """Display every public section of one requirement without mutating it."""
    from rich.markup import escape

    if console is None:
        console = Console()
    story = getattr(spec, "story", None)

    def safe(value: Any, fallback: str = "(none)") -> str:
        text = "" if value is None else str(value)
        return escape(text) if text else fallback

    console.print()
    console.print(f"[bold cyan]Story ID:[/bold cyan] {safe(getattr(story, 'id', ''))}")
    console.print(f"[bold cyan]Status:[/bold cyan] {safe(getattr(story, 'status', 'TODO'))}")
    console.print(f"[bold cyan]Title:[/bold cyan] {safe(getattr(story, 'title', ''))}")
    console.print(f"[bold]Role / Como:[/bold] {safe(getattr(story, 'role', ''))}")
    console.print(f"[bold]Want / Quiero:[/bold] {safe(getattr(story, 'want', ''))}")
    console.print(f"[bold]Benefit / Para:[/bold] {safe(getattr(story, 'benefit', ''))}")

    def section(title: str, items: List[Any], render) -> None:
        console.print(f"\n[bold cyan]{title}[/bold cyan]")
        if not items:
            console.print("  (none)")
            return
        for item in items:
            render(item)

    section(
        "Business Rules",
        list(getattr(spec, "business_rules", []) or []),
        lambda rule: console.print(
            f"  - [magenta]{safe(getattr(rule, 'id', ''))}[/magenta]: "
            f"{safe(getattr(rule, 'description', ''))}"
        ),
    )
    section(
        "Acceptance Criteria",
        list(getattr(spec, "acceptance_criteria", []) or []),
        lambda criterion: console.print(
            f"  - [yellow]{safe(getattr(criterion, 'id', ''))}[/yellow]\n"
            f"    [bold]Given[/bold] {safe(getattr(criterion, 'given', ''))}\n"
            f"    [bold]When[/bold] {safe(getattr(criterion, 'when', ''))}\n"
            f"    [bold]Then[/bold] {safe(getattr(criterion, 'then', ''))}"
        ),
    )
    for title, attribute, identifier_key, description_key in (
        ("Required Data", "required_data", "field", "type"),
        ("Validations", "validations", "field", "rule"),
        ("Exceptions", "exceptions", "code", "description"),
        ("Open Questions", "open_questions", "question", "description"),
    ):
        section(
            title,
            list(getattr(spec, attribute, []) or []),
            lambda item, identifier_key=identifier_key, description_key=description_key: console.print(
                "  - " + safe(
                    _requirement_item_text(
                        item,
                        identifier_key=identifier_key,
                        description_key=description_key,
                    )
                )
            ),
        )

