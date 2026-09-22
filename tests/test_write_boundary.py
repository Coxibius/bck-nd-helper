"""Final persistence-boundary regressions."""

import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from typer.testing import CliRunner

import bck_nd_hlpr.cli.cli as cli_module
import bck_nd_hlpr.core.doc_generator as doc_module
import bck_nd_hlpr.core.utils.delta_cache as delta_module
import bck_nd_hlpr.core.utils.secure_write as write_module
from bck_nd_hlpr.cli.cli import app
from bck_nd_hlpr.core.context_dumper import ContextMetrics
from bck_nd_hlpr.core.doc_generator import DocGenerator
from bck_nd_hlpr.core.orchestrator import OrchestratorResult, ScannerOrchestrator
from bck_nd_hlpr.core.utils.delta_cache import DeltaCacheManager
from bck_nd_hlpr.core.utils.secure_write import (
    ArtifactAlreadyExistsError,
    SecureWriteError,
    atomic_create_project_artifact,
    atomic_write_explicit_output,
)


runner = CliRunner()


def test_no_clobber_creates_and_validates_parents_after_lexical_resolution(
    tmp_path,
    monkeypatch,
):
    project = tmp_path / "project"
    project.mkdir()
    target = project / ".bck-nd" / "requirements" / "US-ORDER.md"
    events = []
    real_resolve = write_module.resolve_project_target
    real_ensure = write_module._ensure_safe_parent
    real_validate = write_module.validate_artifact_target

    def resolve_with_concurrent_parent(root, requested):
        candidate = real_resolve(root, requested)
        candidate.parent.mkdir(parents=True, exist_ok=True)
        events.append(("resolved", candidate.parent.is_dir()))
        return candidate

    def tracked_ensure(root, candidate):
        events.append(("ensure", candidate.parent.is_dir()))
        return real_ensure(root, candidate)

    def tracked_validate(root, candidate):
        events.append(("validate", Path(candidate).parent.is_dir()))
        return real_validate(root, candidate)

    monkeypatch.setattr(write_module, "resolve_project_target", resolve_with_concurrent_parent)
    monkeypatch.setattr(write_module, "_ensure_safe_parent", tracked_ensure)
    monkeypatch.setattr(write_module, "validate_artifact_target", tracked_validate)

    assert atomic_create_project_artifact(project, target, b"complete\n") == target
    assert target.read_bytes() == b"complete\n"
    ensure_index = next(index for index, event in enumerate(events) if event[0] == "ensure")
    validate_index = next(
        index for index, event in enumerate(events) if event[0] == "validate"
    )
    assert ensure_index < validate_index
    assert events[ensure_index] == ("ensure", True)
    assert events[validate_index] == ("validate", True)

    unsafe_project = tmp_path / "unsafe-order"
    unsafe_project.mkdir()
    unsafe_target = unsafe_project / ".bck-nd" / "requirements" / "US-UNSAFE.md"
    unsafe_target.parent.mkdir(parents=True)
    unsafe_state = (
        unsafe_target.parent.lstat().st_dev,
        unsafe_target.parent.lstat().st_ino,
    )
    real_is_link = write_module._is_link_or_reparse
    monkeypatch.setattr(
        write_module,
        "_is_link_or_reparse",
        lambda value: (value.st_dev, value.st_ino) == unsafe_state
        or real_is_link(value),
    )

    with pytest.raises(SecureWriteError):
        atomic_create_project_artifact(unsafe_project, unsafe_target, b"denied\n")
    assert not unsafe_target.exists()
    assert not list(unsafe_target.parent.glob(".*.tmp"))


def test_explicit_output_is_atomic_preserves_mode_and_aborts_race(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "report.txt"
    target.write_bytes(b"old\n")
    original_mode = stat.S_IMODE(target.stat().st_mode)

    assert atomic_write_explicit_output(target, b"new\n") == target.resolve()
    assert target.read_bytes() == b"new\n"
    assert stat.S_IMODE(target.stat().st_mode) == original_mode

    concurrent = b"concurrent winner\n"
    real_chmod = write_module.os.chmod
    raced = False

    def race_during_temp_chmod(path, mode):
        nonlocal raced
        real_chmod(path, mode)
        if not raced and str(path).endswith(".tmp"):
            raced = True
            target.write_bytes(concurrent)

    monkeypatch.setattr(write_module.os, "chmod", race_during_temp_chmod)

    with pytest.raises(SecureWriteError):
        atomic_write_explicit_output(target, b"must not win\n")

    assert raced is True
    assert target.read_bytes() == concurrent
    assert not list(tmp_path.glob(".*.tmp"))


@pytest.mark.parametrize("unsafe_component", ["parent", "target"])
def test_explicit_output_rejects_reparse_components_without_changes(
    tmp_path,
    monkeypatch,
    unsafe_component,
):
    parent = tmp_path / "output"
    parent.mkdir()
    target = parent / "report.txt"
    target.write_bytes(b"preserve\n")
    unsafe = parent if unsafe_component == "parent" else target
    unsafe_state = (unsafe.lstat().st_dev, unsafe.lstat().st_ino)
    real_is_link = write_module._is_link_or_reparse
    monkeypatch.setattr(
        write_module,
        "_is_link_or_reparse",
        lambda value: (value.st_dev, value.st_ino) == unsafe_state
        or real_is_link(value),
    )

    with pytest.raises(SecureWriteError):
        atomic_write_explicit_output(target, b"replace\n")

    assert target.read_bytes() == b"preserve\n"
    assert not list(parent.glob(".*.tmp"))


def test_no_clobber_creation_has_one_winner(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    requirements = project / ".bck-nd" / "requirements"

    for round_index in range(8):
        target = requirements / f"US-RACE-{round_index}.md"
        contents = (
            f"first complete {round_index}\n".encode("utf-8"),
            f"second complete {round_index}\n".encode("utf-8"),
        )
        barrier = Barrier(2)

        def create(content):
            barrier.wait()
            try:
                return atomic_create_project_artifact(project, target, content)
            except ArtifactAlreadyExistsError as exc:
                return exc
            except SecureWriteError as exc:
                return exc

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create, contents))

        assert sum(isinstance(item, Path) for item in results) == 1
        assert sum(isinstance(item, ArtifactAlreadyExistsError) for item in results) == 1
        assert not [
            item
            for item in results
            if isinstance(item, SecureWriteError)
            and not isinstance(item, ArtifactAlreadyExistsError)
        ]
        assert target.read_bytes() in contents
        assert not list(requirements.glob(".*.tmp"))
        assert not list(requirements.glob("*.lock"))


def test_req_init_rejects_reparse_requirements_directory(tmp_path, monkeypatch):
    unsafe_project = tmp_path / "unsafe"
    requirements = unsafe_project / ".bck-nd" / "requirements"
    requirements.mkdir(parents=True)
    unsafe_state = (requirements.lstat().st_dev, requirements.lstat().st_ino)
    real_is_link = write_module._is_link_or_reparse
    monkeypatch.setattr(
        write_module,
        "_is_link_or_reparse",
        lambda value: (value.st_dev, value.st_ino) == unsafe_state
        or real_is_link(value),
    )

    result = runner.invoke(
        app,
        ["req", "init", "US-UNSAFE", "--path", str(unsafe_project)],
    )

    assert result.exit_code == 1
    assert "could not be created safely" in result.stdout.lower()
    assert not (requirements / "US-UNSAFE.md").exists()


def test_delta_cache_serialization_is_deterministic_bounded_and_strict(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "app.py"
    source.write_text("print('ok')\n", encoding="utf-8")
    cache = DeltaCacheManager(tmp_path)

    assert not (tmp_path / ".bck-nd").exists()
    cache.update_file(source)
    cache.metadata = {"z": 1, "a": "first"}
    serialized = cache._serialize_cache()
    monkeypatch.setattr(delta_module, "MAX_DELTA_CACHE_BYTES", len(serialized))

    assert cache.save_cache() is True
    cache_file = tmp_path / ".bck-nd" / "cache" / "delta.json"
    saved = cache_file.read_bytes()
    assert saved == serialized
    assert saved.endswith(b"\n")
    assert list(json.loads(saved)["metadata"]) == ["a", "z"]

    cache.metadata["overflow"] = "x"
    assert cache.save_cache() is False
    assert cache_file.read_bytes() == saved

    monkeypatch.setattr(delta_module, "MAX_DELTA_CACHE_BYTES", 8 * 1024 * 1024)
    cache.metadata = {"bad": float("nan")}
    assert cache.save_cache() is False
    cycle = {}
    cycle["self"] = cycle
    cache.metadata = cycle
    assert cache.save_cache() is False
    assert cache_file.read_bytes() == saved
    assert not list(cache_file.parent.glob(".*.tmp"))


def test_delta_cache_concurrent_save_and_clear_preserve_the_observed_winner(
    tmp_path,
    monkeypatch,
):
    first = DeltaCacheManager(tmp_path)
    second = DeltaCacheManager(tmp_path)
    first.metadata = {"writer": "first"}
    second.metadata = {"writer": "second"}

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda manager: manager.save_cache(), (first, second)))

    assert sorted(outcomes) == [False, True]
    cache_file = tmp_path / ".bck-nd" / "cache" / "delta.json"
    winner = cache_file.read_bytes()
    stale_clear = DeltaCacheManager(tmp_path)
    updater = DeltaCacheManager(tmp_path)
    updater.metadata = {"writer": "new winner"}
    assert updater.save_cache() is True
    updated = cache_file.read_bytes()
    assert updated != winner

    stale_clear.clear()
    assert cache_file.read_bytes() == updated
    assert stale_clear.signatures == {}
    assert stale_clear.metadata == {}

    cache_state = (cache_file.lstat().st_dev, cache_file.lstat().st_ino)
    real_is_link = write_module._is_link_or_reparse
    monkeypatch.setattr(
        write_module,
        "_is_link_or_reparse",
        lambda value: (value.st_dev, value.st_ino) == cache_state
        or real_is_link(value),
    )
    updater.clear()
    assert cache_file.read_bytes() == updated


def test_scan_builds_before_one_atomic_publication_and_preserves_failed_output(
    tmp_path,
    monkeypatch,
):
    output = tmp_path / "scan.txt"
    output.write_bytes(b"previous output\n")
    real_write = cli_module.atomic_write_explicit_output
    publications = []

    def counted_write(target, content):
        publications.append((Path(target), content))
        return real_write(target, content)

    monkeypatch.setattr(cli_module, "atomic_write_explicit_output", counted_write)

    monkeypatch.setattr(
        ScannerOrchestrator,
        "run",
        staticmethod(lambda _config: (_ for _ in ()).throw(RuntimeError("boom"))),
    )
    failed = runner.invoke(
        app,
        ["scan", str(tmp_path), "--tree", "--output", str(output)],
    )
    assert failed.exit_code == 1
    assert output.read_bytes() == b"previous output\n"
    assert publications == []

    result = OrchestratorResult(
        path=str(tmp_path),
        framework="Unknown",
        architecture="",
        features=[],
        summary="",
        tree="TREE-CONTENT",
        uml="classDiagram\n  class Service",
    )
    monkeypatch.setattr(ScannerOrchestrator, "run", staticmethod(lambda _config: result))
    succeeded = runner.invoke(
        app,
        [
            "scan",
            str(tmp_path),
            "--tree",
            "--uml",
            "--output",
            str(output),
        ],
    )

    rendered = output.read_text(encoding="utf-8")
    assert succeeded.exit_code == 0, succeeded.exception
    assert len(publications) == 1
    assert rendered.index("[TREE] Project Structure") < rendered.index(
        "[UML] Class Diagram"
    )
    assert "TREE-CONTENT" in rendered
    assert "classDiagram" in rendered


def test_prompt_full_focused_and_stdout_publish_only_when_requested(
    tmp_path,
    monkeypatch,
):
    class FakeDumper:
        def __init__(self, *args, **kwargs):
            pass

        def get_project_tree(self):
            return "tree"

        def get_uml_diagram(self):
            return "uml"

        def get_er_diagram(self):
            return "er"

        def build(self):
            return "FULL-CONTEXT"

        def build_focused(self, **_kwargs):
            return "FOCUSED-CONTEXT"

        def get_requirements_result(self):
            return None

        def get_requirements_location_report(self):
            return None

        def get_requirements_context(self):
            return None

        def get_context_metrics(self, context):
            return ContextMetrics(
                estimated_tokens=1,
                context_size_bytes=len(context),
                raw_size_bytes=len(context),
                savings_percentage=0.0,
            )

    monkeypatch.setattr(cli_module, "ContextDumper", FakeDumper)
    real_write = cli_module.atomic_write_explicit_output
    publications = []

    def counted_write(target, content):
        publications.append(Path(target))
        return real_write(target, content)

    monkeypatch.setattr(cli_module, "atomic_write_explicit_output", counted_write)
    full = tmp_path / "full.txt"
    focused = tmp_path / "focused.txt"

    full_result = runner.invoke(app, ["prompt", str(tmp_path), "-o", str(full)])
    focused_result = runner.invoke(
        app,
        ["prompt", str(tmp_path), "--tree", "-o", str(focused)],
    )
    stdout_result = runner.invoke(
        app,
        ["prompt", str(tmp_path), "--tree", "-o", "-"],
    )

    assert full_result.exit_code == 0, full_result.exception
    assert focused_result.exit_code == 0, focused_result.exception
    assert stdout_result.exit_code == 0, stdout_result.exception
    assert full.read_text(encoding="utf-8") == "FULL-CONTEXT"
    assert focused.read_text(encoding="utf-8") == "FOCUSED-CONTEXT"
    assert publications == [full, focused]
    assert "FOCUSED-CONTEXT" in stdout_result.stdout
    assert not (tmp_path / "-").exists()


def test_docs_publish_owned_html_atomically_and_preserve_foreign_or_failed_render(
    tmp_path,
    monkeypatch,
):
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("class App: pass\n", encoding="utf-8")
    docs = tmp_path / "docs"
    generated = DocGenerator().generate(str(project), str(docs))
    index = docs / "index.html"

    assert Path(generated) == index
    assert index.read_bytes().startswith(doc_module.DOC_GENERATOR_MARKER)
    original_mode = stat.S_IMODE(index.stat().st_mode)
    assert DocGenerator().generate(str(project), str(docs)) == str(index)
    assert stat.S_IMODE(index.stat().st_mode) == original_mode

    foreign_docs = tmp_path / "foreign"
    foreign_docs.mkdir()
    foreign = foreign_docs / "index.html"
    foreign.write_bytes(b"<html>human portal</html>\n")
    assert DocGenerator().generate(str(project), str(foreign_docs)) is None
    assert foreign.read_bytes() == b"<html>human portal</html>\n"

    before_failure = index.read_bytes()
    monkeypatch.setattr(
        doc_module,
        "_render_template",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("render failed")),
    )
    assert DocGenerator().generate(str(project), str(docs)) is None
    assert index.read_bytes() == before_failure
    assert not list(tmp_path.rglob(".*.tmp"))
