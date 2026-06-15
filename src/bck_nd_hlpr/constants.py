"""
Constantes globales para el ecosistema bck-nd-hlpr.
"""

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
    "venv", ".venv", "env", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", "coverage", ".coverage", "htmlcov", "site-packages", "Lib",

    # Java / Kotlin
    "target", ".gradle", ".mvn",

    # PHP / Laravel
    "vendor", "storage", "bootstrap", "public", ".phpunit.cache",

    # Go / Rust / Ruby
    "pkg", ".bundle"
}
