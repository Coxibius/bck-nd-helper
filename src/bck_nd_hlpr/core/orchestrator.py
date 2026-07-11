"""
ScannerOrchestrator Facade.
Central entry point coordinates scanning/analyzers and returns raw Python data models.
This module is 100% terminal-agnostic and does not use presentation libraries.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Set
from pathlib import Path

# Import the core modules directly
from bck_nd_hlpr.core.scanner import ProjectScanner
from bck_nd_hlpr.core.detector import ArchitectureDetector
from bck_nd_hlpr.core.tree_generator import generate_project_tree
from bck_nd_hlpr.core.analysis import build_er_diagram, build_uml_diagram
from bck_nd_hlpr.core.route_parser import parse_project_routes, generate_mermaid_sequence, get_routes_affected_by_file, generate_api_contract_map
from bck_nd_hlpr.core.infra_parser import parse_infra, parse_docker_compose, generate_mermaid_infra
from bck_nd_hlpr.core.todo_hunter import scan_for_todos
from bck_nd_hlpr.core.security_auditor import scan_security_risks
from bck_nd_hlpr.core.dependency_tracker import DependencyTracker, analyze_impact
from bck_nd_hlpr.core.traceability import parse_project_traceability, generate_mermaid_traceability
from bck_nd_hlpr.core.er_parser import parse_project_for_er, export_entities_as_dict
from bck_nd_hlpr.core.narrator import Narrator


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
    
    # AI Explanation & Narration
    ai_narrative: Optional[str] = None


class ScannerOrchestrator:
    @staticmethod
    def run(config: OrchestratorConfig) -> OrchestratorResult:
        # Detect architecture & framework first
        detector = ArchitectureDetector()
        arch_info = detector.detect(config.path)
        
        result = OrchestratorResult(
            path=str(Path(config.path).resolve()),
            framework=arch_info.get("framework", "Unknown"),
            architecture=arch_info.get("architecture", "Single File"),
            features=arch_info.get("features", []),
            summary=arch_info.get("summary", "")
        )
        
        # 1. Tree
        if config.tree:
            result.tree = generate_project_tree(config.path, depth=config.depth)
            
        # 2. UML
        if config.uml:
            result.uml = build_uml_diagram(config.path, config.depth, arch_info)
            
        # 3. ER
        if config.er:
            result.er = build_er_diagram(config.path, config.depth, arch_info)
            
        # 4. Routes
        if config.routes:
            routes = parse_project_routes(config.path, max_depth=config.depth)
            if routes:
                result.routes = generate_mermaid_sequence(routes)
                
        # 5. Infra
        if config.infra:
            compose_file = parse_infra(config.path)
            if compose_file:
                services = parse_docker_compose(compose_file)
                if services:
                    result.infra = generate_mermaid_infra(services)
                    
        # 6. Traceability
        if config.trace:
            traces = parse_project_traceability(config.path, max_depth=config.depth)
            if traces:
                result.trace = generate_mermaid_traceability(traces)
                
        # 7. Jupyter Notebook Data Science lineage
        if config.datascience:
            scanner = ProjectScanner()
            result.datascience = scanner.scan_notebooks(config.path, max_depth=config.depth)
            
        # 8. Todos (Technical debt)
        if config.todo or config.health:
            result.todos = scan_for_todos(config.path, max_depth=config.depth)
            
        # 9. Security Risks
        if config.audit or config.health:
            result.security_risks = scan_security_risks(config.path, max_depth=config.depth)
            
        # 10. Dependency heatmap
        if config.impact:
            result.dependency_heatmap = analyze_impact(config.path)
            
        # 11. Impact radius
        if config.impact_radius:
            abs_changed_file = str(Path(config.impact_radius).resolve())
            result.impact_radius_report = get_routes_affected_by_file(config.path, abs_changed_file, max_depth=config.depth)
            
        # 12. API Contract map
        if config.contract:
            result.api_contracts = generate_api_contract_map(config.path, max_depth=config.depth)
            
        # 13. Onboarding path
        if config.teach:
            tracker = DependencyTracker(config.path)
            tracker.scan_dependencies()
            result.onboarding_path = tracker.get_onboarding_path()
            
        # 14. Project Health Score
        if config.health:
            scanner = ProjectScanner()
            result.health_score = scanner.calculate_health_score(config.path, max_depth=config.depth)
            
        # 15. Export Data Dictionary
        if config.export_dict:
            result.data_dictionary = export_entities_as_dict(config.path, format=config.export_dict, max_depth=config.depth)
            
        # 16. AI narrative
        if config.ai:
            narrator = Narrator(force_provider=config.provider)
            # Use scan topology from scan() method of ProjectScanner
            scanner = ProjectScanner()
            topology_text = scanner.scan(config.path, max_depth=config.depth)
            result.ai_narrative = narrator.explain(topology_text, use_ai=True, style=config.style)
            
        return result
