
import os
import shutil
import tempfile
from pathlib import Path
from bck_nd_hlpr.detector import ArchitectureDetector

def test_custom_config_detection():
    # Create temp dir
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        
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
        
        print(f"Testing in {tmp_path}")
        detector = ArchitectureDetector()
        results = detector.detect(str(tmp_path))
        
        print(f"Detected Architecture: {results['architecture']}")
        if results['architecture'] == 'MVC + Services (Layered)':
            print("✅ SUCCESS: Custom configuration detected correctly.")
        else:
            print(f"❌ FAILURE: Expected 'MVC + Services (Layered)', got '{results['architecture']}'")
            exit(1)

if __name__ == "__main__":
    test_custom_config_detection()
