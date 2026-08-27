"""Reliability regressions for ignored paths and architectural core context."""

from pathlib import Path

from bck_nd_hlpr.core.context_dumper import ContextDumper
from bck_nd_hlpr.core.dependency_tracker import DependencyTracker
from bck_nd_hlpr.core.er_parser import parse_project_for_er
from bck_nd_hlpr.core.js_parser import parse_project_for_js_uml
from bck_nd_hlpr.core.scanner import ProjectScanner


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
