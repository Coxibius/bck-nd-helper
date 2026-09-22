"""MCP filesystem authorization, isolation, and safe shutdown."""

import inspect
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import bck_nd_hlpr.cli.mcp_server as mcp_server_module
from bck_nd_hlpr.cli.mcp_server import (
    _safe_mcp_project_root,
    get_requirements_summary,
)
from bck_nd_hlpr.core.requirements import RequirementsParser
from bck_nd_hlpr.core.sanitizer import REDACTION_MARKER


class TestMCPProjectBoundary:
    @pytest.mark.parametrize("configured", [None, "", "   "])
    def test_missing_or_empty_roots_fail_closed(
        self,
        tmp_path,
        monkeypatch,
        configured,
    ):
        monkeypatch.chdir(tmp_path)
        if configured is None:
            monkeypatch.delenv("BCK_ND_MCP_ALLOWED_ROOTS", raising=False)
        else:
            monkeypatch.setenv("BCK_ND_MCP_ALLOWED_ROOTS", configured)

        with pytest.raises(mcp_server_module.MCPProjectAccessError) as error:
            _safe_mcp_project_root(".")

        assert str(error.value) == mcp_server_module.MCP_ACCESS_DENIED
        assert str(tmp_path) not in str(error.value)

    def test_relative_or_partially_invalid_root_list_fails_closed(
        self,
        tmp_path,
        monkeypatch,
    ):
        valid = tmp_path / "valid"
        valid.mkdir()

        for configured in (
            "relative-root",
            os.pathsep.join((str(valid), str(tmp_path / "missing"))),
        ):
            monkeypatch.setenv("BCK_ND_MCP_ALLOWED_ROOTS", configured)
            with pytest.raises(mcp_server_module.MCPProjectAccessError):
                _safe_mcp_project_root(str(valid))

    def test_explicit_roots_allow_both_and_reject_external_without_leak(
        self,
        tmp_path,
        monkeypatch,
    ):
        first = tmp_path / "first"
        second = tmp_path / "second"
        outside = tmp_path / "outside-secret-project"
        for directory in (first, second, outside):
            directory.mkdir()
        monkeypatch.setenv(
            "BCK_ND_MCP_ALLOWED_ROOTS",
            os.pathsep.join((str(first), str(second))),
        )

        assert _safe_mcp_project_root(str(first)) == first.resolve()
        assert _safe_mcp_project_root(str(second)) == second.resolve()
        result = get_requirements_summary(str(outside))

        assert result == mcp_server_module.MCP_ACCESS_DENIED
        assert str(outside) not in result
        assert "outside-secret-project" not in result

    def test_single_root_resolves_relative_projects_without_using_cwd(
        self,
        tmp_path,
        monkeypatch,
    ):
        allowed = tmp_path / "allowed"
        api = allowed / "apps" / "api"
        literal_tilde = allowed / "~"
        unrelated_cwd = tmp_path / "unrelated-cwd"
        api.mkdir(parents=True)
        literal_tilde.mkdir()
        unrelated_cwd.mkdir()
        monkeypatch.chdir(unrelated_cwd)
        monkeypatch.setenv("BCK_ND_MCP_ALLOWED_ROOTS", str(allowed))

        assert _safe_mcp_project_root(".") == allowed.resolve()
        assert _safe_mcp_project_root("./") == allowed.resolve()
        assert _safe_mcp_project_root("apps/api") == api.resolve()
        assert _safe_mcp_project_root("~") == literal_tilde.resolve()
        assert _safe_mcp_project_root(".") != unrelated_cwd.resolve()

    def test_multiple_roots_require_an_absolute_project_path(
        self,
        tmp_path,
        monkeypatch,
    ):
        first = tmp_path / "first"
        second = tmp_path / "second"
        outside = tmp_path / "outside-secret"
        (first / "apps" / "api").mkdir(parents=True)
        second.mkdir()
        outside.mkdir()
        monkeypatch.chdir(first)
        monkeypatch.setenv(
            "BCK_ND_MCP_ALLOWED_ROOTS",
            os.pathsep.join((str(first), str(second))),
        )

        for relative in (".", "./", "apps/api"):
            with pytest.raises(mcp_server_module.MCPProjectAccessError) as error:
                _safe_mcp_project_root(relative)
            assert str(error.value) == mcp_server_module.MCP_ACCESS_DENIED
            if relative == "apps/api":
                assert relative not in str(error.value)
            assert str(first) not in str(error.value)
            assert str(second) not in str(error.value)

        assert _safe_mcp_project_root(str(first.resolve())) == first.resolve()
        assert _safe_mcp_project_root(str(second.resolve())) == second.resolve()
        with pytest.raises(mcp_server_module.MCPProjectAccessError) as error:
            _safe_mcp_project_root(str(outside.resolve()))
        assert str(error.value) == mcp_server_module.MCP_ACCESS_DENIED
        assert str(outside) not in str(error.value)

    def test_default_filesystem_tool_uses_the_only_root_from_foreign_cwd(
        self,
        tmp_path,
        monkeypatch,
    ):
        allowed = tmp_path / "allowed"
        unrelated_cwd = tmp_path / "unrelated-cwd"
        allowed.mkdir()
        unrelated_cwd.mkdir()
        monkeypatch.chdir(unrelated_cwd)
        monkeypatch.setenv("BCK_ND_MCP_ALLOWED_ROOTS", str(allowed))

        result = get_requirements_summary()

        assert result.startswith("No requirements found")
        assert result != mcp_server_module.MCP_ACCESS_DENIED
        assert str(allowed) not in result
        assert str(unrelated_cwd) not in result

    @pytest.mark.parametrize(
        "unsafe",
        [
            "../outside",
            "/outside/project",
            "C:/outside/project",
            r"\\server\share\project",
        ],
    )
    def test_portable_external_syntax_is_rejected_lexically(
        self,
        tmp_path,
        monkeypatch,
        unsafe,
    ):
        monkeypatch.setenv("BCK_ND_MCP_ALLOWED_ROOTS", str(tmp_path))

        with pytest.raises(mcp_server_module.MCPProjectAccessError) as error:
            _safe_mcp_project_root(unsafe)

        assert unsafe not in str(error.value)

    def test_canonical_escape_is_rejected(self, tmp_path, monkeypatch):
        allowed = tmp_path / "allowed"
        child = allowed / "child"
        outside = tmp_path / "outside"
        child.mkdir(parents=True)
        outside.mkdir()
        monkeypatch.setenv("BCK_ND_MCP_ALLOWED_ROOTS", str(allowed))
        real_resolve = Path.resolve

        def escaped_resolve(path, strict=False):
            if path == child:
                return real_resolve(outside, strict=strict)
            return real_resolve(path, strict=strict)

        monkeypatch.setattr(Path, "resolve", escaped_resolve)

        with pytest.raises(mcp_server_module.MCPProjectAccessError):
            _safe_mcp_project_root(str(child))

    def test_nonexistent_configured_root_rejects_without_path_leak(
        self,
        tmp_path,
        monkeypatch,
    ):
        missing = tmp_path / "missing-secret-root"
        monkeypatch.setenv("BCK_ND_MCP_ALLOWED_ROOTS", str(missing))

        with pytest.raises(mcp_server_module.MCPProjectAccessError) as error:
            _safe_mcp_project_root(str(tmp_path))

        assert str(error.value) == mcp_server_module.MCP_ACCESS_DENIED
        assert "missing-secret-root" not in str(error.value)

    @pytest.mark.parametrize(
        "unsafe",
        ["../outside", "C:/outside/file.py", r"\\server\share\file.py"],
    )
    def test_secondary_paths_reject_portable_external_syntax(
        self,
        tmp_path,
        unsafe,
    ):
        with pytest.raises(mcp_server_module.MCPProjectAccessError) as error:
            mcp_server_module._safe_mcp_child_path(tmp_path, unsafe)

        assert str(error.value) == mcp_server_module.MCP_ACCESS_DENIED
        assert unsafe not in str(error.value)

    def test_secondary_paths_allow_existing_internal_files(self, tmp_path):
        source = tmp_path / "src" / "app.py"
        source.parent.mkdir()
        source.write_text("VALUE = 1\n", encoding="utf-8")

        assert mcp_server_module._safe_mcp_child_path(
            tmp_path,
            "src/app.py",
        ) == source.resolve()
        assert mcp_server_module._safe_mcp_child_path(
            tmp_path,
            str(source.resolve()),
        ) == source.resolve()

    def test_secondary_path_symlink_escape_is_rejected(
        self,
        tmp_path,
        monkeypatch,
    ):
        project = tmp_path / "project"
        outside = tmp_path / "outside"
        project.mkdir()
        outside.mkdir()
        (outside / "secret.py").write_text("SECRET = True\n", encoding="utf-8")
        link = project / "linked"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (NotImplementedError, OSError):
            escaped = link / "secret.py"
            real_resolve = Path.resolve

            def escaped_resolve(path, strict=False):
                if path == escaped:
                    return real_resolve(outside / "secret.py", strict=True)
                return real_resolve(path, strict=strict)

            monkeypatch.setattr(Path, "resolve", escaped_resolve)

        with pytest.raises(mcp_server_module.MCPProjectAccessError):
            mcp_server_module._safe_mcp_child_path(
                project,
                "linked/secret.py",
            )


FILESYSTEM_TOOL_PARAMETERS = {
    "scan_project": "path",
    "get_project_tree": "path",
    "get_uml_diagram": "path",
    "get_er_diagram": "path",
    "get_routes_diagram": "path",
    "get_infra_diagram": "path",
    "scan_todos": "path",
    "audit_security": "path",
    "analyze_impact": "path",
    "generate_ai_context": "path",
    "generate_html_docs": "path",
    "explain_architecture_with_ai": "path",
    "get_traceability_diagram": "path",
    "init_ci": "path",
    "get_project_health": "root_path",
    "get_guided_onboarding": "root_path",
    "export_data_dictionary": "root_path",
    "get_impact_radius": "root_path",
    "get_api_contract_map": "root_path",
    "get_asg_graph": "root_path",
    "get_architecture_summary": "root_path",
    "get_product_context": "project_path",
    "get_requirements_summary": "project_path",
}

EXPECTED_TOOL_SIGNATURES = {
    "scan_project": ("path", "depth"),
    "get_project_tree": ("path", "depth"),
    "get_uml_diagram": ("path", "depth"),
    "get_er_diagram": ("path", "depth"),
    "get_routes_diagram": ("path", "depth"),
    "get_infra_diagram": ("path",),
    "scan_todos": ("path", "depth"),
    "audit_security": ("path", "depth"),
    "analyze_impact": ("path",),
    "generate_ai_context": ("path", "depth", "output"),
    "generate_html_docs": ("path", "output"),
    "render_flow_diagram": ("layout",),
    "explain_architecture_with_ai": ("path", "depth", "style", "provider"),
    "get_traceability_diagram": ("path", "depth"),
    "init_ci": ("path",),
    "get_project_health": ("root_path", "depth"),
    "get_guided_onboarding": ("root_path", "depth"),
    "export_data_dictionary": ("root_path", "format"),
    "get_impact_radius": ("root_path", "changed_file", "depth"),
    "get_api_contract_map": ("root_path", "depth"),
    "get_asg_graph": ("root_path", "depth"),
    "get_architecture_summary": ("root_path", "depth"),
    "get_product_context": ("project_path", "target_path", "max_chars"),
    "get_requirements_summary": ("project_path",),
}


def _write_mcp_requirement(project: Path, story_id: str) -> None:
    directory = project / ".bck-nd" / "requirements"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{story_id}.json").write_text(
        json.dumps(
            {
                "story": {
                    "id": story_id,
                    "status": "TODO",
                    "title": f"Story {story_id}",
                    "role": "user",
                    "want": f"complete {story_id}",
                    "benefit": "receive value",
                }
            }
        ),
        encoding="utf-8",
    )


class TestUniversalMCPFilesystemBoundary:
    @pytest.mark.parametrize(
        ("tool_name", "project_parameter"),
        FILESYSTEM_TOOL_PARAMETERS.items(),
    )
    def test_every_filesystem_tool_authorizes_before_engine_access(
        self,
        monkeypatch,
        tool_name,
        project_parameter,
    ):
        calls = []

        def deny(project_path):
            calls.append(project_path)
            raise mcp_server_module.MCPProjectAccessError(
                mcp_server_module.MCP_ACCESS_DENIED
            )

        monkeypatch.setattr(mcp_server_module, "_safe_mcp_project_root", deny)
        tool = getattr(mcp_server_module, tool_name)

        result = tool(**{project_parameter: "outside-secret-project"})

        assert result == mcp_server_module.MCP_ACCESS_DENIED
        assert calls == ["outside-secret-project"]
        assert "outside-secret-project" not in result

    def test_tool_registry_keeps_23_filesystem_tools_and_one_text_tool(self):
        registered = set(mcp_server_module.mcp._tool_manager._tools)

        assert len(registered) == 24
        assert set(FILESYSTEM_TOOL_PARAMETERS) <= registered
        assert registered - set(FILESYSTEM_TOOL_PARAMETERS) == {
            "render_flow_diagram"
        }

    def test_all_tool_names_and_public_signatures_are_unchanged(self):
        registered = set(mcp_server_module.mcp._tool_manager._tools)

        assert registered == set(EXPECTED_TOOL_SIGNATURES)
        for tool_name, expected_parameters in EXPECTED_TOOL_SIGNATURES.items():
            tool = getattr(mcp_server_module, tool_name)
            assert tuple(inspect.signature(tool).parameters) == expected_parameters

    def test_final_output_boundary_redacts_paths_errors_and_concurrent_streams(
        self,
        tmp_path,
        monkeypatch,
        capsys,
    ):
        secret = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"
        monkeypatch.setenv("BCK_ND_MCP_ALLOWED_ROOTS", str(tmp_path))
        original_stdout = sys.stdout
        original_stderr = sys.stderr

        @mcp_server_module.redirect_stdout_to_stderr
        def successful(path="."):
            print(f"incidental stdout {secret}")
            print(f"incidental stderr {secret}", file=sys.stderr)
            time.sleep(0.01)
            return (
                f"Project: {tmp_path}\n"
                f"token = {secret}\n"
                "```mermaid\ngraph LR\n  A --> B\n```"
            )

        @mcp_server_module.redirect_stdout_to_stderr
        def failing(path="."):
            print(f"failure output {secret}")
            raise RuntimeError(f"{secret} at {tmp_path}\nTraceback: private")

        with ThreadPoolExecutor(max_workers=2) as pool:
            outputs = list(pool.map(lambda _index: successful(), range(2)))
        failure = failing()
        captured = capsys.readouterr()

        assert captured.out == ""
        assert captured.err == ""
        assert sys.stdout is original_stdout
        assert sys.stderr is original_stderr
        assert outputs[0] == outputs[1]
        assert all(REDACTION_MARKER in output for output in outputs)
        assert all(secret not in output for output in outputs)
        assert all(str(tmp_path) not in output for output in outputs)
        assert all("```mermaid\ngraph LR\n  A --> B\n```" in output for output in outputs)
        assert failure == mcp_server_module.MCP_TOOL_ERROR
        assert secret not in failure
        assert str(tmp_path) not in failure
        assert "Traceback" not in failure

    @pytest.mark.parametrize("invalid_depth", [True, -1, 21, "3", 1.5])
    def test_mcp_argument_boundary_rejects_invalid_depth_format_and_layout(
        self,
        tmp_path,
        monkeypatch,
        invalid_depth,
    ):
        monkeypatch.setenv("BCK_ND_MCP_ALLOWED_ROOTS", str(tmp_path))
        monkeypatch.setattr(
            mcp_server_module,
            "generate_project_tree",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("engine should not run")
            ),
        )

        assert mcp_server_module.get_project_tree(depth=invalid_depth) == (
            mcp_server_module.MCP_ARGUMENT_ERROR
        )
        assert mcp_server_module.export_data_dictionary(format="xml") == (
            mcp_server_module.MCP_ARGUMENT_ERROR
        )
        assert mcp_server_module.render_flow_diagram(
            "x" * (mcp_server_module.MAX_MCP_LAYOUT_CHARS + 1)
        ) == mcp_server_module.MCP_ARGUMENT_ERROR

    def test_requirements_summary_reports_scope_without_merging_or_reloading_current(
        self,
        tmp_path,
        monkeypatch,
    ):
        outer = tmp_path / "outer"
        inner = outer / "Sistemas1-Equipo321-VidaSalud"
        for story_id in ("HU05", "HU06"):
            _write_mcp_requirement(outer, story_id)
        for story_id in ("HU01", "HU02", "HU03", "HU04", "HU05", "HU06", "HU07"):
            _write_mcp_requirement(inner, story_id)
        monkeypatch.setenv("BCK_ND_MCP_ALLOWED_ROOTS", str(outer))
        real_load = RequirementsParser.load_collection
        calls = []

        def counted_load(project_path):
            calls.append(Path(project_path).resolve())
            return real_load(project_path)

        monkeypatch.setattr(RequirementsParser, "load_collection", counted_load)

        outer_result = get_requirements_summary()
        outer_context = outer_result.split("<requirements_context>", 1)[1]

        assert outer_result.startswith("<requirements_scope>")
        assert outer_result.index("<requirements_scope>") < outer_result.index(
            "<requirements_context>"
        )
        assert "Sistemas1-Equipo321-VidaSalud" in outer_result
        assert "HU05" in outer_result and "HU06" in outer_result
        assert "HU01" not in outer_context and "HU07" not in outer_context
        assert calls.count(outer.resolve()) == 1
        assert str(outer.resolve()) not in outer_result

        calls.clear()
        inner_result = get_requirements_summary(project_path=str(inner.resolve()))

        assert "<requirements_scope>" not in inner_result
        assert "<requirements_context>" not in inner_result
        for story_id in ("HU01", "HU02", "HU03", "HU04", "HU05", "HU06", "HU07"):
            assert story_id in inner_result
        assert calls == [inner.resolve()]
        assert str(inner.resolve()) not in inner_result

    def test_text_only_tool_does_not_require_filesystem_authorization(
        self,
        monkeypatch,
    ):
        class FakeRouter:
            def process(self, layout):
                print(f"rendered: {layout}")

        def unexpected_authorization(project_path):
            raise AssertionError(f"unexpected filesystem access: {project_path}")

        monkeypatch.setattr(mcp_server_module, "Router", FakeRouter)
        monkeypatch.setattr(
            mcp_server_module,
            "_safe_mcp_project_root",
            unexpected_authorization,
        )

        assert mcp_server_module.render_flow_diagram("Client -> API") == (
            "rendered: Client -> API\n"
        )

    def test_generate_ai_context_uses_authorized_project_for_relative_output(
        self,
        tmp_path,
        monkeypatch,
    ):
        project = tmp_path / "project"
        cwd = tmp_path / "cwd"
        project.mkdir()
        cwd.mkdir()
        monkeypatch.chdir(cwd)
        monkeypatch.setenv("BCK_ND_MCP_ALLOWED_ROOTS", str(project))
        observed = []

        class FakeDumper:
            def __init__(self, path, depth):
                observed.append(Path(path))

            def build(self):
                return "safe context"

            def get_uml_diagram(self):
                return None

            def get_er_diagram(self):
                return None

        import bck_nd_hlpr.core.context_dumper as context_dumper_module

        monkeypatch.setattr(context_dumper_module, "ContextDumper", FakeDumper)
        result = mcp_server_module.generate_ai_context(
            path=str(project),
            output="ai_context.txt",
        )

        assert observed == [project.resolve()]
        assert (project / "ai_context.txt").read_text(encoding="utf-8") == (
            "<!-- bck-nd-hlpr generated AI context -->\nsafe context"
        )
        assert not (cwd / "ai_context.txt").exists()
        assert "File: ai_context.txt" in result
        assert str(project.resolve()) not in result

    def test_ai_context_rejects_arbitrary_and_foreign_targets_without_changes(
        self,
        tmp_path,
        monkeypatch,
    ):
        project = tmp_path / "project"
        source = project / "src" / "main.py"
        project.mkdir()
        source.parent.mkdir()
        source.write_bytes(b"print('preserve source')\n")
        foreign_context = project / "ai_context.txt"
        foreign_context.write_bytes(b"human-authored context\n")
        monkeypatch.setenv("BCK_ND_MCP_ALLOWED_ROOTS", str(project))

        import bck_nd_hlpr.core.context_dumper as context_dumper_module

        class ForbiddenDumper:
            def __init__(self, *args, **kwargs):
                raise AssertionError("unsafe output must be rejected before scanning")

        monkeypatch.setattr(context_dumper_module, "ContextDumper", ForbiddenDumper)

        source_result = mcp_server_module.generate_ai_context(
            str(project),
            output="src/main.py",
        )
        foreign_result = mcp_server_module.generate_ai_context(
            str(project),
            output="ai_context.txt",
        )

        assert source_result == mcp_server_module.MCP_ARTIFACT_WRITE_DENIED
        assert foreign_result == mcp_server_module.MCP_ARTIFACT_WRITE_DENIED
        assert source.read_bytes() == b"print('preserve source')\n"
        assert foreign_context.read_bytes() == b"human-authored context\n"
        assert str(project) not in source_result + foreign_result

    def test_generated_ai_context_can_be_atomically_updated(self, tmp_path, monkeypatch):
        project = tmp_path / "project"
        output_dir = project / ".bck-nd" / "generated" / "contexts"
        output_dir.mkdir(parents=True)
        output = output_dir / "focused.txt"
        output.write_text(
            "<!-- bck-nd-hlpr previous context -->\nold",
            encoding="utf-8",
        )
        monkeypatch.setenv("BCK_ND_MCP_ALLOWED_ROOTS", str(project))

        import bck_nd_hlpr.core.context_dumper as context_dumper_module

        class FakeDumper:
            def __init__(self, path, depth):
                pass

            def build(self):
                return "new context"

            def get_uml_diagram(self):
                return None

            def get_er_diagram(self):
                return None

        monkeypatch.setattr(context_dumper_module, "ContextDumper", FakeDumper)

        result = mcp_server_module.generate_ai_context(
            str(project),
            output=".bck-nd/generated/contexts/focused.txt",
        )

        assert "File: .bck-nd/generated/contexts/focused.txt" in result
        assert output.read_text(encoding="utf-8") == (
            "<!-- bck-nd-hlpr generated AI context -->\nnew context"
        )
        assert not list(output_dir.glob(".*.tmp"))

    def test_ai_context_rejects_reparse_target_deterministically(
        self,
        tmp_path,
        monkeypatch,
    ):
        project = tmp_path / "project"
        project.mkdir()
        target = project / "ai_context.txt"
        target.write_text(
            "<!-- bck-nd-hlpr previous context -->\nold",
            encoding="utf-8",
        )
        monkeypatch.setenv("BCK_ND_MCP_ALLOWED_ROOTS", str(project))
        import bck_nd_hlpr.core.utils.secure_write as secure_write_module

        monkeypatch.setattr(
            secure_write_module,
            "_is_link_or_reparse",
            lambda _stat: True,
        )

        result = mcp_server_module.generate_ai_context(str(project))

        assert result == mcp_server_module.MCP_ARTIFACT_WRITE_DENIED
        assert target.read_text(encoding="utf-8").endswith("old")

    def test_generate_ai_context_rejects_external_project_and_output(
        self,
        tmp_path,
        monkeypatch,
    ):
        allowed = tmp_path / "allowed"
        outside = tmp_path / "outside-secret-project"
        allowed.mkdir()
        outside.mkdir()
        secret = "external-product-secret"
        product = outside / ".bck-nd" / "product"
        product.mkdir(parents=True)
        (product / "PRD.md").write_text(secret, encoding="utf-8")
        monkeypatch.setenv("BCK_ND_MCP_ALLOWED_ROOTS", str(allowed))

        denied_project = mcp_server_module.generate_ai_context(str(outside))
        denied_output = mcp_server_module.generate_ai_context(
            str(allowed),
            output=str(outside / "context.txt"),
        )

        assert denied_project == mcp_server_module.MCP_ACCESS_DENIED
        assert denied_output == mcp_server_module.MCP_ARTIFACT_WRITE_DENIED
        assert secret not in denied_project
        assert not (outside / "context.txt").exists()

    def test_html_docs_impact_and_ai_provider_stop_after_denial(
        self,
        tmp_path,
        monkeypatch,
    ):
        allowed = tmp_path / "allowed"
        outside = tmp_path / "outside-secret-project"
        allowed.mkdir()
        outside.mkdir()
        changed = outside / "secret.py"
        changed.write_text("SECRET = True\n", encoding="utf-8")
        monkeypatch.setenv("BCK_ND_MCP_ALLOWED_ROOTS", str(allowed))

        class ForbiddenEngine:
            def __init__(self, *args, **kwargs):
                raise AssertionError("engine must not be constructed after denial")

        monkeypatch.setattr(mcp_server_module, "DocGenerator", ForbiddenEngine)
        monkeypatch.setattr(mcp_server_module, "ProjectScanner", ForbiddenEngine)

        docs = mcp_server_module.generate_html_docs(
            str(allowed),
            output=str(outside / "docs"),
        )
        impact = mcp_server_module.get_impact_radius(
            str(allowed),
            changed_file=str(changed),
        )
        ai_result = mcp_server_module.explain_architecture_with_ai(str(outside))

        assert docs == mcp_server_module.MCP_ARTIFACT_WRITE_DENIED
        assert impact == mcp_server_module.MCP_ACCESS_DENIED
        assert ai_result == mcp_server_module.MCP_ACCESS_DENIED
        assert not (outside / "docs").exists()

    def test_html_docs_preserves_foreign_portal_and_cleans_staging(
        self,
        tmp_path,
        monkeypatch,
    ):
        project = tmp_path / "project"
        docs = project / "docs"
        docs.mkdir(parents=True)
        index = docs / "index.html"
        index.write_bytes(b"<html>human portal</html>")
        monkeypatch.setenv("BCK_ND_MCP_ALLOWED_ROOTS", str(project))
        staged = []

        class FakeDocGenerator:
            def generate(self, root_path, output_dir):
                staged.append(Path(output_dir))
                generated = Path(output_dir) / "index.html"
                generated.parent.mkdir(parents=True, exist_ok=True)
                generated.write_text("<html>generated</html>", encoding="utf-8")
                return str(generated)

        monkeypatch.setattr(mcp_server_module, "DocGenerator", FakeDocGenerator)

        result = mcp_server_module.generate_html_docs(str(project), output="docs")

        assert result == mcp_server_module.MCP_ARTIFACT_WRITE_DENIED
        assert index.read_bytes() == b"<html>human portal</html>"
        assert all(not directory.exists() for directory in staged)
        assert not list(docs.glob(".*.tmp"))

    def test_html_docs_updates_marked_portal_from_staging(self, tmp_path, monkeypatch):
        project = tmp_path / "project"
        docs = project / ".bck-nd" / "generated" / "docs"
        docs.mkdir(parents=True)
        index = docs / "index.html"
        index.write_text(
            "<!-- bck-nd-hlpr generated documentation -->\n<html>old</html>",
            encoding="utf-8",
        )
        monkeypatch.setenv("BCK_ND_MCP_ALLOWED_ROOTS", str(project))
        staged = []

        class FakeDocGenerator:
            def generate(self, root_path, output_dir):
                staged.append(Path(output_dir))
                generated = Path(output_dir) / "index.html"
                generated.parent.mkdir(parents=True, exist_ok=True)
                generated.write_text("<html>new</html>", encoding="utf-8")
                return str(generated)

        monkeypatch.setattr(mcp_server_module, "DocGenerator", FakeDocGenerator)

        result = mcp_server_module.generate_html_docs(
            str(project),
            output=".bck-nd/generated/docs",
        )

        assert "File: .bck-nd/generated/docs/index.html" in result
        assert index.read_text(encoding="utf-8") == (
            "<!-- bck-nd-hlpr generated documentation -->\n<html>new</html>"
        )
        assert all(not directory.exists() for directory in staged)
        assert not list(docs.glob(".*.tmp"))

    def test_html_docs_rejects_reparse_destination_without_touching_external(
        self,
        tmp_path,
        monkeypatch,
    ):
        project = tmp_path / "project"
        external = tmp_path / "external"
        project.mkdir()
        external.mkdir()
        external_index = external / "index.html"
        external_index.write_bytes(b"external portal")
        monkeypatch.setenv("BCK_ND_MCP_ALLOWED_ROOTS", str(project))
        import bck_nd_hlpr.core.utils.secure_write as secure_write_module

        monkeypatch.setattr(
            secure_write_module,
            "_is_link_or_reparse",
            lambda _stat: True,
        )

        result = mcp_server_module.generate_html_docs(str(project), output="docs")

        assert result == mcp_server_module.MCP_ARTIFACT_WRITE_DENIED
        assert external_index.read_bytes() == b"external portal"



class TestMCPServerShutdown:
    @pytest.fixture(autouse=True)
    def explicit_allowed_root(self, tmp_path, monkeypatch):
        monkeypatch.setenv(
            "BCK_ND_MCP_ALLOWED_ROOTS",
            str(tmp_path.resolve()),
        )
    def test_manual_stdio_interrupt_exits_cleanly(self, monkeypatch):
        """Ctrl+C while manually running the stdio server should not leak a traceback."""
        class NonInteractiveInput:
            @staticmethod
            def isatty():
                return False

        def interrupted_run(*, transport):
            assert transport == "stdio"
            raise KeyboardInterrupt

        monkeypatch.setattr(mcp_server_module.sys, "argv", ["bck-nd-mcp"])
        monkeypatch.setattr(mcp_server_module.sys, "stdin", NonInteractiveInput())
        monkeypatch.setattr(mcp_server_module.mcp, "run", interrupted_run)

        assert mcp_server_module.main() is None
