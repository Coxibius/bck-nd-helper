"""Cross-platform clipboard encoding regressions."""

import subprocess

import pytest

import bck_nd_hlpr.cli.cli as cli_module


UNICODE_CONTEXT = "├── árbol\n└── módulo │ conexión — listo ✨ áéíóú 🚀"


def test_windows_clipboard_uses_clip_with_utf16le(monkeypatch):
    calls = []

    def fake_run(command, *, input, check):
        calls.append((command, input, check))

    monkeypatch.setattr(cli_module.sys, "platform", "win32")
    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)

    assert cli_module.copy_to_clipboard(UNICODE_CONTEXT) is True
    assert calls == [(["clip"], UNICODE_CONTEXT.encode("utf-16le"), True)]


def test_macos_clipboard_preserves_utf8(monkeypatch):
    calls = []

    def fake_run(command, *, input, check):
        calls.append((command, input, check))

    monkeypatch.setattr(cli_module.sys, "platform", "darwin")
    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)

    assert cli_module.copy_to_clipboard(UNICODE_CONTEXT) is True
    assert calls == [(["pbcopy"], UNICODE_CONTEXT.encode("utf-8"), True)]


@pytest.mark.parametrize(
    ("available", "expected_command"),
    [
        ({"wl-copy"}, ["wl-copy"]),
        ({"xclip"}, ["xclip", "-selection", "clipboard"]),
    ],
)
def test_linux_clipboards_preserve_utf8(monkeypatch, available, expected_command):
    calls = []

    def fake_run(command, *, input, check):
        calls.append((command, input, check))

    monkeypatch.setattr(cli_module.sys, "platform", "linux")
    monkeypatch.setattr(
        cli_module.shutil,
        "which",
        lambda command: command if command in available else None,
    )
    monkeypatch.setattr(cli_module.subprocess, "run", fake_run)

    assert cli_module.copy_to_clipboard(UNICODE_CONTEXT) is True
    assert calls == [(expected_command, UNICODE_CONTEXT.encode("utf-8"), True)]


def test_clipboard_failure_preserves_boolean_contract(monkeypatch):
    monkeypatch.setattr(cli_module.sys, "platform", "darwin")
    monkeypatch.setattr(
        cli_module.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            subprocess.CalledProcessError(1, ["pbcopy"])
        ),
    )

    assert cli_module.copy_to_clipboard(UNICODE_CONTEXT) is False
