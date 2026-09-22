"""MCP client configuration and installation behavior."""

import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

import bck_nd_hlpr.cli.mcp_server as mcp_server_module
from bck_nd_hlpr.cli.mcp_server import (
    MCPConfigError,
    _find_antigravity_executable,
    _get_antigravity_config_path,
    _install_claude_desktop,
    _install_mcp_clients,
    _update_mcp_config_file,
)
from bck_nd_hlpr.core.utils.file_lock import exclusive_file_lock


class TestMCPInstaller:
    """Tests for the multi-client --install auto-installer."""

    @pytest.fixture(autouse=True)
    def explicit_allowed_root(self, tmp_path, monkeypatch):
        monkeypatch.setenv(
            "BCK_ND_MCP_ALLOWED_ROOTS",
            str(tmp_path.resolve()),
        )

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
                "bck-nd-mcp": {
                    "command": "bck-nd-mcp",
                    "env": {
                        "BCK_ND_MCP_ALLOWED_ROOTS": str(tmp_path.resolve())
                    },
                }
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
        assert data["mcpServers"]["bck-nd-mcp"] == {
            "command": "bck-nd-mcp",
            "env": {"BCK_ND_MCP_ALLOWED_ROOTS": str(tmp_path.resolve())},
        }
        # Other top-level keys preserved
        assert data["someOtherKey"] is True
        assert config_path.with_name("claude_desktop_config.json.bak").read_bytes() == (
            json.dumps(existing).encode("utf-8")
        )
        assert not list(tmp_path.glob(".*.tmp"))

    def test_install_handles_corrupt_json(self, tmp_path):
        """--install must reject corrupt JSON without destroying it."""
        config_path = tmp_path / "claude_desktop_config.json"
        original = b"{invalid json!!"
        config_path.write_bytes(original)

        with pytest.raises(MCPConfigError):
            _install_claude_desktop(config_path=config_path)

        assert config_path.read_bytes() == original
        assert not config_path.with_name("claude_desktop_config.json.bak").exists()
        assert not list(tmp_path.glob("*.tmp"))

    def test_install_handles_non_dict_json(self, tmp_path):
        """--install must reject a non-object root without changing it."""
        config_path = tmp_path / "claude_desktop_config.json"
        original = b"[1, 2, 3]"
        config_path.write_bytes(original)

        with pytest.raises(MCPConfigError):
            _install_claude_desktop(config_path=config_path)

        assert config_path.read_bytes() == original
        assert not list(tmp_path.glob("*.tmp"))

    @pytest.mark.parametrize("invalid_servers", [[], "server", None])
    def test_install_rejects_non_object_mcp_servers(
        self,
        tmp_path,
        invalid_servers,
    ):
        config_path = tmp_path / "mcp.json"
        original = json.dumps(
            {"mcpServers": invalid_servers, "secret": "preserve-me"}
        ).encode("utf-8")
        config_path.write_bytes(original)

        with pytest.raises(MCPConfigError):
            _update_mcp_config_file(config_path)

        assert config_path.read_bytes() == original
        assert not list(tmp_path.glob("*.tmp"))

    @pytest.mark.parametrize(
        "original",
        [
            b'{"mcpServers":{},"mcpServers":{"evil":{}}}',
            (
                b'{"mcpServers":{"github":{"command":"first",'
                b'"command":"second"}}}'
            ),
        ],
    )
    def test_install_rejects_duplicate_json_keys_at_any_depth(
        self,
        tmp_path,
        original,
    ):
        config_path = tmp_path / "mcp.json"
        config_path.write_bytes(original)

        with pytest.raises(MCPConfigError) as error:
            _update_mcp_config_file(config_path)

        assert config_path.read_bytes() == original
        assert not config_path.with_name("mcp.json.bak").exists()
        assert not list(tmp_path.glob(".*.tmp"))
        assert "mcpServers" not in str(error.value)
        assert "command" not in str(error.value)

    def test_install_keeps_distinct_case_sensitive_json_keys(self, tmp_path):
        config_path = tmp_path / "mcp.json"
        config_path.write_text(
            '{"mcpServers":{},"Setting":true,"setting":false}',
            encoding="utf-8",
        )

        _update_mcp_config_file(config_path)

        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert data["Setting"] is True
        assert data["setting"] is False

    def test_installer_waits_for_lock_then_reads_latest_configuration(
        self,
        tmp_path,
        monkeypatch,
    ):
        config_path = tmp_path / "mcp.json"
        original = b'{"mcpServers":{"original":{"command":"old"}}}\n'
        latest = b'{"mcpServers":{"latest":{"command":"keep"}},"flag":true}\n'
        config_path.write_bytes(original)
        lock_path = mcp_server_module._mcp_config_lock_path(config_path)
        attempted = threading.Event()
        results = []
        real_lock = exclusive_file_lock

        @contextmanager
        def observed_lock(path, *, timeout):
            attempted.set()
            with real_lock(path, timeout=timeout) as descriptor:
                yield descriptor

        monkeypatch.setattr(
            mcp_server_module,
            "exclusive_file_lock",
            observed_lock,
        )

        def update():
            try:
                results.append(_update_mcp_config_file(config_path))
            except Exception as exc:  # pragma: no cover - asserted below
                results.append(exc)

        with real_lock(lock_path, timeout=0.2):
            thread = threading.Thread(target=update)
            thread.start()
            assert attempted.wait(1.0)
            assert config_path.read_bytes() == original
            config_path.write_bytes(latest)

        thread.join(timeout=2.0)
        assert not thread.is_alive()
        assert results == [config_path.with_name("mcp.json.bak")]
        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert data["mcpServers"]["latest"] == {"command": "keep"}
        assert data["mcpServers"]["bck-nd-mcp"] == {"command": "bck-nd-mcp"}
        assert data["flag"] is True
        assert config_path.with_name("mcp.json.bak").read_bytes() == latest

    def test_two_installer_writers_serialize_without_losing_servers(self, tmp_path):
        config_path = tmp_path / "mcp.json"
        config_path.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "github": {
                            "command": "github-mcp",
                            "env": {"TOKEN": "fixture-secret"},
                        }
                    },
                    "setting": {"preserve": True},
                }
            ),
            encoding="utf-8",
        )
        start = threading.Event()
        errors = []

        def update(command):
            start.wait(1.0)
            try:
                _update_mcp_config_file(
                    config_path,
                    {"command": command},
                )
            except Exception as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        threads = [
            threading.Thread(target=update, args=("writer-a",)),
            threading.Thread(target=update, args=("writer-b",)),
        ]
        for thread in threads:
            thread.start()
        start.set()
        for thread in threads:
            thread.join(timeout=2.0)

        assert not errors
        assert not any(thread.is_alive() for thread in threads)
        final = json.loads(config_path.read_text(encoding="utf-8"))
        backup = json.loads(
            config_path.with_name("mcp.json.bak").read_text(encoding="utf-8")
        )
        assert final["mcpServers"]["github"]["env"]["TOKEN"] == "fixture-secret"
        assert final["setting"] == {"preserve": True}
        assert list(final["mcpServers"]).count("bck-nd-mcp") == 1
        assert {
            final["mcpServers"]["bck-nd-mcp"]["command"],
            backup["mcpServers"]["bck-nd-mcp"]["command"],
        } == {"writer-a", "writer-b"}

    def test_installer_lock_timeout_is_safe_and_path_neutral(
        self,
        tmp_path,
        monkeypatch,
    ):
        config_path = tmp_path / "secret-config-name.json"
        original = b'{"mcpServers":{"github":{"command":"keep"}}}\n'
        config_path.write_bytes(original)
        lock_path = mcp_server_module._mcp_config_lock_path(config_path)
        monkeypatch.setattr(mcp_server_module, "MCP_CONFIG_LOCK_TIMEOUT", 0.02)

        with exclusive_file_lock(lock_path, timeout=0.2):
            with pytest.raises(MCPConfigError) as error:
                _update_mcp_config_file(config_path)

        assert config_path.read_bytes() == original
        assert "secret-config-name" not in str(error.value)
        assert "github" not in str(error.value)
        assert not config_path.with_name("secret-config-name.json.bak").exists()
        assert not list(tmp_path.glob(".*.tmp"))

    def test_install_preserves_verified_backup_and_concurrent_content(
        self,
        tmp_path,
        monkeypatch,
    ):
        config_path = tmp_path / "mcp.json"
        original = json.dumps(
            {
                "mcpServers": {
                    "github": {
                        "command": "github-mcp",
                        "env": {"TOKEN": "fixture-secret"},
                    }
                },
                "unrelated": True,
            }
        ).encode("utf-8")
        concurrent = b'{"mcpServers":{"concurrent":{"command":"keep"}}}\n'
        config_path.write_bytes(original)
        real_chmod = mcp_server_module.os.chmod
        raced = False

        def race_during_temp_chmod(path, mode):
            nonlocal raced
            real_chmod(path, mode)
            if not raced and str(path).endswith(".tmp"):
                raced = True
                config_path.write_bytes(concurrent)

        monkeypatch.setattr(mcp_server_module.os, "chmod", race_during_temp_chmod)

        with pytest.raises(MCPConfigError, match="concurrently"):
            _update_mcp_config_file(config_path)

        assert raced is True
        assert config_path.read_bytes() == concurrent
        assert config_path.with_name("mcp.json.bak").read_bytes() == original
        assert not list(tmp_path.glob(".*.tmp"))

    def test_install_rejects_link_or_reparse_target_without_disclosure(
        self,
        tmp_path,
        monkeypatch,
    ):
        config_path = tmp_path / "mcp.json"
        config_path.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(
            mcp_server_module,
            "_is_link_or_reparse",
            lambda _path_stat: True,
        )

        with pytest.raises(MCPConfigError) as error:
            _update_mcp_config_file(config_path)

        assert str(config_path) not in str(error.value)
        assert config_path.read_text(encoding="utf-8") == "{}"

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
        assert data["mcpServers"]["bck-nd-mcp"] == {
            "command": "bck-nd-mcp",
            "env": {"BCK_ND_MCP_ALLOWED_ROOTS": str(tmp_path.resolve())},
        }

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
        assert data["mcpServers"]["bck-nd-mcp"] == {
            "command": "bck-nd-mcp",
            "env": {"BCK_ND_MCP_ALLOWED_ROOTS": str(tmp_path.resolve())},
        }

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
                "bck-nd-mcp": {
                    "command": "bck-nd-mcp",
                    "env": {
                        "BCK_ND_MCP_ALLOWED_ROOTS": str(tmp_path.resolve())
                    },
                }
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
        assert data["mcpServers"]["bck-nd-mcp"] == {
            "command": "bck-nd-mcp",
            "env": {"BCK_ND_MCP_ALLOWED_ROOTS": str(tmp_path.resolve())},
        }
        assert data["customSettings"] == {"enabled": True}

    def test_install_output_contains_manual_ide_settings(self, tmp_path):
        """--install should output the manual configuration box with server name and command."""
        claude_path = tmp_path / "claude.json"
        result = _install_claude_desktop(config_path=claude_path)

        assert "Claude Desktop" in result
        assert "bck-nd-mcp" in result
        assert "Server Name" in result
        assert "Command" in result
        assert "BCK_ND_MCP_ALLOWED_ROOTS" in result
        assert str(tmp_path.resolve()) in result

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
            "env": {
                "BCK_ND_MCP_ALLOWED_ROOTS": str(tmp_path.resolve())
            },
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

    def test_install_without_explicit_roots_writes_nothing(
        self,
        tmp_path,
        monkeypatch,
    ):
        config_path = tmp_path / "claude.json"
        monkeypatch.delenv("BCK_ND_MCP_ALLOWED_ROOTS", raising=False)

        with pytest.raises(MCPConfigError) as error:
            _install_claude_desktop(config_path=config_path)

        assert not config_path.exists()
        assert "--allowed-root" in str(error.value)
        assert str(tmp_path) not in str(error.value)

    def test_install_explicit_roots_override_environment_and_are_deduplicated(
        self,
        tmp_path,
        monkeypatch,
    ):
        first = tmp_path / "first"
        second = tmp_path / "second"
        ignored = tmp_path / "ignored"
        for directory in (first, second, ignored):
            directory.mkdir()
        config_path = tmp_path / "claude.json"
        monkeypatch.setenv("BCK_ND_MCP_ALLOWED_ROOTS", str(ignored))

        _install_claude_desktop(
            config_path=config_path,
            allowed_roots=[second, first, second],
        )

        data = json.loads(config_path.read_text(encoding="utf-8"))
        configured = data["mcpServers"]["bck-nd-mcp"]["env"][
            "BCK_ND_MCP_ALLOWED_ROOTS"
        ]
        assert configured == os.pathsep.join(
            sorted((str(first.resolve()), str(second.resolve())), key=os.path.normcase)
        )
        assert str(ignored) not in configured

    def test_install_injects_roots_into_all_configured_clients(self, tmp_path):
        allowed = tmp_path / "workspace"
        allowed.mkdir()
        claude = tmp_path / "claude.json"
        cursor = tmp_path / "cursor.json"
        antigravity = tmp_path / "antigravity.json"

        _install_claude_desktop(
            config_path=claude,
            cursor_config_path=cursor,
            antigravity_config_path=antigravity,
            allowed_roots=[allowed],
        )

        for config_path in (claude, cursor, antigravity):
            data = json.loads(config_path.read_text(encoding="utf-8"))
            assert data["mcpServers"]["bck-nd-mcp"]["env"] == {
                "BCK_ND_MCP_ALLOWED_ROOTS": str(allowed.resolve())
            }

    def test_main_install_allowed_root_and_repeated_install_are_idempotent(
        self,
        tmp_path,
        monkeypatch,
        capsys,
    ):
        allowed = tmp_path / "workspace"
        allowed.mkdir()
        config_path = tmp_path / "claude.json"
        monkeypatch.setattr(
            mcp_server_module,
            "_get_claude_config_path",
            lambda: config_path,
        )
        monkeypatch.setattr(mcp_server_module, "_get_cursor_config_paths", lambda: [])
        monkeypatch.setattr(mcp_server_module, "_find_antigravity_executable", lambda: None)
        monkeypatch.setattr(
            mcp_server_module,
            "_get_antigravity_config_path",
            lambda: tmp_path / "missing" / "antigravity.json",
        )

        for _ in range(2):
            monkeypatch.setattr(
                mcp_server_module.sys,
                "argv",
                ["bck-nd-mcp", "--install", "--allowed-root", str(allowed)],
            )
            assert mcp_server_module.main() is None

        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert list(data["mcpServers"]) == ["bck-nd-mcp"]
        assert data["mcpServers"]["bck-nd-mcp"]["env"] == {
            "BCK_ND_MCP_ALLOWED_ROOTS": str(allowed.resolve())
        }
        assert "configured successfully" in capsys.readouterr().out
