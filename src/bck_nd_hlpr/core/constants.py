"""
Constantes globales para el ecosistema bck-nd-hlpr.
"""

GLOBAL_IGNORE_DIRS = {
    # Control de Versiones / IDEs
    ".git", ".github", ".idea", ".vscode", ".vs", "venv_subida", ".bck-nd-cache",
    
    # Caches universales y OS
    "tmp", "temp", "logs", ".DS_Store",

    # JS / TS / Node / Frontend
    "node_modules", "dist", "build", "out", ".next", ".nuxt", "bower_components",

    # C# / .NET
    "bin", "obj", "Properties", "TestResults", "packages",

    # Python
    "venv", ".venv", "env", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", "coverage", ".coverage", "htmlcov", "site-packages", "Lib",

    # Java / Kotlin
    "target", ".gradle", ".mvn",

    # PHP / Laravel
    "vendor", "storage", "bootstrap", "public", ".phpunit.cache",

    # Go / Rust / Ruby
    "pkg", ".bundle"

    
}

# Nuevas constantes para el modulo que genera el context dump (bck-nd prompt)
SKIP_DIRS = {".expo", ".next", "dist", "build", "coverage", "__pycache__", ".git", ".bck-nd-cache"}
SKIP_FILES = {"package-lock.json", "yarn.lock", "poetry.lock", "Pipfile.lock", ".DS_Store", "Thumbs.db", ".bck-nd-cache"}
SKIP_EXTENSIONS = {".lock", ".map", ".min.js", ".pyc", ".pyo", ".exe", ".dll"}
CODE_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx", ".cs", ".go", ".rs", ".java", ".php", ".rb", ".vue", ".svelte"}
ENTRY_POINTS = {"App.js", "main.py", "Program.cs", "index.js", "app.py"}

# Nombre por defecto del archivo de salida del context dump
DEFAULT_OUTPUT_FILE = "ai_context.txt"

# Versión actual de la aplicación
VERSION = "2.4.1"