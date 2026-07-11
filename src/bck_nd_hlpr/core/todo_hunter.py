"""
TODO Hunter - Technical Debt Scanner

Scans project files for technical debt markers (TODO, FIXME, HACK, XXX, BUG)
and displays them in a beautifully formatted table using Rich.
"""

import re
from pathlib import Path
from typing import List, Dict, Optional
from bck_nd_hlpr.core.constants import GLOBAL_IGNORE_DIRS

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
        return any(part in GLOBAL_IGNORE_DIRS for part in path.parts)
    
    def scan_directory(directory: Path, current_depth: int = 0):
        """Recursively scan directory for code files."""
        if current_depth > max_depth:
            return
        
        try:
            for item in directory.iterdir():
                # Skip ignored directories
                if item.is_dir():
                    if item.name not in GLOBAL_IGNORE_DIRS and not should_ignore(item):
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



# ═══════════════════════════════════════════════════════════════════════════════
# FUTURE FUNCTIONS — Cimientos para features planificadas
# ═══════════════════════════════════════════════════════════════════════════════

def get_todo_score_breakdown(root_path: str, max_depth: int = 10) -> dict:
    """[STUB] Retorna métricas de deuda técnica normalizadas para el Health Score.
    
    Diseño futuro:
    1. Llamar a scan_for_todos(root_path, max_depth).
    2. Ponderar por severidad: BUG × 5, FIXME × 3, HACK × 3, TODO × 1, XXX × 2.
    3. Retornar: {total_items, by_type: {TODO: n, FIXME: n, ...}, weighted_score, debt_level: str}.
    """
    pass

