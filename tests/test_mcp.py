"""
Unit tests for Pillar D: Client & MCP Integration (get_asg_graph, get_architecture_summary)
and the --install auto-installer for Claude Desktop, Cursor, and Antigravity.
"""

import json
import pytest
from pathlib import Path

import bck_nd_hlpr.cli.mcp_server as mcp_server_module
from bck_nd_hlpr.cli.mcp_server import (
    get_architecture_summary,
    get_asg_graph,
    get_requirements_summary,
    _find_antigravity_executable,
    _get_antigravity_config_path,
    _install_claude_desktop,
    _install_mcp_clients,
)
from bck_nd_hlpr.cli.formatters import format_asg_json
from bck_nd_hlpr.core.asg import ASGGraph, ASGNode, NodeKind, ASGEdge, EdgeKind


class TestMCPTools:
    @pytest.fixture
    def mock_project(self, tmp_path):
        app_file = tmp_path / "app.py"
        app_file.write_text(
            "from flask import Flask\n"
            "app = Flask(__name__)\n"
            "@app.route('/api/users')\n"
            "def get_users(): return 'users'\n",
            encoding="utf-8"
        )
        return tmp_path

    def test_get_asg_graph_mcp_tool(self, mock_project):
        raw_json = get_asg_graph(root_path=str(mock_project))
        assert isinstance(raw_json, str)

        data = json.loads(raw_json)
        assert "nodes" in data
        assert "edges" in data
        assert isinstance(data["nodes"], list)
        assert isinstance(data["edges"], list)

    def test_get_architecture_summary_mcp_tool(self, mock_project):
        summary = get_architecture_summary(root_path=str(mock_project))
        assert isinstance(summary, str)
        assert "Architectural Summary" in summary
        assert "Framework:" in summary
        assert "Provider Metadata:" in summary
        assert "Provider Name:" in summary

    def test_format_asg_json_formatter(self):
        graph = ASGGraph()
        node = ASGNode(id="TestNode", name="TestNode", kind=NodeKind.CLASS)
        graph.add_node(node)

        json_out = format_asg_json(graph)
        data = json.loads(json_out)
        assert len(data["nodes"]) == 1
        assert data["nodes"][0]["id"] == "TestNode"

        # None input fallback
        empty_out = format_asg_json(None)
        assert json.loads(empty_out) == {"nodes": [], "edges": []}

    def test_get_requirements_summary_with_specs(self, tmp_path):
        req_dir = tmp_path / ".bck-nd" / "requirements"
        req_dir.mkdir(parents=True)

        hu01_content = {
            "story": {
                "id": "HU01",
                "title": "Registrar cliente",
                "role": "Agente de campo",
                "want": "Registrar un nuevo cliente",
                "benefit": "Contar con información centralizada",
                "status": "TODO",
            },
            "business_rules": [
                {"id": "BR01", "description": "El documento debe ser único."},
            ],
            "acceptance_criteria": [
                {
                    "id": "AC01",
                    "given": "datos válidos",
                    "when": "submit",
                    "then": "cliente registrado",
                }
            ],
        }
        (req_dir / "HU01.json").write_text(json.dumps(hu01_content), encoding="utf-8")

        result = get_requirements_summary(project_path=str(tmp_path))
        assert "Requirements Summary" in result
        assert "HU01" in result
        assert "Registrar cliente" in result
        assert "Agente de campo" in result
        assert "BR01" in result
        assert "AC01" in result

    def test_get_requirements_summary_empty(self, tmp_path):
        result = get_requirements_summary(project_path=str(tmp_path))
        assert "No requirements found under .bck-nd/requirements/" in result


class TestClipboardIntegration:
    def test_prompt_copy_flag_copies_generated_context(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner
        import bck_nd_hlpr.cli.cli as cli_module

        (tmp_path / "main.py").write_text("print('hello')", encoding="utf-8")
        output_file = tmp_path / "context.txt"
        copied = []
        monkeypatch.setattr(
            cli_module,
            "copy_to_clipboard",
            lambda text: copied.append(text) is None,
        )

        result = CliRunner().invoke(
            cli_module.app,
            [
                "prompt",
                str(tmp_path),
                "--tree",
                "--copy",
                "--output",
                str(output_file),
            ],
        )

        assert result.exit_code == 0, result.exception
        assert copied == [output_file.read_text(encoding="utf-8")]
        assert "Context copied to clipboard" in result.stdout


class TestMCPInstaller:
    """Tests for the multi-client --install auto-installer."""

    def test_install_creates_new_config(self, tmp_path):
        """--install should create a fresh config file when none exists."""
        config_path = tmp_path / "Claude" / "claude_desktop_config.json"
        assert not config_path.exists()

        result = _install_claude_desktop(config_path=config_path)

        assert config_path.is_file()
        assert "✅" in result

        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert data == {
            "mcpServers": {
                "bck-nd-mcp": {"command": "bck-nd-mcp"}
            }
        }

    def test_install_updates_existing_config(self, tmp_path):
        """--install should merge into an existing config, preserving other servers."""
        config_path = tmp_path / "claude_desktop_config.json"
        existing = {
            "mcpServers": {
                "other-server": {"command": "other-cmd", "args": ["--flag"]}
            },
            "someOtherKey": True,
        }
        config_path.write_text(json.dumps(existing), encoding="utf-8")

        _install_claude_desktop(config_path=config_path)

        data = json.loads(config_path.read_text(encoding="utf-8"))
        # Original server preserved
        assert data["mcpServers"]["other-server"] == {"command": "other-cmd", "args": ["--flag"]}
        # New server added
        assert data["mcpServers"]["bck-nd-mcp"] == {"command": "bck-nd-mcp"}
        # Other top-level keys preserved
        assert data["someOtherKey"] is True

    def test_install_handles_corrupt_json(self, tmp_path):
        """--install should recover gracefully from a corrupt config file."""
        config_path = tmp_path / "claude_desktop_config.json"
        config_path.write_text("{invalid json!!", encoding="utf-8")

        _install_claude_desktop(config_path=config_path)

        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert data["mcpServers"]["bck-nd-mcp"] == {"command": "bck-nd-mcp"}
        assert config_path.with_name("claude_desktop_config.json.bak").read_text(
            encoding="utf-8"
        ) == "{invalid json!!"

    def test_install_handles_non_dict_json(self, tmp_path):
        """--install should handle a config file that contains non-dict JSON (e.g. a list)."""
        config_path = tmp_path / "claude_desktop_config.json"
        config_path.write_text("[1, 2, 3]", encoding="utf-8")

        _install_claude_desktop(config_path=config_path)

        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        assert data["mcpServers"]["bck-nd-mcp"] == {"command": "bck-nd-mcp"}

    def test_install_overwrites_stale_entry(self, tmp_path):
        """--install should update an existing bck-nd-mcp entry if it has stale config."""
        config_path = tmp_path / "claude_desktop_config.json"
        existing = {
            "mcpServers": {
                "bck-nd-mcp": {"command": "old-command", "args": ["--old"]}
            }
        }
        config_path.write_text(json.dumps(existing), encoding="utf-8")

        _install_claude_desktop(config_path=config_path)

        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert data["mcpServers"]["bck-nd-mcp"] == {"command": "bck-nd-mcp"}

    def test_install_removes_legacy_entries(self, tmp_path):
        """--install should automatically remove legacy server keys (backend-helper, bck_nd_hlpr)."""
        config_path = tmp_path / "claude_desktop_config.json"
        existing = {
            "mcpServers": {
                "backend-helper": {"command": "backend-helper"},
                "bck_nd_hlpr": {"command": "python", "args": ["-m", "bck_nd_hlpr"]},
                "unrelated-server": {"command": "unrelated-tool"},
            }
        }
        config_path.write_text(json.dumps(existing), encoding="utf-8")

        _install_claude_desktop(config_path=config_path)

        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert "backend-helper" not in data["mcpServers"]
        assert "bck_nd_hlpr" not in data["mcpServers"]
        assert data["mcpServers"]["unrelated-server"] == {"command": "unrelated-tool"}
        assert data["mcpServers"]["bck-nd-mcp"] == {"command": "bck-nd-mcp"}

    def test_install_updates_cursor_config(self, tmp_path):
        """--install should create/update Cursor MCP config when path is provided."""
        cursor_path = tmp_path / ".cursor" / "mcp.json"
        claude_path = tmp_path / "Claude" / "claude_desktop_config.json"

        result = _install_claude_desktop(config_path=claude_path, cursor_config_path=cursor_path)

        assert cursor_path.is_file()
        assert claude_path.is_file()
        assert "Cursor configured" in result

        data = json.loads(cursor_path.read_text(encoding="utf-8"))
        assert data == {
            "mcpServers": {
                "bck-nd-mcp": {"command": "bck-nd-mcp"}
            }
        }

    def test_install_merges_cursor_config_preserving_other_servers(self, tmp_path):
        """--install should merge Cursor config, removing legacy keys and keeping other servers."""
        cursor_path = tmp_path / ".cursor" / "mcp.json"
        claude_path = tmp_path / "Claude" / "claude_desktop_config.json"

        cursor_path.parent.mkdir(parents=True, exist_ok=True)
        existing = {
            "mcpServers": {
                "custom-tool": {"command": "custom-binary"},
                "backend-helper": {"command": "legacy-cmd"},
            },
            "customSettings": {"enabled": True},
        }
        cursor_path.write_text(json.dumps(existing), encoding="utf-8")

        _install_claude_desktop(config_path=claude_path, cursor_config_path=cursor_path)

        data = json.loads(cursor_path.read_text(encoding="utf-8"))
        assert "backend-helper" not in data["mcpServers"]
        assert data["mcpServers"]["custom-tool"] == {"command": "custom-binary"}
        assert data["mcpServers"]["bck-nd-mcp"] == {"command": "bck-nd-mcp"}
        assert data["customSettings"] == {"enabled": True}

    def test_install_output_contains_manual_ide_settings(self, tmp_path):
        """--install should output the manual configuration box with server name and command."""
        claude_path = tmp_path / "claude.json"
        result = _install_claude_desktop(config_path=claude_path)

        assert "Claude Desktop" in result
        assert "bck-nd-mcp" in result
        assert "Server Name" in result
        assert "Command" in result

    def test_antigravity_uses_official_global_config_path(self, tmp_path, monkeypatch):
        """Antigravity should use ~/.gemini/config/mcp_config.json."""
        monkeypatch.setattr(mcp_server_module.Path, "home", staticmethod(lambda: tmp_path))

        assert _get_antigravity_config_path() == (
            tmp_path / ".gemini" / "config" / "mcp_config.json"
        )

    def test_finds_current_antigravity_ide_command(self, monkeypatch):
        """The renamed antigravity-ide launcher should be preferred."""
        calls = []

        def fake_which(command):
            calls.append(command)
            if command == "antigravity-ide":
                return "C:/Program Files/Antigravity/bin/antigravity-ide.cmd"
            return None

        monkeypatch.setattr(mcp_server_module.shutil, "which", fake_which)

        assert _find_antigravity_executable().endswith("antigravity-ide.cmd")
        assert calls == ["antigravity-ide"]

    def test_install_updates_antigravity_preserving_other_servers(self, tmp_path):
        """Antigravity installation must leave GitHub and other MCP entries untouched."""
        claude_path = tmp_path / "Claude" / "claude_desktop_config.json"
        antigravity_path = tmp_path / ".gemini" / "config" / "mcp_config.json"
        antigravity_path.parent.mkdir(parents=True)
        existing = {
            "mcpServers": {
                "github-mcp-server": {
                    "command": "docker",
                    "args": ["run", "github-mcp-server"],
                    "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "test-secret"},
                },
                "supabase": {"serverUrl": "https://example.test/mcp"},
            },
            "customSettings": {"enabled": True},
        }
        antigravity_path.write_text(json.dumps(existing), encoding="utf-8")

        result = _install_claude_desktop(
            config_path=claude_path,
            antigravity_config_path=antigravity_path,
        )

        data = json.loads(antigravity_path.read_text(encoding="utf-8"))
        assert data["mcpServers"]["github-mcp-server"] == existing["mcpServers"][
            "github-mcp-server"
        ]
        assert data["mcpServers"]["supabase"] == existing["mcpServers"]["supabase"]
        assert data["customSettings"] == {"enabled": True}
        assert data["mcpServers"]["bck-nd-mcp"] == {
            "command": str(Path(mcp_server_module.sys.executable).resolve()),
            "args": ["-m", "bck_nd_hlpr.cli.mcp_server"],
        }
        assert "Antigravity IDE / CLI configured successfully" in result
        assert antigravity_path.with_name("mcp_config.json.bak").is_file()

    def test_antigravity_install_is_idempotent(self, tmp_path):
        """Repeated installation should update one stable entry without duplicates."""
        antigravity_path = tmp_path / ".gemini" / "config" / "mcp_config.json"

        for _ in range(2):
            _install_claude_desktop(antigravity_config_path=antigravity_path)

        data = json.loads(antigravity_path.read_text(encoding="utf-8"))
        assert list(data["mcpServers"]) == ["bck-nd-mcp"]

    def test_auto_installer_detects_antigravity_without_real_home_writes(
        self,
        tmp_path,
        monkeypatch,
    ):
        """The production no-argument flow should register a detected Antigravity IDE."""
        claude_path = tmp_path / "Claude" / "claude_desktop_config.json"
        antigravity_path = tmp_path / ".gemini" / "config" / "mcp_config.json"
        monkeypatch.setattr(
            mcp_server_module,
            "_get_claude_config_path",
            lambda: claude_path,
        )
        monkeypatch.setattr(mcp_server_module, "_get_cursor_config_paths", lambda: [])
        monkeypatch.setattr(
            mcp_server_module,
            "_get_antigravity_config_path",
            lambda: antigravity_path,
        )
        monkeypatch.setattr(
            mcp_server_module,
            "_find_antigravity_executable",
            lambda: "C:/Antigravity/antigravity-ide.cmd",
        )

        result = _install_mcp_clients()

        assert antigravity_path.is_file()
        assert "detected: C:/Antigravity/antigravity-ide.cmd" in result

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


