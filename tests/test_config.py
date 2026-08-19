
import os
import pytest
from pathlib import Path
from bck_nd_hlpr.core.detector import ArchitectureDetector

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
    assert "2.4.0" in result.stdout

    result_short = runner.invoke(app, ["-v"])
    assert result_short.exit_code == 0
    assert "bck-nd-hlpr" in result_short.stdout
    assert "2.4.0" in result_short.stdout

def test_cli_version_flag():
    """Test 200: Verify bck-nd --version outputs version and exits cleanly."""
    from typer.testing import CliRunner
    from bck_nd_hlpr.cli.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "bck-nd-hlpr" in result.output
    assert "2.4.0" in result.output


def test_cli_version_short_flag():
    """Test 201: Verify bck-nd -v outputs version and exits cleanly."""
    from typer.testing import CliRunner
    from bck_nd_hlpr.cli.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["-v"])
    assert result.exit_code == 0
    assert "2.4.0" in result.output
