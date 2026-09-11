"""Reliability regressions for ignored paths and architectural core context."""

import copy
from pathlib import Path
import pytest

from bck_nd_hlpr.core.context_dumper import ContextDumper
from bck_nd_hlpr.core.dependency_tracker import DependencyTracker
from bck_nd_hlpr.core.er_parser import parse_project_for_er
from bck_nd_hlpr.core.js_parser import parse_project_for_js_uml
from bck_nd_hlpr.core.orchestrator import OrchestratorConfig, ScannerOrchestrator
from bck_nd_hlpr.core.scanner import ProjectScanner
from bck_nd_hlpr.core.tree_generator import generate_project_tree
from bck_nd_hlpr.core.uml_parser import is_empty_mermaid_class_diagram
from bck_nd_hlpr.core.sanitizer import REDACTION_MARKER
from bck_nd_hlpr.core.utils.cache import FileCache
from bck_nd_hlpr.core.utils.indexer import FileSystemIndexer


def _write(root: Path, relative_path: str, content: str) -> Path:
    target = root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def _core_paths(root: Path, *, limit: int = 20) -> list[str]:
    return [
        item["path"]
        for item in ContextDumper(
            path=str(root), depth=None, max_core_files=limit
        ).get_core_files()
    ]


def test_reparse_entries_never_reach_index_tree_cache_or_context(
    tmp_path,
    monkeypatch,
):
    import bck_nd_hlpr.core.tree_generator as tree_module
    import bck_nd_hlpr.core.utils.cache as cache_module
    import bck_nd_hlpr.core.utils.indexer as indexer_module

    secret = "ghp_externalfilesystemsecret1234567890"
    linked_file = _write(tmp_path, "main.py", secret)
    linked_directory = tmp_path / "linked-directory"
    linked_directory.mkdir()
    _write(linked_directory, "outside.py", secret)
    _write(tmp_path, "app.py", "print('safe')\n")

    unsafe_states = {
        (linked_file.lstat().st_dev, linked_file.lstat().st_ino),
        (linked_directory.lstat().st_dev, linked_directory.lstat().st_ino),
    }

    def simulated_reparse(path_stat):
        return (path_stat.st_dev, path_stat.st_ino) in unsafe_states

    monkeypatch.setattr(indexer_module, "_is_link_or_reparse", simulated_reparse)
    monkeypatch.setattr(tree_module, "_is_link_or_reparse", simulated_reparse)
    monkeypatch.setattr(cache_module, "_is_link_or_reparse", simulated_reparse)
    FileCache.clear()

    index = FileSystemIndexer(str(tmp_path), max_depth=5).build()
    tree = generate_project_tree(str(tmp_path), depth=5)
    dumper = ContextDumper(path=str(tmp_path), depth=5, include_prd=False)
    core = dumper.get_core_files()
    context = dumper.build()

    assert linked_file not in index.all_files
    assert not any("linked-directory" in str(path) for path in index.all_files)
    assert "main.py" not in tree
    assert "linked-directory" not in tree
    assert not any(item["path"] == "main.py" for item in core)
    assert secret not in context
    with pytest.raises(OSError):
        FileCache.read_file(linked_file)
    assert str(linked_file) not in FileCache._cache


def test_real_symlink_entries_are_excluded_when_platform_allows_them(tmp_path):
    outside = tmp_path / "outside"
    project = tmp_path / "project"
    outside.mkdir()
    project.mkdir()
    secret = "external-symlink-secret"
    external_file = _write(outside, "secret.py", secret)
    external_directory = outside / "directory"
    external_directory.mkdir()
    _write(external_directory, "nested.py", secret)
    file_link = project / "main.py"
    directory_link = project / "linked"
    try:
        file_link.symlink_to(external_file)
        directory_link.symlink_to(external_directory, target_is_directory=True)
    except OSError:
        return

    FileCache.clear()
    index = FileSystemIndexer(str(project), max_depth=5).build()
    tree = generate_project_tree(str(project), depth=5)
    context = ContextDumper(
        path=str(project), depth=5, include_prd=False
    ).build()

    assert index.all_files == []
    assert "main.py" not in tree
    assert "linked" not in tree
    assert secret not in context
    with pytest.raises(OSError):
        FileCache.read_file(file_link)


def test_file_cache_verified_descriptor_read_is_cached_and_closed(
    tmp_path,
    monkeypatch,
):
    import bck_nd_hlpr.core.utils.cache as cache_module

    source = _write(tmp_path, "regular.py", "VALUE = 1\n")
    real_open = cache_module.os.open
    real_close = cache_module.os.close
    real_read_all = cache_module._read_all
    opened = []
    closed = []
    complete_reads = []

    def tracked_open(*args, **kwargs):
        descriptor = real_open(*args, **kwargs)
        opened.append(descriptor)
        return descriptor

    def tracked_close(descriptor):
        closed.append(descriptor)
        return real_close(descriptor)

    def tracked_read_all(descriptor):
        complete_reads.append(descriptor)
        return real_read_all(descriptor)

    monkeypatch.setattr(cache_module.os, "open", tracked_open)
    monkeypatch.setattr(cache_module.os, "close", tracked_close)
    monkeypatch.setattr(cache_module, "_read_all", tracked_read_all)
    FileCache.clear()

    assert FileCache.read_file(source) == "VALUE = 1\n"
    assert len(complete_reads) == 1
    assert FileCache.read_file(source) == "VALUE = 1\n"
    assert len(complete_reads) == 1
    assert len(opened) == 1
    assert closed == opened


def test_file_cache_rejects_content_changed_during_descriptor_read(
    tmp_path,
    monkeypatch,
):
    import bck_nd_hlpr.core.utils.cache as cache_module

    source = _write(tmp_path, "raced.py", "VALUE = 'before'\n")
    concurrent = "VALUE = 'concurrent writer wins'\n"
    real_read_all = cache_module._read_all
    calls = 0

    def raced_read_all(descriptor):
        nonlocal calls
        content = real_read_all(descriptor)
        calls += 1
        if calls == 1:
            source.write_text(concurrent, encoding="utf-8")
        return content

    monkeypatch.setattr(cache_module, "_read_all", raced_read_all)
    FileCache.clear()

    with pytest.raises(OSError, match="Unsafe file read denied"):
        FileCache.read_file(source)

    assert source.read_text(encoding="utf-8") == concurrent
    assert str(source) not in FileCache._cache


def test_file_cache_preserves_universal_newline_compatibility(tmp_path):
    source = tmp_path / "windows-newlines.py"
    source.write_bytes(b"first\r\nsecond\rthird\n")
    FileCache.clear()

    assert FileCache.read_file(source) == "first\nsecond\nthird\n"


def test_context_redacts_core_paths_contents_and_every_requirement_field(
    tmp_path,
    monkeypatch,
):
    from bck_nd_hlpr.core.requirements import (
        AcceptanceCriteria,
        BusinessRule,
        RequirementSpecification,
        RequirementsLoadResult,
        RequirementsParser,
        UserStory,
    )

    secret = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"
    secret_directory = tmp_path / secret
    source = _write(secret_directory, "main.py", f'TOKEN = "{secret}"\n')
    original_source = source.read_bytes()
    spec = RequirementSpecification(
        story=UserStory(
            id=secret,
            title=f"Title {secret}",
            role=f"Role {secret}",
            want=f"Want {secret}",
            benefit=f"Benefit {secret}",
            status=f"TODO-{secret}",
        ),
        business_rules=[BusinessRule(id=secret, description=f"Rule {secret}")],
        acceptance_criteria=[
            AcceptanceCriteria(
                id=secret,
                given=f"Given {secret}",
                when=f"When {secret}",
                then=f"Then {secret}",
            )
        ],
        required_data=[{"name": "token", "value": secret}],
        validations=[{"token": secret}],
        exceptions=[{"secret": secret}],
        open_questions=[f"Question {secret}"],
    )
    original_model = copy.deepcopy(spec.to_dict())
    monkeypatch.setattr(
        RequirementsParser,
        "load_collection",
        classmethod(lambda _cls, _root: RequirementsLoadResult((spec,))),
    )

    dumper = ContextDumper(
        path=str(tmp_path), depth=5, max_core_files=10, include_prd=False
    )
    full = dumper.build()
    focused = dumper.build_focused(include_requirements=True, include_tree=True)

    for rendered in (full, focused):
        assert secret not in rendered
        assert REDACTION_MARKER in rendered
        assert "<requirements_context>" in rendered
    assert "<core_files>" in full
    assert "<project_tree>" in full
    assert spec.to_dict() == original_model
    assert source.read_bytes() == original_source


def test_secret_free_context_keeps_xml_like_structure(tmp_path):
    _write(tmp_path, "main.py", "print('safe')\n")

    rendered = ContextDumper(
        path=str(tmp_path), depth=3, include_prd=False
    ).build()

    assert "<project_tree>" in rendered
    assert "</project_tree>" in rendered
    assert "<core_files>" in rendered
    assert "</core_files>" in rendered
    assert REDACTION_MARKER not in rendered


def test_uml_and_er_exclude_gitignored_environments(tmp_path):
    _write(tmp_path, ".gitignore", "cuarentena_env/\ntest_env/\n")
    _write(tmp_path, "visible.py", "class VisiblePython:\n    pass\n")
    _write(
        tmp_path,
        "visible.ts",
        "export interface VisibleContract { id: string; }\n",
    )
    _write(
        tmp_path,
        "models.py",
        "class VisibleRecord(Base):\n    id = Column(Integer, primary_key=True)\n",
    )

    _write(
        tmp_path,
        "cuarentena_env/ignored.py",
        "class QuarantinedPython:\n    pass\n",
    )
    _write(
        tmp_path,
        "cuarentena_env/ignored.ts",
        "export interface QuarantinedContract { secret: string; }\n",
    )
    _write(
        tmp_path,
        "cuarentena_env/models.py",
        "class QuarantinedRecord(Base):\n    id = Column(Integer)\n",
    )
    _write(
        tmp_path,
        "test_env/ignored.py",
        "class TestEnvironmentClass:\n    pass\n",
    )
    _write(
        tmp_path,
        "test_env/ignored.ts",
        "export interface TestEnvironmentContract { hidden: boolean; }\n",
    )

    scanner = ProjectScanner()
    classes = scanner.collect_uml_classes(str(tmp_path), max_depth=5)
    class_names = {item.name for item in classes}
    modules = {item.module for item in classes}

    assert {"VisiblePython", "VisibleContract"} <= class_names
    assert "QuarantinedPython" not in class_names
    assert "QuarantinedContract" not in class_names
    assert "TestEnvironmentClass" not in class_names
    assert "TestEnvironmentContract" not in class_names
    assert not any("cuarentena_env" in module or "test_env" in module for module in modules)

    mermaid = scanner.scan_uml(str(tmp_path), max_depth=5)
    assert "VisiblePython" in mermaid
    assert "VisibleContract" in mermaid
    assert "Quarantined" not in mermaid
    assert "TestEnvironment" not in mermaid
    assert "cuarentena_env" not in mermaid
    assert "test_env" not in mermaid

    # Direct Tree-sitter-backed project traversal uses the same ignore index.
    js_classes = parse_project_for_js_uml(str(tmp_path), max_depth=5)
    js_names = {item.name for item in js_classes}
    assert "VisibleContract" in js_names
    assert "QuarantinedContract" not in js_names
    assert "TestEnvironmentContract" not in js_names

    entities = parse_project_for_er(str(tmp_path), max_depth=5)
    entity_names = {entity.name for entity in entities}
    assert "VisibleRecord" in entity_names
    assert "QuarantinedRecord" not in entity_names


def test_dependency_tracker_excludes_gitignored_sources(tmp_path):
    _write(tmp_path, ".gitignore", "test_env/\n")
    _write(tmp_path, "main.py", "from shared_kernel import execute\n")
    _write(tmp_path, "worker.py", "from shared_kernel import execute\n")
    _write(tmp_path, "shared_kernel.py", "def execute():\n    return True\n")
    _write(
        tmp_path,
        "test_env/ignored_consumer.py",
        "from shared_kernel import execute\n",
    )

    tracker = DependencyTracker(str(tmp_path))
    tracker.scan_dependencies()

    assert "test_env/ignored_consumer.py" not in tracker.all_files
    assert tracker.usage_map["shared_kernel.py"] == {"main.py", "worker.py"}
    onboarding_files = {item["file"] for item in tracker.get_onboarding_path()}
    assert "shared_kernel.py" in onboarding_files
    assert not any(path.startswith("test_env/") for path in onboarding_files)


def test_core_files_prioritize_entrypoint_and_dependency_centrality(tmp_path):
    _write(tmp_path, "main.py", "from workflow_engine import execute\n")
    _write(tmp_path, "feature_a.py", "from workflow_engine import execute\n")
    _write(tmp_path, "feature_b.py", "from workflow_engine import execute\n")
    _write(tmp_path, "workflow_engine.py", "def execute():\n    return 'ok'\n")
    _write(tmp_path, "router.py", "ROUTES = []\n")
    _write(tmp_path, "models.py", "class DecorativeName:\n    pass\n")

    first = _core_paths(tmp_path, limit=6)
    second = _core_paths(tmp_path, limit=6)

    assert first == second
    assert first[0] == "main.py"
    assert "workflow_engine.py" in first
    assert first.index("workflow_engine.py") < first.index("router.py")
    assert first.index("workflow_engine.py") < first.index("models.py")
    assert _core_paths(tmp_path, limit=2) == ["main.py", "workflow_engine.py"]


def test_core_files_exclude_tests_fixtures_scripts_envs_and_generated_files(tmp_path):
    _write(tmp_path, ".gitignore", "ignored_area/\n")
    _write(tmp_path, "main.py", "from core_service import execute\n")
    _write(tmp_path, "core_service.py", "def execute():\n    return True\n")
    _write(tmp_path, "router.py", "ROUTES = []\n")
    _write(tmp_path, "tests/test_core_service.py", "from core_service import execute\n")
    _write(tmp_path, "fixtures/sample.py", "class FixtureData:\n    pass\n")
    _write(tmp_path, "scripts/migrate.py", "print('migrate')\n")
    _write(tmp_path, "venv/Lib/site-packages/dependency.py", "VALUE = 1\n")
    _write(tmp_path, "ignored_area/important_service.py", "VALUE = 1\n")
    _write(tmp_path, "conftest.py", "VALUE = 1\n")
    _write(tmp_path, "helper_test.py", "VALUE = 1\n")
    _write(tmp_path, "component.test.ts", "export const value = 1\n")
    _write(tmp_path, "component.spec.ts", "export const value = 1\n")
    _write(tmp_path, "pywin32_postinstall.py", "VALUE = 1\n")

    paths = _core_paths(tmp_path)

    assert paths[:2] == ["main.py", "core_service.py"]
    forbidden_fragments = (
        "tests/", "fixtures/", "scripts/", "venv/", "ignored_area/",
        "conftest.py", "helper_test.py", ".test.", ".spec.", "postinstall",
    )
    assert not any(
        fragment in path for path in paths for fragment in forbidden_fragments
    )


def test_core_files_empty_dependency_graph_uses_deterministic_fallback(tmp_path):
    _write(tmp_path, "main.py", "print('start')\n")
    _write(tmp_path, "models.py", "class User:\n    pass\n")
    _write(tmp_path, "router.py", "ROUTES = []\n")
    _write(tmp_path, "unrelated.py", "VALUE = 1\n")

    assert _core_paths(tmp_path) == ["main.py", "models.py", "router.py"]
    assert _core_paths(tmp_path) == ["main.py", "models.py", "router.py"]


def test_core_files_dependency_failure_falls_back_safely(tmp_path, monkeypatch):
    _write(tmp_path, "main.py", "print('start')\n")
    _write(tmp_path, "models.py", "class User:\n    pass\n")

    def fail_scan(_self):
        raise OSError("dependency graph unavailable")

    monkeypatch.setattr(DependencyTracker, "scan_dependencies", fail_scan)

    assert _core_paths(tmp_path) == ["main.py", "models.py"]


def test_nested_monorepo_gitignores_stop_sources_before_every_consumer(tmp_path):
    _write(tmp_path, ".gitignore", "root-quarantine/\n")
    _write(
        tmp_path,
        "frontend/.gitignore",
        "ignored-generated/\n*.generated.ts\n!keep.generated.ts\n",
    )
    _write(tmp_path, "backend/.gitignore", "quarantine/\n")
    _write(
        tmp_path,
        "frontend/src/visible.ts",
        "export interface VisibleFrontend { id: string; }\n",
    )
    _write(
        tmp_path,
        "frontend/src/keep.generated.ts",
        "export interface ExplicitlyKept { id: string; }\n",
    )
    _write(
        tmp_path,
        "frontend/src/cache.generated.ts",
        "export interface IgnoredGenerated { secret: string; }\n",
    )
    _write(
        tmp_path,
        "frontend/ignored-generated/secret.ts",
        "export interface IgnoredDirectoryType { secret: string; }\n",
    )
    _write(tmp_path, "backend/app/main.py", "from .models import VisibleRecord\n")
    _write(
        tmp_path,
        "backend/app/models.py",
        "class VisibleRecord(Base):\n    id = Column(Integer, primary_key=True)\n",
    )
    _write(
        tmp_path,
        "backend/quarantine/secret.py",
        "class QuarantinedBackend(Base):\n    token = Column(String)\n",
    )
    _write(
        tmp_path,
        "root-quarantine/secret.py",
        "class RootQuarantined:\n    pass\n",
    )

    index_first = FileSystemIndexer(str(tmp_path), max_depth=8).build()
    index_second = FileSystemIndexer(str(tmp_path), max_depth=8).build()
    first_paths = [
        path.relative_to(tmp_path).as_posix() for path in index_first.all_files
    ]
    second_paths = [
        path.relative_to(tmp_path).as_posix() for path in index_second.all_files
    ]
    tree = generate_project_tree(str(tmp_path), depth=8)
    core_paths = _core_paths(tmp_path)
    scanner = ProjectScanner()
    uml = scanner.scan_uml(str(tmp_path), max_depth=8)
    er_names = {
        entity.name for entity in parse_project_for_er(str(tmp_path), max_depth=8)
    }
    tracker = DependencyTracker(str(tmp_path))
    tracker.scan_dependencies()

    assert first_paths == second_paths
    assert "frontend/src/visible.ts" in first_paths
    assert "frontend/src/keep.generated.ts" in first_paths
    assert "frontend/src/cache.generated.ts" not in first_paths
    assert not any("ignored-generated" in path for path in first_paths)
    assert not any("quarantine" in path for path in first_paths)
    assert "ignored-generated" not in tree
    assert "quarantine" not in tree
    assert not any("quarantine" in path or "ignored-generated" in path for path in core_paths)
    assert "VisibleFrontend" in uml
    assert "ExplicitlyKept" in uml
    assert "IgnoredGenerated" not in uml
    assert "IgnoredDirectoryType" not in uml
    assert "QuarantinedBackend" not in uml
    assert "VisibleRecord" in er_names
    assert "QuarantinedBackend" not in er_names
    assert not any(
        "quarantine" in path or "ignored-generated" in path
        for path in tracker.all_files
    )


def test_context_er_matches_canonical_polyglot_scan_and_caches(
    tmp_path,
    monkeypatch,
):
    import bck_nd_hlpr.core.er_parser as er_parser_module

    _write(
        tmp_path,
        "package.json",
        '{"dependencies":{"next":"14.0.0","react":"18.0.0"}}\n',
    )
    _write(
        tmp_path,
        "src/interfaces.ts",
        """export interface PersonalReason {
    id: string;
    reason: string;
}
""",
    )
    depth = 5
    scan_result = ScannerOrchestrator.run(
        OrchestratorConfig(
            path=str(tmp_path),
            depth=depth,
            er=True,
            use_cache=False,
        )
    )
    original_parse = er_parser_module.parse_project_for_er
    calls = 0

    def tracked_parse(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_parse(*args, **kwargs)

    monkeypatch.setattr(er_parser_module, "parse_project_for_er", tracked_parse)
    dumper = ContextDumper(path=str(tmp_path), depth=depth, include_prd=False)

    prompt_er = dumper.get_er_diagram()

    assert scan_result.er
    assert prompt_er is not None
    assert "PersonalReason" in scan_result.er
    assert "PersonalReason" in prompt_er
    assert prompt_er == scan_result.er
    assert dumper.get_er_diagram() == prompt_er
    assert calls == 1


def test_context_uml_matches_canonical_polyglot_scan_and_caches(
    tmp_path,
    monkeypatch,
):
    _write(
        tmp_path,
        "package.json",
        '{"dependencies":{"next":"14.0.0","react":"18.0.0"}}\n',
    )
    _write(
        tmp_path,
        "src/contracts.ts",
        "export interface FrontendContract { id: string; }\n",
    )
    _write(
        tmp_path,
        "backend/models.py",
        "class BackendModel:\n    pass\n",
    )
    depth = 5
    scan_result = ScannerOrchestrator.run(
        OrchestratorConfig(
            path=str(tmp_path),
            depth=depth,
            uml=True,
            use_cache=False,
        )
    )
    original_scan_uml = ProjectScanner.scan_uml
    calls = 0

    def tracked_scan_uml(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        return original_scan_uml(self, *args, **kwargs)

    monkeypatch.setattr(ProjectScanner, "scan_uml", tracked_scan_uml)
    dumper = ContextDumper(path=str(tmp_path), depth=depth, include_prd=False)

    prompt_uml = dumper.get_uml_diagram()

    assert scan_result.uml
    assert not is_empty_mermaid_class_diagram(scan_result.uml)
    assert prompt_uml is not None
    assert "FrontendContract" in scan_result.uml
    assert "BackendModel" in scan_result.uml
    assert "FrontendContract" in prompt_uml
    assert "BackendModel" in prompt_uml
    assert prompt_uml == scan_result.uml
    assert dumper.get_uml_diagram() == prompt_uml
    assert calls == 1
