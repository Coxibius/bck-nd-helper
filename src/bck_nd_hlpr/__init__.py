# bck-nd-hlpr package init
import sys

__version__ = "2.5.0"
from bck_nd_hlpr.core import (
    ai_providers,
    analysis,
    base_analyzer,
    base_tree_sitter,
    canvas,
    ci_generator,
    constants,
    context_dumper,
    csharp_parser,
    dependency_tracker,
    detector,
    django_parser,
    doc_generator,
    er_parser,
    go_parser,
    infra_parser,
    java_parser,
    js_parser,
    narrator,
    php_parser,
    renderers,
    route_parser,
    rust_parser,
    router,
    sanitizer,
    scanner,
    security_auditor,
    todo_hunter,
    traceability,
    tree_generator,
    ts_base,
    uml_parser,
    utils,
)
from bck_nd_hlpr.core.utils import cleaning, downloader, gitignore_parser

# Populate sys.modules for backwards compatibility with absolute imports from tests and legacy files
sys.modules["bck_nd_hlpr.ai_providers"] = ai_providers
sys.modules["bck_nd_hlpr.analysis"] = analysis
sys.modules["bck_nd_hlpr.base_analyzer"] = base_analyzer
sys.modules["bck_nd_hlpr.base_tree_sitter"] = base_tree_sitter
sys.modules["bck_nd_hlpr.canvas"] = canvas
sys.modules["bck_nd_hlpr.ci_generator"] = ci_generator
sys.modules["bck_nd_hlpr.constants"] = constants
sys.modules["bck_nd_hlpr.context_dumper"] = context_dumper
sys.modules["bck_nd_hlpr.csharp_parser"] = csharp_parser
sys.modules["bck_nd_hlpr.dependency_tracker"] = dependency_tracker
sys.modules["bck_nd_hlpr.detector"] = detector
sys.modules["bck_nd_hlpr.django_parser"] = django_parser
sys.modules["bck_nd_hlpr.doc_generator"] = doc_generator
sys.modules["bck_nd_hlpr.er_parser"] = er_parser
sys.modules["bck_nd_hlpr.go_parser"] = go_parser
sys.modules["bck_nd_hlpr.infra_parser"] = infra_parser
sys.modules["bck_nd_hlpr.java_parser"] = java_parser
sys.modules["bck_nd_hlpr.js_parser"] = js_parser
sys.modules["bck_nd_hlpr.narrator"] = narrator
sys.modules["bck_nd_hlpr.php_parser"] = php_parser
sys.modules["bck_nd_hlpr.renderers"] = renderers
sys.modules["bck_nd_hlpr.route_parser"] = route_parser
sys.modules["bck_nd_hlpr.rust_parser"] = rust_parser
sys.modules["bck_nd_hlpr.router"] = router
sys.modules["bck_nd_hlpr.sanitizer"] = sanitizer
sys.modules["bck_nd_hlpr.scanner"] = scanner
sys.modules["bck_nd_hlpr.security_auditor"] = security_auditor
sys.modules["bck_nd_hlpr.todo_hunter"] = todo_hunter
sys.modules["bck_nd_hlpr.traceability"] = traceability
sys.modules["bck_nd_hlpr.tree_generator"] = tree_generator
sys.modules["bck_nd_hlpr.ts_base"] = ts_base
sys.modules["bck_nd_hlpr.uml_parser"] = uml_parser
sys.modules["bck_nd_hlpr.utils"] = utils
sys.modules["bck_nd_hlpr.utils.cleaning"] = cleaning
sys.modules["bck_nd_hlpr.utils.downloader"] = downloader
sys.modules["bck_nd_hlpr.utils.gitignore_parser"] = gitignore_parser

def __getattr__(name: str):
    """Lazy-load CLI so `import bck_nd_hlpr` never pulls Typer/MCP into core imports."""
    if name == "app":
        from bck_nd_hlpr.cli.cli import app as _app
        return _app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
