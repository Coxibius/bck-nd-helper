"""
ContextDumper: Genera un único archivo de texto optimizado con etiquetas XML
para ser pegado en ChatGPT/Claude y dar contexto instantáneo del proyecto.

Parte de la Fase 2 del Roadmap: 'bck-nd prompt'
"""
import os
import sys
from pathlib import Path
from typing import List, Optional

from bck_nd_hlpr.tree_generator import generate_project_tree


# ──────────────────────────────────────────────
# Constantes de configuración
# ──────────────────────────────────────────────

from bck_nd_hlpr.constants import GLOBAL_IGNORE_DIRS

# Archivos que queremos leer como "core files" del backend.
# Ordenados por prioridad descendente.
CORE_FILE_CANDIDATES: List[str] = [
    # Puntos de entrada
    "main.py", "app.py", "application.py", "server.py", "wsgi.py", "asgi.py",
    # Modelos / Esquemas
    "models.py", "model.py", "schemas.py", "schema.py", "entities.py",
    # Rutas / Vistas
    "router.py", "routes.py", "views.py", "urls.py", "api.py",
    # Configuración
    "config.py", "settings.py", "database.py", "db.py",
    # Principal genérico
    "index.js", "index.ts", "server.js", "server.ts",
    "app.js", "app.ts",
    # .NET
    "Program.cs", "Startup.cs",
]

MAX_CORE_FILES = 5
MAX_FILE_CHARS = 8_000   # máximo caracteres por archivo de código fuente


class ContextDumper:
    """
    Genera un contexto completo del proyecto en formato XML-like
    optimizado para LLMs (ChatGPT, Claude, Gemini, etc.)
    """

    def __init__(self, path: str = ".", depth: int = 4):
        self.root = Path(path).resolve()
        self.depth = depth

    # ──────────────────────────────────────────
    # 1. ÁRBOL DE DIRECTORIOS
    # ──────────────────────────────────────────

    def get_project_tree(self) -> str:
        """Genera un árbol de directorios limpio ignorando carpetas de ruido."""
        return generate_project_tree(str(self.root), depth=self.depth)

    def _should_ignore(self, path: Path) -> bool:
        """Determina si un archivo o directorio debe ser ignorado.
        
        Mantenido para compatibilidad con get_core_files() que lo usa
        indirectamente a través de GLOBAL_IGNORE_DIRS.
        """
        name = path.name
        
        # Ignorar carpetas de la lista negra global
        if path.is_dir() and name in GLOBAL_IGNORE_DIRS:
            return True
            
        # Ignorar si algún componente de la ruta está en la lista negra
        try:
            rel_parts = path.relative_to(self.root).parts
            if any(p in GLOBAL_IGNORE_DIRS for p in rel_parts):
                return True
        except ValueError:
            if any(p in GLOBAL_IGNORE_DIRS for p in path.parts):
                return True
                
        # Ignorar carpetas/archivos que empiezan con punto (excepto archivos config comunes)
        if name.startswith(".") and path.is_dir():
            return True
            
        # Ignorar carpetas que terminan en .egg-info
        if path.is_dir() and name.endswith(".egg-info"):
            return True
            
        return False

    # ──────────────────────────────────────────
    # 2. DIAGRAMAS UML & ER
    # ──────────────────────────────────────────

    def get_uml_diagram(self) -> Optional[str]:
        """
        Genera el diagrama UML de clases usando la lógica polimórfica
        ya existente en ProjectScanner (reutilización, no duplicación).
        """
        try:
            from bck_nd_hlpr.scanner import ProjectScanner
            from bck_nd_hlpr.detector import ArchitectureDetector
            from bck_nd_hlpr.uml_parser import generate_mermaid_class_diagram

            scanner = ProjectScanner()
            arch_info = scanner.detect_architecture(str(self.root))
            framework = arch_info.get("framework", "")

            uml_diagram: Optional[str] = None

            if framework == ".NET Core / C#":
                from bck_nd_hlpr.csharp_parser import parse_project_for_csharp_uml
                classes = parse_project_for_csharp_uml(str(self.root), max_depth=self.depth)
                if classes:
                    uml_diagram = generate_mermaid_class_diagram(classes)

            elif framework in ("Express.js", "Next.js"):
                from bck_nd_hlpr.js_parser import parse_project_for_js_uml
                classes = parse_project_for_js_uml(str(self.root), max_depth=self.depth)
                if classes:
                    uml_diagram = generate_mermaid_class_diagram(classes)

            elif framework == "Django":
                from bck_nd_hlpr.django_parser import parse_project_for_django_uml
                classes = parse_project_for_django_uml(str(self.root), max_depth=self.depth)
                if classes:
                    uml_diagram = generate_mermaid_class_diagram(classes)

            elif framework in ("Spring Boot", "Java (Maven)", "Java (Gradle)"):
                from bck_nd_hlpr.java_parser import parse_project_for_java_uml
                classes = parse_project_for_java_uml(str(self.root), max_depth=self.depth)
                if classes:
                    uml_diagram = generate_mermaid_class_diagram(classes)

            elif framework in ("Laravel", "PHP"):
                from bck_nd_hlpr.php_parser import parse_project_for_php_uml
                classes = parse_project_for_php_uml(str(self.root), max_depth=self.depth)
                if classes:
                    uml_diagram = generate_mermaid_class_diagram(classes)

            else:
                # Fallback: Python genérico vía scanner
                uml_code = scanner.scan_uml(str(self.root), max_depth=self.depth)
                if uml_code and "class Empty" not in uml_code and "No classes found" not in uml_code:
                    uml_diagram = uml_code

            return uml_diagram

        except Exception as e:
            print(f"[ContextDumper] Warning: UML generation failed: {e}", file=sys.stderr)
            return None

    def get_er_diagram(self) -> Optional[str]:
        """
        Genera el diagrama ER reutilizando la lógica de er_parser + parsers específicos.
        """
        try:
            from bck_nd_hlpr.scanner import ProjectScanner
            from bck_nd_hlpr.er_parser import parse_project_for_er, generate_mermaid_er

            scanner = ProjectScanner()
            arch_info = scanner.detect_architecture(str(self.root))
            framework = arch_info.get("framework", "")

            entities = None

            if framework == ".NET Core / C#":
                from bck_nd_hlpr.csharp_parser import parse_project_for_csharp_er
                entities = parse_project_for_csharp_er(str(self.root), max_depth=self.depth)

            elif framework in ("Express.js", "Next.js"):
                from bck_nd_hlpr.js_parser import parse_project_for_js_er
                entities = parse_project_for_js_er(str(self.root), max_depth=self.depth)

            elif framework == "Django":
                from bck_nd_hlpr.django_parser import parse_project_for_django_er
                entities = parse_project_for_django_er(str(self.root), max_depth=self.depth)

            elif framework in ("Spring Boot", "Java (Maven)", "Java (Gradle)"):
                from bck_nd_hlpr.java_parser import parse_project_for_java_er
                entities = parse_project_for_java_er(str(self.root), max_depth=self.depth)

            elif framework in ("Laravel", "PHP"):
                from bck_nd_hlpr.php_parser import parse_project_for_php_er
                entities = parse_project_for_php_er(str(self.root), max_depth=self.depth)

            else:
                entities = parse_project_for_er(str(self.root), max_depth=self.depth)

            if entities:
                er_code = generate_mermaid_er(entities)
                return er_code if er_code else None

            return None

        except Exception as e:
            print(f"[ContextDumper] Warning: ER generation failed: {e}", file=sys.stderr)
            return None

    # ──────────────────────────────────────────
    # 3. CORE FILES
    # ──────────────────────────────────────────

    def get_core_files(self) -> List[dict]:
        """
        Encuentra y lee los archivos más importantes del backend.
        Retorna una lista de dicts: [{path, content}]
        """
        found: List[dict] = []
        candidate_map: dict[str, Path] = {}

        # Walk the project tree and index files by name
        for root_dir, dirs, files in os.walk(self.root):
            dirs[:] = [
                d for d in dirs
                if d not in GLOBAL_IGNORE_DIRS
                and not d.startswith(".")
                and not d.endswith(".egg-info")
            ]

            try:
                rel_parts = Path(root_dir).relative_to(self.root).parts
                if any(p in GLOBAL_IGNORE_DIRS for p in rel_parts):
                    continue
            except ValueError:
                if any(p in GLOBAL_IGNORE_DIRS for p in Path(root_dir).parts):
                    continue

            rel_root = Path(root_dir).relative_to(self.root)
            depth = len(rel_root.parts)
            if depth > self.depth:
                continue

            for file_name in files:
                if file_name not in candidate_map and file_name in CORE_FILE_CANDIDATES:
                    candidate_map[file_name] = Path(root_dir) / file_name

        # Preserve CORE_FILE_CANDIDATES priority order
        for candidate_name in CORE_FILE_CANDIDATES:
            if len(found) >= MAX_CORE_FILES:
                break
            if candidate_name in candidate_map:
                file_path = candidate_map[candidate_name]
                content = self._read_file_safe(file_path)
                if content:
                    rel_path = file_path.relative_to(self.root)
                    found.append({
                        "path": str(rel_path).replace("\\", "/"),
                        "content": content,
                    })

        return found

    def _read_file_safe(self, path: Path) -> Optional[str]:
        """Lee un archivo de forma segura, truncando si es necesario."""
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            if len(content) > MAX_FILE_CHARS:
                content = content[:MAX_FILE_CHARS] + f"\n\n... [TRUNCATED — file exceeds {MAX_FILE_CHARS} chars]"
            return content
        except Exception:
            return None

    # ──────────────────────────────────────────
    # 4. ENSAMBLADO FINAL DEL CONTEXTO
    # ──────────────────────────────────────────

    def build(self) -> str:
        """
        Construye el archivo de contexto completo con etiquetas XML-like.
        Retorna el string listo para escribir a disco.
        """
        sections: List[str] = []

        # Header
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        sections.append(
            f"<!-- ============================================================ -->\n"
            f"<!-- bck-nd-hlpr Context Dump — Generated: {now}               -->\n"
            f"<!-- Paste this file into ChatGPT / Claude for instant AI context -->\n"
            f"<!-- ============================================================ -->\n"
        )

        # ── 1. Project Tree ───────────────────────────────────────────────
        sections.append("<project_tree>")
        sections.append(self.get_project_tree())
        sections.append("</project_tree>\n")

        # ── 2. UML Diagram ────────────────────────────────────────────────
        sections.append("<architecture_uml>")
        uml = self.get_uml_diagram()
        if uml:
            sections.append("```mermaid")
            sections.append(uml)
            sections.append("```")
        else:
            sections.append("<!-- No UML classes detected in this project. -->")
        sections.append("</architecture_uml>\n")

        # ── 3. ER Diagram ─────────────────────────────────────────────────
        sections.append("<architecture_er>")
        er = self.get_er_diagram()
        if er:
            sections.append("```mermaid")
            sections.append(er)
            sections.append("```")
        else:
            sections.append("<!-- No database models detected in this project. -->")
        sections.append("</architecture_er>\n")

        # ── 4. Core Files ─────────────────────────────────────────────────
        sections.append("<core_files>")
        core_files = self.get_core_files()
        if core_files:
            for file_info in core_files:
                lang = self._detect_lang(file_info["path"])
                sections.append(f'<file path="{file_info["path"]}">')
                sections.append(f"```{lang}")
                sections.append(file_info["content"])
                sections.append("```")
                sections.append("</file>\n")
        else:
            sections.append("<!-- No core backend files detected. -->")
        sections.append("</core_files>")

        return "\n".join(sections)

    def _detect_lang(self, path: str) -> str:
        """Detecta el lenguaje de programación por extensión para el bloque de código."""
        ext_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".cs": "csharp",
            ".java": "java",
            ".php": "php",
            ".go": "go",
            ".rb": "ruby",
            ".rs": "rust",
        }
        ext = Path(path).suffix.lower()
        return ext_map.get(ext, "text")
