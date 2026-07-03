"""
Tests para las mejoras de exclusión de archivos en ContextDumper y tree_generator.

Cubre:
  - Exclusión de SKIP_DIRS, SKIP_FILES, SKIP_EXTENSIONS
  - Respeto a .gitignore (con y sin trailing slash)
  - Exclusión del archivo de output
  - Archivos no-code > 50KB excluidos de core_files
  - Prioridad de entry points en core_files
  - Proyecto sin .gitignore no da error
"""
import os
import pytest
from pathlib import Path

from bck_nd_hlpr.tree_generator import generate_project_tree
from bck_nd_hlpr.context_dumper import ContextDumper
from bck_nd_hlpr.utils.gitignore_parser import parse_gitignore, matches_gitignore


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════

def _create_project(tmp_path, structure: dict):
    """
    Crea una estructura de proyecto a partir de un dict.
    Claves que terminan en '/' crean directorios (valor es otro dict).
    Claves sin '/' crean archivos (valor es contenido string).
    """
    for name, content in structure.items():
        if name.endswith("/"):
            dir_path = tmp_path / name.rstrip("/")
            dir_path.mkdir(parents=True, exist_ok=True)
            if isinstance(content, dict):
                _create_project(dir_path, content)
        else:
            file_path = tmp_path / name
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")


# ═══════════════════════════════════════════════════════════
# Tests: Exclusión de directorios (SKIP_DIRS / GLOBAL_IGNORE_DIRS)
# ═══════════════════════════════════════════════════════════

class TestSkipDirsExclusion:
    def test_node_modules_excluded(self, tmp_path):
        _create_project(tmp_path, {
            "src/": {"app.py": "print('hello')"},
            "node_modules/": {"lodash/": {"index.js": "module.exports = {}"}},
        })
        tree = generate_project_tree(str(tmp_path))
        # Buscar en líneas del tree (no en root dir name)
        tree_lines = tree.split("\n")[1:]  # skip root line
        assert not any("node_modules" in line for line in tree_lines)
        assert "app.py" in tree

    def test_expo_next_dist_excluded(self, tmp_path):
        _create_project(tmp_path, {
            "src/": {"main.py": "pass"},
            ".expo/": {"config.json": "{}"},
            ".next/": {"build.js": ""},
            "dist/": {"bundle.js": ""},
        })
        tree = generate_project_tree(str(tmp_path))
        tree_lines = tree.split("\n")[1:]
        assert not any(".expo" in line for line in tree_lines)
        assert not any(".next" in line for line in tree_lines)
        assert not any("dist/" in line for line in tree_lines)
        assert "main.py" in tree

    def test_venv_pycache_excluded(self, tmp_path):
        _create_project(tmp_path, {
            "app.py": "pass",
            "venv/": {"lib/": {"site.py": ""}},
            "__pycache__/": {"app.cpython-310.pyc": ""},
        })
        tree = generate_project_tree(str(tmp_path))
        tree_lines = tree.split("\n")[1:]
        assert not any("venv" in line for line in tree_lines)
        assert not any("__pycache__" in line for line in tree_lines)


# ═══════════════════════════════════════════════════════════
# Tests: Exclusión de archivos (SKIP_FILES)
# ═══════════════════════════════════════════════════════════

class TestSkipFilesExclusion:
    def test_lockfiles_excluded(self, tmp_path):
        _create_project(tmp_path, {
            "app.py": "pass",
            "package-lock.json": "{}",
            "yarn.lock": "",
            "poetry.lock": "",
            "Pipfile.lock": "",
        })
        tree = generate_project_tree(str(tmp_path))
        assert "package-lock.json" not in tree
        assert "yarn.lock" not in tree
        assert "poetry.lock" not in tree
        assert "Pipfile.lock" not in tree
        assert "app.py" in tree


# ═══════════════════════════════════════════════════════════
# Tests: Exclusión de extensiones (SKIP_EXTENSIONS)
# ═══════════════════════════════════════════════════════════

class TestSkipExtensionsExclusion:
    def test_minified_and_compiled_excluded(self, tmp_path):
        _create_project(tmp_path, {
            "app.js": "console.log('hi')",
            "bundle.min.js": "var a=1;",
            "app.pyc": b"compiled".decode("latin-1"),
            "styles.css.map": "{}",
        })
        tree = generate_project_tree(str(tmp_path))
        assert "bundle.min.js" not in tree
        assert "app.pyc" not in tree
        assert "styles.css.map" not in tree
        assert "app.js" in tree


# ═══════════════════════════════════════════════════════════
# Tests: Respeto a .gitignore
# ═══════════════════════════════════════════════════════════

class TestGitignoreRespected:
    def test_gitignore_dir_with_trailing_slash(self, tmp_path):
        """dist/ (con slash) debe excluir el directorio 'dist' pero NO un archivo llamado 'dist'."""
        _create_project(tmp_path, {
            ".gitignore": "secret_data/\n",
            "src/": {"app.py": "pass"},
            "secret_data/": {"passwords.txt": "hunter2"},
        })
        tree = generate_project_tree(str(tmp_path))
        assert "secret_data" not in tree
        assert "passwords.txt" not in tree
        assert "app.py" in tree

    def test_gitignore_dir_without_trailing_slash(self, tmp_path):
        """'logs' (sin slash) debe excluir tanto archivos como directorios llamados 'logs'."""
        _create_project(tmp_path, {
            ".gitignore": "logs\n",
            "src/": {"app.py": "pass"},
            "logs/": {"error.log": "error"},
        })
        tree = generate_project_tree(str(tmp_path))
        assert "logs" not in tree
        assert "error.log" not in tree

    def test_gitignore_glob_pattern(self, tmp_path):
        """*.log debe excluir todos los archivos .log."""
        _create_project(tmp_path, {
            ".gitignore": "*.log\n",
            "app.py": "pass",
            "error.log": "error happened",
            "debug.log": "debug info",
            "data.txt": "data",
        })
        tree = generate_project_tree(str(tmp_path))
        assert "error.log" not in tree
        assert "debug.log" not in tree
        assert "app.py" in tree
        assert "data.txt" in tree

    def test_gitignore_with_comments_and_blanks(self, tmp_path):
        """Comentarios y líneas en blanco se ignoran correctamente."""
        _create_project(tmp_path, {
            ".gitignore": "# Este es un comentario\n\n*.tmp\n\n# Otro comentario\nsecrets/\n",
            "app.py": "pass",
            "cache.tmp": "temp",
            "secrets/": {"key.pem": "private"},
        })
        tree = generate_project_tree(str(tmp_path))
        assert "cache.tmp" not in tree
        assert "secrets" not in tree
        assert "app.py" in tree

    def test_gitignore_trailing_slash_does_not_match_file(self, tmp_path):
        """'notes/' (con trailing slash) NO debe excluir un ARCHIVO llamado 'notes'."""
        _create_project(tmp_path, {
            ".gitignore": "notes/\n",
            "notes": "This is a file, not a directory",
            "app.py": "pass",
        })
        tree = generate_project_tree(str(tmp_path))
        # El archivo 'notes' NO debe ser excluido (el patrón es dir-only)
        assert "notes" in tree
        assert "app.py" in tree

    def test_gitignore_pattern_pyc_bracket(self, tmp_path):
        """*.py[cod] debe matchear .pyc, .pyo, .pyd via fnmatch."""
        _create_project(tmp_path, {
            ".gitignore": "*.py[cod]\n",
            "app.py": "pass",
            "app.pyc": "compiled",
            "app.pyo": "optimized",
        })
        tree = generate_project_tree(str(tmp_path))
        assert "app.pyc" not in tree
        assert "app.pyo" not in tree
        assert "app.py" in tree


class TestGitignoreMissing:
    def test_no_gitignore_no_error(self, tmp_path):
        """Sin .gitignore el escaneo funciona normalmente."""
        _create_project(tmp_path, {
            "src/": {"app.py": "pass"},
            "README.md": "# Project",
        })
        # No crash
        tree = generate_project_tree(str(tmp_path))
        assert "app.py" in tree
        assert "README.md" in tree

    def test_parse_gitignore_returns_empty_on_missing(self, tmp_path):
        patterns = parse_gitignore(tmp_path)
        assert patterns == []


# ═══════════════════════════════════════════════════════════
# Tests: Exclusión del archivo de output
# ═══════════════════════════════════════════════════════════

class TestOutputFileExclusion:
    def test_default_output_excluded_from_tree(self, tmp_path):
        _create_project(tmp_path, {
            "app.py": "pass",
            "ai_context.txt": "generated context here...",
        })
        tree = generate_project_tree(str(tmp_path))
        assert "ai_context.txt" not in tree
        assert "app.py" in tree

    def test_custom_output_excluded_from_tree(self, tmp_path):
        _create_project(tmp_path, {
            "app.py": "pass",
            "my_context.txt": "generated context...",
        })
        tree = generate_project_tree(str(tmp_path), output_file="my_context.txt")
        assert "my_context.txt" not in tree
        assert "app.py" in tree

    def test_output_excluded_from_core_files(self, tmp_path):
        """ai_context.txt no debe aparecer en core_files."""
        _create_project(tmp_path, {
            "main.py": "print('entry')",
            "ai_context.txt": "big generated context...",
        })
        dumper = ContextDumper(path=str(tmp_path), depth=4)
        core = dumper.get_core_files()
        core_paths = [f["path"] for f in core]
        assert "ai_context.txt" not in core_paths


# ═══════════════════════════════════════════════════════════
# Tests: Core files - prioridad y tamaño
# ═══════════════════════════════════════════════════════════

class TestCoreFilesPriority:
    def test_entry_points_come_first(self, tmp_path):
        """main.py (entry point) debe aparecer antes que models.py."""
        _create_project(tmp_path, {
            "models.py": "class User: pass",
            "main.py": "if __name__ == '__main__': pass",
        })
        dumper = ContextDumper(path=str(tmp_path), depth=4)
        core = dumper.get_core_files()
        paths = [f["path"] for f in core]
        assert "main.py" in paths
        assert "models.py" in paths
        assert paths.index("main.py") < paths.index("models.py")

    def test_large_noncode_file_excluded_from_core(self, tmp_path):
        """Un archivo > 50KB sin extensión de código no se incluye en core."""
        _create_project(tmp_path, {
            "main.py": "print('entry')",
            "data.csv": "x," * 30_000,  # > 50KB
        })
        dumper = ContextDumper(path=str(tmp_path), depth=4)
        core = dumper.get_core_files()
        core_paths = [f["path"] for f in core]
        assert "data.csv" not in core_paths
        assert "main.py" in core_paths


# ═══════════════════════════════════════════════════════════
# Tests: gitignore_parser directos
# ═══════════════════════════════════════════════════════════

class TestGitignoreParserUnit:
    def test_parse_strips_comments(self, tmp_path):
        (tmp_path / ".gitignore").write_text("# comment\nfoo\n\nbar\n", encoding="utf-8")
        patterns = parse_gitignore(tmp_path)
        assert patterns == ["foo", "bar"]

    def test_parse_ignores_negation(self, tmp_path):
        (tmp_path / ".gitignore").write_text("dist\n!dist/important\n", encoding="utf-8")
        patterns = parse_gitignore(tmp_path)
        assert "dist" in patterns
        assert "!dist/important" not in patterns

    def test_matches_dir_only_pattern(self, tmp_path):
        """'build/' solo matchea directorios, no archivos."""
        patterns = ["build/"]
        build_dir = tmp_path / "build"
        build_dir.mkdir()
        build_file = tmp_path / "build_file"
        build_file.write_text("", encoding="utf-8")

        assert matches_gitignore(build_dir, tmp_path, patterns) is True
        # Un archivo con nombre diferente a "build" no debería matchear
        assert matches_gitignore(build_file, tmp_path, patterns) is False

    def test_matches_name_pattern_both(self, tmp_path):
        """'temp' (sin slash) matchea tanto archivos como directorios."""
        patterns = ["temp"]
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()
        temp_file = tmp_path / "src"
        temp_file.mkdir()
        actual_file = temp_file / "temp"
        actual_file.write_text("data", encoding="utf-8")

        assert matches_gitignore(temp_dir, tmp_path, patterns) is True
        assert matches_gitignore(actual_file, tmp_path, patterns) is True

    def test_matches_glob_extension(self, tmp_path):
        """'*.log' matchea archivos con extensión .log."""
        patterns = ["*.log"]
        log_file = tmp_path / "app.log"
        log_file.write_text("log", encoding="utf-8")
        py_file = tmp_path / "app.py"
        py_file.write_text("pass", encoding="utf-8")

        assert matches_gitignore(log_file, tmp_path, patterns) is True
        assert matches_gitignore(py_file, tmp_path, patterns) is False

    def test_dist_slash_vs_dist(self, tmp_path):
        """
        Caso clave: 'dist/' vs 'dist'.
        - 'dist/' debe matchear SOLO directorios llamados dist
        - 'dist' debe matchear archivos Y directorios llamados dist
        """
        dist_dir = tmp_path / "dist"
        dist_dir.mkdir()
        dist_file = tmp_path / "dist_report"
        dist_file.mkdir()
        actual_dist_file = tmp_path / "src"
        actual_dist_file.mkdir()
        real_dist_file = actual_dist_file / "dist"
        real_dist_file.write_text("file named dist", encoding="utf-8")

        # Con trailing slash: solo directorios
        slash_patterns = ["dist/"]
        assert matches_gitignore(dist_dir, tmp_path, slash_patterns) is True
        assert matches_gitignore(real_dist_file, tmp_path, slash_patterns) is False

        # Sin trailing slash: ambos
        no_slash_patterns = ["dist"]
        assert matches_gitignore(dist_dir, tmp_path, no_slash_patterns) is True
        assert matches_gitignore(real_dist_file, tmp_path, no_slash_patterns) is True


# ═══════════════════════════════════════════════════════════
# Tests: Integración ContextDumper con .gitignore
# ═══════════════════════════════════════════════════════════

class TestContextDumperGitignoreIntegration:
    def test_gitignore_excludes_from_core_files(self, tmp_path):
        _create_project(tmp_path, {
            ".gitignore": "config.py\n",
            "main.py": "print('entry')",
            "config.py": "SECRET = 'hunter2'",
        })
        dumper = ContextDumper(path=str(tmp_path), depth=4)
        core = dumper.get_core_files()
        core_paths = [f["path"] for f in core]
        assert "config.py" not in core_paths
        assert "main.py" in core_paths

    def test_gitignore_excludes_dir_from_tree_via_dumper(self, tmp_path):
        _create_project(tmp_path, {
            ".gitignore": "private/\n",
            "src/": {"app.py": "pass"},
            "private/": {"keys.txt": "secret"},
        })
        dumper = ContextDumper(path=str(tmp_path), depth=4)
        tree = dumper.get_project_tree()
        assert "private" not in tree
        assert "app.py" in tree
