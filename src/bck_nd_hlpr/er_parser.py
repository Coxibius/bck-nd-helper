"""
Módulo para la generación de Diagramas E-R (Entity-Relationship) mediante análisis estático.
Soporta detección básica de modelos SQLAlchemy y Django.
"""
import ast
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any

class EREntity:
    """Representa una entidad (tabla) en el diagrama ER."""
    def __init__(self, name: str):
        self.name = name
        self.columns: List[tuple[str, str]] = []  # (name, type)
        self.relationships: List[tuple[str, str, str]] = [] # (target_entity, relation_type, label)

class ERExtractor(ast.NodeVisitor):
    """
    Analiza AST para encontrar modelos de base de datos.
    """
    def __init__(self):
        self.entities: List[EREntity] = []
        self.current_entity: Optional[EREntity] = None
        self.imports: Dict[str, str] = {}

    def visit_ImportFrom(self, node: ast.ImportFrom):
        module = node.module or ""
        for alias in node.names:
            name = alias.name
            asname = alias.asname or name
            self.imports[asname] = f"{module}.{name}" if module else name
        self.generic_visit(node)

    def _is_model(self, bases: List[Any]) -> bool:
        """Heurística para determinar si es un modelo ORM."""
        model_bases = {'Base', 'Model', 'db.Model', 'models.Model', 'DeclarativeBase'}
        for base in bases:
            if isinstance(base, ast.Name) and base.id in model_bases:
                return True
            if isinstance(base, ast.Attribute) and base.attr == 'Model':
                return True
        return False

    def visit_ClassDef(self, node: ast.ClassDef):
        if self._is_model(node.bases):
            self.current_entity = EREntity(node.name)
            self.entities.append(self.current_entity)
            self.generic_visit(node)
            self.current_entity = None
        else:
            # Aún si no hereda explícitamente, buscamos si tiene __tablename__
            has_tablename = any(
                isinstance(n, ast.Assign) and 
                any(isinstance(t, ast.Name) and t.id == '__tablename__' for t in n.targets)
                for n in node.body
            )
            if has_tablename:
                self.current_entity = EREntity(node.name)
                self.entities.append(self.current_entity)
                self.generic_visit(node)
                self.current_entity = None

    def visit_Assign(self, node: ast.Assign):
        if not self.current_entity:
            return

        target_name = ""
        for target in node.targets:
            if isinstance(target, ast.Name):
                target_name = target.id
        
        if not target_name:
            return

        if isinstance(node.value, ast.Call):
            func_name = ""
            if isinstance(node.value.func, ast.Name):
                func_name = node.value.func.id
            elif isinstance(node.value.func, ast.Attribute):
                func_name = node.value.func.attr

            # SQLAlchemy
            if func_name in ['Column', 'Mapped']:
                col_type = "Unknown"
                if node.value.args:
                    arg0 = node.value.args[0]
                    if isinstance(arg0, ast.Name):
                        col_type = arg0.id
                    elif isinstance(arg0, ast.Attribute):
                        col_type = arg0.attr
                self.current_entity.columns.append((target_name, col_type))
                
                # Busqueda simple de ForeignKey en args
                for arg in node.value.args:
                    if isinstance(arg, ast.Call) and getattr(arg.func, 'id', '') == 'ForeignKey':
                         if arg.args and isinstance(arg.args[0], ast.Constant):
                             # 'users.id' -> target 'User' (heuristic)
                             fk_ref = str(arg.args[0].value)
                             target_table = fk_ref.split('.')[0]
                             self.current_entity.relationships.append((target_table, "}o--||", "FK"))

            # Django
            elif 'Field' in func_name:
                col_type = func_name.replace("Field", "")
                self.current_entity.columns.append((target_name, col_type))
                
                if 'ForeignKey' in func_name or 'OneToOne' in func_name:
                     if node.value.args:
                        arg0 = node.value.args[0]
                        target = "Unknown"
                        if isinstance(arg0, ast.Name):
                            target = arg0.id
                        elif isinstance(arg0, ast.Constant):
                            target = str(arg0.value)
                        elif isinstance(arg0, ast.Str): # Python < 3.8
                             target = arg0.s
                        self.current_entity.relationships.append((target, "}o--||", "FK"))

    def visit_AnnAssign(self, node: ast.AnnAssign):
        # TODO: Soportar Mapped[int] si es necesario en el futuro
        pass

def parse_prisma_schema(file_path: Path) -> List[EREntity]:
    entities = []
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            
        model_blocks = re.findall(r'model\s+(\w+)\s*\{([^}]+)\}', content)
        for model_name, body in model_blocks:
            entity = EREntity(model_name)
            for line in body.splitlines():
                line = line.strip()
                if not line or line.startswith("//"):
                    continue
                
                parts = line.split()
                if len(parts) >= 2:
                    field_name = parts[0]
                    field_type = parts[1]
                    
                    is_relation = False
                    is_id = "@id" in line
                    
                    clean_type = field_type.replace("?", "").replace("[]", "")
                    prisma_types = {"String", "Int", "Float", "Boolean", "DateTime", "Json", "Decimal", "BigInt", "Bytes"}
                    
                    if clean_type not in prisma_types:
                        is_relation = True
                        
                    if is_relation:
                        rel_symbol = "||--o{" if "[]" in field_type else "}o--||"
                        entity.relationships.append((clean_type, rel_symbol, field_name))
                    else:
                        col_type = field_type
                        if is_id:
                            col_type += " PK"
                        entity.columns.append((field_name, col_type))
            entities.append(entity)
    except Exception as e:
        print(f"Error parsing Prisma schema {file_path}: {e}", file=sys.stderr)
    return entities

def parse_sql_file(file_path: Path) -> List[EREntity]:
    entities = []
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            
        content = re.sub(r'--.*$', '', content, flags=re.MULTILINE)
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        
        create_tables = re.findall(r'(?i)CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+|`\w+`|"\w+")\s*\((.*?)\)\s*;', content, flags=re.DOTALL)
        
        for table_name_raw, table_body in create_tables:
            table_name = table_name_raw.strip('`" ')
            entity = EREntity(table_name)
            
            parts = []
            current_part = []
            paren_depth = 0
            for char in table_body:
                if char == '(':
                    paren_depth += 1
                    current_part.append(char)
                elif char == ')':
                    paren_depth -= 1
                    current_part.append(char)
                elif char == ',' and paren_depth == 0:
                    parts.append("".join(current_part).strip())
                    current_part = []
                else:
                    current_part.append(char)
            if current_part:
                parts.append("".join(current_part).strip())
                
            for part in parts:
                part = part.strip()
                if not part:
                    continue
                    
                fk_match = re.search(r'(?i)(?:CONSTRAINT\s+\w+\s+)?FOREIGN\s+KEY\s*\((.*?)\)\s*REFERENCES\s+(\w+|`\w+`|"\w+")\s*\((.*?)\)', part)
                if fk_match:
                    fk_col = fk_match.group(1).strip('`" ')
                    target_table = fk_match.group(2).strip('`" ')
                    entity.relationships.append((target_table, "}o--||", fk_col))
                    continue
                    
                pk_match = re.search(r'(?i)PRIMARY\s+KEY\s*\((.*?)\)', part)
                if pk_match:
                    pk_cols = [c.strip('`" ') for c in pk_match.group(1).split(',')]
                    for i, (col_name, col_type) in enumerate(entity.columns):
                        if col_name in pk_cols:
                            entity.columns[i] = (col_name, col_type + " PK")
                    continue
                    
                tokens = part.split()
                if len(tokens) >= 2:
                    col_name = tokens[0].strip('`" ')
                    if col_name.upper() in ["CONSTRAINT", "PRIMARY", "UNIQUE", "KEY", "INDEX", "FOREIGN"]:
                        continue
                        
                    col_type = tokens[1]
                    is_pk = "PRIMARY KEY" in part.upper()
                    if is_pk:
                        col_type += " PK"
                    entity.columns.append((col_name, col_type))
            entities.append(entity)
    except Exception as e:
        print(f"Error parsing SQL file {file_path}: {e}", file=sys.stderr)
    return entities

def parse_drizzle_schema(file_path: Path) -> List[EREntity]:
    entities = []
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            
        table_matches = re.finditer(r'(?:export\s+)?const\s+(\w+)\s*=\s*(?:pgTable|mysqlTable|sqliteTable)\(\s*[\'"](\w+)[\'"]\s*,\s*\{', content)
        
        for table_match in table_matches:
            table_name = table_match.group(2)
            
            start_idx = table_match.end()
            brace_count = 1
            body_chars = []
            for i in range(start_idx, len(content)):
                char = content[i]
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                body_chars.append(char)
                if brace_count == 0:
                    break
            
            body_text = "".join(body_chars)[:-1]
            entity = EREntity(table_name)
            
            for line in body_text.splitlines():
                line = line.strip()
                if not line or line.startswith("//"):
                    continue
                
                col_match = re.match(r'(\w+)\s*:\s*(\w+)\((.*?)\)(.*)', line)
                if col_match:
                    col_name = col_match.group(1)
                    col_type_fn = col_match.group(2)
                    modifiers = col_match.group(4)
                    
                    is_pk = "primaryKey" in modifiers
                    ref_match = re.search(r'\.references\(\(\)\s*=>\s*(\w+)\.(\w+)\)', modifiers)
                    if ref_match:
                        ref_table = ref_match.group(1)
                        entity.relationships.append((ref_table, "}o--||", col_name))
                        
                    col_type = col_type_fn
                    if is_pk:
                        col_type += " PK"
                    entity.columns.append((col_name, col_type))
            entities.append(entity)
    except Exception as e:
        print(f"Error parsing Drizzle schema {file_path}: {e}", file=sys.stderr)
    return entities

def parse_project_for_er(root_path: str, max_depth: int = 3) -> List[EREntity]:
    all_entities = []
    root = Path(root_path)
    
    ignore_dirs = {'venv', 'env', '.venv', '__pycache__', '.git', 'node_modules', 'dist', 'build'}

    for root_dir, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith('.')]
        
        try:
            current_depth = len(Path(root_dir).relative_to(root).parts)
        except ValueError:
            current_depth = 0
            
        if current_depth > max_depth:
            continue
            
        for file in files:
            file_path = Path(root_dir) / file
            # 1. Python Models (SQLAlchemy / Django)
            if file.endswith(".py"):
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    tree = ast.parse(content)
                    extractor = ERExtractor()
                    extractor.visit(tree)
                    all_entities.extend(extractor.entities)
                except Exception:
                    pass
            # 2. Prisma Schemas
            elif file.endswith(".prisma"):
                all_entities.extend(parse_prisma_schema(file_path))
            # 3. SQL Migrations & Tables
            elif file.endswith(".sql"):
                all_entities.extend(parse_sql_file(file_path))
            # 4. JS/TS files (Drizzle schemas)
            elif file.endswith((".js", ".ts", ".jsx", ".tsx")):
                all_entities.extend(parse_drizzle_schema(file_path))
                    
    # Unified execution of language-specific parsers that walk the project:
    # 5. C# ER Parser (Entity Framework)
    try:
        from bck_nd_hlpr.csharp_parser import parse_project_for_csharp_er
        all_entities.extend(parse_project_for_csharp_er(root_path, max_depth=max_depth))
    except Exception as e:
        print(f"Error parsing C# ER: {e}", file=sys.stderr)
        
    # 6. Java ER Parser (Spring Boot / JPA)
    try:
        from bck_nd_hlpr.java_parser import parse_project_for_java_er
        all_entities.extend(parse_project_for_java_er(root_path, max_depth=max_depth))
    except Exception as e:
        print(f"Error parsing Java ER: {e}", file=sys.stderr)
        
    # 7. JS/TS ER Parser (Mongoose / Sequelize)
    try:
        from bck_nd_hlpr.js_parser import parse_project_for_js_er
        all_entities.extend(parse_project_for_js_er(root_path, max_depth=max_depth))
    except Exception as e:
        print(f"Error parsing JS/TS ER: {e}", file=sys.stderr)
        
    # 8. PHP ER Parser (Laravel / Eloquent)
    try:
        from bck_nd_hlpr.php_parser import parse_project_for_php_er
        all_entities.extend(parse_project_for_php_er(root_path, max_depth=max_depth))
    except Exception as e:
        print(f"Error parsing PHP ER: {e}", file=sys.stderr)

    # Deduplicate entities by name to avoid duplicates
    seen = {}
    deduped = []
    for ent in all_entities:
        if ent.name not in seen:
            seen[ent.name] = ent
            deduped.append(ent)
        else:
            existing = seen[ent.name]
            existing.columns.extend([col for col in ent.columns if col not in existing.columns])
            existing.relationships.extend([rel for rel in ent.relationships if rel not in existing.relationships])
            
    return deduped

def generate_mermaid_er(entities: List[EREntity]) -> str:
    lines = ["erDiagram"]
    
    if not entities:
        return ""

    import re
    def sanitize(name: str) -> str:
        # Reemplazar caracteres no alfanuméricos por guiones bajos
        s = re.sub(r'[^A-Za-z0-9_]', '_', str(name).strip())
        if not s: return "E_UNKNOWN"
        if not s[0].isalpha():
            s = 'E_' + s
        return s

    entity_names = {sanitize(e.name) for e in entities}
    
    # 1. Definir Entidades
    for entity in entities:
        safe_entity_name = sanitize(entity.name)
        if entity.columns:
            lines.append(f"    {safe_entity_name} {{")
            for col_name, col_type in entity.columns:
                # Mermaid ER no soporta espacios, <, >, etc en tipos y nombres
                clean_type = sanitize(col_type)
                clean_col = sanitize(col_name)
                lines.append(f"        {clean_type} {clean_col}")
            lines.append("    }")
        else:
            lines.append(f"    {safe_entity_name}")
    
    # 2. Definir Relaciones
    for entity in entities:
        safe_entity_name = sanitize(entity.name)
        for target, rel_type, label in entity.relationships:
            safe_target = sanitize(target)
            
            # Heurística para encontrar el nombre real de la clase destino
            real_target = safe_target
            
            # Si target es 'users' (tabla) y tenemos clase 'User'
            candidate_singular = safe_target.capitalize()
            # Quitamos 's' final simple
            candidate_singular_s = safe_target[:-1].capitalize() if safe_target.endswith('s') else safe_target

            if safe_target in entity_names:
                real_target = safe_target
            elif candidate_singular in entity_names:
                real_target = candidate_singular
            elif candidate_singular_s in entity_names:
                real_target = candidate_singular_s
            
            # Solo dibujamos si el target existe (o lo forzamos si se prefiere)
            # Para robustez, dibujamos igual, Mermaid lo creará si no existe
            safe_label = str(label).replace('"', '').replace('\n', '')
            lines.append(f"    {safe_entity_name} {rel_type} {real_target} : \"{safe_label}\"")
            
    return "\n".join(lines)
