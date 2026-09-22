
import os
import builtins
import importlib.util
import types
import pytest
from pathlib import Path
try:
    import tomllib
except ImportError:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib

import bck_nd_hlpr
from bck_nd_hlpr.core.detector import ArchitectureDetector
from bck_nd_hlpr.core.constants import VERSION


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_release_version_sources_are_synchronized():
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)["project"]

    project_version = project["version"]
    classifiers = project["classifiers"]
    dependencies = project["dependencies"]
    mcp_dependencies = [
        dependency
        for dependency in dependencies
        if dependency == "mcp"
        or dependency.startswith("mcp<")
        or dependency.startswith("mcp>")
        or dependency.startswith("mcp=")
        or dependency.startswith("mcp~")
        or dependency.startswith("mcp!")
    ]

    assert project_version == "2.5.0"
    assert bck_nd_hlpr.__version__ == project_version
    assert VERSION == project_version
    assert project["requires-python"] == ">=3.10"
    assert "Programming Language :: Python :: 3.9" not in classifiers
    assert {
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
    }.issubset(classifiers)
    assert mcp_dependencies == ["mcp>=1.28.1,<2"]
    assert "mcp" not in dependencies

def test_custom_config_detection(tmp_path):
    # Setup custom directories
    (tmp_path / "pyproject.toml").write_text("""
[tool.bck-nd]
controllers = ["manejadores"]
models = ["datos"]
services = ["logica"]
    """, encoding="utf-8")
    
    (tmp_path / "manejadores").mkdir()
    (tmp_path / "manejadores" / "usuario_ctrl.py").touch()
    
    (tmp_path / "datos").mkdir()
    (tmp_path / "datos" / "usuario.py").touch()
    
    (tmp_path / "logica").mkdir()
    (tmp_path / "logica" / "usuario_svc.py").touch()
    
    detector = ArchitectureDetector()
    results = detector.detect(str(tmp_path))
    
    assert results['architecture'] == 'MVC + Services (Layered)'
    # Verify that it detected them because if it used default config it would be Monolithic


def test_detector_uses_tomli_when_tomllib_is_unavailable(monkeypatch):
    import bck_nd_hlpr.core.detector as detector_module

    fallback = types.SimpleNamespace(loads=tomllib.loads)
    original_import = builtins.__import__

    def controlled_import(name, *args, **kwargs):
        if name == "tomllib":
            raise ImportError("simulated Python 3.10")
        if name == "tomli":
            return fallback
        if name == "toml":
            raise AssertionError("the unrelated toml package must not be imported")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", controlled_import)
    spec = importlib.util.spec_from_file_location(
        "_bck_nd_detector_python310", detector_module.__file__
    )
    isolated = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(isolated)

    assert isolated.toml is fallback
    
def test_default_config_detection(tmp_path):
    # Setup default directories
    (tmp_path / "controllers").mkdir()
    (tmp_path / "models").mkdir()
    
    detector = ArchitectureDetector()
    results = detector.detect(str(tmp_path))
    
    assert results['architecture'] == 'MVC Pattern'


def test_cli_version():
    from typer.testing import CliRunner
    from bck_nd_hlpr.cli.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "bck-nd-hlpr" in result.stdout
    assert VERSION in result.stdout

    result_short = runner.invoke(app, ["-v"])
    assert result_short.exit_code == 0
    assert "bck-nd-hlpr" in result_short.stdout
    assert VERSION in result_short.stdout

def test_cli_version_flag():
    """Test 200: Verify bck-nd --version outputs version and exits cleanly."""
    from typer.testing import CliRunner
    from bck_nd_hlpr.cli.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "bck-nd-hlpr" in result.output
    assert VERSION in result.output


def test_cli_version_short_flag():
    """Test 201: Verify bck-nd -v outputs version and exits cleanly."""
    from typer.testing import CliRunner
    from bck_nd_hlpr.cli.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["-v"])
    assert result.exit_code == 0
    assert VERSION in result.output

