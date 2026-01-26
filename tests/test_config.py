
import os
import pytest
from pathlib import Path
from bck_nd_hlpr.detector import ArchitectureDetector

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
