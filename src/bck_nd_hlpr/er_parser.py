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
from bck_nd_hlpr.constants import GLOBAL_IGNORE_DIRS

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
    def __init__(self, is_model_file: bool = False):
        self.entities: List[EREntity] = []
        self.current_entity: Optional[EREntity] = None
        self.imports: Dict[str, str] = {}
        self.is_model_file = is_model_file

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
        if self._is_model(node.bases) or self.is_model_file:
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
            elif 'Field' in func_name or 'ManyToManyField' in func_name:
                col_type = func_name.replace("Field", "")
                self.current_entity.columns.append((target_name, col_type))
                
                if 'ForeignKey' in func_name or 'OneToOne' in func_name or 'ManyToManyField' in func_name:
                     if node.value.args:
                        arg0 = node.value.args[0]
                        target = "Unknown"
                        if isinstance(arg0, ast.Name):
                            target = arg0.id
                        elif isinstance(arg0, ast.Constant):
                            target = str(arg0.value)
                        elif isinstance(arg0, ast.Str): # Python < 3.8
                             target = arg0.s
                        
                        target = target.strip("'\"")
                        if "." in target:
                            target = target.split(".")[-1]
                        
                        if 'ManyToManyField' in func_name:
                            rel_type = "}o--o{"
                        elif 'OneToOne' in func_name:
                            rel_type = "||--||"
                        else:
                            rel_type = "}o--||"
                            
                        self.current_entity.relationships.append((target, rel_type, "FK"))

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

def extract_bracket_content(text: str, start_idx: int, open_char: str = '{', close_char: str = '}') -> str:
    brace_count = 1
    body_chars = []
    for i in range(start_idx, len(text)):
        char = text[i]
        if char == open_char:
            brace_count += 1
        elif char == close_char:
            brace_count -= 1
        body_chars.append(char)
        if brace_count == 0:
            break
    if body_chars and body_chars[-1] == close_char:
        return "".join(body_chars)[:-1]
    return "".join(body_chars)

def parse_ts_interfaces_and_types(file_path: Path) -> List[EREntity]:
    entities = []
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            
        content = re.sub(r'//.*$', '', content, flags=re.MULTILINE)
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        
        # 1. Match interfaces
        interface_matches = re.finditer(r'(?:export\s+)?(?:default\s+)?interface\s+(\w+)(?:\s+extends\s+[^{]+)?\s*\{', content)
        for match in interface_matches:
            name = match.group(1)
            body = extract_bracket_content(content, match.end(), '{', '}')
            entity = parse_ts_fields(name, body)
            if entity:
                entities.append(entity)
                
        # 2. Match types
        type_matches = re.finditer(r'(?:export\s+)?type\s+(\w+)\s*=\s*\{', content)
        for match in type_matches:
            name = match.group(1)
            body = extract_bracket_content(content, match.end(), '{', '}')
            entity = parse_ts_fields(name, body)
            if entity:
                entities.append(entity)
    except Exception as e:
        print(f"Error parsing TS interfaces/types in {file_path}: {e}", file=sys.stderr)
    return entities

def parse_ts_fields(entity_name: str, body: str) -> Optional[EREntity]:
    entity = EREntity(entity_name)
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        
        match = re.match(r'(\w+)\s*(\??)\s*:\s*([^;,\n]+)', line)
        if match:
            field_name = match.group(1)
            field_type = match.group(3).strip()
            
            is_relation = False
            target_class = ""
            rel_symbol = "}o--||"
            
            if field_name.endswith("Id") or field_name.endswith("_id"):
                is_relation = True
                base_name = field_name[:-2] if field_name.endswith("Id") else field_name[:-3]
                if base_name:
                    target_class = base_name[0].upper() + base_name[1:]
                else:
                    target_class = "Unknown"
                rel_symbol = "}o--||"
            elif "[]" in field_type or "Array<" in field_type:
                is_relation = True
                if "[]" in field_type:
                    target_class = field_type.replace("[]", "").strip()
                elif "Array<" in field_type:
                    start_idx = field_type.find("<")
                    end_idx = field_type.rfind(">")
                    if start_idx != -1 and end_idx != -1:
                        target_class = field_type[start_idx+1:end_idx].strip()
                rel_symbol = "||--o{"
                
                primitives = {"string", "number", "boolean", "any", "unknown", "void", "null", "undefined", "object"}
                if target_class.lower() in primitives:
                    is_relation = False
            
            if is_relation and target_class:
                entity.relationships.append((target_class, rel_symbol, field_name, "inferred from controller/collection"))
            else:
                entity.columns.append((field_name, field_type))
                
    if entity.columns or entity.relationships:
        return entity
    return None

def parse_firestore_collections(file_path: Path) -> List[EREntity]:
    entities_dict = {}
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            
        # Verify first 20 lines contains firestore or firebaseConfig
        first_20 = "\n".join(content.splitlines()[:20])
        if not re.search(r'firestore|firebaseConfig', first_20, re.IGNORECASE):
            return []

        content = re.sub(r'//.*$', '', content, flags=re.MULTILINE)
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        
        simple_cols = re.findall(r'collection\(\s*(?:[^"\'\)]+,\s*)?["\']([^"\'\)]+)["\']\s*\)', content)
        for col_name in simple_cols:
            if col_name not in entities_dict:
                entity_name = col_name[0].upper() + col_name[1:] if col_name else "Unknown"
                entities_dict[col_name] = EREntity(entity_name)
                
        # Case 1: collection("users").doc(...).collection("posts")
        chain_matches = re.finditer(r'collection\(\s*(?:[^"\'\)]+,\s*)?["\']([^"\']+)["\']\s*\)\s*\.doc\([^)]*\)\s*\.collection\(\s*(?:[^"\'\)]+,\s*)?["\']([^"\']+)["\']\s*\)', content)
        for match in chain_matches:
            parent_raw = match.group(1)
            child_raw = match.group(2)
            add_firestore_relation(entities_dict, parent_raw, child_raw)
            
        # Case 2: collection(doc(collection(db, "users"), "userId"), "posts")
        nested_matches = re.finditer(r'collection\(\s*doc\(\s*collection\(\s*(?:[^"\'\)]+,\s*)?["\']([^"\']+)["\']\s*\)\s*,\s*[^)]+\)\s*,\s*["\']([^"\']+)["\']\s*\)', content)
        for match in nested_matches:
            parent_raw = match.group(1)
            child_raw = match.group(2)
            add_firestore_relation(entities_dict, parent_raw, child_raw)
            
        # Case 3: collection(db, "users", userId, "posts")
        multi_arg_matches = re.finditer(r'collection\(\s*[^,]+\s*,\s*["\']([^"\']+)["\']\s*,\s*[^,]+\s*,\s*["\']([^"\']+)["\']\s*\)', content)
        for match in multi_arg_matches:
            parent_raw = match.group(1)
            child_raw = match.group(2)
            add_firestore_relation(entities_dict, parent_raw, child_raw)
            
    except Exception as e:
        print(f"Error parsing Firestore collections in {file_path}: {e}", file=sys.stderr)
        
    return list(entities_dict.values())

def add_firestore_relation(entities_dict: dict, parent_raw: str, child_raw: str):
    parent_name = parent_raw[0].upper() + parent_raw[1:] if parent_raw else "Unknown"
    child_name = child_raw[0].upper() + child_raw[1:] if child_raw else "Unknown"
    
    if parent_raw not in entities_dict:
        entities_dict[parent_raw] = EREntity(parent_name)
    if child_raw not in entities_dict:
        entities_dict[child_raw] = EREntity(child_name)
        
    parent_entity = entities_dict[parent_raw]
    exists = any(r[0] == child_name for r in parent_entity.relationships)
    if not exists:
        parent_entity.relationships.append((child_name, "||--o{", child_raw, "inferred from controller/collection"))

def parse_mongoose_schemas(file_path: Path) -> List[EREntity]:
    entities = []
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            
        content = re.sub(r'//.*$', '', content, flags=re.MULTILINE)
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        
        model_names = {}
        model_matches = re.finditer(r'(?:mongoose\.)?model\s*\(\s*["\']([^"\']+)["\']\s*,\s*(\w+)', content)
        for m in model_matches:
            entity_name = m.group(1)
            schema_var = m.group(2)
            model_names[schema_var] = entity_name
            
        schema_matches = re.finditer(r'(?:const|let|var)\s+(\w+)\s*=\s*new\s+(?:mongoose\.)?Schema\s*\(', content)
        for match in schema_matches:
            schema_var = match.group(1)
            entity_name = model_names.get(schema_var)
            if not entity_name:
                if schema_var.lower().endswith("schema"):
                    entity_name = schema_var[:-6]
                else:
                    entity_name = schema_var
                entity_name = entity_name[0].upper() + entity_name[1:]
                
            body = extract_bracket_content(content, match.end(), '(', ')')
            obj_start = body.find('{')
            if obj_start != -1:
                obj_body = extract_bracket_content(body, obj_start + 1, '{', '}')
                entity = parse_mongoose_fields(entity_name, obj_body)
                if entity:
                    entities.append(entity)
    except Exception as e:
        print(f"Error parsing Mongoose schemas in {file_path}: {e}", file=sys.stderr)
    return entities

def parse_mongoose_fields(entity_name: str, body: str) -> Optional[EREntity]:
    entity = EREntity(entity_name)
    field_matches = re.finditer(r'\b(\w+)\s*:\s*', body)
    matches_list = list(field_matches)
    
    for idx, match in enumerate(matches_list):
        field_name = match.group(1)
        def_start = match.end()
        
        # Skip whitespace
        if def_start < len(body):
            rest = body[def_start:].lstrip()
            def_start = len(body) - len(rest)
            
        if def_start >= len(body):
            continue
            
        first_char = body[def_start]
        if first_char == '{':
            def_content = '{' + extract_bracket_content(body, def_start + 1, '{', '}') + '}'
        elif first_char == '[':
            def_content = '[' + extract_bracket_content(body, def_start + 1, '[', ']') + ']'
        else:
            remaining = body[def_start:]
            comma_idx = remaining.find(',')
            if comma_idx != -1:
                def_content = remaining[:comma_idx].strip()
            else:
                def_content = remaining.strip()
                
        ref_match = re.search(r'\bref\s*:\s*["\']([^"\']+)["\']', def_content)
        if ref_match:
            ref_target = ref_match.group(1)
            ref_target = ref_target[0].upper() + ref_target[1:] if ref_target else "Unknown"
            is_array = '[' in def_content
            rel_symbol = "||--o{" if is_array else "}o--||"
            entity.relationships.append((ref_target, rel_symbol, field_name, "inferred from controller/collection"))
        else:
            type_match = re.search(r'\btype\s*:\s*([^,}\]]+)', def_content)
            if type_match:
                f_type = type_match.group(1).strip().replace("mongoose.Schema.Types.", "").replace("Schema.Types.", "")
            else:
                f_type = def_content.strip()
                if len(f_type) > 30:
                    f_type = "Object"
            entity.columns.append((field_name, f_type))
            
    if entity.columns or entity.relationships:
        return entity
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# ORM Parser Stubs — Maqueta general (regex-based, sin tree-sitter)
# ═══════════════════════════════════════════════════════════════════════════════
#
# ┌─────────────────┬──────────────────────────────┬─────────────────────────────────────────────┐
# │ ORM             │ Archivos detectados          │ Señales que busca                           │
# ├─────────────────┼──────────────────────────────┼─────────────────────────────────────────────┤
# │ SQLAlchemy      │ *model*.py, *schema*.py      │ Column(ForeignKey()), relationship(),       │
# │                 │                              │ declarative_base()                          │
# ├─────────────────┼──────────────────────────────┼─────────────────────────────────────────────┤
# │ Django ORM      │ models.py, *model*.py        │ models.Model, ForeignKey, ManyToManyField   │
# ├─────────────────┼──────────────────────────────┼─────────────────────────────────────────────┤
# │ Prisma          │ schema.prisma                │ model NombreModelo { ... }                  │
# ├─────────────────┼──────────────────────────────┼─────────────────────────────────────────────┤
# │ TypeORM         │ *entity*.ts, *model*.ts      │ @Entity(), @Column(), @ManyToOne(),         │
# │                 │                              │ @OneToMany(), @ManyToMany(), @JoinColumn()  │
# ├─────────────────┼──────────────────────────────┼─────────────────────────────────────────────┤
# │ Sequelize       │ *model*.js, *model*.ts       │ Model.init(), belongsTo(), hasMany(),       │
# │                 │                              │ belongsToMany(), hasOne()                   │
# ├─────────────────┼──────────────────────────────┼─────────────────────────────────────────────┤
# │ EF Core         │ *Context*.cs, *DbContext*.cs │ DbSet<T>, HasForeignKey(), HasMany(),       │
# │                 │ *Model*.cs                   │ WithMany(), [ForeignKey],                   │
# │                 │                              │ virtual ICollection<T>                      │
# └─────────────────┴──────────────────────────────┴─────────────────────────────────────────────┘
#

class ORMParserStub:
    """Protocolo base para los stubs de parsers ORM."""
    name: str = "base"

    def _walk_files(self, root_path: str, extensions: tuple, name_hints: list = None, max_depth: int = 3):
        """Helper: yield (file_path, content) for matching files."""
        root = Path(root_path)
        for root_dir, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS and not d.startswith('.')]
            try:
                depth = len(Path(root_dir).relative_to(root).parts)
            except ValueError:
                depth = 0
            if depth > max_depth:
                continue
            for f in files:
                if not f.endswith(extensions):
                    continue
                if name_hints:
                    f_lower = f.lower()
                    if not any(h in f_lower for h in name_hints):
                        continue
                fp = Path(root_dir) / f
                try:
                    with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                        yield fp, fh.read()
                except Exception:
                    continue

    def detect(self, root_path: str) -> bool:
        """¿Existe este ORM en el proyecto?"""
        return False

    def extract(self, root_path: str) -> List[EREntity]:
        """Extraer entidades y relaciones."""
        return []

    def _extract_indented_block(self, content: str, start: int) -> str:
        """Extrae líneas indentadas después de una definición de clase."""
        lines = content[start:].split('\n')
        block = []
        for line in lines:
            if line.strip() == '':
                block.append(line)
                continue
            if line and not line[0].isspace() and line.strip() != '':
                if block:  # no romper en la primera línea vacía
                    break
            block.append(line)
        return '\n'.join(block)


class SQLAlchemyParser(ORMParserStub):
    """
    Detecta modelos SQLAlchemy via regex.
    Señales: Column(ForeignKey()), relationship(), declarative_base()
    """
    name = "sqlalchemy"

    def detect(self, root_path: str) -> bool:
        for _, content in self._walk_files(root_path, (".py",), ["model", "schema"]):
            if re.search(r'(?:declarative_base|Column|relationship)\s*\(', content):
                return True
        return False

    def extract(self, root_path: str) -> List[EREntity]:
        entities = []
        for _, content in self._walk_files(root_path, (".py",), ["model", "schema"]):
            # Buscar clases que heredan de Base / DeclarativeBase
            class_matches = re.finditer(
                r'class\s+(\w+)\s*\(\s*(?:\w+\.)*(?:Base|DeclarativeBase|Model)\s*(?:,\s*\w+)*\s*\)\s*:',
                content
            )
            for cm in class_matches:
                class_name = cm.group(1)
                class_start = cm.end()
                class_body = self._extract_indented_block(content, class_start)

                entity = EREntity(class_name)

                # Columnas: name = Column(Type, ...) o mapped_column(Type, ...)
                col_matches = re.finditer(
                    r'(\w+)\s*=\s*(?:mapped_column|Column)\s*\(\s*(\w+)?',
                    class_body
                )
                for col in col_matches:
                    col_name = col.group(1)
                    col_type = col.group(2) or "Unknown"
                    entity.columns.append((col_name, col_type))

                # ForeignKey dentro de Column
                fk_matches = re.finditer(
                    r'(\w+)\s*=\s*(?:mapped_column|Column)\s*\([^)]*ForeignKey\s*\(\s*["\']([^"\']+)["\']\s*\)',
                    class_body
                )
                for fk in fk_matches:
                    fk_ref = fk.group(2)  # e.g. "users.id"
                    target_table = fk_ref.split('.')[0]
                    entity.relationships.append((target_table, "}o--||", fk.group(1)))

                # relationship()
                rel_matches = re.finditer(
                    r'(\w+)\s*=\s*relationship\s*\(\s*["\'](\w+)["\']',
                    class_body
                )
                for rel in rel_matches:
                    rel_name = rel.group(1)
                    rel_target = rel.group(2)
                    entity.relationships.append((rel_target, "||--o{", rel_name))

                if entity.columns or entity.relationships:
                    entities.append(entity)
        return entities


class DjangoORMParser(ORMParserStub):
    """
    Detecta modelos Django via regex.
    Señales: models.Model, ForeignKey, ManyToManyField, OneToOneField
    """
    name = "django"

    def detect(self, root_path: str) -> bool:
        for _, content in self._walk_files(root_path, (".py",), ["model"]):
            if re.search(r'models\.Model', content):
                return True
        return False

    def extract(self, root_path: str) -> List[EREntity]:
        entities = []
        for _, content in self._walk_files(root_path, (".py",), ["model"]):
            class_matches = re.finditer(
                r'class\s+(\w+)\s*\(\s*(?:\w+\.)*(?:Model|AbstractUser)\s*(?:,\s*\w+)*\s*\)\s*:',
                content
            )
            for cm in class_matches:
                class_name = cm.group(1)
                class_start = cm.end()
                class_body = self._extract_indented_block(content, class_start)

                entity = EREntity(class_name)

                # Campos Django: name = models.CharField(...) / models.IntegerField(...)
                field_matches = re.finditer(
                    r'(\w+)\s*=\s*models\.(\w+)\s*\(',
                    class_body
                )
                for fm in field_matches:
                    field_name = fm.group(1)
                    field_type = fm.group(2)

                    if field_type == 'ForeignKey':
                        target_match = re.search(
                            r'models\.ForeignKey\s*\(\s*(?:["\'])?(\w+)(?:["\'])?\s*[,)]',
                            class_body[fm.start():]
                        )
                        target = target_match.group(1) if target_match else "Unknown"
                        entity.relationships.append((target, "}o--||", field_name))
                    elif field_type == 'ManyToManyField':
                        target_match = re.search(
                            r'models\.ManyToManyField\s*\(\s*(?:["\'])?(\w+)(?:["\'])?\s*[,)]',
                            class_body[fm.start():]
                        )
                        target = target_match.group(1) if target_match else "Unknown"
                        entity.relationships.append((target, "}o--o{", field_name))
                    elif field_type == 'OneToOneField':
                        target_match = re.search(
                            r'models\.OneToOneField\s*\(\s*(?:["\'])?(\w+)(?:["\'])?\s*[,)]',
                            class_body[fm.start():]
                        )
                        target = target_match.group(1) if target_match else "Unknown"
                        entity.relationships.append((target, "||--||", field_name))
                    else:
                        col_type = field_type.replace("Field", "")
                        entity.columns.append((field_name, col_type))

                if entity.columns or entity.relationships:
                    entities.append(entity)
        return entities


class PrismaParser(ORMParserStub):
    """
    Detecta y parsea schema.prisma.
    Reutiliza parse_prisma_schema() existente.
    """
    name = "prisma"

    def detect(self, root_path: str) -> bool:
        root = Path(root_path)
        for root_dir, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS and not d.startswith('.')]
            if "schema.prisma" in files:
                return True
        return False

    def extract(self, root_path: str) -> List[EREntity]:
        entities = []
        root = Path(root_path)
        for root_dir, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS and not d.startswith('.')]
            if "schema.prisma" in files:
                fp = Path(root_dir) / "schema.prisma"
                entities.extend(parse_prisma_schema(fp))
        return entities


class TypeORMParser(ORMParserStub):
    """
    Detecta entidades TypeORM via regex en archivos *.entity.ts, *.model.ts.
    Señales: @Entity(), @Column(), @ManyToOne(() => X), @OneToMany(() => X),
             @ManyToMany(() => X), @JoinColumn()
    """
    name = "typeorm"

    def detect(self, root_path: str) -> bool:
        for _, content in self._walk_files(root_path, (".ts",), ["entity", "model"]):
            # Remove line and block comments to avoid false positives
            cleaned = re.sub(r'//.*', '', content)
            cleaned = re.sub(r'/\*.*?\*/', '', cleaned, flags=re.DOTALL)
            if re.search(r'@Entity\s*\(', cleaned):
                return True
        return False

    def extract(self, root_path: str) -> List[EREntity]:
        entities = []
        for _, content in self._walk_files(root_path, (".ts",), ["entity", "model"]):
            if not re.search(r'@Entity\s*\(', content):
                continue

            # Buscar clases con @Entity()
            class_matches = re.finditer(
                r'@Entity\s*\([^)]*\)\s*(?:export\s+)?class\s+(\w+)',
                content
            )
            for cm in class_matches:
                class_name = cm.group(1)
                # Extraer cuerpo de la clase con balance de llaves
                brace_start = content.find('{', cm.end())
                if brace_start == -1:
                    continue
                class_body = extract_bracket_content(content, brace_start + 1, '{', '}')

                entity = EREntity(class_name)

                # @Column() fields: capturar nombre y tipo
                col_matches = re.finditer(
                    r'@Column\s*\([^)]*\)\s*(\w+)\s*(?::\s*(\w+))?',
                    class_body
                )
                for col in col_matches:
                    col_name = col.group(1)
                    col_type = col.group(2) or "Unknown"
                    entity.columns.append((col_name, col_type))

                # @PrimaryGeneratedColumn()
                pk_matches = re.finditer(
                    r'@PrimaryGeneratedColumn\s*\([^)]*\)\s*(\w+)\s*(?::\s*(\w+))?',
                    class_body
                )
                for pk in pk_matches:
                    pk_name = pk.group(1)
                    pk_type = pk.group(2) or "number"
                    entity.columns.append((pk_name, pk_type + " PK"))

                # Relaciones: @ManyToOne(() => Target, ...), @OneToMany(() => Target, ...),
                #             @ManyToMany(() => Target, ...), @OneToOne(() => Target, ...)
                # Captura el target del arrow function: () => ClassName
                rel_patterns = [
                    (r'@ManyToOne\s*\(\s*\(\)\s*=>\s*(\w+)', "}o--||"),
                    (r'@OneToMany\s*\(\s*\(\)\s*=>\s*(\w+)', "||--o{"),
                    (r'@ManyToMany\s*\(\s*\(\)\s*=>\s*(\w+)', "}o--o{"),
                    (r'@OneToOne\s*\(\s*\(\)\s*=>\s*(\w+)', "||--||"),
                ]
                for pattern, rel_type in rel_patterns:
                    for rel_match in re.finditer(pattern, class_body):
                        target = rel_match.group(1)
                        # Buscar el nombre del campo en la línea siguiente
                        after = class_body[rel_match.end():]
                        field_match = re.search(r'(?:[^;]*\n\s*)?(\w+)\s*(?:[\?!]?\s*:\s*|\s*;)', after)
                        field_name = field_match.group(1) if field_match else target.lower()
                        entity.relationships.append((target, rel_type, field_name))

                if entity.columns or entity.relationships:
                    entities.append(entity)
        return entities


class SequelizeParser(ORMParserStub):
    """
    Detecta modelos Sequelize via regex.
    Señales: Model.init(), sequelize.define(), belongsTo(), hasMany(),
             belongsToMany(), hasOne()
    """
    name = "sequelize"

    def detect(self, root_path: str) -> bool:
        for _, content in self._walk_files(root_path, (".js", ".ts"), ["model"]):
            if re.search(r'(?:Model\.init|sequelize\.define|\.belongsTo|\.hasMany|\.hasOne|\.belongsToMany)\s*\(', content):
                return True
        return False

    def extract(self, root_path: str) -> List[EREntity]:
        entities = []
        for fp, content in self._walk_files(root_path, (".js", ".ts"), ["model"]):
            file_entities = []

            # Método 1: class X extends Model — init({ fields }, { ... })
            class_matches = re.finditer(
                r'class\s+(\w+)\s+extends\s+Model\s*\{',
                content
            )
            for cm in class_matches:
                class_name = cm.group(1)
                entity = EREntity(class_name)

                # Buscar ModelName.init({ field: DataTypes.X, ... }, ...)
                init_match = re.search(
                    rf'{class_name}\.init\s*\(\s*\{{',
                    content
                )
                if init_match:
                    init_body = extract_bracket_content(content, init_match.end(), '{', '}')
                    field_matches = re.finditer(
                        r'(\w+)\s*:\s*(?:DataTypes\.)?(\w+)',
                        init_body
                    )
                    for fm in field_matches:
                        entity.columns.append((fm.group(1), fm.group(2)))

                if entity.columns or entity.relationships:
                    file_entities.append(entity)

            # Método 2: sequelize.define('ModelName', { ... })
            define_matches = re.finditer(
                r'sequelize\.define\s*\(\s*["\'](\w+)["\']\s*,\s*\{',
                content
            )
            for dm in define_matches:
                model_name = dm.group(1)
                entity = EREntity(model_name)
                body = extract_bracket_content(content, dm.end(), '{', '}')
                field_matches = re.finditer(
                    r'(\w+)\s*:\s*(?:DataTypes\.)?(\w+)',
                    body
                )
                for fm in field_matches:
                    entity.columns.append((fm.group(1), fm.group(2)))
                if entity.columns:
                    file_entities.append(entity)

            # Relaciones: Model.belongsTo(Target), Model.hasMany(Target), etc.
            rel_patterns = [
                (r'(\w+)\.belongsTo\s*\(\s*(\w+)', "}o--||"),
                (r'(\w+)\.hasMany\s*\(\s*(\w+)', "||--o{"),
                (r'(\w+)\.hasOne\s*\(\s*(\w+)', "||--||"),
                (r'(\w+)\.belongsToMany\s*\(\s*(\w+)', "}o--o{"),
            ]
            for pattern, rel_type in rel_patterns:
                for rel_match in re.finditer(pattern, content):
                    source_model = rel_match.group(1)
                    target_model = rel_match.group(2)
                    # Buscar la entidad source y agregar relación
                    found = False
                    for ent in file_entities:
                        if ent.name == source_model:
                            ent.relationships.append((target_model, rel_type, target_model.lower()))
                            found = True
                            break
                    if not found:
                        # Si no existe la entidad, crearla stub
                        stub = EREntity(source_model)
                        stub.relationships.append((target_model, rel_type, target_model.lower()))
                        file_entities.append(stub)

            entities.extend(file_entities)
        return entities


class EFCoreParser(ORMParserStub):
    """
    Detecta modelos Entity Framework Core via regex.
    Señales: DbSet<T>, virtual ICollection<T>, [ForeignKey], HasMany(), WithMany()
    name = "efcore"

    def detect(self, root_path: str) -> bool:
        for _, content in self._walk_files(root_path, (".cs",), ["context", "dbcontext", "model"]):
            # Remove line and block comments to avoid false positives
            cleaned = re.sub(r'//.*', '', content)
            cleaned = re.sub(r'/\*.*?\*/', '', cleaned, flags=re.DOTALL)
            if re.search(r'DbSet\s*<\s*\w+\s*>', cleaned) or re.search(r'DbContext', cleaned):
                return True
        return False

    def extract(self, root_path: str) -> List[EREntity]:
        entities = []
        entities_from_dbset = set()

        # Paso 1: Buscar DbContext para extraer DbSet<T> como entidades
        for _, content in self._walk_files(root_path, (".cs",), ["context", "dbcontext"]):
            dbset_matches = re.finditer(r'DbSet\s*<\s*(\w+)\s*>', content)
            for dm in dbset_matches:
                entity_name = dm.group(1)
                entities_from_dbset.add(entity_name)

        # Paso 2: Buscar archivos de modelo para extraer propiedades
        for _, content in self._walk_files(root_path, (".cs",), ["model", "entity"]):
            class_matches = re.finditer(
                r'(?:public\s+)?class\s+(\w+)\s*(?::\s*[^{]+)?\s*\{',
                content
            )
            for cm in class_matches:
                class_name = cm.group(1)
                # Solo parsear si fue registrado como DbSet o tiene nombre sugerente
                if class_name not in entities_from_dbset and not any(
                    class_name.endswith(s) for s in ["Model", "Entity"]
                ):
                    continue

                brace_start = content.find('{', cm.end() - 1)
                if brace_start == -1:
                    continue
                class_body = extract_bracket_content(content, brace_start + 1, '{', '}')

                entity = EREntity(class_name)

                # Propiedades: public Type Name { get; set; }
                prop_matches = re.finditer(
                    r'public\s+(?:virtual\s+)?([\w<>?\[\]]+)\s+(\w+)\s*\{',
                    class_body
                )
                for pm in prop_matches:
                    prop_type = pm.group(1)
                    prop_name = pm.group(2)

                    # Detectar colecciones como relaciones
                    collection_match = re.match(r'(?:ICollection|List|IEnumerable|IList)<(\w+)>', prop_type)
                    if collection_match:
                        target = collection_match.group(1)
                        entity.relationships.append((target, "||--o{", prop_name))
                    elif prop_type.replace("?", "") not in {
                        "int", "string", "bool", "double", "float", "decimal",
                        "DateTime", "Guid", "long", "short", "byte", "char"
                    } and not prop_type.startswith("I") and prop_type[0].isupper():
                        # Propiedad de navegación (FK implícita)
                        entity.relationships.append((prop_type.replace("?", ""), "}o--||", prop_name))
                    else:
                        col_type = prop_type
                        # Detectar [Key] antes de esta propiedad
                        before = class_body[:pm.start()]
                        if re.search(r'\[Key\]\s*$', before):
                            col_type += " PK"
                        entity.columns.append((prop_name, col_type))

                if entity.columns or entity.relationships:
                    entities.append(entity)

        # Agregar entidades detectadas en DbSet que no se encontraron como clase
        found_names = {e.name for e in entities}
        for db_ent in entities_from_dbset:
            if db_ent not in found_names:
                entities.append(EREntity(db_ent))

        return entities


# ── Registro global de parsers ORM ──────────────────────────────────────────
ORM_REGISTRY: List[ORMParserStub] = [
    SQLAlchemyParser(),
    DjangoORMParser(),
    PrismaParser(),
    TypeORMParser(),
    SequelizeParser(),
    EFCoreParser(),
]

def run_orm_parsers(root_path: str) -> List[EREntity]:
    """
    Orquestador: detecta qué ORMs están presentes, corre solo los detectados,
    y retorna la lista combinada de entidades (sin deduplicar - eso lo hace
    parse_project_for_er).
    """
    all_entities: List[EREntity] = []
    for parser in ORM_REGISTRY:
        try:
            if parser.detect(root_path):
                results = parser.extract(root_path)
                all_entities.extend(results)
        except Exception as e:
            print(f"Error in ORM parser '{parser.name}': {e}", file=sys.stderr)
    return all_entities


def parse_project_for_er(root_path: str, max_depth: int = 3) -> List[EREntity]:
    all_entities = []
    root = Path(root_path)

    # Check if firebaseConfig.ts is present
    firebase_config_present = False
    for r_dir, _, f_files in os.walk(root):
        if "firebaseConfig.ts" in f_files:
            firebase_config_present = True
            break

    # Check if mongoose is in package.json
    mongoose_present = False
    pkg_json = root / "package.json"
    if pkg_json.is_file():
        try:
            with open(pkg_json, "r", encoding="utf-8", errors="ignore") as f:
                pkg_content = f.read()
            if "mongoose" in pkg_content:
                mongoose_present = True
        except Exception:
            pass

    for root_dir, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS and not d.startswith('.')]
        
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
                is_model_file = "model" in file.lower()
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    tree = ast.parse(content)
                    extractor = ERExtractor(is_model_file=is_model_file)
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
            # 4. JS/TS files (Drizzle schemas, TS interfaces/types, Firestore, Mongoose)
            elif file.endswith((".js", ".ts", ".jsx", ".tsx")):
                all_entities.extend(parse_drizzle_schema(file_path))
                
                file_lower = file.lower()
                if file.endswith(".ts") and any(k in file_lower for k in ["model", "type", "interface"]):
                    all_entities.extend(parse_ts_interfaces_and_types(file_path))
                    
                if firebase_config_present and file.endswith((".ts", ".tsx")):
                    all_entities.extend(parse_firestore_collections(file_path))
                    
                if mongoose_present and any(k in file_lower for k in ["schema", "model"]):
                    all_entities.extend(parse_mongoose_schemas(file_path))
                    
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

    # 9. ORM Parser Stubs (SQLAlchemy, Django, Prisma, TypeORM, Sequelize, EF Core)
    all_entities.extend(run_orm_parsers(root_path))

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
            
            # Deduplicate relationships by (target, type, label) key
            rel_seen = {}
            for rel in existing.relationships:
                key = (rel[0], rel[1], rel[2])
                rel_seen[key] = rel
            for rel in ent.relationships:
                key = (rel[0], rel[1], rel[2])
                if key not in rel_seen:
                    rel_seen[key] = rel
                    existing.relationships.append(rel)
                else:
                    if len(rel) > 3 and len(rel_seen[key]) <= 3:
                        existing.relationships.remove(rel_seen[key])
                        rel_seen[key] = rel
                        existing.relationships.append(rel)
            
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
        for rel in entity.relationships:
            target = rel[0]
            rel_type = rel[1]
            label = rel[2]
            comment = rel[3] if len(rel) > 3 else None
            
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
            
            safe_label = str(label).replace('"', '').replace('\n', '')
            rel_line = f"    {safe_entity_name} {rel_type} {real_target} : \"{safe_label}\""
            if comment:
                rel_line += f" %% -- {comment}"
            lines.append(rel_line)
            
    return "\n".join(lines)
