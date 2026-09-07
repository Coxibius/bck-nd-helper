import re
import os
from pathlib import Path
from bck_nd_hlpr.core.credential_patterns import (
    BEARER_PATTERN,
    CONNECTION_URI_PATTERN,
    KEY_VALUE_PATTERN,
    PRIVATE_KEY_HEADER_PATTERN,
    RAW_CREDENTIAL_PATTERNS,
    REDACTION_MARKER,
    credential_metadata_for_key,
)
from bck_nd_hlpr.core.sanitizer import sanitize_text
from bck_nd_hlpr.core.utils.indexer import FileSystemIndexer
from typing import List, Dict, Optional

_IP_ADDRESS_PATTERN = re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b')


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _is_lexically_within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath([_path_key(path), _path_key(root)]) == _path_key(root)
    except (OSError, ValueError):
        return False


def _security_file_candidates(
    root_path: str,
    max_depth: Optional[int],
    file_list: Optional[List],
) -> tuple[Path, List[Path]]:
    """Return deterministic, project-contained candidates without an unsafe fallback."""
    root = Path(os.path.abspath(str(root_path)))
    if file_list is None:
        try:
            file_index = FileSystemIndexer(
                str(root),
                max_depth=max_depth,
            ).build()
        except Exception:
            return root, []
        root = file_index.root
        file_list = file_index.all_files

    candidates = {}
    for candidate in file_list:
        path = Path(candidate)
        if _is_lexically_within(path, root):
            candidates[_path_key(path)] = path
    return root, sorted(
        candidates.values(),
        key=lambda path: (str(path).casefold(), str(path)),
    )

# Backward-compatible public registry, derived from the shared credential rules.
RISK_PATTERNS = {
    severity: [
        (rule.pattern, rule.name, "Secrets")
        for rule in RAW_CREDENTIAL_PATTERNS
        if rule.severity == severity
    ]
    for severity in ("CRITICAL", "HIGH", "WARNING")
}
RISK_PATTERNS["CRITICAL"].append(
    (PRIVATE_KEY_HEADER_PATTERN, "Private Key (PEM)", "Secrets")
)
RISK_PATTERNS["HIGH"].append(
    (CONNECTION_URI_PATTERN, "Connection String with Credentials", "Secrets")
)
RISK_PATTERNS["WARNING"].extend(
    [
        (BEARER_PATTERN, "Authorization Header", "Secrets"),
        (_IP_ADDRESS_PATTERN, "Hardcoded IP Address", "Config"),
    ]
)

def scan_sensitive_exposures(root_path: str, entities: List, file_list: Optional[List] = None) -> List[Dict]:
    """
    Analyzes the DB models detected by er_parser and cross-references them with the API
    routes detected by route_parser to warn if sensitive fields may be exposed.

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

    # 1. Identify entities with sensitive columns
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
        
    root, project_files = _security_file_candidates(
        root_path,
        max_depth=None,
        file_list=file_list,
    )

    # 2. Filter the verified index; never fall back to a separate os.walk.
    file_iter = (
        file_path for file_path in project_files
        if file_path.suffix in _EXPOSURE_SUFFIXES
    )

    for file_path in file_iter:
        try:
            from bck_nd_hlpr.core.utils.cache import FileCache
            content = FileCache.read_file(file_path, encoding='utf-8', errors='ignore')
            
            lines = content.splitlines()
            for i, line in enumerate(lines, 1):
                if len(line) > 500:
                    continue
                
                # Ignore comments
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
                            'file': sanitize_text(str(file_path.relative_to(root))),
                            'line': i,
                            'type': 'Sensitive Data Exposure',
                            'severity': 'HIGH',
                            'category': 'Sensitive Data',
                            'message': sanitize_text(
                                f"Entity '{ent_name}' (sensitive cols: {cols_str}) "
                                f"exposed in {match_type}: {stripped[:60]}"
                            ),
                        })
                        break # Avoid duplicating on the same line
        except Exception:
            pass
                
    return risks


def scan_security_risks(root_path: str, max_depth: Optional[int] = 10, file_list: Optional[List] = None) -> List[Dict]:
    """
    Scans project for security risks.

    Args:
        root_path: Root directory to scan.
        max_depth: Maximum directory depth to traverse.
        file_list: Optional pre-computed list of Path objects from FileSystemIndexer.
                   When provided, skips directory walking and scans these files directly.
    """
    risks = []
    root, project_files = _security_file_candidates(
        root_path,
        max_depth=max_depth,
        file_list=file_list,
    )
    
    # Check for environmental config files that shouldn't be committed
    unsafe_files = ['.env', '.env.local', 'secrets.json', 'credentials.json']
    project_file_keys = {_path_key(path) for path in project_files}
    for file in unsafe_files:
        path = root / file
        if _path_key(path) in project_file_keys:
            risks.append({
                'file': file,
                'line': 0,
                'type': 'Unsafe Configuration File',
                'severity': 'HIGH',
                'category': 'Config',
                'message': 'Sensitive configuration file found (ensure it is git-ignored)'
            })

    def scan_file(file_path: Path):
        try:
            from bck_nd_hlpr.core.utils.cache import FileCache
            content = FileCache.read_file(file_path, encoding='utf-8', errors='ignore')
            
            # Scan line by line for precise reporting
            lines = content.splitlines()
            for i, line in enumerate(lines, 1):
                if len(line) > 500: continue # Skip huge lines (minified code)
                
                # Ignore comments
                stripped_line = line.strip()
                if stripped_line.startswith('#') or stripped_line.startswith('//'):
                    continue
                
                if any(
                    env_call in line
                    for env_call in [
                        "os.getenv",
                        "os.environ",
                        "getenv",
                        "process.env",
                        "System.getenv",
                        "$_ENV",
                        "$_SERVER",
                    ]
                ):
                    continue
                if "EXAMPLE" in line.upper() or "TEMPLATE" in line.upper():
                    continue

                matches = []
                key_match = KEY_VALUE_PATTERN.search(line)
                if key_match:
                    key = key_match.group("key") or ""
                    val_clean = (
                        key_match.group("double_value")
                        or key_match.group("single_value")
                        or key_match.group("unquoted_value")
                        or ""
                    ).strip()
                    desc, severity = credential_metadata_for_key(key)
                    matches.append(
                        (key_match, key, val_clean, desc, severity, "Secrets")
                    )

                connection_match = CONNECTION_URI_PATTERN.search(line)
                if connection_match:
                    matches.append(
                        (
                            connection_match,
                            "",
                            connection_match.group("value"),
                            "Connection String with Credentials",
                            "HIGH",
                            "Secrets",
                        )
                    )

                bearer_match = BEARER_PATTERN.search(line)
                if bearer_match:
                    matches.append(
                        (
                            bearer_match,
                            "",
                            bearer_match.group("value"),
                            "Authorization Header",
                            "WARNING",
                            "Secrets",
                        )
                    )

                private_key_match = PRIVATE_KEY_HEADER_PATTERN.search(line)
                if private_key_match:
                    matches.append(
                        (
                            private_key_match,
                            "",
                            private_key_match.group(0),
                            "Private Key (PEM)",
                            "CRITICAL",
                            "Secrets",
                        )
                    )

                for rule in RAW_CREDENTIAL_PATTERNS:
                    raw_match = rule.pattern.search(line)
                    if raw_match:
                        matches.append(
                            (
                                raw_match,
                                "",
                                raw_match.group(0),
                                rule.name,
                                rule.severity,
                                "Secrets",
                            )
                        )

                ip_match = _IP_ADDRESS_PATTERN.search(line)
                if ip_match and not (
                    ip_match.group(0).startswith("127.")
                    or ip_match.group(0) == "0.0.0.0"
                ):
                    matches.append(
                        (
                            ip_match,
                            "",
                            ip_match.group(0),
                            "Hardcoded IP Address",
                            "WARNING",
                            "Config",
                        )
                    )

                seen_findings = set()
                for match, key, val_clean, desc, severity, category in matches:
                    if not val_clean or val_clean == REDACTION_MARKER:
                        continue
                    if key and val_clean.casefold() == key.casefold():
                        continue

                    config_suffixes = {
                        '.yml', '.yaml', '.json', '.properties', '.ini', '.conf'
                    }
                    config_names = {'.env', '.env.local'}
                    is_config_file = (
                        file_path.suffix in config_suffixes
                        or file_path.name in config_names
                    )
                    if not is_config_file and key:
                        quoted = (
                            key_match is match
                            and (
                                match.group("double_value") is not None
                                or match.group("single_value") is not None
                            )
                        )
                        if not quoted:
                            if (
                                re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]*', val_clean)
                                or val_clean.casefold()
                                in {'true', 'false', 'none', 'null', 'undefined'}
                                or '(' in val_clean
                                or ')' in val_clean
                            ):
                                continue

                    exact_placeholders = {
                        'test', 'example', 'dummy', 'xxx', 'changeme',
                        'mysecret', 'secret_key',
                    }
                    substr_placeholders = [
                        'your_key_here', 'your_token_here', 'placeholder'
                    ]
                    val_lower = val_clean.casefold()
                    if val_lower in exact_placeholders:
                        continue
                    if any(placeholder in val_lower for placeholder in substr_placeholders):
                        continue
                    if val_clean.startswith('<') and val_clean.endswith('>'):
                        continue
                    if val_clean.startswith('${') and val_clean.endswith('}'):
                        continue
                    if '%' in val_clean and val_clean.endswith('s'):
                        continue

                    finding_key = (match.start(), match.end(), desc, severity, category)
                    if finding_key in seen_findings:
                        continue
                    seen_findings.add(finding_key)
                    risks.append({
                        'file': sanitize_text(str(file_path.relative_to(root))),
                        'line': i,
                        'type': desc,
                        'severity': severity,
                        'category': category,
                        'message': f"Match: {REDACTION_MARKER}",
                    })
        except Exception:
            pass

    # ── File iteration: fast path or legacy walk ──
    scannable_suffixes = {'.py', '.js', '.ts', '.json', '.yml', '.yaml', '.xml', '.sh', '.go', '.rs', '.cs', '.java', '.php', '.rb'}
    scannable_names = {'.env', '.env.local'}  # dotfiles detected by name

    for file_path in project_files:
        # Scan source code and config files. Dotfiles such as .env are matched
        # by name because Path('.env').suffix is empty on Windows.
        if file_path.suffix in scannable_suffixes or file_path.name in scannable_names:
            scan_file(file_path)
                
    # Run Sensitive Data Tracker
    try:
        from bck_nd_hlpr.core.er_parser import parse_project_for_er
        entities = parse_project_for_er(str(root)) if project_files else []
        exposure_risks = scan_sensitive_exposures(
            str(root),
            entities,
            file_list=project_files,
        )
        risks.extend(exposure_risks)
    except Exception:
        pass
                
    return risks



# ═══════════════════════════════════════════════════════════════════════════════
# FUTURE FUNCTIONS — Foundations for planned features
# ═══════════════════════════════════════════════════════════════════════════════

def get_security_score_breakdown(root_path: str, max_depth: Optional[int] = 10) -> dict:
    """[STUB] Returns normalized security metrics for the Health Score.
    
    Future design:
    1. Call scan_security_risks(root_path, max_depth).
    2. Calculate penalty: CRITICAL × 20, HIGH × 10, WARNING × 3.
    3. Return: {total_risks, critical, high, warning, penalty_score, has_env_exposed: bool}.
    """
    pass
