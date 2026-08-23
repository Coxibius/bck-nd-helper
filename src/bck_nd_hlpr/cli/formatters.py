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


def display_requirements_table(specs: List[Any], console: Optional[Console] = None) -> None:
    """Displays project requirements summary in a Rich table."""
    if console is None:
        console = Console()
    from rich import box
    table = Table(
        title=f"Project Requirements & User Stories ({len(specs)} found)",
        show_header=True,
        header_style="bold cyan",
        border_style="bright_black",
        box=box.ROUNDED,
    )
    table.add_column("Story ID", style="cyan bold", justify="center")
    table.add_column("Status", justify="center")
    table.add_column("Title", style="bold")
    table.add_column("Crit.", justify="right", style="green")
    table.add_column("Rules", justify="right", style="magenta")

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
        status_style = status_styles.get(raw_status, "white")
        title = getattr(story, "title", "Untitled") if story else "Untitled"
        crit_count = len(getattr(spec, "acceptance_criteria", []) or [])
        rules_count = len(getattr(spec, "business_rules", []) or [])

        table.add_row(
            story_id or "N/A",
            Text(raw_status, style=status_style),
            title or "Untitled",
            str(crit_count),
            str(rules_count),
        )

    console.print()
    console.print(table)


def get_requirements_table_string(specs: List[Any], plain: bool = False) -> str:
    """Returns project requirements summary table as a formatted string."""
    output = io.StringIO()
    if plain:
        console = Console(file=output, force_terminal=False, no_color=True, width=120)
    else:
        console = Console(file=output, force_terminal=True, width=120)

    from rich import box
    table = Table(
        title="Project Requirements" if plain else f"Project Requirements & User Stories ({len(specs)} found)",
        show_header=True,
        header_style="bold cyan" if not plain else None,
        border_style="bright_black" if not plain else None,
        box=box.ASCII if plain else box.ROUNDED,
    )
    table.add_column("Story ID", style="cyan bold" if not plain else None, justify="center")
    table.add_column("Status", justify="center")
    table.add_column("Title", style="bold" if not plain else None)
    table.add_column("Crit.", justify="right", style="green" if not plain else None)
    table.add_column("Rules", justify="right", style="magenta" if not plain else None)

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
        crit_count = len(getattr(spec, "acceptance_criteria", []) or [])
        rules_count = len(getattr(spec, "business_rules", []) or [])

        table.add_row(
            story_id or "N/A",
            Text(raw_status, style=status_style) if status_style else raw_status,
            title or "Untitled",
            str(crit_count),
            str(rules_count),
        )

    console.print(table)
    return output.getvalue()

