import re
import os
from pathlib import Path
from typing import List, Dict
from rich.console import Console
from rich.table import Table
from rich.text import Text

# Reuse patterns from sanitizer but we want to capturing them for reporting
# We redefine them here slightly to separate Logic. 
# Ideally we import them, but sanitizer regexes are for replacement (finding keys).
# Here we want to report the FINDING.

RISK_PATTERNS = {
    'CRITICAL': [
        (r'(?i)(password|passwd|pwd|secret|api_key|token|auth_token|access_token|bearer)\s*[:=]\s*[\'"]?([^\s,;\'"}]+)[\'"]?', "Hardcoded Credential"),
        (r'-----BEGIN [A-Z]+ PRIVATE KEY-----', "Private Key (PEM)"),
        (r'(?i)AWS_ACCESS_KEY_ID\s*=\s*[\'"]AKIA[0-9A-Z]{16}[\'"]', "AWS Access Key"),
        (r'AAAA[A-Za-z0-9+/]{8,}', "Potential High Entropy Token")
    ],
    'HIGH': [
        (r'(?i)(db_pass|database_password|postgres_password|mysql_root_password)\s*[:=]\s*[\'"]?([^\s,;\'"}]+)[\'"]?', "Database Password"),
        (r'(?i)(database_url|connection_string)\s*[:=]\s*[\'"]?[a-z]+://[^:]+:[^@]+@[^/]+', "Connection String with Credentials")
    ],
    'WARNING': [
        (r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', "Hardcoded IP Address"),
        (r'(?i)authorization\s*:\s*[\'"]Bearer\s+[a-zA-Z0-9_\-\.]+[\'"]', "Authorization Header"),
    ]
}

# Ignore list similar to scanner
IGNORE_DIRS = {
    'venv', 'env', '.venv', '__pycache__', '.git', 'node_modules', 'dist', 'build', 'htmlcov'
}

def scan_security_risks(root_path: str, max_depth: int = 10) -> List[Dict]:
    """
    Scans project for security risks.
    """
    risks = []
    root = Path(root_path).resolve()
    
    # Check for environmental config files that shouldn't be committed
    unsafe_files = ['.env', '.env.local', 'secrets.json', 'credentials.json']
    for file in unsafe_files:
        path = root / file
        if path.exists():
            # Check if ignored (naive check, real check needs parsing .gitignore)
            # For now, just REPORT that they exist.
            risks.append({
                'file': file,
                'line': 0,
                'type': 'WARNING',
                'severity': 'HIGH', # Having .env in repo is bad
                'message': 'Sensitive configuration file found (ensure it is git-ignored)'
            })

    def should_ignore(path: Path) -> bool:
        return any(part in IGNORE_DIRS for part in path.parts)

    def scan_file(file_path: Path):
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                
            # Scan line by line for precise reporting
            lines = content.splitlines()
            for i, line in enumerate(lines, 1):
                if len(line) > 500: continue # Skip huge lines (minified code)
                
                for severity, patterns in RISK_PATTERNS.items():
                    for pattern, desc in patterns:
                        # Exclude some false positives naively
                        if "os.getenv" in line or "os.environ" in line: continue
                        if "EXAMPLE" in line.upper() or "TEMPLATE" in line.upper(): continue
                        
                        match = re.search(pattern, line)
                        if match:
                            # Avoid matching simple variable usage like "password = password"
                            # Our regex enforces assignment syntax usually
                            
                            # Filter local IP (127.0.0.1, 0.0.0.0) if strictly hardcoded IP check
                            if desc == "Hardcoded IP Address":
                                ip = match.group(0)
                                if ip.startswith("127.") or ip == "0.0.0.0": continue
                                # If looks like version number (1.0.0.0), skip. 
                                # This is hard. Let's keep it simple for now.
                            
                            secret_preview = match.group(0)
                            if len(secret_preview) > 40: secret_preview = secret_preview[:37] + "..."
                            
                            risks.append({
                                'file': str(file_path.relative_to(root)),
                                'line': i,
                                'type': desc,
                                'severity': severity,
                                'message': f"Match: {secret_preview}"
                            })
                            # Break inner loop to avoid double reporting same line? No, multiple risks possible.
        except Exception:
            pass

    for root_dir, dirs, files in os.walk(root):
        rel_root = Path(root_dir).relative_to(root)
        if str(rel_root) == ".": depth = 0
        else: depth = len(rel_root.parts)
        
        if depth > max_depth:
            del dirs[:]
            continue
            
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        
        for file in files:
            file_path = Path(root_dir) / file
            # Scan source code and config files
            if file_path.suffix in ['.py', '.js', '.ts', '.json', '.yml', '.yaml', '.xml', '.env', '.sh', '.go', '.rs']:
                scan_file(file_path)
                
    return risks

def get_security_report_string(risks: List[Dict], plain: bool = False) -> str:
    """Generates the security report table string."""
    import io
    output = io.StringIO()
    
    if plain:
        console = Console(file=output, force_terminal=False, no_color=True, width=120)
    else:
        console = Console(file=output, force_terminal=True, width=120)
        
    table = Table(
        title="🚨 SECURITY AUDIT REPORT 🚨",
        show_header=True,
        header_style="bold red" if not plain else None,
        border_style="red" if not plain else None,
        title_style="bold red" if not plain else None
    )
    
    table.add_column("Severity", style="bold red" if not plain else None, width=10)
    table.add_column("File", style="cyan" if not plain else None)
    table.add_column("Line", justify="right")
    table.add_column("Risk Type", style="yellow" if not plain else None)
    table.add_column("Message")
    
    # Sort by severity (CRITICAL -> HIGH -> WARNING)
    severity_order = {'CRITICAL': 0, 'HIGH': 1, 'WARNING': 2}
    sorted_risks = sorted(risks, key=lambda x: (severity_order.get(x['severity'], 99), x['file']))
    
    for risk in sorted_risks:
        sev = risk['severity']
        style = "bold red" if sev == 'CRITICAL' else ("bold orange3" if sev == 'HIGH' else "yellow")
        if plain: style = None
        
        table.add_row(
            Text(sev, style=style),
            risk['file'],
            str(risk['line']),
            risk['type'],
            risk['message']  # Should ideally be sanitized before printing? 
                             # The whole point is showing WHERE it is. 
                             # Maybe mask the actual secret in the preview?
                             # For an AUDIT tool for the dev, showing it is helpful. 
                             # But `todo_hunter` didn't mask. 
                             # Let's keep it provided the user is running this locally.
        )
        
    console.print(table)
    
    if not risks:
        console.print("\n[bold green]✅ No obvious security risks found.[/bold green]" if not plain else "\n✅ No obvious security risks found.")
    else:
        console.print(f"\n[bold red]Found {len(risks)} potential security risks.[/bold red]" if not plain else f"\nFound {len(risks)} potential security risks.")
    
    return output.getvalue()
