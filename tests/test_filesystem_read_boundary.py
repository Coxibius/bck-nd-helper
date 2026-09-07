"""Regressions for the trusted, bounded project filesystem read boundary."""

import json
import os
import stat
from pathlib import Path

import pytest

import bck_nd_hlpr.core.detector as detector_module
import bck_nd_hlpr.core.utils.cache as cache_module
import bck_nd_hlpr.core.utils.delta_cache as delta_module
from bck_nd_hlpr.core.dependency_tracker import DependencyTracker
from bck_nd_hlpr.core.detector import ArchitectureDetector
from bck_nd_hlpr.core.utils.cache import FileCache
from bck_nd_hlpr.core.utils.delta_cache import DeltaCacheManager
from bck_nd_hlpr.core.utils.indexer import FileSystemIndexer


def _mark_paths_as_reparse(monkeypatch, *paths: Path) -> None:
    unsafe = {(path.lstat().st_dev, path.lstat().st_ino) for path in paths}
    original = cache_module._is_link_or_reparse
    monkeypatch.setattr(
        cache_module,
        "_is_link_or_reparse",
        lambda value: (value.st_dev, value.st_ino) in unsafe or original(value),
    )


def _write(root: Path, relative: str, content: str = "safe\n") -> Path:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def test_project_reader_accepts_regular_file_and_normalizes_newlines(tmp_path):
    source = tmp_path / "main.py"
    source.write_bytes(b"first\r\nsecond\rthird\n")
    FileCache.clear()

    assert cache_module.MAX_SCANNED_FILE_BYTES == 8 * 1024 * 1024
    assert FileCache.read_project_file(tmp_path, source) == "first\nsecond\nthird\n"


@pytest.mark.parametrize(
    "candidate",
    [
        "../outside.py",
        "..\\outside.py",
        "/outside.py",
        "C:\\outside.py",
        "C:outside.py",
        "\\\\host\\share\\x.py",
    ],
)
def test_project_reader_rejects_external_and_portable_traversal(tmp_path, candidate):
    with pytest.raises(OSError, match="Project file read denied") as captured:
        FileCache.read_project_file(tmp_path, candidate)

    assert str(tmp_path) not in str(captured.value)
    assert candidate not in str(captured.value)


@pytest.mark.parametrize("unsafe_component", ["target", "parent"])
def test_project_reader_rejects_simulated_reparse_target_and_parent(
    tmp_path, monkeypatch, unsafe_component
):
    parent = tmp_path / "linked"
    source = _write(tmp_path, "linked/main.py")
    unsafe_path = source if unsafe_component == "target" else parent
    unsafe = {(unsafe_path.lstat().st_dev, unsafe_path.lstat().st_ino)}
    original = cache_module._is_link_or_reparse
    monkeypatch.setattr(
        cache_module,
        "_is_link_or_reparse",
        lambda path_stat: (path_stat.st_dev, path_stat.st_ino) in unsafe
        or original(path_stat),
    )
    FileCache.clear()

    with pytest.raises(OSError):
        FileCache.read_project_file(tmp_path, source)
    assert not FileCache._cache


def test_project_reader_rejects_non_regular_file(tmp_path):
    directory = tmp_path / "directory.py"
    directory.mkdir()

    with pytest.raises(OSError):
        FileCache.read_project_file(tmp_path, directory)


def test_project_reader_enforces_exact_byte_limit_without_partial_result(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(cache_module, "MAX_SCANNED_FILE_BYTES", 32, raising=False)
    exact = tmp_path / "exact.bin"
    over = tmp_path / "over.bin"
    exact.write_bytes(b"x" * 32)
    over.write_bytes(b"x" * 33)
    FileCache.clear()

    assert FileCache.read_project_file(tmp_path, exact) == "x" * 32
    with pytest.raises(OSError):
        FileCache.read_project_file(tmp_path, over)
    assert all("over.bin" not in str(key) for key in FileCache._cache)


def test_project_reader_accepts_exact_canonical_limit_and_rejects_one_more(tmp_path):
    exact = tmp_path / "exact.bin"
    over = tmp_path / "over.bin"
    exact.write_bytes(b"x" * cache_module.MAX_SCANNED_FILE_BYTES)
    over.write_bytes(b"x" * (cache_module.MAX_SCANNED_FILE_BYTES + 1))
    FileCache.clear()

    assert len(FileCache.read_project_bytes(tmp_path, exact)) == 8 * 1024 * 1024
    with pytest.raises(OSError):
        FileCache.read_project_bytes(tmp_path, over)
    assert all("over.bin" not in str(key) for key in FileCache._cache)


def test_project_reader_cache_hit_performs_no_second_complete_read(tmp_path, monkeypatch):
    source = _write(tmp_path, "cached.py", "VALUE = 1\n")
    real_read_all = cache_module._read_all
    calls = []

    def tracked_read_all(descriptor, *args, **kwargs):
        calls.append(descriptor)
        return real_read_all(descriptor, *args, **kwargs)

    monkeypatch.setattr(cache_module, "_read_all", tracked_read_all)
    FileCache.clear()

    assert FileCache.read_project_file(tmp_path, source) == "VALUE = 1\n"
    assert FileCache.read_project_file(tmp_path, source) == "VALUE = 1\n"
    assert len(calls) == 1


def test_project_reader_discards_content_changed_during_read(tmp_path, monkeypatch):
    source = _write(tmp_path, "race.py", "before\n")
    real_read_all = cache_module._read_all

    def raced_read(descriptor, *args, **kwargs):
        content = real_read_all(descriptor, *args, **kwargs)
        source.write_text("concurrent\n", encoding="utf-8")
        return content

    monkeypatch.setattr(cache_module, "_read_all", raced_read)
    FileCache.clear()

    with pytest.raises(OSError):
        FileCache.read_project_file(tmp_path, source)
    assert not FileCache._cache
    assert source.read_text(encoding="utf-8") == "concurrent\n"


def test_project_reader_closes_descriptor_and_does_not_cache_failed_read(
    tmp_path, monkeypatch
):
    source = _write(tmp_path, "descriptor.py")
    real_open = cache_module.os.open
    real_close = cache_module.os.close
    opened = []
    closed = []

    def tracked_open(*args, **kwargs):
        descriptor = real_open(*args, **kwargs)
        opened.append(descriptor)
        return descriptor

    def tracked_close(descriptor):
        closed.append(descriptor)
        return real_close(descriptor)

    monkeypatch.setattr(cache_module.os, "open", tracked_open)
    monkeypatch.setattr(cache_module.os, "close", tracked_close)
    monkeypatch.setattr(
        cache_module,
        "_read_all",
        lambda _descriptor: (_ for _ in ()).throw(OSError("simulated")),
    )
    FileCache.clear()

    with pytest.raises(OSError):
        FileCache.read_project_file(tmp_path, source)

    assert opened and closed == opened
    assert not FileCache._cache
    with pytest.raises(OSError):
        os.fstat(opened[0])


def test_ignored_package_file_cannot_change_framework_detection(tmp_path):
    _write(tmp_path, ".gitignore", "package.json\n")
    _write(
        tmp_path,
        "package.json",
        json.dumps({"dependencies": {"next": "latest"}}),
    )

    result = ArchitectureDetector().detect(str(tmp_path))

    assert result["framework"] == "Unknown"


def test_package_replaced_after_snapshot_cannot_change_detection(
    tmp_path, monkeypatch
):
    package = _write(
        tmp_path,
        "package.json",
        json.dumps({"dependencies": {"next": "latest"}}),
    )
    snapshot = FileSystemIndexer(str(tmp_path), max_depth=None).build()
    _mark_paths_as_reparse(monkeypatch, package)
    FileCache.clear()

    result = ArchitectureDetector().detect(str(tmp_path), file_index=snapshot)

    assert result["framework"] == "Unknown"


def test_routes_traceability_and_infra_omit_replaced_candidates(
    tmp_path, monkeypatch
):
    from bck_nd_hlpr.core.infra_parser import parse_docker_compose, parse_infra
    from bck_nd_hlpr.core.route_parser import parse_project_routes
    from bck_nd_hlpr.core.traceability import parse_project_traceability

    route = _write(
        tmp_path,
        "app/route.py",
        "@app.get('/secret')\ndef secret():\n    return service()\n",
    )
    next_route = _write(
        tmp_path,
        "app/api/route.ts",
        "export async function POST() { return null }\n",
    )
    compose = _write(
        tmp_path,
        "docker-compose.yml",
        "services:\n  private:\n    image: postgres\n",
    )
    snapshot = FileSystemIndexer(str(tmp_path), max_depth=None).build()
    _mark_paths_as_reparse(monkeypatch, route, next_route, compose)
    FileCache.clear()

    assert parse_project_routes(
        str(tmp_path), max_depth=None, file_index=snapshot
    ) == []
    assert parse_project_traceability(
        str(tmp_path), max_depth=None, file_index=snapshot
    ) == []
    compose_path = parse_infra(str(tmp_path), file_index=snapshot)
    assert compose_path is not None
    assert parse_docker_compose(
        compose_path, project_root=str(tmp_path)
    ) == {}


def test_provider_and_context_size_omit_replaced_candidates(tmp_path, monkeypatch):
    from bck_nd_hlpr.core.context_dumper import ContextDumper

    source = _write(tmp_path, "main.py", "from fastapi import FastAPI\n")
    dumper = ContextDumper(path=str(tmp_path), depth=None, include_prd=False)
    _mark_paths_as_reparse(monkeypatch, source)
    FileCache.clear()

    result = ArchitectureDetector().detect(
        str(tmp_path), file_index=dumper._file_index
    )

    assert result["framework"] == "Unknown"
    assert dumper.get_raw_source_size() == 0
    assert dumper.get_core_files() == []


def test_provider_does_not_return_models_or_routes_replaced_after_snapshot(
    tmp_path, monkeypatch
):
    from bck_nd_hlpr.core.providers.django import DjangoProvider

    model = _write(tmp_path, "app/models.py", "class Secret: pass\n")
    route = _write(tmp_path, "app/urls.py", "urlpatterns = []\n")
    snapshot = FileSystemIndexer(str(tmp_path), max_depth=None).build()
    provider = DjangoProvider()
    provider._set_file_index(snapshot)
    _mark_paths_as_reparse(monkeypatch, model, route)

    assert provider.find_model_files(tmp_path) == []
    assert provider.find_route_files(tmp_path) == []


def test_provider_registry_builds_at_most_one_snapshot(tmp_path, monkeypatch):
    import bck_nd_hlpr.core.providers  # noqa: F401
    import bck_nd_hlpr.core.providers.registry as registry_module

    package = _write(tmp_path, "package.json", '{"dependencies": {}}')
    supplied_snapshot = FileSystemIndexer(str(tmp_path), max_depth=None).build()
    real_build = registry_module.FileSystemIndexer.build
    calls = []

    def tracked_build(indexer):
        calls.append(indexer.root)
        return real_build(indexer)

    monkeypatch.setattr(registry_module.FileSystemIndexer, "build", tracked_build)
    registry = registry_module.ProviderRegistry.get_instance()

    first = registry.detect_all(tmp_path)
    second = registry.detect_all(
        tmp_path,
        file_index=supplied_snapshot,
    )

    assert package.exists()
    assert first and second
    assert len(calls) == 1


def test_detector_fails_closed_when_snapshot_cannot_be_built(tmp_path, monkeypatch):
    _write(tmp_path, "main.py", "from fastapi import FastAPI\n")
    monkeypatch.setattr(
        detector_module.FileSystemIndexer,
        "build",
        lambda _self: (_ for _ in ()).throw(OSError("index unavailable")),
        raising=False,
    )
    monkeypatch.setattr(
        detector_module.os,
        "walk",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("fallback traversal used")
        ),
    )

    result = ArchitectureDetector().detect(str(tmp_path))

    assert result["framework"] == "Unknown"


def test_dependency_tracker_uses_only_snapshot_paths_and_neutral_external_rejection(
    tmp_path,
):
    outside = _write(tmp_path.parent, "outside_dependency.py", "VALUE = 1\n")
    source = _write(tmp_path, "main.py", "from ..outside_dependency import VALUE\n")
    tracker = DependencyTracker(str(tmp_path))

    tracker.scan_dependencies()
    result = tracker.calculate_impact_radius(str(outside))

    assert str(outside) not in repr(tracker.imports_map)
    assert str(outside) not in repr(result)
    assert result == {"changed_file": "<outside-project>", "affected_files": []}
    assert source.relative_to(tmp_path).as_posix() in tracker.all_files


def test_dependency_tracker_resolves_valid_snapshot_module_deterministically(tmp_path):
    _write(tmp_path, "service.py", "VALUE = 1\n")
    _write(tmp_path, "main.py", "from service import VALUE\n")
    snapshot = FileSystemIndexer(str(tmp_path), max_depth=None).build()
    tracker = DependencyTracker(str(tmp_path), file_index=snapshot)

    tracker.scan_dependencies()
    first = {key: sorted(value) for key, value in tracker.usage_map.items()}
    tracker.scan_dependencies()
    second = {key: sorted(value) for key, value in tracker.usage_map.items()}

    assert first == second == {"service.py": ["main.py"]}


def test_uml_and_er_omit_candidate_replaced_after_index(tmp_path, monkeypatch):
    from bck_nd_hlpr.core.er_parser import parse_project_for_er
    from bck_nd_hlpr.core.uml_parser import parse_file_for_uml

    source = _write(
        tmp_path,
        "models.py",
        "class SecretModel:\n    password: str\n",
    )
    snapshot = FileSystemIndexer(str(tmp_path), max_depth=None).build()
    _mark_paths_as_reparse(monkeypatch, source)
    FileCache.clear()

    assert parse_file_for_uml(source, tmp_path) == []
    assert parse_project_for_er(
        str(tmp_path), max_depth=None, file_index=snapshot
    ) == []


def test_context_core_centrality_remains_stable_for_normal_project(tmp_path):
    from bck_nd_hlpr.core.context_dumper import ContextDumper

    _write(tmp_path, "main.py", "from service import run\nrun()\n")
    _write(tmp_path, "service.py", "def run():\n    return 1\n")
    _write(tmp_path, "unused.py", "VALUE = 0\n")

    first = ContextDumper(
        path=str(tmp_path), depth=None, include_prd=False
    ).get_core_files()
    second = ContextDumper(
        path=str(tmp_path), depth=None, include_prd=False
    ).get_core_files()

    assert first == second
    assert [item["path"] for item in first][:2] == ["main.py", "service.py"]


def test_delta_cache_rejects_external_and_source_link_candidates(tmp_path, monkeypatch):
    source = _write(tmp_path, "main.py")
    outside = _write(tmp_path.parent, "outside_delta.py")
    manager = DeltaCacheManager(tmp_path)

    manager.update_file(outside)
    assert manager.compute_signature(outside) == {}
    assert manager.is_unmodified(outside) is False
    assert manager.signatures == {}

    source_stat = source.lstat()
    original = cache_module._is_link_or_reparse
    monkeypatch.setattr(
        cache_module,
        "_is_link_or_reparse",
        lambda value: (
            value.st_dev == source_stat.st_dev and value.st_ino == source_stat.st_ino
        )
        or original(value),
    )
    assert manager.compute_signature(source) == {}
    manager.update_file(source)
    assert manager.signatures == {}


def test_delta_cache_race_during_hash_never_updates_signature(tmp_path, monkeypatch):
    source = _write(tmp_path, "main.py", "before\n")
    manager = DeltaCacheManager(tmp_path)
    real_read_all = cache_module._read_all

    def raced_read(descriptor, *args, **kwargs):
        content = real_read_all(descriptor, *args, **kwargs)
        source.write_text("changed\n", encoding="utf-8")
        return content

    monkeypatch.setattr(cache_module, "_read_all", raced_read)
    FileCache.clear()

    manager.update_file(source)

    assert manager.signatures == {}


def test_orchestrator_index_failure_does_not_activate_analyzer_walks(
    tmp_path, monkeypatch
):
    import bck_nd_hlpr.core.orchestrator as orchestrator_module

    _write(tmp_path, "main.py", "# TODO must stay unread\n")
    observed = []
    monkeypatch.setattr(
        orchestrator_module.FileSystemIndexer,
        "build",
        lambda _self: (_ for _ in ()).throw(OSError("unavailable")),
    )

    def no_fallback(_root, max_depth=None, file_list=None):
        observed.append(file_list)
        assert file_list == []
        return []

    monkeypatch.setattr(orchestrator_module, "scan_for_todos", no_fallback)

    result = orchestrator_module.ScannerOrchestrator.run(
        orchestrator_module.OrchestratorConfig(
            path=str(tmp_path), todo=True, use_cache=False
        )
    )

    assert observed == [[]]
    assert result.todos == []
    assert result.file_index is not None
    assert result.file_index.all_files == []


@pytest.mark.parametrize(
    "payload",
    [
        "not-json",
        "[]",
        '{"signatures":[],"metadata":{}}',
        '{"signatures":{},"metadata":[]}',
        '{"signatures":{"../outside.py":{}},"metadata":{}}',
        '{"signatures":{"C:\\\\outside.py":{}},"metadata":{}}',
        '{"signatures":{"C:outside.py":{}},"metadata":{}}',
        '{"signatures":{"\\\\\\\\host\\\\share\\\\x.py":{}},"metadata":{}}',
    ],
)
def test_delta_cache_invalid_or_unsafe_payload_fails_closed(tmp_path, payload):
    cache_dir = tmp_path / ".bck-nd" / "cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "delta.json").write_text(payload, encoding="utf-8")

    manager = DeltaCacheManager(tmp_path)

    assert manager.signatures == {}
    assert manager.metadata == {}


def test_delta_cache_rejects_oversized_and_simulated_reparse_cache(
    tmp_path, monkeypatch
):
    cache_dir = tmp_path / ".bck-nd" / "cache"
    cache_dir.mkdir(parents=True)
    cache_file = cache_dir / "delta.json"
    cache_file.write_text('{"signatures":{},"metadata":{}}', encoding="utf-8")
    monkeypatch.setattr(delta_module, "MAX_DELTA_CACHE_BYTES", 8, raising=False)

    oversized = DeltaCacheManager(tmp_path)
    assert oversized.signatures == {}
    assert oversized.metadata == {}

    monkeypatch.setattr(delta_module, "MAX_DELTA_CACHE_BYTES", 1024, raising=False)
    cache_stat = cache_file.lstat()
    original = cache_module._is_link_or_reparse
    monkeypatch.setattr(
        cache_module,
        "_is_link_or_reparse",
        lambda value: (
            value.st_dev == cache_stat.st_dev and value.st_ino == cache_stat.st_ino
        )
        or original(value),
    )
    linked = DeltaCacheManager(tmp_path)
    assert linked.signatures == {}
    assert linked.metadata == {}


def test_delta_cache_valid_payload_still_loads(tmp_path):
    cache_dir = tmp_path / ".bck-nd" / "cache"
    cache_dir.mkdir(parents=True)
    payload = {
        "version": "1.0",
        "metadata": {"scan": "ok"},
        "signatures": {
            "src/main.py": {"mtime": 1.0, "size": 1, "hash": "abc"}
        },
    }
    (cache_dir / "delta.json").write_text(json.dumps(payload), encoding="utf-8")

    manager = DeltaCacheManager(tmp_path)

    assert manager.metadata == {"scan": "ok"}
    assert set(manager.signatures) == {"src/main.py"}


def test_index_snapshot_is_deterministic_and_excludes_ignored_sources(tmp_path):
    _write(tmp_path, ".gitignore", "generated/\n")
    visible = _write(tmp_path, "src/b.py")
    _write(tmp_path, "src/a.py")
    _write(tmp_path, "generated/secret.py")

    first = FileSystemIndexer(str(tmp_path), max_depth=None).build()
    second = FileSystemIndexer(str(tmp_path), max_depth=None).build()

    assert first.all_files == second.all_files
    assert visible in first.all_files
    assert not any("generated" in path.parts for path in first.all_files)
