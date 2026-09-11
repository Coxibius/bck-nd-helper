"""
Constantes globales para el ecosistema bck-nd-hlpr.
"""

VERSION = "2.5.0"

BCK_ND_DIRECTORY = ".bck-nd"
BCK_ND_CACHE_DIRECTORY = "cache"
BCK_ND_CACHE_PATH = f"{BCK_ND_DIRECTORY}/{BCK_ND_CACHE_DIRECTORY}"

GLOBAL_IGNORE_DIRS = {
    # Control de Versiones / IDEs
    ".git", ".github", ".idea", ".vscode", ".vs", "venv_subida",
    
    # Caches universales y OS
    "tmp", "temp", "logs", ".DS_Store",

    # JS / TS / Node / Frontend
    "node_modules", "dist", "build", "out", ".next", ".nuxt", "bower_components",

    # C# / .NET
    "bin", "obj", "Properties", "TestResults", "packages",

    # Python
    "venv", ".venv", "env", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", "coverage", ".coverage", "htmlcov", "site-packages",

    # Java / Kotlin
    "target", ".gradle", ".mvn",

    # PHP / Laravel
    "vendor", "storage", "bootstrap", "public", ".phpunit.cache",

    # Go / Rust / Ruby
    "pkg", ".bundle"

    
}

# Nuevas constantes para el modulo que genera el context dump (bck-nd prompt)
SKIP_DIRS = {".expo", ".next", "dist", "build", "coverage", "__pycache__", ".git"}
SKIP_FILES = {"package-lock.json", "yarn.lock", "poetry.lock", "Pipfile.lock", ".DS_Store", "Thumbs.db"}
SKIP_EXTENSIONS = {".lock", ".map", ".min.js", ".pyc", ".pyo", ".exe", ".dll"}
CODE_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx", ".cs", ".go", ".rs", ".java", ".php", ".rb", ".vue", ".svelte"}
ENTRY_POINTS = {"App.js", "main.py", "Program.cs", "index.js", "app.py"}

# Nombre por defecto del archivo de salida del context dump
DEFAULT_OUTPUT_FILE = "ai_context.txt"
