"""
TODO Hunter - Technical Debt Scanner

Scans project files for technical debt markers (TODO, FIXME, HACK, XXX, BUG)
and displays them in a beautifully formatted table using Rich.
"""

import re
from pathlib import Path
from typing import List, Dict, Optional
from rich.console import Console
from rich.table import Table
from rich.text import Text

# Directories to ignore during scanning
IGNORE_DIRS = {
    'venv', 'env', '.venv', '.env',
    'node_modules', 'bower_components',
    '.git', '.svn', '.hg',
    'build', 'dist', '__pycache__',
    '.pytest_cache', '.mypy_cache',
    'vendor', 'target'
}

# File extensions to scan
SCANNABLE_EXTENSIONS = {
    '.py', '.js', '.ts', '.jsx', '.tsx',
    '.go', '.rs', '.java', '.c', '.cpp', '.h', '.hpp',
    '.rb', '.php', '.swift', '.kt', '.scala',
    '.cs', '.dart', '.lua', '.sh', '.bash'
}

# Comment syntax by file extension
COMMENT_STYLES = {
    # Python, Ruby, Shell, Bash
    '.py': '#', '.rb': '#', '.sh': '#', '.bash': '#',
    # JavaScript, TypeScript, Java, C/C++, Go, Rust, etc.
    '.js': '//', '.ts': '//', '.jsx': '//', '.tsx': '//',
    '.java': '//', '.c': '//', '.cpp': '//', '.h': '//', '.hpp': '//',
    '.go': '//', '.rs': '//', '.swift': '//', '.kt': '//', '.scala': '//',
    '.cs': '//', '.dart': '//', '.php': '//',
    # Lua uses --
    '.lua': '--',
}

# Debt marker keywords
DEBT_MARKERS = ['TODO', 'FIXME', 'HACK', 'XXX', 'BUG']

# Color scheme for each debt type
TYPE_COLORS = {
    'TODO': 'blue',
    'FIXME': 'yellow',
    'HACK': 'magenta',
    'XXX': 'red',
    'BUG': 'bright_red',
}


def scan_for_todos(root_path: str, max_depth: int = 10) -> List[Dict]:
    """
    Recursively scans project for technical debt markers.
    
    Args:
        root_path: Root directory to scan
        max_depth: Maximum directory depth to traverse
        
    Returns:
        List of dictionaries containing todo information
    """
    todos = []
    root = Path(root_path).resolve()
    
    def should_ignore(path: Path) -> bool:
        """Check if path should be ignored."""
        return any(part in IGNORE_DIRS for part in path.parts)
    
    def scan_directory(directory: Path, current_depth: int = 0):
        """Recursively scan directory for code files."""
        if current_depth > max_depth:
            return
        
        try:
            for item in directory.iterdir():
                # Skip ignored directories
                if item.is_dir():
                    if item.name not in IGNORE_DIRS and not should_ignore(item):
                        scan_directory(item, current_depth + 1)
                
                # Scan files with supported extensions
                elif item.is_file() and item.suffix in SCANNABLE_EXTENSIONS:
                    file_todos = parse_file_for_todos(str(item))
                    todos.extend(file_todos)
        
        except (PermissionError, OSError):
            # Skip directories/files we can't access
            pass
    
    scan_directory(root)
    return todos


def parse_file_for_todos(file_path: str) -> List[Dict]:
    """
    Parses a single file for technical debt markers.
    
    Args:
        file_path: Path to file to parse
        
    Returns:
        List of dictionaries with format:
        {
            'file': 'relative/path/to/file.py',
            'line': 42,
            'type': 'TODO',
            'message': 'Implement feature X'
        }
    """
    todos = []
    path = Path(file_path)
    
    # Get comment style for this file type
    comment_char = COMMENT_STYLES.get(path.suffix, '#')
    
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line_num, line in enumerate(f, start=1):
                line = line.strip()
                
                # Check each debt marker
                for marker in DEBT_MARKERS:
                    # Build pattern: comment_char + optional whitespace + marker + optional colon + whitespace + message
                    # Examples: "# TODO: message", "// FIXME message", "-- HACK: message"
                    pattern = rf'{re.escape(comment_char)}\s*{marker}:?\s+(.+)'
                    match = re.search(pattern, line, re.IGNORECASE)
                    
                    if match:
                        message = match.group(1).strip()
                        
                        todos.append({
                            'file': str(path.name),  # Just filename for now
                            'line': line_num,
                            'type': marker,
                            'message': message
                        })
                        break  # Only one marker per line
    
    except (UnicodeDecodeError, PermissionError, FileNotFoundError):
        # Skip files we can't read
        pass
    
    return todos


def display_todos_table(todos: List[Dict]) -> None:
    """
    Displays technical debt items in a beautiful Rich table.
    
    Args:
        todos: List of todo dictionaries to display
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
    
    # Add columns
    table.add_column("File", style="cyan", no_wrap=False, width=30)
    table.add_column("Line", style="white", justify="right", width=6)
    table.add_column("Type", style="bold", width=8)
    table.add_column("Message", style="white", no_wrap=False)
    
    # Sort todos by file, then line number
    sorted_todos = sorted(todos, key=lambda x: (x['file'], x['line']))
    
    # Add rows
    for todo in sorted_todos:
        # Color-code the type
        type_color = TYPE_COLORS.get(todo['type'], 'white')
        type_text = Text(todo['type'], style=type_color)
        
        # Truncate message if too long
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
    display_statistics(todos, console)


    # Display statistics
    display_statistics(todos, console)


def get_todos_table_string(todos: List[Dict], plain: bool = False) -> str:
    """
    Returns the technical debt table as a string.
    
    Args:
        todos: List of debt items
        plain: If True, strips ANSI color codes for clean text usage.
    """
    import io
    from rich.console import Console
    
    output = io.StringIO()
    # force_terminal=False + no_color=True -> Plain text
    # force_terminal=True -> ANSI codes (even if redirected)
    
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
        box=None if plain else None # Standard box is fine for text too, actually.
        # Use rich defaults for ASCII box if plain? 
        # Rich "no_color" just removes colors, but keeps box characters. 
        # User complained about "←[1m←[31mCRITICAL", which are ANSI codes. 
        # Box chars like ┌── are Unicode, not ANSI. 
        # If user wants PURE ASCII (no unicode box), that's different.
        # But request specifically said "NO CÓDIGOS DE COLOR ANSI".
    )
    
    # Add columns
    table.add_column("File", style="cyan" if not plain else None, no_wrap=False, width=30)
    table.add_column("Line", style="white" if not plain else None, justify="right", width=6)
    table.add_column("Type", style="bold" if not plain else None, width=8)
    table.add_column("Message", style="white" if not plain else None, no_wrap=False)
    
    # Sort todos
    sorted_todos = sorted(todos, key=lambda x: (x['file'], x['line']))
    
    # Add rows
    for todo in sorted_todos:
        type_color = TYPE_COLORS.get(todo['type'], 'white')
        type_text = Text(todo['type'], style=type_color if not plain else None)
        message = todo['message']
        if len(message) > 60:
            message = message[:57] + "..."
        
        table.add_row(todo['file'], str(todo['line']), type_text, message)
    
    console.print(table)
    console.print()
    display_statistics(todos, console)
    
    return output.getvalue()


def display_statistics(todos: List[Dict], console: Console) -> None:
    """
    Displays summary statistics of technical debt.
    
    Args:
        todos: List of todo dictionaries
        console: Rich console for output
    """
    # Count by type
    type_counts = {}
    for todo in todos:
        debt_type = todo['type']
        type_counts[debt_type] = type_counts.get(debt_type, 0) + 1
    
    # Display summary
    console.print("📊 [bold cyan]Summary by Type:[/bold cyan]")
    
    for marker in DEBT_MARKERS:
        count = type_counts.get(marker, 0)
        color = TYPE_COLORS.get(marker, 'white')
        
        if count > 0:
            console.print(f"  [{color}]●[/{color}] {marker}: [bold]{count}[/bold] items")
        else:
            console.print(f"  [dim]○[/dim] {marker}: [dim]0[/dim] items")
    
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


