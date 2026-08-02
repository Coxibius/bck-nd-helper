"""
Unit tests for Pillar C: Incremental Delta Cache Engine (DeltaCacheManager)
"""

import json
import time
from pathlib import Path
import pytest

from bck_nd_hlpr.core.utils.delta_cache import DeltaCacheManager
from bck_nd_hlpr.core.orchestrator import ScannerOrchestrator, OrchestratorConfig
from bck_nd_hlpr.core.context_dumper import ContextDumper
from bck_nd_hlpr.core.tree_generator import generate_project_tree


class TestDeltaCacheManager:
    @pytest.fixture
    def temp_project(self, tmp_path):
        app_file = tmp_path / "app.py"
        app_file.write_text("print('hello world')", encoding="utf-8")
        
        utils_dir = tmp_path / "utils"
        utils_dir.mkdir()
        helper_file = utils_dir / "helper.py"
        helper_file.write_text("def help(): pass", encoding="utf-8")
        
        return tmp_path

    def test_compute_signature_and_unmodified(self, temp_project):
        cache = DeltaCacheManager(temp_project)
        app_file = temp_project / "app.py"

        assert cache.is_unmodified(app_file) is False

        cache.update_file(app_file)
        assert cache.is_unmodified(app_file) is True

    def test_cache_miss_on_content_change(self, temp_project):
        cache = DeltaCacheManager(temp_project)
        app_file = temp_project / "app.py"

        cache.update_file(app_file)
        assert cache.is_unmodified(app_file) is True

        # Modify content
        time.sleep(0.01)
        app_file.write_text("print('modified content')", encoding="utf-8")

        assert cache.is_unmodified(app_file) is False

    def test_cache_invalidation_on_deletion(self, temp_project):
        cache = DeltaCacheManager(temp_project)
        app_file = temp_project / "app.py"

        cache.update_file(app_file)
        assert cache.is_unmodified(app_file) is True

        app_file.unlink()
        assert cache.is_unmodified(app_file) is False

    def test_get_unmodified_and_modified_files(self, temp_project):
        cache = DeltaCacheManager(temp_project)
        f1 = temp_project / "app.py"
        f2 = temp_project / "utils" / "helper.py"

        cache.update_file(f1)

        unmodified = cache.get_unmodified_files([f1, f2])
        modified = cache.get_modified_files([f1, f2])

        assert f1 in unmodified
        assert f2 not in unmodified
        assert f2 in modified
        assert f1 not in modified

    def test_sync_files(self, temp_project):
        cache = DeltaCacheManager(temp_project)
        f1 = temp_project / "app.py"
        f2 = temp_project / "utils" / "helper.py"

        cache.sync_files([f1, f2])
        assert len(cache.signatures) == 2

        # Delete f2 and sync
        f2.unlink()
        cache.sync_files([f1])
        assert len(cache.signatures) == 1

    def test_save_and_load_cache(self, temp_project):
        cache = DeltaCacheManager(temp_project)
        f1 = temp_project / "app.py"
        cache.update_file(f1, extra_data={"parsed": True})
        assert cache.save_cache() is True

        cache_file = temp_project / ".bck-nd-cache"
        assert cache_file.exists()

        new_cache = DeltaCacheManager(temp_project)
        assert new_cache.is_unmodified(f1) is True
        assert new_cache.get_file_data(f1) == {"parsed": True}

    def test_clear_cache(self, temp_project):
        cache = DeltaCacheManager(temp_project)
        f1 = temp_project / "app.py"
        cache.update_file(f1)
        cache.save_cache()
        assert (temp_project / ".bck-nd-cache").exists()

        cache.clear()
        assert not (temp_project / ".bck-nd-cache").exists()
        assert len(cache.signatures) == 0


class TestOrchestratorCacheIntegration:
    def test_orchestrator_saves_cache_when_enabled(self, tmp_path):
        (tmp_path / "main.py").write_text("print('test')", encoding="utf-8")

        config = OrchestratorConfig(path=str(tmp_path), use_cache=True, tree=True)
        result = ScannerOrchestrator.run(config)

        assert result.delta_cache is not None
        cache_file = tmp_path / ".bck-nd-cache"
        assert cache_file.exists()

    def test_orchestrator_bypasses_cache_when_disabled(self, tmp_path):
        (tmp_path / "main.py").write_text("print('test')", encoding="utf-8")

        config = OrchestratorConfig(path=str(tmp_path), use_cache=False, tree=True)
        result = ScannerOrchestrator.run(config)

        assert result.delta_cache is None
        cache_file = tmp_path / ".bck-nd-cache"
        assert not cache_file.exists()


class TestCacheExclusions:
    def test_cache_excluded_from_tree(self, tmp_path):
        (tmp_path / "main.py").write_text("print('test')", encoding="utf-8")
        cache = DeltaCacheManager(tmp_path)
        cache.update_file(tmp_path / "main.py")
        cache.save_cache()

        tree_str = generate_project_tree(str(tmp_path))
        assert ".bck-nd-cache" not in tree_str

    def test_cache_excluded_from_context_dumper(self, tmp_path):
        (tmp_path / "main.py").write_text("print('test')", encoding="utf-8")
        cache = DeltaCacheManager(tmp_path)
        cache.update_file(tmp_path / "main.py")
        cache.save_cache()

        dumper = ContextDumper(path=str(tmp_path))
        dump_output = dumper.build()
        assert ".bck-nd-cache" not in dump_output
