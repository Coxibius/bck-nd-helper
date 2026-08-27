"""
Módulo para la generación de Diagramas E-R (Entity-Relationship) mediante análisis estático.
Soporta detección básica de modelos SQLAlchemy y Django.
"""
import ast
import csv
import io
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any
from bck_nd_hlpr.core.base_tree_sitter import walk_source_files
from bck_nd_hlpr.core.utils.indexer import FileSystemIndexer

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

    def _extract_type_from_annotation(self, node: ast.AST) -> str:
        try:
            if isinstance(node, ast.Name):
                return node.id
            if isinstance(node, (ast.Constant, ast.Str)):
                val = getattr(node, 'value', getattr(node, 's', ''))
                val_str = str(val)
                if val_str and val_str[0] in ("'", '"') and len(val_str) >= 2 and val_str[-1] == val_str[0]:
                    val_str = val_str[1:-1]
                return val_str.strip("'\"")
            if isinstance(node, ast.Attribute):
                return node.attr
            if isinstance(node, ast.Subscript):
                container = self._extract_type_from_annotation(node.value)
                slice_node = node.slice
                if isinstance(slice_node, ast.Index):
                    slice_node = slice_node.value
                inner = self._extract_type_from_annotation(slice_node)
                if container in ('Mapped', 'Optional'):
                    unwrapped = inner
                    for _ in range(8):
                        re_unwrapped = self._unwrap_mapped_optional(unwrapped)
                        if re_unwrapped == unwrapped:
                            break
                        unwrapped = re_unwrapped
                    return unwrapped
                if container == 'Union':
                    if isinstance(slice_node, ast.Tuple):
                        parts = [self._extract_type_from_annotation(e) for e in slice_node.elts]
                        non_none = [p for p in parts if p not in ('None', 'NoneType', '')]
                        if non_none:
                            candidate = non_none[0]
                            for _ in range(8):
                                re_unwrapped = self._unwrap_mapped_optional(candidate)
                                if re_unwrapped == candidate:
                                    break
                                candidate = re_unwrapped
                            return candidate
                return f"{container}[{inner}]"
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
                left = self._extract_type_from_annotation(node.left)
                right = self._extract_type_from_annotation(node.right)
                non_none = [p for p in (left, right) if p not in ('None', 'NoneType', '')]
                if non_none:
                    candidate = non_none[0]
                    for _ in range(8):
                        re_unwrapped = self._unwrap_mapped_optional(candidate)
                        if re_unwrapped == candidate:
                            break
                        candidate = re_unwrapped
                    return candidate
        except Exception:
            pass
        return ""

    def _unwrap_mapped_optional(self, typ_str: str) -> str:
        """Recursively unwrap nested SQLAlchemy 2.0 ``Mapped[Optional[Mapped[T]]]``
        style generic annotations into the innermost concrete type *T*.

        The helper strips one layer of ``Mapped[...]``, ``Optional[...]``, or
        ``Union[..., None]`` / ``X | None`` per call; callers are expected to
        loop until the string stabilizes.  Non-generic strings are returned
        unchanged, and string-quoted forward references retain their quotes
        to preserve round-trip semantics with :meth:`_extract_type_from_annotation`.
        """
        if not typ_str:
            return typ_str
        s = typ_str.strip()
        if len(s) >= 2 and s[0] in ("'", '"') and s[-1] == s[0]:
            return s
        if s.startswith("Mapped[") and s.endswith("]"):
            inner = s[7:-1].strip()
            return inner if inner else s
        if s.startswith("Optional[") and s.endswith("]"):
            inner = s[9:-1].strip()
            return inner if inner else s
        if s.startswith("Union[") and s.endswith("]"):
            inner = s[6:-1].strip()
            depth = 0
            current = []
            parts: List[str] = []
            for ch in inner:
                if ch in ("[", "<"):
                    depth += 1
                    current.append(ch)
                elif ch in ("]", ">"):
                    depth -= 1
                    current.append(ch)
                elif ch == "," and depth == 0:
                    parts.append("".join(current).strip())
                    current = []
                else:
                    current.append(ch)
            tail = "".join(current).strip()
            if tail:
                parts.append(tail)
            non_none = [p for p in parts if p not in ("None", "NoneType", "")]
            if non_none:
                return non_none[0]
            return s
        if "|" in s:
            depth = 0
            current = []
            parts: List[str] = []
            for ch in s:
                if ch in ("[", "<"):
                    depth += 1
                    current.append(ch)
                elif ch in ("]", ">"):
                    depth -= 1
                    current.append(ch)
                elif ch == "|" and depth == 0:
                    parts.append("".join(current).strip())
                    current = []
                else:
                    current.append(ch)
            tail = "".join(current).strip()
            if tail:
                parts.append(tail)
            non_none = [p for p in parts if p not in ("None", "NoneType", "")]
            if non_none:
                return non_none[0]
        return s


    def _clean_target_type(self, typ_str: str) -> tuple[str, str]:
        typ_str = typ_str.strip()
        is_list = False
        for prefix in ["List[", "list[", "Set[", "set[", "ICollection[", "Collection["]:
            if typ_str.startswith(prefix) and typ_str.endswith("]"):
                typ_str = typ_str[len(prefix):-1].strip()
                is_list = True
                break
        typ_str = typ_str.strip("'\"")
        if "." in typ_str:
            typ_str = typ_str.split(".")[-1]
        rel_symbol = "||--o{" if is_list else "}o--||"
        return typ_str, rel_symbol

    def _extract_relationship_target_from_call(self, call_node: ast.Call) -> Optional[str]:
        try:
            if call_node.args:
                arg0 = call_node.args[0]
                if isinstance(arg0, (ast.Constant, ast.Str)):
                    val = getattr(arg0, 'value', getattr(arg0, 's', ''))
                    return str(val).strip("'\"")
                if isinstance(arg0, ast.Name):
                    return arg0.id
        except Exception:
            pass
        return None

    def visit_ImportFrom(self, node: ast.ImportFrom):
        try:
            module = node.module or ""
            for alias in node.names:
                name = alias.name
                asname = alias.asname or name
                self.imports[asname] = f"{module}.{name}" if module else name
            self.generic_visit(node)
        except Exception:
            pass

    def _is_model(self, bases: List[Any]) -> bool:
        try:
            model_bases = {'Base', 'Model', 'db.Model', 'models.Model', 'DeclarativeBase'}
            for base in bases:
                if isinstance(base, ast.Name) and base.id in model_bases:
                    return True
                if isinstance(base, ast.Attribute) and base.attr == 'Model':
                    return True
        except Exception:
            pass
        return False

    def visit_TypeAlias(self, node: ast.AST) -> None:
        """Gracefully ignore Python 3.12 PEP 695 ``type`` alias statements.

        ``ast.TypeAlias`` nodes are produced by ``type X = ...`` syntax.
        This stub prevents :class:`ast.NodeVisitor` from raising an
        ``AttributeError`` and simply continues traversal of child nodes.
        """
        self.generic_visit(node)

    def visit_Match(self, node: ast.AST) -> None:
        """Gracefully process Python 3.10+ ``match / case`` statements.

        :class:`ast.Match` nodes are produced by ``match expr: case ...`` syntax.
        This stub calls :meth:`generic_visit` so sub-nodes (e.g., class definitions
        inside case branches) are still visited without raising ``AttributeError``.
        """
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        try:
            if self._is_model(node.bases) or self.is_model_file:
                self.current_entity = EREntity(node.name)
                self.entities.append(self.current_entity)
                self.generic_visit(node)
                self.current_entity = None
            else:
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
        except Exception:
            pass

    def visit_Assign(self, node: ast.Assign):
        try:
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

                # SQLAlchemy relationship
                if func_name == 'relationship':
                    rel_target = self._extract_relationship_target_from_call(node.value)
                    if rel_target:
                        rel_symbol = "||--o{" if target_name.endswith('s') else "}o--||"
                        is_one_to_one = False
                        for kw in node.value.keywords:
                            if kw.arg == 'uselist':
                                val = getattr(kw.value, 'value', getattr(kw.value, 'value', None))
                                if val is False:
                                    is_one_to_one = True
                        if is_one_to_one:
                            rel_symbol = "||--||"
                        self.current_entity.relationships.append((rel_target, rel_symbol, target_name))
                    return

                # SQLAlchemy Column / mapped_column
                if func_name in ['Column', 'Mapped', 'mapped_column']:
                    col_type = "Unknown"
                    if node.value.args:
                        arg0 = node.value.args[0]
                        if isinstance(arg0, ast.Name):
                            col_type = arg0.id
                        elif isinstance(arg0, ast.Attribute):
                            col_type = arg0.attr
                    self.current_entity.columns.append((target_name, col_type))
                    
                    # Busqueda de ForeignKey en args
                    for arg in node.value.args:
                        if isinstance(arg, ast.Call) and getattr(arg.func, 'id', '') == 'ForeignKey':
                             if arg.args and isinstance(arg.args[0], (ast.Constant, ast.Str)):
                                 fk_ref = str(getattr(arg.args[0], 'value', getattr(arg.args[0], 's', '')))
                                 target_table = fk_ref.split('.')[0]
                                 self.current_entity.relationships.append((target_table, "}o--||", target_name))
                    return

                # Django
                if 'Field' in func_name or 'ManyToManyField' in func_name:
                    col_type = func_name.replace("Field", "")
                    self.current_entity.columns.append((target_name, col_type))
                    
                    if 'ForeignKey' in func_name or 'OneToOne' in func_name or 'ManyToManyField' in func_name:
                        if node.value.args:
                            arg0 = node.value.args[0]
                            target = "Unknown"
                            if isinstance(arg0, ast.Name):
                                target = arg0.id
                            elif isinstance(arg0, (ast.Constant, ast.Str)):
                                target = str(getattr(arg0, 'value', getattr(arg0, 's', '')))
                            
                            target = target.strip("'\"")
                            if "." in target:
                                target = target.split(".")[-1]
                            
                            if 'ManyToManyField' in func_name:
                                rel_type = "}o--o{"
                            elif 'OneToOne' in func_name:
                                rel_type = "||--||"
                            else:
                                rel_type = "}o--||"
                                
                            self.current_entity.relationships.append((target, rel_type, target_name))
        except Exception:
            pass

    def visit_AnnAssign(self, node: ast.AnnAssign):
        try:
            if not self.current_entity:
                return
                
            if not isinstance(node.target, ast.Name):
                return
            target_name = node.target.id
            
            typ_str = self._extract_type_from_annotation(node.annotation)
            
            is_relationship = False
            rel_target = None
            rel_symbol = "}o--||"
            
            func_name = ""
            if node.value and isinstance(node.value, ast.Call):
                if isinstance(node.value.func, ast.Name):
                    func_name = node.value.func.id
                elif isinstance(node.value.func, ast.Attribute):
                    func_name = node.value.func.attr
                    
            if func_name == 'relationship':
                is_relationship = True
                rel_target = self._extract_relationship_target_from_call(node.value)
                
                is_one_to_one = False
                for kw in node.value.keywords:
                    if kw.arg == 'uselist':
                        val = getattr(kw.value, 'value', getattr(kw.value, 'value', None))
                        if val is False:
                            is_one_to_one = True
                
                if is_one_to_one:
                    rel_symbol = "||--||"
                elif typ_str:
                    _, inferred_symbol = self._clean_target_type(typ_str)
                    if inferred_symbol == "||--o{":
                        rel_symbol = "||--o{"
            
            if not rel_target and typ_str:
                clean_t, inferred_symbol = self._clean_target_type(typ_str)
                primitives = {"int", "str", "float", "bool", "bytes", "datetime", "date", "time", "decimal", "Decimal", "dict", "list", "set"}
                if clean_t and clean_t not in primitives and clean_t[0].isupper():
                    is_relationship = True
                    rel_target = clean_t
                    rel_symbol = inferred_symbol
                    
            if is_relationship and rel_target:
                self.current_entity.relationships.append((rel_target, rel_symbol, target_name))
            else:
                col_type = typ_str or "Unknown"
                if col_type.startswith("Mapped[") and col_type.endswith("]"):
                    col_type = col_type[7:-1]
                
                if func_name in ('mapped_column', 'Column') and node.value and isinstance(node.value, ast.Call):
                    for arg in node.value.args:
                        if isinstance(arg, ast.Call) and getattr(arg.func, 'id', '') == 'ForeignKey':
                            if arg.args and isinstance(arg.args[0], (ast.Constant, ast.Str)):
                                fk_ref = str(getattr(arg.args[0], 'value', getattr(arg.args[0], 's', '')))
                                target_table = fk_ref.split('.')[0]
                                self.current_entity.relationships.append((target_table, "}o--||", target_name))
                
                self.current_entity.columns.append((target_name, col_type))
        except Exception:
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

    def _walk_files(self, root_path: str, extensions: tuple, name_hints: list = None, max_depth: Optional[int] = 3):
        """Helper: yield (file_path, content) for matching files."""
        for fp, _rel_path in walk_source_files(
            root_path, extensions, max_depth=max_depth
        ):
            if name_hints:
                f_lower = fp.name.lower()
                if not any(h in f_lower for h in name_hints):
                    continue
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                    yield fp, fh.read()
            except Exception:
                continue

    def detect(self, root_path: str, max_depth: Optional[int] = 3) -> bool:
        """¿Existe este ORM en el proyecto?"""
        return False

    def extract(self, root_path: str, max_depth: Optional[int] = 3) -> List[EREntity]:
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

    def detect(self, root_path: str, max_depth: Optional[int] = 3) -> bool:
        try:
            for _, content in self._walk_files(
                root_path, (".py",), ["model", "schema"], max_depth=max_depth
            ):
                if re.search(r'(?:declarative_base|Column|relationship|mapped_column|Mapped)\s*\(?', content):
                    return True
        except Exception:
            pass
        return False

    def extract(self, root_path: str, max_depth: Optional[int] = 3) -> List[EREntity]:
        entities = []
        try:
            for _, content in self._walk_files(
                root_path, (".py",), ["model", "schema"], max_depth=max_depth
            ):
                try:
                    # Buscar clases que heredan de Base / DeclarativeBase / Model
                    class_matches = re.finditer(
                        r'class\s+(\w+)\s*\(\s*(?:\w+\.)*(?:Base|DeclarativeBase|Model)\s*(?:,\s*\w+)*\s*\)\s*:',
                        content
                    )
                    for cm in class_matches:
                        class_name = cm.group(1)
                        class_start = cm.end()
                        class_body = self._extract_indented_block(content, class_start)

                        entity = EREntity(class_name)

                        # Parse lines inside class body
                        for line in class_body.splitlines():
                            line = line.strip()
                            if not line or line.startswith('#'):
                                continue
                            
                            try:
                                # 1. Look for relationship
                                rel_match = re.search(
                                    r'(\w+)\s*(?::\s*Mapped\s*\[\s*([\w\[\]\'"]+)\s*\])?\s*=\s*relationship\s*\(\s*["\']?(\w+)["\']?',
                                    line
                                )
                                if rel_match:
                                    rel_name = rel_match.group(1)
                                    target = rel_match.group(3)
                                    rel_type = "||--o{" if rel_name.endswith('s') or 'List' in (rel_match.group(2) or '') else "}o--||"
                                    if 'uselist=False' in line:
                                        rel_type = "||--||"
                                    entity.relationships.append((target, rel_type, rel_name))
                                    continue
                                    
                                # 2. Look for annotated column: name: Mapped[Type] = ...
                                ann_col_match = re.search(
                                    r'(\w+)\s*:\s*Mapped\s*\[\s*([\w\[\]\'"]+)\s*\](?:\s*=\s*(?:mapped_column|Column)\s*\((.*?)\))?',
                                    line
                                )
                                if ann_col_match:
                                    col_name = ann_col_match.group(1)
                                    raw_type = ann_col_match.group(2)
                                    clean_type = raw_type.replace('"', '').replace("'", "")
                                    if any(p in clean_type for p in ['List', 'list', 'Set', 'set']):
                                        target = clean_type.replace('List[', '').replace('list[', '').replace('Set[', '').replace('set[', '').replace(']', '')
                                        entity.relationships.append((target, "||--o{", col_name))
                                    else:
                                        entity.columns.append((col_name, clean_type))
                                        fk_match = re.search(r'ForeignKey\s*\(\s*["\']([^"\']+)["\']\s*\)', line)
                                        if fk_match:
                                            fk_ref = fk_match.group(1)
                                            target_table = fk_ref.split('.')[0]
                                            entity.relationships.append((target_table, "}o--||", col_name))
                                    continue
                                    
                                # 3. Look for standard Column assignment
                                col_match = re.search(r'(\w+)\s*=\s*(?:mapped_column|Column)\s*\(\s*(\w+)?', line)
                                if col_match:
                                    col_name = col_match.group(1)
                                    col_type = col_match.group(2) or "Unknown"
                                    entity.columns.append((col_name, col_type))
                                    
                                    fk_match = re.search(r'ForeignKey\s*\(\s*["\']([^"\']+)["\']\s*\)', line)
                                    if fk_match:
                                        fk_ref = fk_match.group(1)
                                        target_table = fk_ref.split('.')[0]
                                        entity.relationships.append((target_table, "}o--||", col_name))
                                    continue
                            except Exception:
                                pass

                        if entity.columns or entity.relationships:
                            entities.append(entity)
                except Exception:
                    pass
        except Exception:
            pass
        return entities


class DjangoORMParser(ORMParserStub):
    """
    Detecta modelos Django via regex.
    Señales: models.Model, ForeignKey, ManyToManyField, OneToOneField
    """
    name = "django"

    def detect(self, root_path: str, max_depth: Optional[int] = 3) -> bool:
        try:
            for _, content in self._walk_files(
                root_path, (".py",), ["model"], max_depth=max_depth
            ):
                if re.search(r'(?:models\.Model|ForeignKey|ManyToManyField|OneToOneField)', content):
                    return True
        except Exception:
            pass
        return False

    def extract(self, root_path: str, max_depth: Optional[int] = 3) -> List[EREntity]:
        entities = []
        try:
            for _, content in self._walk_files(
                root_path, (".py",), ["model"], max_depth=max_depth
            ):
                try:
                    class_matches = re.finditer(
                        r'class\s+(\w+)\s*\(\s*(?:\w+\.)*(?:Model|AbstractUser)\s*(?:,\s*\w+)*\s*\)\s*:',
                        content
                    )
                    for cm in class_matches:
                        class_name = cm.group(1)
                        class_start = cm.end()
                        class_body = self._extract_indented_block(content, class_start)

                        entity = EREntity(class_name)

                        # Campos Django
                        field_matches = re.finditer(
                            r'(\w+)\s*=\s*(?:models\.)?(\w+)\s*\(',
                            class_body
                        )
                        for fm in field_matches:
                            try:
                                field_name = fm.group(1)
                                field_type = fm.group(2)

                                if field_type == 'ForeignKey':
                                    target_match = re.search(
                                        r'(?:models\.)?ForeignKey\s*\(\s*(?:["\'])?(\w+)(?:["\'])?\s*[,)]',
                                        class_body[fm.start():]
                                    )
                                    target = target_match.group(1) if target_match else "Unknown"
                                    entity.relationships.append((target, "}o--||", field_name))
                                elif field_type == 'ManyToManyField':
                                    target_match = re.search(
                                        r'(?:models\.)?ManyToManyField\s*\(\s*(?:["\'])?(\w+)(?:["\'])?\s*[,)]',
                                        class_body[fm.start():]
                                    )
                                    target = target_match.group(1) if target_match else "Unknown"
                                    entity.relationships.append((target, "}o--o{", field_name))
                                elif field_type == 'OneToOneField':
                                    target_match = re.search(
                                        r'(?:models\.)?OneToOneField\s*\(\s*(?:["\'])?(\w+)(?:["\'])?\s*[,)]',
                                        class_body[fm.start():]
                                    )
                                    target = target_match.group(1) if target_match else "Unknown"
                                    entity.relationships.append((target, "||--||", field_name))
                                else:
                                    col_type = field_type.replace("Field", "")
                                    entity.columns.append((field_name, col_type))
                            except Exception:
                                pass

                        if entity.columns or entity.relationships:
                            entities.append(entity)
                except Exception:
                    pass
        except Exception:
            pass
        return entities


class PrismaParser(ORMParserStub):
    """
    Detecta y parsea schema.prisma.
    Reutiliza parse_prisma_schema() existente.
    """
    name = "prisma"

    def detect(self, root_path: str, max_depth: Optional[int] = 3) -> bool:
        try:
            for fp, _content in self._walk_files(
                root_path, (".prisma",), ["schema"], max_depth=max_depth
            ):
                if fp.name == "schema.prisma":
                    return True
        except Exception:
            pass
        return False

    def extract(self, root_path: str, max_depth: Optional[int] = 3) -> List[EREntity]:
        entities = []
        try:
            for fp, _content in self._walk_files(
                root_path, (".prisma",), ["schema"], max_depth=max_depth
            ):
                if fp.name == "schema.prisma":
                    entities.extend(parse_prisma_schema(fp))
        except Exception:
            pass
        return entities


class TypeORMParser(ORMParserStub):
    """
    Detecta entidades TypeORM via regex en archivos *.entity.ts, *.model.ts.
    Señales: @Entity(), @Column(), @ManyToOne(() => X), @OneToMany(() => X),
             @ManyToMany(() => X), @JoinColumn()
    """
    name = "typeorm"

    def detect(self, root_path: str, max_depth: Optional[int] = 3) -> bool:
        try:
            for _, content in self._walk_files(
                root_path, (".ts",), ["entity", "model"], max_depth=max_depth
            ):
                cleaned = re.sub(r'//.*', '', content)
                cleaned = re.sub(r'/\*.*?\*/', '', cleaned, flags=re.DOTALL)
                if re.search(r'@Entity\s*\(', cleaned):
                    return True
        except Exception:
            pass
        return False

    def extract(self, root_path: str, max_depth: Optional[int] = 3) -> List[EREntity]:
        entities = []
        try:
            for _, content in self._walk_files(
                root_path, (".ts",), ["entity", "model"], max_depth=max_depth
            ):
                try:
                    if not re.search(r'@Entity\s*\(', content):
                        continue
                    class_matches = re.finditer(
                        r'@Entity\s*\([^)]*\)\s*(?:export\s+)?class\s+(\w+)',
                        content
                    )
                    for cm in class_matches:
                        class_name = cm.group(1)
                        brace_start = content.find('{', cm.end())
                        if brace_start == -1:
                            continue
                        class_body = extract_bracket_content(content, brace_start + 1, '{', '}')

                        entity = EREntity(class_name)

                        col_matches = re.finditer(
                            r'@Column\s*\([^)]*\)\s*(\w+)\s*(?::\s*(\w+))?',
                            class_body
                        )
                        for col in col_matches:
                            col_name = col.group(1)
                            col_type = col.group(2) or "Unknown"
                            entity.columns.append((col_name, col_type))

                        pk_matches = re.finditer(
                            r'@PrimaryGeneratedColumn\s*\([^)]*\)\s*(\w+)\s*(?::\s*(\w+))?',
                            class_body
                        )
                        for pk in pk_matches:
                            pk_name = pk.group(1)
                            pk_type = pk.group(2) or "number"
                            entity.columns.append((pk_name, pk_type + " PK"))

                        rel_patterns = [
                            (r'@ManyToOne\s*\(\s*\(\)\s*=>\s*(\w+)', "}o--||"),
                            (r'@OneToMany\s*\(\s*\(\)\s*=>\s*(\w+)', "||--o{"),
                            (r'@ManyToMany\s*\(\s*\(\)\s*=>\s*(\w+)', "}o--o{"),
                            (r'@OneToOne\s*\(\s*\(\)\s*=>\s*(\w+)', "||--||"),
                        ]
                        for pattern, rel_type in rel_patterns:
                            for rel_match in re.finditer(pattern, class_body):
                                target = rel_match.group(1)
                                after = class_body[rel_match.end():]
                                field_match = re.search(r'(?:[^;]*\n\s*)?(\w+)\s*(?:[\?!]?\s*:\s*|\s*;)', after)
                                field_name = field_match.group(1) if field_match else target.lower()
                                entity.relationships.append((target, rel_type, field_name))

                        if entity.columns or entity.relationships:
                            entities.append(entity)
                except Exception:
                    pass
        except Exception:
            pass
        return entities


class SequelizeParser(ORMParserStub):
    """
    Detecta modelos Sequelize via regex.
    Señales: Model.init(), sequelize.define(), belongsTo(), hasMany(),
             belongsToMany(), hasOne()
    """
    name = "sequelize"

    def detect(self, root_path: str, max_depth: Optional[int] = 3) -> bool:
        try:
            for _, content in self._walk_files(
                root_path, (".js", ".ts"), ["model"], max_depth=max_depth
            ):
                if re.search(r'(?:Model\.init|sequelize\.define|\.belongsTo|\.hasMany|\.hasOne|\.belongsToMany)\s*\(', content):
                    return True
        except Exception:
            pass
        return False

    def extract(self, root_path: str, max_depth: Optional[int] = 3) -> List[EREntity]:
        entities = []
        try:
            for fp, content in self._walk_files(
                root_path, (".js", ".ts"), ["model"], max_depth=max_depth
            ):
                try:
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
                except Exception:
                    pass
        except Exception:
            pass
        return entities


class EFCoreParser(ORMParserStub):
    """
    Detecta modelos Entity Framework Core via regex.
    Señales: DbSet<T>, virtual ICollection<T>, [ForeignKey], HasMany(), WithMany()
    """
    name = "efcore"

    def detect(self, root_path: str, max_depth: Optional[int] = 3) -> bool:
        try:
            for _, content in self._walk_files(
                root_path,
                (".cs",),
                ["context", "dbcontext", "model"],
                max_depth=max_depth,
            ):
                # Remove line and block comments to avoid false positives
                cleaned = re.sub(r'//.*', '', content)
                cleaned = re.sub(r'/\*.*?\*/', '', cleaned, flags=re.DOTALL)
                if re.search(r'DbSet\s*<\s*\w+\s*>', cleaned) or re.search(r'DbContext', cleaned):
                    return True
        except Exception:
            pass
        return False

    def extract(self, root_path: str, max_depth: Optional[int] = 3) -> List[EREntity]:
        entities = []
        try:
            entities_from_dbset = set()

            # Paso 1: Buscar DbContext para extraer DbSet<T> como entidades
            for _, content in self._walk_files(
                root_path,
                (".cs",),
                ["context", "dbcontext"],
                max_depth=max_depth,
            ):
                try:
                    dbset_matches = re.finditer(r'DbSet\s*<\s*(\w+)\s*>', content)
                    for dm in dbset_matches:
                        entity_name = dm.group(1)
                        entities_from_dbset.add(entity_name)
                except Exception:
                    pass

            # Paso 2: Buscar archivos de modelo para extraer propiedades
            for _, content in self._walk_files(
                root_path,
                (".cs",),
                ["model", "entity"],
                max_depth=max_depth,
            ):
                try:
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
                except Exception:
                    pass

            # Agregar entidades detectadas en DbSet que no se encontraron como clase
            found_names = {e.name for e in entities}
            for db_ent in entities_from_dbset:
                if db_ent not in found_names:
                    entities.append(EREntity(db_ent))
        except Exception:
            pass

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

def run_orm_parsers(
    root_path: str,
    max_depth: Optional[int] = 3,
) -> List[EREntity]:
    """
    Orquestador: detecta qué ORMs están presentes, corre solo los detectados,
    y retorna la lista combinada de entidades (sin deduplicar - eso lo hace
    parse_project_for_er).
    """
    all_entities: List[EREntity] = []
    for parser in ORM_REGISTRY:
        try:
            if parser.detect(root_path, max_depth=max_depth):
                results = parser.extract(root_path, max_depth=max_depth)
                all_entities.extend(results)
        except Exception as e:
            print(f"Error in ORM parser '{parser.name}': {e}", file=sys.stderr)
    return all_entities


def parse_project_for_er(root_path: str, max_depth: Optional[int] = 3) -> List[EREntity]:
    all_entities = []
    root = Path(root_path).resolve()
    file_index = FileSystemIndexer(str(root), max_depth=max_depth).build()
    project_files = file_index.all_files

    # Check if firebaseConfig.ts is present
    firebase_config_present = any(
        file_path.name == "firebaseConfig.ts" for file_path in project_files
    )

    # Check if mongoose is in package.json
    mongoose_present = False
    pkg_json = root / "package.json"
    if pkg_json in project_files:
        try:
            with open(pkg_json, "r", encoding="utf-8", errors="ignore") as f:
                pkg_content = f.read()
            if "mongoose" in pkg_content:
                mongoose_present = True
        except Exception:
            pass

    for file_path in project_files:
            file = file_path.name
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
        from bck_nd_hlpr.core.csharp_parser import parse_project_for_csharp_er
        all_entities.extend(parse_project_for_csharp_er(root_path, max_depth=max_depth))
    except Exception as e:
        print(f"Error parsing C# ER: {e}", file=sys.stderr)
        
    # 6. Java ER Parser (Spring Boot / JPA)
    try:
        from bck_nd_hlpr.core.java_parser import parse_project_for_java_er
        all_entities.extend(parse_project_for_java_er(root_path, max_depth=max_depth))
    except Exception as e:
        print(f"Error parsing Java ER: {e}", file=sys.stderr)
        
    # 7. JS/TS ER Parser (Mongoose / Sequelize)
    try:
        from bck_nd_hlpr.core.js_parser import parse_project_for_js_er
        all_entities.extend(parse_project_for_js_er(root_path, max_depth=max_depth))
    except Exception as e:
        print(f"Error parsing JS/TS ER: {e}", file=sys.stderr)
        
    # 8. PHP ER Parser (Laravel / Eloquent)
    try:
        from bck_nd_hlpr.core.php_parser import parse_project_for_php_er
        all_entities.extend(parse_project_for_php_er(root_path, max_depth=max_depth))
    except Exception as e:
        print(f"Error parsing PHP ER: {e}", file=sys.stderr)

    # 9. ORM Parser Stubs (SQLAlchemy, Django, Prisma, TypeORM, Sequelize, EF Core)
    all_entities.extend(run_orm_parsers(root_path, max_depth=max_depth))

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
            # Safe unpack: tuples may be 3 or 4+ elements
            rel_seen = {}
            for rel in existing.relationships:
                target, rel_type, label, *rest = rel
                key = (target, rel_type, label)
                rel_seen[key] = rel
            for rel in ent.relationships:
                target, rel_type, label, *rest = rel
                key = (target, rel_type, label)
                if key not in rel_seen:
                    rel_seen[key] = rel
                    existing.relationships.append(rel)
                else:
                    if len(rel) > 3 and len(rel_seen[key]) <= 3:
                        existing.relationships.remove(rel_seen[key])
                        rel_seen[key] = rel
                        existing.relationships.append(rel)
            
    return deduped

def resolve_relationship_target(target: str, label: str, entity_names: set) -> Optional[str]:
    """Resolves relationship target using exact match, namespace stripping,
    singularization, casing matching, and method label fallback.
    
    Returns resolved target entity name if matched, or None if target is Unknown/unresolved.
    """
    import re
    def sanitize(name: str) -> str:
        s = re.sub(r'[^A-Za-z0-9_]', '_', str(name).strip())
        if not s: return "E_UNKNOWN"
        if not s[0].isalpha():
            s = 'E_' + s
        return s

    def clean_php_namespace(raw: str) -> str:
        if not raw: return ""
        c = raw.strip("'\" \t\r\n")
        c = re.sub(r'::class$', '', c, flags=re.IGNORECASE)
        c = c.replace('/', '\\')
        parts = [p for p in c.split('\\') if p]
        if parts:
            res = parts[-1].strip("'\" ")
            if res and res.lower() != "class":
                return res
        return ""

    raw_target = str(target).strip() if target else ""
    cleaned_target = clean_php_namespace(raw_target)

    candidates = []
    if cleaned_target and cleaned_target.lower() not in ("unknown", "e_unknown"):
        candidates.append(cleaned_target)

    safe_label = str(label).strip() if label else ""
    if safe_label:
        candidates.append(safe_label)

    def get_variations(s: str) -> List[str]:
        if not s: return []
        res = [s, s.capitalize(), s.lower(), s.upper()]
        if s.endswith("ies") and len(s) > 3:
            sing = s[:-3] + "y"
            res.extend([sing, sing.capitalize()])
        elif s.endswith("es") and len(s) > 2:
            sing = s[:-2]
            res.extend([sing, sing.capitalize()])
        elif s.endswith("s") and not s.endswith("ss") and len(s) > 1:
            sing = s[:-1]
            res.extend([sing, sing.capitalize()])
        return res

    entity_names_lower = {e.lower(): e for e in entity_names}

    for cand in candidates:
        for v in get_variations(cand):
            safe_v = sanitize(v)
            if safe_v in entity_names:
                return safe_v
            if v.lower() in entity_names_lower:
                return entity_names_lower[v.lower()]

    if cleaned_target and cleaned_target.lower() not in ("unknown", "e_unknown"):
        s_target = sanitize(cleaned_target)
        if s_target != "E_UNKNOWN" and s_target.lower() != "unknown":
            return s_target

    return None

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
            target, rel_type, label, *rest = rel
            comment = rest[0] if rest else None
            
            real_target = resolve_relationship_target(target, label, entity_names)
            
            if not real_target or real_target == "E_UNKNOWN" or real_target.lower() == "unknown":
                continue

            safe_label = str(label).replace('"', '').replace('\n', '')
            rel_line = f"    {safe_entity_name} {rel_type} {real_target} : \"{safe_label}\""
            if comment:
                rel_line += f" %% -- {comment}"
            lines.append(rel_line)
            
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# FUTURE FUNCTIONS — Cimientos para features planificadas
# ═══════════════════════════════════════════════════════════════════════════════

def export_entities_as_dict(root_path: str, format: str = "json", max_depth: Optional[int] = 3) -> str:
    """Exporta las entidades ER detectadas como Data Dictionary.

    Args:
        root_path: Ruta raíz del proyecto a analizar.
        format: Formato de salida — ``"json"`` o ``"csv"``.
        max_depth: Profundidad máxima de recorrido en el árbol de directorios.

    Returns:
        String formateado con el diccionario de datos del proyecto.
    """
    entities = parse_project_for_er(root_path, max_depth)

    # Serializar cada entidad a un dict plano
    tables: List[Dict[str, Any]] = []
    for entity in entities:
        columns_list: List[Dict[str, str]] = []
        for col_name, col_type in entity.columns:
            is_pk = "PK" in col_type
            clean_type = col_type.replace(" PK", "").strip() if is_pk else col_type
            columns_list.append({
                "name": col_name,
                "type": clean_type,
                "is_pk": is_pk,
            })

        relationships_list: List[Dict[str, str]] = []
        for rel in entity.relationships:
            target, rel_type, label, *rest = rel
            comment = rest[0] if rest else ""
            relationships_list.append({
                "target": target,
                "type": rel_type,
                "label": label,
                "comment": comment,
            })

        tables.append({
            "name": entity.name,
            "columns": columns_list,
            "relationships": relationships_list,
        })

    if format == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Table", "Type", "Name", "Details"])
        for table in tables:
            for col in table["columns"]:
                details = "PK" if col["is_pk"] else ""
                writer.writerow([table["name"], "column", col["name"], col["type"] + (" PK" if details else "")])
            for rel in table["relationships"]:
                detail_parts = [f"{rel['type']} -> {rel['target']}"]
                if rel.get("comment"):
                    detail_parts.append(rel["comment"])
                writer.writerow([table["name"], "relationship", rel["label"], " | ".join(detail_parts)])
        return buf.getvalue()

    # Default: JSON
    return json.dumps(tables, indent=2, ensure_ascii=False)


def get_entities_for_contract_map(root_path: str, max_depth: Optional[int] = 3) -> dict:
    """Retorna entidades indexadas por nombre para cruce con rutas API.

    El diccionario resultante tiene la forma::

        {
            "NombreEntidad": {
                "columns": {"nombre_col": "tipo_col", ...},
                "relationships": [
                    {"target": "Destino", "relation_type": "Simbolo", "label": "NombreCampo"},
                    ...
                ]
            },
            ...
        }

    Será consumido por ``DependencyTracker.get_dependency_graph_for_routes()``
    para construir el mapa completo: Route → Handler → Service → Model → Columns.

    Args:
        root_path: Ruta raíz del proyecto a analizar.
        max_depth: Profundidad máxima de recorrido en el árbol de directorios.

    Returns:
        Diccionario indexado por nombre de entidad.
    """
    entities = parse_project_for_er(root_path, max_depth)

    result: Dict[str, Dict[str, Any]] = {}
    for entity in entities:
        columns: Dict[str, str] = {}
        for col_name, col_type in entity.columns:
            columns[col_name] = col_type

        relationships: List[Dict[str, str]] = []
        for rel in entity.relationships:
            target, rel_type, label, *_rest = rel
            relationships.append({
                "target": target,
                "relation_type": rel_type,
                "label": label,
            })

        result[entity.name] = {
            "columns": columns,
            "relationships": relationships,
        }

    return result
