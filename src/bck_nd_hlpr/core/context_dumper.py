"""
ContextDumper: Genera un único archivo de texto optimizado con etiquetas XML
para ser pegado en ChatGPT/Claude y dar contexto instantáneo del proyecto.

Parte de la Fase 2 del Roadmap: 'bck-nd prompt'
"""
import os
import sys
from pathlib import Path
from typing import List, Optional

from bck_nd_hlpr.core.tree_generator import generate_project_tree
from bck_nd_hlpr.core.utils.gitignore_parser import parse_gitignore, matches_gitignore


# ──────────────────────────────────────────────
# Constantes de configuración
# ──────────────────────────────────────────────

from bck_nd_hlpr.core.constants import (
    GLOBAL_IGNORE_DIRS,
    SKIP_DIRS,
    SKIP_FILES,
    SKIP_EXTENSIONS,
    CODE_EXTENSIONS,
    ENTRY_POINTS,
    DEFAULT_OUTPUT_FILE,
)

# Archivos que queremos leer como "core files" del backend.
# Ordenados por prioridad descendente.
CORE_FILE_CANDIDATES: List[str] = [
    # Puntos de entrada
    "App.js", "main.py", "app.py", "application.py", "server.py", "wsgi.py", "asgi.py",
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

    def __init__(self, path: str = ".", depth: Optional[int] = None, output_file: str = DEFAULT_OUTPUT_FILE, max_core_files: Optional[int] = None):
        self.root = Path(path).resolve()
        self.depth = depth
        self.output_file = output_file

        # Check if it is a mobile project to set the default max_core_files
        self.is_mobile = (
            ((self.root / "app.json").is_file() and (self.root / "package.json").is_file()) or
            (self.root / "app" / "_layout.tsx").is_file()
        )

        if max_core_files is not None:
            self.max_core_files = max_core_files
        else:
            self.max_core_files = 8 if self.is_mobile else 5

        # Parsear .gitignore una sola vez en la inicialización
        self._gitignore_patterns = parse_gitignore(self.root)

    # ──────────────────────────────────────────
    # 1. ÁRBOL DE DIRECTORIOS
    # ──────────────────────────────────────────

    def get_project_tree(self) -> str:
        """Genera un árbol de directorios limpio ignorando carpetas de ruido."""
        return generate_project_tree(
            str(self.root),
            depth=self.depth,
            output_file=self.output_file,
        )

    def _should_ignore(self, path: Path) -> bool:
        """Determina si un archivo o directorio debe ser ignorado."""
        from bck_nd_hlpr.core.constants import BCK_ND_CACHE_DIRECTORY, BCK_ND_DIRECTORY

        name = path.name

        try:
            rel_parts = path.relative_to(self.root).parts
        except ValueError:
            rel_parts = path.parts

        if len(rel_parts) >= 2 and rel_parts[:2] == (
            BCK_ND_DIRECTORY,
            BCK_ND_CACHE_DIRECTORY,
        ):
            return True

        # ── 0. Excluir el propio archivo de output ──
        if not path.is_dir() and name == self.output_file:
            return True

        if path.is_dir():
            if name in GLOBAL_IGNORE_DIRS or name in SKIP_DIRS:
                return True
            try:
                if any(p in GLOBAL_IGNORE_DIRS or p in SKIP_DIRS for p in rel_parts):
                    return True
            except ValueError:
                if any(p in GLOBAL_IGNORE_DIRS or p in SKIP_DIRS for p in path.parts):
                    return True
            if name.startswith(".") and name != BCK_ND_DIRECTORY and path.is_dir():
                return True
            if name.endswith(".egg-info"):
                return True
        else:
            if name in SKIP_FILES:
                return True
            name_lower = name.lower()
            if any(name_lower.endswith(ext.lower()) for ext in SKIP_EXTENSIONS):
                return True

        # ── Reglas dinámicas (.gitignore) ──
        if self._gitignore_patterns and matches_gitignore(path, self.root, self._gitignore_patterns):
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
            from bck_nd_hlpr.core.scanner import ProjectScanner
            from bck_nd_hlpr.core.detector import ArchitectureDetector
            from bck_nd_hlpr.core.uml_parser import generate_mermaid_class_diagram

            scanner = ProjectScanner()
            arch_info = scanner.detect_architecture(str(self.root))
            framework = arch_info.get("framework", "")

            uml_diagram: Optional[str] = None

            if framework == ".NET Core / C#":
                from bck_nd_hlpr.core.csharp_parser import parse_project_for_csharp_uml
                classes = parse_project_for_csharp_uml(str(self.root), max_depth=self.depth)
                if classes:
                    uml_diagram = generate_mermaid_class_diagram(classes)

            elif framework in ("Express.js", "Next.js", "NestJS", "Fastify", "Koa", "Node.js", "React"):
                from bck_nd_hlpr.core.js_parser import parse_project_for_js_uml
                classes = parse_project_for_js_uml(str(self.root), max_depth=self.depth)
                if classes:
                    uml_diagram = generate_mermaid_class_diagram(classes)

            elif framework == "Django":
                from bck_nd_hlpr.core.django_parser import parse_project_for_django_uml
                classes = parse_project_for_django_uml(str(self.root), max_depth=self.depth)
                if classes:
                    uml_diagram = generate_mermaid_class_diagram(classes)

            elif framework in ("Spring Boot", "Java (Maven)", "Java (Gradle)"):
                from bck_nd_hlpr.core.java_parser import parse_project_for_java_uml
                classes = parse_project_for_java_uml(str(self.root), max_depth=self.depth)
                if classes:
                    uml_diagram = generate_mermaid_class_diagram(classes)

            elif framework in ("Laravel", "PHP"):
                from bck_nd_hlpr.core.php_parser import parse_project_for_php_uml
                classes = parse_project_for_php_uml(str(self.root), max_depth=self.depth)
                if classes:
                    uml_diagram = generate_mermaid_class_diagram(classes)

            else:
                # Fallback: Python genérico vía scanner
                uml_code = scanner.scan_uml(str(self.root), max_depth=self.depth)
                from bck_nd_hlpr.core.uml_parser import is_empty_mermaid_class_diagram
                if not is_empty_mermaid_class_diagram(uml_code):
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
            from bck_nd_hlpr.core.scanner import ProjectScanner
            from bck_nd_hlpr.core.er_parser import parse_project_for_er, generate_mermaid_er

            scanner = ProjectScanner()
            arch_info = scanner.detect_architecture(str(self.root))
            framework = arch_info.get("framework", "")

            entities = None

            if framework == ".NET Core / C#":
                from bck_nd_hlpr.core.csharp_parser import parse_project_for_csharp_er
                entities = parse_project_for_csharp_er(str(self.root), max_depth=self.depth)

            elif framework in ("Express.js", "Next.js", "NestJS", "Fastify", "Koa", "Node.js", "React"):
                from bck_nd_hlpr.core.js_parser import parse_project_for_js_er
                entities = parse_project_for_js_er(str(self.root), max_depth=self.depth)

            elif framework == "Django":
                from bck_nd_hlpr.core.django_parser import parse_project_for_django_er
                entities = parse_project_for_django_er(str(self.root), max_depth=self.depth)

            elif framework in ("Spring Boot", "Java (Maven)", "Java (Gradle)"):
                from bck_nd_hlpr.core.java_parser import parse_project_for_java_er
                entities = parse_project_for_java_er(str(self.root), max_depth=self.depth)

            elif framework in ("Laravel", "PHP"):
                from bck_nd_hlpr.core.php_parser import parse_project_for_php_er
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
        Encuentra y lee los archivos más importantes del backend o mobile.
        Retorna una lista de dicts: [{path, content}]
        """
        found: List[dict] = []
        all_files: List[Path] = []

        # Walk the project tree and index all files
        for root_dir, dirs, files in os.walk(self.root):
            dirs[:] = [
                d for d in dirs
                if d not in GLOBAL_IGNORE_DIRS
                and d not in SKIP_DIRS
                and not d.startswith(".")
                and not d.endswith(".egg-info")
            ]

            try:
                rel_parts = Path(root_dir).relative_to(self.root).parts
                if any(p in GLOBAL_IGNORE_DIRS or p in SKIP_DIRS for p in rel_parts):
                    continue
            except ValueError:
                if any(p in GLOBAL_IGNORE_DIRS or p in SKIP_DIRS for p in Path(root_dir).parts):
                    continue

            rel_root = Path(root_dir).relative_to(self.root)
            depth = len(rel_root.parts)
            if self.depth is not None and depth > self.depth:
                continue

            for file_name in files:
                file_path = Path(root_dir) / file_name
                if self._should_ignore(file_path):
                    continue
                all_files.append(file_path)

        if self.is_mobile:
            # Prioritize in this order:
            # 1. src/api/*.ts (recursively, sorted alphabetically)
            # 2. src/config/*.ts (recursively, sorted alphabetically)
            # 3. hooks/*.tsx (recursively, sorted alphabetically)
            # 4. app/index.tsx
            # 5. App.js
            # 6. src/utils/*.ts (recursively, sorted alphabetically)
            group1 = []
            group2 = []
            group3 = []
            group4 = []
            group5 = []
            group6 = []

            for file_path in all_files:
                rel_path = file_path.relative_to(self.root)
                rel_p_str = str(rel_path).replace("\\", "/")

                if rel_p_str.startswith("src/api/") and rel_p_str.endswith(".ts"):
                    group1.append(file_path)
                elif rel_p_str.startswith("src/config/") and rel_p_str.endswith(".ts"):
                    group2.append(file_path)
                elif rel_p_str.startswith("hooks/") and rel_p_str.endswith(".tsx"):
                    group3.append(file_path)
                elif rel_p_str == "app/index.tsx":
                    group4.append(file_path)
                elif rel_p_str == "App.js":
                    group5.append(file_path)
                elif rel_p_str.startswith("src/utils/") and rel_p_str.endswith(".ts"):
                    group6.append(file_path)

            group1.sort(key=lambda p: str(p.relative_to(self.root)).replace("\\", "/"))
            group2.sort(key=lambda p: str(p.relative_to(self.root)).replace("\\", "/"))
            group3.sort(key=lambda p: str(p.relative_to(self.root)).replace("\\", "/"))
            group4.sort(key=lambda p: str(p.relative_to(self.root)).replace("\\", "/"))
            group5.sort(key=lambda p: str(p.relative_to(self.root)).replace("\\", "/"))
            group6.sort(key=lambda p: str(p.relative_to(self.root)).replace("\\", "/"))

            ordered_candidates = group1 + group2 + group3 + group4 + group5 + group6
        else:
            candidate_map: dict[str, Path] = {}
            for file_path in all_files:
                file_name = file_path.name
                if file_name not in candidate_map and file_name in CORE_FILE_CANDIDATES:
                    candidate_map[file_name] = file_path

            # Prioritize entry points over other candidates
            entry_candidates = []
            other_candidates = []

            for candidate_name in CORE_FILE_CANDIDATES:
                if candidate_name in candidate_map:
                    file_path = candidate_map[candidate_name]
                    if candidate_name in ENTRY_POINTS:
                        entry_candidates.append(file_path)
                    else:
                        other_candidates.append(file_path)

            ordered_candidates = entry_candidates + other_candidates

        for file_path in ordered_candidates:
            if len(found) >= self.max_core_files:
                break

            is_entry = file_path.name in ENTRY_POINTS or (self.is_mobile and (file_path.name == "index.tsx" or file_path.name == "App.js"))

            # Size limit check for non-entry files
            try:
                size = file_path.stat().st_size
            except Exception:
                size = 0

            ext = file_path.suffix.lower()

            # Rule: if size > 50KB and not a known code extension, and not an entry point:
            # We do NOT include its content.
            if not is_entry and size > 50 * 1024 and ext not in CODE_EXTENSIONS:
                continue

            content = self._read_file_safe(file_path, is_entry_point=is_entry)
            if content is not None:
                rel_path = file_path.relative_to(self.root)
                found.append({
                    "path": str(rel_path).replace("\\", "/"),
                    "content": content,
                })

        return found

    def _read_file_safe(self, path: Path, is_entry_point: bool = False) -> Optional[str]:
        """Lee un archivo de forma segura, truncando si es necesario."""
        from bck_nd_hlpr.core.utils.cache import FileCache
        try:
            content = FileCache.read_file(path, encoding="utf-8", errors="ignore")
            if not is_entry_point and len(content) > MAX_FILE_CHARS:
                content = content[:MAX_FILE_CHARS] + f"\n\n... [TRUNCATED — file exceeds {MAX_FILE_CHARS} chars]"
            return content
        except Exception:
            return None

    # ──────────────────────────────────────────
    # 4. REQUERIMIENTOS / HISTORIAS DE USUARIO
    # ──────────────────────────────────────────

    def get_requirements_context(self) -> Optional[str]:
        """
        Lee y formatea las especificaciones de requerimientos e historias de usuario
        desde .bck-nd/requirements/ si existen.
        """
        try:
            from bck_nd_hlpr.core.requirements import RequirementsParser
            specs = RequirementsParser.load_from_directory(self.root)
            if not specs:
                return None

            lines = ["<!-- User Stories & Acceptance Criteria -->"]
            for spec in specs:
                story = spec.story
                status_str = f" [{story.status}]" if story.status else ""
                title_str = f" - {story.title}" if story.title else ""
                lines.append(f"{story.id}{status_str}{title_str}")
                if story.role:
                    lines.append(f"  As a: {story.role}")
                if story.want:
                    lines.append(f"  I want: {story.want}")
                if story.benefit:
                    lines.append(f"  So that: {story.benefit}")

                if spec.business_rules:
                    lines.append("  Business Rules:")
                    for br in spec.business_rules:
                        lines.append(f"    - {br.id}: {br.description}")

                if spec.acceptance_criteria:
                    lines.append("  Acceptance Criteria:")
                    for ac in spec.acceptance_criteria:
                        lines.append(f"    - {ac.id}: Given {ac.given} When {ac.when} Then {ac.then}")

                if spec.required_data:
                    lines.append("  Required Data:")
                    for item in spec.required_data:
                        lines.append(f"    - {item}")

                if spec.validations:
                    lines.append("  Validations:")
                    for val in spec.validations:
                        lines.append(f"    - {val}")

                if spec.exceptions:
                    lines.append("  Exceptions:")
                    for exc in spec.exceptions:
                        lines.append(f"    - {exc}")

                if spec.open_questions:
                    lines.append("  Open Questions:")
                    for q in spec.open_questions:
                        lines.append(f"    - {q}")

                lines.append("")

            return "\n".join(lines).rstrip()
        except Exception as e:
            print(f"[ContextDumper] Warning: Requirements parsing failed: {e}", file=sys.stderr)
            return None

    # ──────────────────────────────────────────
    # 5. FOCUSED BUILD (--uml / --er / --tree / --req)
    # ──────────────────────────────────────────

    def build_focused(
        self,
        include_tree: bool = False,
        include_uml: bool = False,
        include_er: bool = False,
        include_requirements: bool = False,
    ) -> str:
        """
        Build a lightweight context file containing only the requested sections.
        At least one of the flags must be True.
        Returns the XML-tagged string ready to write to disk.
        """
        sections: List[str] = []

        # Header
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        # Build a human-readable label for the header
        parts = []
        if include_tree:
            parts.append("Tree")
        if include_uml:
            parts.append("UML")
        if include_er:
            parts.append("ER")
        if include_requirements:
            parts.append("Requirements")
        focus_label = " + ".join(parts)

        sections.append(
            f"<!-- ============================================================ -->\n"
            f"<!-- bck-nd-hlpr Focused Context ({focus_label}) — Generated: {now} -->\n"
            f"<!-- Paste this file into ChatGPT / Claude for instant AI context -->\n"
            f"<!-- ============================================================ -->\n"
        )

        # ── Tree ──────────────────────────────────────────────────────────
        if include_tree:
            sections.append("<project_tree>")
            sections.append(self.get_project_tree())
            sections.append("</project_tree>\n")

        # ── UML ───────────────────────────────────────────────────────────
        if include_uml:
            sections.append("<architecture_uml>")
            uml = self.get_uml_diagram()
            if uml:
                sections.append("```mermaid")
                sections.append(uml)
                sections.append("```")
            else:
                sections.append("<!-- No UML classes detected in this project. -->")
            sections.append("</architecture_uml>\n")

        # ── ER ────────────────────────────────────────────────────────────
        if include_er:
            sections.append("<architecture_er>")
            er = self.get_er_diagram()
            if er:
                sections.append("```mermaid")
                sections.append(er)
                sections.append("```")
            else:
                sections.append("<!-- No database models detected in this project. -->")
            sections.append("</architecture_er>\n")

        # ── Requirements ──────────────────────────────────────────────────
        if include_requirements:
            sections.append("<requirements_context>")
            req_ctx = self.get_requirements_context()
            if req_ctx:
                sections.append(req_ctx)
            else:
                sections.append("<!-- No requirements detected in .bck-nd/requirements/. -->")
            sections.append("</requirements_context>\n")

        return "\n".join(sections)

    # ──────────────────────────────────────────
    # 6. ENSAMBLADO FINAL DEL CONTEXTO (FULL)
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

        # ── 4. Requirements Context ───────────────────────────────────────
        req_ctx = self.get_requirements_context()
        if req_ctx:
            sections.append("<requirements_context>")
            sections.append(req_ctx)
            sections.append("</requirements_context>\n")

        # ── 5. Core Files ─────────────────────────────────────────────────
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
            ".jsx": "javascript",
            ".tsx": "typescript",
            ".cs": "csharp",
            ".java": "java",
            ".php": "php",
            ".go": "go",
            ".rb": "ruby",
            ".rs": "rust",
            ".vue": "html",
            ".svelte": "html",
        }
        ext = Path(path).suffix.lower()
        return ext_map.get(ext, "text")
