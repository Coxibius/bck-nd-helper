"""
ScannerOrchestrator Facade.
Central entry point coordinates scanning/analyzers and returns raw Python data models.
This module is 100% terminal-agnostic and does not use presentation libraries.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Set
from pathlib import Path

# --- Lightweight, always-needed core imports (kept global) ---
from bck_nd_hlpr.core.scanner import ProjectScanner
from bck_nd_hlpr.core.detector import ArchitectureDetector
from bck_nd_hlpr.core.tree_generator import generate_project_tree
from bck_nd_hlpr.core.todo_hunter import scan_for_todos
from bck_nd_hlpr.core.security_auditor import scan_security_risks
from bck_nd_hlpr.core.dependency_tracker import DependencyTracker, analyze_impact
from bck_nd_hlpr.core.narrator import Narrator
from bck_nd_hlpr.core.utils.indexer import FileSystemIndexer, FileIndex
from bck_nd_hlpr.core.utils.cache import FileCache
from bck_nd_hlpr.core.utils.delta_cache import DeltaCacheManager
# NOTE: Heavy polyglot parser modules (analysis, route_parser, infra_parser,
# traceability, er_parser) are imported lazily inside their respective
# conditional blocks in ScannerOrchestrator.run() to avoid loading all
# parsing libraries on startup.


@dataclass(frozen=True)
class OrchestratorConfig:
    path: str = "."                   # Root directory of project to scan
    depth: int = 3                     # Directory recursion depth
    uml: bool = False                  # Flag to request UML diagram
    er: bool = False                   # Flag to request ER diagram
    routes: bool = False               # Flag to request API routes map
    infra: bool = False                # Flag to request Infrastructure diagram
    todo: bool = False                 # Flag to request Technical Debt scan
    audit: bool = False                # Flag to request Security audit
    impact: bool = False               # Flag to request Dependency heatmap (impact map)
    trace: bool = False                # Flag to request Route-to-DB traceability
    tree: bool = False                 # Flag to request ASCII project tree
    datascience: bool = False          # Flag to request Jupyter Notebook lineage map
    contract: bool = False             # Flag to request API contract mapping
    health: bool = False               # Flag to request consolidated Health Score
    teach: bool = False                # Flag to request Pedagogical onboarding path
    export_dict: Optional[str] = None  # Format to export data dictionary ("json" or "csv")
    impact_radius: Optional[str] = None # Path of a file to calculate blast radius
    ai: bool = False                   # Enable AI-powered narration/explain
    style: str = "pro"                 # AI personality style
    provider: Optional[str] = None     # Force specific AI provider
    plain: bool = True                 # Return raw unformatted text (strips ANSI internally if requested)
    use_cache: bool = True             # Enable incremental delta cache engine
    requirements: bool = False         # Flag to request Project Requirements summary


@dataclass
class OrchestratorResult:
    # High-level Metadata
    path: str
    framework: str
    architecture: str
    features: List[str]
    summary: str
    
    # Diagram & Structure Data (Mermaid / ASCII representations)
    tree: Optional[str] = None
    uml: Optional[str] = None
    er: Optional[str] = None
    routes: Optional[str] = None
    infra: Optional[str] = None
    trace: Optional[str] = None
    datascience: Optional[str] = None
    
    # Raw scan metric lists (decoupled from any console formatting)
    todos: Optional[List[Dict[str, Any]]] = None           # keys: file, line, type, message
    security_risks: Optional[List[Dict[str, Any]]] = None # keys: file, line, type, severity, category, message
    dependency_heatmap: Optional[Dict[str, Set[str]]] = None # map: file -> set of dependents
    impact_radius_report: Optional[Dict[str, Any]] = None # keys: changed_file, affected_files, affected_routes
    api_contracts: Optional[List[Dict[str, Any]]] = None   # keys: route, file, matched_model, columns
    onboarding_path: Optional[List[Dict[str, Any]]] = None  # step details: file, tier, role, hint, in_degree, out_degree
    health_score: Optional[Dict[str, Any]] = None         # keys: score, grade, breakdown (critical_risks, etc.)
    data_dictionary: Optional[Any] = None                 # raw structures / list of entities for exporter
    requirements: Optional[List[Any]] = None              # parsed RequirementSpecification objects
    
    # AI Explanation & Narration
    ai_narrative: Optional[str] = None
    
    # Execution Warnings
    execution_warnings: List[str] = field(default_factory=list)
    
    # v3.0.0: Pre-built file index for single-pass scanning
    file_index: Optional[Any] = None  # FileIndex from utils.indexer

    # v3.1.0: Unified Abstract Semantic Graph
    asg_graph: Optional[Any] = None  # ASGGraph instance

    # v3.2.0: Delta Cache Manager instance
    delta_cache: Optional[Any] = None  # DeltaCacheManager instance


class ScannerOrchestrator:
    @staticmethod
    def run(config: OrchestratorConfig) -> OrchestratorResult:
        import logging
        logger = logging.getLogger(__name__)

        # ── v3.0.0: Clear memory cache for new scan ──
        FileCache.clear()

        # ── v3.2.0: Delta Cache Initialization ──
        delta_cache = DeltaCacheManager(config.path) if config.use_cache else None

        # Detect architecture & framework first
        try:
            detector = ArchitectureDetector()
            arch_info = detector.detect(config.path)
        except Exception as e:
            logger.warning(f"Error detecting architecture: {e}")
            arch_info = {}

        result = OrchestratorResult(
            path=str(Path(config.path).resolve()),
            framework=arch_info.get("framework", "Unknown"),
            architecture=arch_info.get("architecture", "Single File"),
            features=arch_info.get("features", []),
            summary=arch_info.get("summary", ""),
            delta_cache=delta_cache
        )

        # ── v3.0.0: Build file index once for all analyzers ──
        try:
            indexer = FileSystemIndexer(config.path, max_depth=config.depth)
            file_index = indexer.build()
            result.file_index = file_index
            if delta_cache and file_index:
                delta_cache.sync_files(file_index.all_files)
        except Exception as e:
            logger.warning(f"FileSystemIndexer error (falling back to per-analyzer walks): {e}")
            file_index = None
        
        # ── Build Concurrent Tasks ──
        import concurrent.futures
        tasks = [] # List of tuples: (attr_name, func, err_prefix, default_value)

        if config.tree:
            def _task_tree():
                return generate_project_tree(config.path, depth=config.depth)
            tasks.append(("tree", _task_tree, "Tree Generation Error", None))

        if config.uml:
            def _task_uml():
                from bck_nd_hlpr.core.analysis import build_uml_diagram
                return build_uml_diagram(config.path, config.depth, arch_info)
            tasks.append(("uml", _task_uml, "UML Generation Error", None))

        if config.er:
            def _task_er():
                from bck_nd_hlpr.core.analysis import build_er_diagram
                return build_er_diagram(config.path, config.depth, arch_info)
            tasks.append(("er", _task_er, "ER Diagram Error", None))

        if config.routes:
            def _task_routes():
                from bck_nd_hlpr.core.route_parser import parse_project_routes, generate_mermaid_sequence
                r = parse_project_routes(config.path, max_depth=config.depth)
                return generate_mermaid_sequence(r) if r else None
            tasks.append(("routes", _task_routes, "Routes Diagram Error", None))

        if config.infra:
            def _task_infra():
                from bck_nd_hlpr.core.infra_parser import parse_infra, parse_docker_compose, generate_mermaid_infra
                compose_file = parse_infra(config.path)
                if compose_file:
                    services = parse_docker_compose(compose_file)
                    if services:
                        return generate_mermaid_infra(services)
                return None
            tasks.append(("infra", _task_infra, "Infrastructure Diagram Error", None))

        if config.trace:
            def _task_trace():
                from bck_nd_hlpr.core.traceability import parse_project_traceability, generate_mermaid_traceability
                traces = parse_project_traceability(config.path, max_depth=config.depth)
                return generate_mermaid_traceability(traces) if traces else None
            tasks.append(("trace", _task_trace, "Traceability Diagram Error", None))

        if config.datascience:
            def _task_datascience():
                scanner = ProjectScanner()
                return scanner.scan_notebooks(config.path, max_depth=config.depth)
            tasks.append(("datascience", _task_datascience, "Data Science Lineage Error", None))

        if config.todo or config.health:
            def _task_todo():
                _file_list = file_index.all_files if file_index else None
                return scan_for_todos(config.path, max_depth=config.depth, file_list=_file_list)
            tasks.append(("todos", _task_todo, "Technical Debt Scan Error", []))

        if config.audit or config.health:
            def _task_audit():
                _file_list = file_index.all_files if file_index else None
                return scan_security_risks(config.path, max_depth=config.depth, file_list=_file_list)
            tasks.append(("security_risks", _task_audit, "Security Audit Error", []))

        if config.impact:
            def _task_impact():
                return analyze_impact(config.path)
            tasks.append(("dependency_heatmap", _task_impact, "Dependency Heatmap Error", {}))

        if config.impact_radius:
            def _task_impact_radius():
                from bck_nd_hlpr.core.route_parser import get_routes_affected_by_file
                abs_changed_file = str(Path(config.impact_radius).resolve())
                return get_routes_affected_by_file(config.path, abs_changed_file, max_depth=config.depth)
            tasks.append(("impact_radius_report", _task_impact_radius, "Impact Radius Error", {}))

        if config.contract:
            def _task_contract():
                from bck_nd_hlpr.core.route_parser import generate_api_contract_map
                return generate_api_contract_map(config.path, max_depth=config.depth)
            tasks.append(("api_contracts", _task_contract, "API Contract Map Error", []))

        if config.teach:
            def _task_teach():
                tracker = DependencyTracker(config.path)
                tracker.scan_dependencies()
                return tracker.get_onboarding_path()
            tasks.append(("onboarding_path", _task_teach, "Onboarding Path Error", []))

        if config.health:
            def _task_health():
                scanner = ProjectScanner()
                return scanner.calculate_health_score(config.path, max_depth=config.depth)
            tasks.append(("health_score", _task_health, "Project Health Score Error", {}))

        if config.export_dict:
            def _task_export_dict():
                from bck_nd_hlpr.core.er_parser import export_entities_as_dict
                return export_entities_as_dict(config.path, format=config.export_dict, max_depth=config.depth)
            tasks.append(("data_dictionary", _task_export_dict, "Data Dictionary Export Error", None))

        if config.ai:
            def _task_ai():
                narrator = Narrator(force_provider=config.provider)
                scanner = ProjectScanner()
                topology_text = scanner.scan(config.path, max_depth=config.depth)
                return narrator.explain(topology_text, use_ai=True, style=config.style)
            tasks.append(("ai_narrative", _task_ai, "AI Narrative Error", None))

        if config.requirements:
            def _task_req():
                from bck_nd_hlpr.core.requirements import RequirementsParser
                return RequirementsParser.load_from_directory(config.path)
            tasks.append(("requirements", _task_req, "Requirements Loading Error", []))

        # ── Concurrency Execution Block ──
        def _execute_task(attr_name, func, error_prefix, default_value):
            try:
                res = func()
                return attr_name, res, []
            except Exception as e:
                msg = f"{error_prefix}: {e}"
                logger.warning(msg)
                return attr_name, default_value, [msg]

        if tasks:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                futures = [
                    executor.submit(_execute_task, name, func, err, default)
                    for name, func, err, default in tasks
                ]
                for future in concurrent.futures.as_completed(futures):
                    try:
                        attr_name, res, warnings = future.result()
                        setattr(result, attr_name, res)
                        if warnings:
                            result.execution_warnings.extend(warnings)
                    except Exception as e:
                        logger.error(f"Executor failed unexpectedly: {e}")

        if delta_cache:
            delta_cache.save_cache()

        return result