import re
import os
from pathlib import Path
from bck_nd_hlpr.core.constants import GLOBAL_IGNORE_DIRS
from typing import List, Dict, Optional

# RISK_PATTERNS with pattern, desc, and category
RISK_PATTERNS = {
    'CRITICAL': [
        (r'(?i)(password|passwd|pwd|secret|api_key|token|auth_token|access_token|bearer)\s*[:=]\s*[\'"]?([^\s,;\'"}]+)[\'"]?', "Hardcoded Credential", "Secrets"),
        (r'-----BEGIN [A-Z]+ PRIVATE KEY-----', "Private Key (PEM)", "Secrets"),
        (r'\b(AKIA[0-9A-Z]{16})\b', "AWS Access Key", "Secrets"),
        (r'(?i)(AWS_SECRET_ACCESS_KEY)\s*=\s*[\'"]([A-Za-z0-9/+]{40})[\'"]', "AWS Secret Key", "Secrets"),
        (r'\b(ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{82})\b', "GitHub Token", "Secrets"),
        (r'\bglpat-[A-Za-z0-9\-]{20}\b', "GitLab Token", "Secrets"),
        (r'\bsk_live_[A-Za-z0-9]{24,}\b', "Stripe Secret", "Secrets"),
        (r'\bsk_test_[A-Za-z0-9]{24,}\b', "Stripe Test Key", "Secrets"),
        (r'(?i)twilio.*[0-9a-f]{32}', "Twilio Auth Token", "Secrets"),
        (r'SG\.[A-Za-z0-9\-_]{22}\.[A-Za-z0-9\-_]{43}', "SendGrid Key", "Secrets"),
        (r'eyJ[A-Za-z0-9\-_]{10,}\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+', "JWT Hardcoded", "Secrets"),
        (r'[a-z0-9]{32}-us[0-9]{1,2}', "Mailchimp Key", "Secrets"),
        (r'AAAA[A-Za-z0-9+/]{8,}', "Potential High Entropy Token", "Secrets")
    ],
    'HIGH': [
        (r'(?i)(db_pass|database_password|postgres_password|mysql_root_password)\s*[:=]\s*[\'"]?([^\s,;\'"}]+)[\'"]?', "Database Password", "Secrets"),
        (r'(?i)(database_url|connection_string)\s*[:=]\s*[\'"]?[a-z]+://[^:]+:[^@]+@[^/]+', "Connection String with Credentials", "Secrets"),
        (r'xox[baprs]-[A-Za-z0-9\-]{10,}', "Slack Token", "Secrets"),
        (r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', "Heroku Key", "Secrets"),
        (r'npm_[A-Za-z0-9]{36}', "NPM Token", "Secrets")
    ],
    'WARNING': [
        (r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', "Hardcoded IP Address", "Config"),
        (r'(?i)authorization\s*:\s*[\'"]Bearer\s+[a-zA-Z0-9_\-\.]+[\'"]', "Authorization Header", "Secrets"),
    ]
}

def scan_sensitive_exposures(root_path: str, entities: List, file_list: Optional[List] = None) -> List[Dict]:
    """
    Analiza los modelos de BD detectados por er_parser y los cruza con las rutas de API
    detectadas por route_parser para advertir si campos sensibles pueden estar expuestos.

    Args:
        root_path: Root directory of the project.
        entities: List of ER entities from er_parser.
        file_list: Optional pre-computed list of Path objects from FileSystemIndexer.
                   When provided, skips directory walking and scans these files directly.
    """
    risks = []
    SENSITIVE_FIELDS = {
        'password', 'passwd', 'secret', 'token', 'credit_card', 
        'card_number', 'cvv', 'ssn', 'social_security', 'pin'
    }
    
    _EXPOSURE_SUFFIXES = {'.py', '.js', '.ts', '.cs', '.java', '.php', '.rb'}

    # 1. Identificar entidades con columnas sensibles
    sensitive_entities = {}
    for entity in entities:
        sens_cols = []
        for col_name, col_type in entity.columns:
            if any(sf in col_name.lower() for sf in SENSITIVE_FIELDS):
                sens_cols.append(col_name)
        if sens_cols:
            sensitive_entities[entity.name] = sens_cols
            
    if not sensitive_entities:
        return risks
        
    root = Path(root_path).resolve()
    
    # 2. Build file iterator — fast path or legacy walk
    if file_list is not None:
        file_iter = (
            Path(f) for f in file_list
            if Path(f).suffix in _EXPOSURE_SUFFIXES
        )
    else:
        def _walk_files():
            for root_dir, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS]
                for file in files:
                    file_path = Path(root_dir) / file
                    if file_path.suffix in _EXPOSURE_SUFFIXES:
                        yield file_path
        file_iter = _walk_files()

    for file_path in file_iter:
        try:
            from bck_nd_hlpr.core.utils.cache import FileCache
            content = FileCache.read_file(file_path, encoding='utf-8', errors='ignore')
            
            lines = content.splitlines()
            for i, line in enumerate(lines, 1):
                if len(line) > 500:
                    continue
                
                # Ignorar comentarios
                stripped = line.strip()
                if stripped.startswith('#') or stripped.startswith('//'):
                    continue
                    
                for ent_name, sens_cols in sensitive_entities.items():
                    ent_lower = ent_name.lower()
                    
                    # response_model=User, schema=UserSchema, schema=User
                    p_model = rf'\b(response_model|schema)\s*=\s*\w*{re.escape(ent_name)}\w*'
                    
                    # return user, return user_list, return users
                    p_return = rf'\breturn\s+[^;]*?\b{re.escape(ent_lower)}\b'
                    
                    # jsonify(user), jsonify(user_data)
                    p_json = rf'\bjsonify\(\s*[^)]*?\b{re.escape(ent_lower)}\b'
                    
                    match_type = ""
                    if re.search(p_model, line):
                        match_type = "schema/model reference"
                    elif re.search(p_return, line, re.IGNORECASE):
                        match_type = "return variable"
                    elif re.search(p_json, line, re.IGNORECASE):
                        match_type = "jsonify call"
                        
                    if match_type:
                        cols_str = ", ".join(sens_cols)
                        if "import " in line or "from " in line or "require(" in line:
                            continue
                        
                        risks.append({
                            'file': str(file_path.relative_to(root)),
                            'line': i,
                            'type': 'Sensitive Data Exposure',
                            'severity': 'HIGH',
                            'category': 'Sensitive Data',
                            'message': f"Entity '{ent_name}' (sensitive cols: {cols_str}) exposed in {match_type}: {stripped[:60]}"
                        })
                        break # Evitar duplicar en la misma línea
        except Exception:
            pass
                
    return risks


def scan_security_risks(root_path: str, max_depth: int = 10, file_list: Optional[List] = None) -> List[Dict]:
    """
    Scans project for security risks.

    Args:
        root_path: Root directory to scan.
        max_depth: Maximum directory depth to traverse.
        file_list: Optional pre-computed list of Path objects from FileSystemIndexer.
                   When provided, skips directory walking and scans these files directly.
    """
    risks = []
    root = Path(root_path).resolve()
    
    # Check for environmental config files that shouldn't be committed
    unsafe_files = ['.env', '.env.local', 'secrets.json', 'credentials.json']
    for file in unsafe_files:
        path = root / file
        if path.exists():
            risks.append({
                'file': file,
                'line': 0,
                'type': 'Unsafe Configuration File',
                'severity': 'HIGH',
                'category': 'Config',
                'message': 'Sensitive configuration file found (ensure it is git-ignored)'
            })

    def should_ignore(path: Path) -> bool:
        return any(part in GLOBAL_IGNORE_DIRS for part in path.parts)

    def scan_file(file_path: Path):
        try:
            from bck_nd_hlpr.core.utils.cache import FileCache
            content = FileCache.read_file(file_path, encoding='utf-8', errors='ignore')
            
            # Scan line by line for precise reporting
            lines = content.splitlines()
            for i, line in enumerate(lines, 1):
                if len(line) > 500: continue # Skip huge lines (minified code)
                
                # Ignorar comentarios
                stripped_line = line.strip()
                if stripped_line.startswith('#') or stripped_line.startswith('//'):
                    continue
                
                for severity, patterns in RISK_PATTERNS.items():
                    for pattern, desc, category in patterns:
                        # Exclude some false positives
                        if any(env_call in line for env_call in ["os.getenv", "os.environ", "getenv", "process.env", "System.getenv", "$_ENV", "$_SERVER"]):
                            continue
                        if "EXAMPLE" in line.upper() or "TEMPLATE" in line.upper(): continue
                        
                        match = re.search(pattern, line)
                        if match:
                            # Extract key and value
                            key = ""
                            val = ""
                            if match.lastindex and match.lastindex >= 2:
                                key = match.group(1)
                                val = match.group(2)
                            else:
                                val = match.group(0)
                            
                            val_clean = val.strip('\'"')
                            
                            # Filter local IP (127.0.0.1, 0.0.0.0) if strictly hardcoded IP check
                            if desc == "Hardcoded IP Address":
                                ip = match.group(0)
                                if ip.startswith("127.") or ip == "0.0.0.0": continue
                            
                            # False positive check: RHS equals LHS
                            if key and val_clean.lower() == key.lower():
                                continue
                                
                            # False positive check: RHS is a variable/expression and NOT quoted (for source files)
                            config_suffixes = {'.yml', '.yaml', '.json', '.properties', '.ini', '.conf'}
                            config_names = {'.env', '.env.local'}  # dotfiles have no suffix on Windows
                            is_config_file = file_path.suffix in config_suffixes or file_path.name in config_names
                            if not is_config_file and key:
                                if not (f"'{val_clean}'" in line or f'"{val_clean}"' in line):
                                    if re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', val_clean) or val_clean.lower() in ['true', 'false', 'none', 'null', 'undefined']:
                                        continue
                                    if '(' in val_clean or ')' in val_clean:
                                        continue
                            
                            # Placeholders ignored
                            # Exact-match placeholders (short/generic words that could be substrings of real tokens)
                            exact_placeholders = {'test', 'example', 'dummy', 'xxx', 'changeme', 'mysecret', 'secret_key'}
                            # Substring-match placeholders (specific enough to safely substring-check)
                            substr_placeholders = ['your_key_here', 'your_token_here', 'placeholder']
                            val_lower = val_clean.lower()
                            if val_lower in exact_placeholders:
                                continue
                            if any(p in val_lower for p in substr_placeholders):
                                continue
                                
                            if val_clean.startswith('<') and val_clean.endswith('>'):
                                continue
                            if val_clean.startswith('${') and val_clean.endswith('}'):
                                continue
                            if '%' in val_clean and val_clean.endswith('s'):
                                continue
                                
                            # Mínimo de longitud para el valor (> 6 chars)
                            if desc in ["Hardcoded Credential", "Database Password"] and len(val_clean) <= 6:
                                continue
                            
                            secret_preview = match.group(0)
                            if len(secret_preview) > 40: secret_preview = secret_preview[:37] + "..."
                            
                            risks.append({
                                'file': str(file_path.relative_to(root)),
                                'line': i,
                                'type': desc,
                                'severity': severity,
                                'category': category,
                                'message': f"Match: {secret_preview}"
                            })
        except Exception:
            pass

    # ── File iteration: fast path or legacy walk ──
    scannable_suffixes = {'.py', '.js', '.ts', '.json', '.yml', '.yaml', '.xml', '.sh', '.go', '.rs', '.cs', '.java', '.php', '.rb'}
    scannable_names = {'.env', '.env.local'}  # dotfiles detected by name

    if file_list is not None:
        # Fast path: use pre-indexed file list
        for f in file_list:
            file_path = Path(f)
            if file_path.suffix in scannable_suffixes or file_path.name in scannable_names:
                scan_file(file_path)
    else:
        # Legacy path: own directory walk
        for root_dir, dirs, files in os.walk(root):
            rel_root = Path(root_dir).relative_to(root)
            if str(rel_root) == ".": depth_val = 0
            else: depth_val = len(rel_root.parts)
            
            if depth_val > max_depth:
                del dirs[:]
                continue
                
            dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS]
            
            for file in files:
                file_path = Path(root_dir) / file
                # Scan source code and config files
                # Note: dotfiles like .env have no suffix on Windows (Path('.env').suffix == '')
                if file_path.suffix in scannable_suffixes or file_path.name in scannable_names:
                    scan_file(file_path)
                
    # Run Sensitive Data Tracker
    try:
        from bck_nd_hlpr.core.er_parser import parse_project_for_er
        entities = parse_project_for_er(str(root))
        exposure_risks = scan_sensitive_exposures(str(root), entities)
        risks.extend(exposure_risks)
    except Exception:
        pass
                
    return risks



# ═══════════════════════════════════════════════════════════════════════════════
# FUTURE FUNCTIONS — Cimientos para features planificadas
# ═══════════════════════════════════════════════════════════════════════════════

def get_security_score_breakdown(root_path: str, max_depth: int = 10) -> dict:
    """[STUB] Retorna métricas de seguridad normalizadas para el Health Score.
    
    Diseño futuro:
    1. Llamar a scan_security_risks(root_path, max_depth).
    2. Calcular penalización: CRITICAL × 20, HIGH × 10, WARNING × 3.
    3. Retornar: {total_risks, critical, high, warning, penalty_score, has_env_exposed: bool}.
    """
    pass
