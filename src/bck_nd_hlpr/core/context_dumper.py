"""
ContextDumper: Genera un único archivo de texto optimizado con etiquetas XML
para ser pegado en ChatGPT/Claude y dar contexto instantáneo del proyecto.

Parte de la Fase 2 del Roadmap: 'bck-nd prompt'
"""
import os
import sys
import math
from dataclasses import dataclass
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

CORE_ENTRYPOINT_CANDIDATES: List[str] = [
    "App.js", "main.py", "app.py", "application.py", "server.py",
    "wsgi.py", "asgi.py", "Program.cs", "Startup.cs", "index.js",
    "index.ts", "server.js", "server.ts", "app.ts",
]

_CORE_EXCLUDED_DIRECTORIES = frozenset({
    "test", "tests", "testing", "fixture", "fixtures", "scripts", "script",
})
_CORE_DOMAIN_HINTS = (
    "orchestrator", "scanner", "registry", "service", "manager", "engine",
    "repository", "model", "schema", "entity", "controller", "core",
)

MAX_CORE_FILES = 5
MAX_FILE_CHARS = 8_000   # máximo caracteres por archivo de código fuente


@dataclass(frozen=True)
class ContextMetrics:
    """Size and token estimates for one generated AI context."""

    estimated_tokens: int
    context_size_bytes: int
    raw_size_bytes: int
    savings_percentage: float

    @property
    def context_kb(self) -> float:
        return self.context_size_bytes / 1024

    @property
    def raw_kb(self) -> float:
        return self.raw_size_bytes / 1024


def estimate_token_count(text: str, chars_per_token: float = 3.5) -> int:
    """Estimate LLM tokens using the code/XML heuristic of 3.5 characters."""
    if not text:
        return 0
    if chars_per_token <= 0:
        raise ValueError("chars_per_token must be greater than zero")
    return math.ceil(len(text) / chars_per_token)


def calculate_context_metrics(
    context: str,
    raw_size_bytes: int,
    chars_per_token: float = 3.5,
) -> ContextMetrics:
    """Calculate token, byte-size, and exact raw-repository savings metrics."""
    context_size = len(context.encode("utf-8"))
    raw_size = max(0, int(raw_size_bytes))
    savings = (
        ((raw_size - context_size) / raw_size) * 100
        if raw_size
        else 0.0
    )
    return ContextMetrics(
        estimated_tokens=estimate_token_count(context, chars_per_token),
        context_size_bytes=context_size,
        raw_size_bytes=raw_size,
        savings_percentage=savings,
    )


def format_context_metrics(metrics: ContextMetrics) -> str:
    """Render the standard ``bck-nd prompt`` metrics footer."""
    return (
        f"📊 AI Context: ~{metrics.estimated_tokens:,} tokens "
        f"({metrics.context_kb:.1f} KB) | ⚡ "
        f"{metrics.savings_percentage:.1f}% context savings vs raw codebase "
        f"({metrics.raw_kb:.1f} KB)"
    )


class ContextDumper:
    """
    Genera un contexto completo del proyecto en formato XML-like
    optimizado para LLMs (ChatGPT, Claude, Gemini, etc.)
    """

    def __init__(self, path: str = ".", depth: Optional[int] = None, output_file: str = DEFAULT_OUTPUT_FILE, max_core_files: Optional[int] = None):
        self.root = Path(path).resolve()
        self.depth = depth
        self.output_file = output_file
        self._uml_diagram: Optional[str] = None
        self._er_diagram: Optional[str] = None
        self._uml_diagram_cached = False
        self._er_diagram_cached = False

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

    def get_raw_source_size(self) -> int:
        """Return bytes used by non-ignored source files in the scan scope."""
        total_bytes = 0
        for root_dir, dirs, files in os.walk(self.root):
            current_dir = Path(root_dir)
            try:
                current_depth = len(current_dir.relative_to(self.root).parts)
            except ValueError:
                current_depth = 0

            if self.depth is not None and current_depth > self.depth:
                del dirs[:]
                continue

            dirs[:] = [
                name
                for name in dirs
                if not self._should_ignore(current_dir / name)
            ]
            if self.depth is not None and current_depth >= self.depth:
                del dirs[:]

            for file_name in files:
                file_path = current_dir / file_name
                if (
                    file_path.suffix.lower() not in CODE_EXTENSIONS
                    or self._should_ignore(file_path)
                ):
                    continue
                try:
                    total_bytes += file_path.stat().st_size
                except OSError:
                    continue
        return total_bytes

    def get_context_metrics(self, context: str) -> ContextMetrics:
        """Calculate metrics for generated context against the scanned sources."""
        return calculate_context_metrics(context, self.get_raw_source_size())

    # ──────────────────────────────────────────
    # 2. DIAGRAMAS UML & ER
    # ──────────────────────────────────────────

    def get_uml_diagram(self) -> Optional[str]:
        """
        Genera el diagrama UML de clases usando la lógica polimórfica
        ya existente en ProjectScanner (reutilización, no duplicación).
        """
        if self._uml_diagram_cached:
            return self._uml_diagram

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

            self._uml_diagram = uml_diagram

        except Exception as e:
            print(f"[ContextDumper] Warning: UML generation failed: {e}", file=sys.stderr)
            self._uml_diagram = None

        self._uml_diagram_cached = True
        return self._uml_diagram

    def get_er_diagram(self) -> Optional[str]:
        """
        Genera el diagrama ER reutilizando la lógica de er_parser + parsers específicos.
        """
        if self._er_diagram_cached:
            return self._er_diagram

        try:
            from bck_nd_hlpr.core.scanner import ProjectScanner
            from bck_nd_hlpr.core.er_parser import parse_project_for_er, generate_mermaid_er

            scanner = ProjectScanner()
            arch_info = scanner.detect_architecture(str(self.root))
            framework = arch_info.get("framework", "")

            entities = []

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
                self._er_diagram = er_code if er_code else None

        except Exception as e:
            print(f"[ContextDumper] Warning: ER generation failed: {e}", file=sys.stderr)
            self._er_diagram = None

        self._er_diagram_cached = True
        return self._er_diagram

    # ──────────────────────────────────────────
    # 3. CORE FILES
    # ──────────────────────────────────────────

    def _is_core_file_eligible(self, file_path: Path) -> bool:
        """Return whether *file_path* is safe architectural context."""
        if file_path.suffix.lower() not in CODE_EXTENSIONS:
            return False
        if self._should_ignore(file_path):
            return False

        try:
            rel_path = file_path.relative_to(self.root)
        except ValueError:
            return False

        directory_parts = {part.lower() for part in rel_path.parts[:-1]}
        if directory_parts & _CORE_EXCLUDED_DIRECTORIES:
            return False

        name = file_path.name.lower()
        stem = file_path.stem.lower()
        if name == "conftest.py":
            return False
        if name.startswith("test_") or stem.endswith("_test"):
            return False
        if ".test." in name or ".spec." in name:
            return False
        if "fixture" in stem:
            return False
        if "postinstall" in stem or stem.endswith("_post_install"):
            return False
        return True

    @staticmethod
    def _is_core_entrypoint(file_path: Path) -> bool:
        entrypoint_names = {name.lower() for name in CORE_ENTRYPOINT_CANDIDATES}
        return file_path.name.lower() in entrypoint_names

    def _relative_core_path(self, file_path: Path) -> str:
        return str(file_path.relative_to(self.root)).replace("\\", "/")

    def _domain_priority(self, file_path: Path) -> int:
        rel_lower = self._relative_core_path(file_path).lower()
        for priority, hint in enumerate(reversed(_CORE_DOMAIN_HINTS), start=1):
            if hint in rel_lower:
                return priority
        return 0

    @staticmethod
    def _deduplicate_paths(paths: List[Path]) -> List[Path]:
        result: List[Path] = []
        seen = set()
        for path in paths:
            if path in seen:
                continue
            seen.add(path)
            result.append(path)
        return result

    def _fallback_core_candidates(self, all_files: List[Path]) -> List[Path]:
        """Preserve deterministic filename heuristics when no graph exists."""
        priorities = {
            name.lower(): index for index, name in enumerate(CORE_FILE_CANDIDATES)
        }
        candidates = [
            path for path in all_files
            if path.name.lower() in priorities and not self._is_core_entrypoint(path)
        ]
        candidates.sort(
            key=lambda path: (
                priorities[path.name.lower()],
                len(path.relative_to(self.root).parts),
                self._relative_core_path(path),
            )
        )

        # Match the old one-file-per-known-name behavior, now deterministically.
        selected: List[Path] = []
        seen_names = set()
        for path in candidates:
            name = path.name.lower()
            if name in seen_names:
                continue
            seen_names.add(name)
            selected.append(path)
        return selected

    def get_core_files(self) -> List[dict]:
        """
        Encuentra y lee los archivos más importantes del backend o mobile.
        Retorna una lista de dicts: [{path, content}]
        """
        found: List[dict] = []
        from bck_nd_hlpr.core.utils.indexer import FileSystemIndexer

        file_index = FileSystemIndexer(
            str(self.root), max_depth=self.depth
        ).build()
        all_files = [
            path for path in file_index.all_files
            if self._is_core_file_eligible(path)
        ]

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
            entry_priorities = {
                name.lower(): index
                for index, name in enumerate(CORE_ENTRYPOINT_CANDIDATES)
            }
            entry_candidates = [
                path for path in all_files if self._is_core_entrypoint(path)
            ]
            entry_candidates.sort(
                key=lambda path: (
                    entry_priorities[path.name.lower()],
                    len(path.relative_to(self.root).parts),
                    self._relative_core_path(path),
                )
            )

            fallback_candidates = self._fallback_core_candidates(all_files)
            graph_candidates: List[Path] = []
            domain_candidates: List[Path] = []

            try:
                from bck_nd_hlpr.core.dependency_tracker import DependencyTracker

                tracker = DependencyTracker(str(self.root))
                tracker.scan_dependencies()
                eligible_paths = {
                    self._relative_core_path(path) for path in all_files
                }

                ranked = []
                for path in all_files:
                    if self._is_core_entrypoint(path):
                        continue
                    rel_path = self._relative_core_path(path)
                    incoming = len(
                        set(tracker.usage_map.get(rel_path, set())) & eligible_paths
                    )
                    outgoing = len(
                        set(tracker.imports_map.get(rel_path, set())) & eligible_paths
                    )
                    domain_priority = self._domain_priority(path)
                    if incoming or outgoing:
                        ranked.append(
                            (path, incoming, outgoing, domain_priority)
                        )

                ranked.sort(
                    key=lambda item: (
                        -(item[1] * 4 + item[2]),
                        -item[1],
                        -item[2],
                        -item[3],
                        self._relative_core_path(item[0]),
                    )
                )
                graph_candidates = [item[0] for item in ranked]

                if ranked:
                    ranked_paths = set(graph_candidates)
                    domain_candidates = [
                        path for path in all_files
                        if path not in ranked_paths
                        and not self._is_core_entrypoint(path)
                        and self._domain_priority(path) > 0
                    ]
                    domain_candidates.sort(
                        key=lambda path: (
                            -self._domain_priority(path),
                            self._relative_core_path(path),
                        )
                    )
            except Exception:
                # Dependency analysis is advisory; filename fallback stays safe.
                graph_candidates = []
                domain_candidates = []

            ordered_candidates = self._deduplicate_paths(
                entry_candidates
                + graph_candidates
                + domain_candidates
                + fallback_candidates
            )

        for file_path in ordered_candidates:
            if len(found) >= self.max_core_files:
                break

            is_entry = self._is_core_entrypoint(file_path) or (
                self.is_mobile
                and (file_path.name == "index.tsx" or file_path.name == "App.js")
            )

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
