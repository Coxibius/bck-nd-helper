"""
Unit tests for Pillar C: Incremental Delta Cache Engine (DeltaCacheManager)
"""

import json
import time
from pathlib import Path
import pytest

import bck_nd_hlpr.core.utils.delta_cache as delta_module
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

        cache_file = temp_project / ".bck-nd" / "cache" / "delta.json"
        assert cache_file.exists()

        new_cache = DeltaCacheManager(temp_project)
        assert new_cache.is_unmodified(f1) is True
        assert new_cache.get_file_data(f1) == {"parsed": True}

    def test_clear_cache(self, temp_project):
        cache = DeltaCacheManager(temp_project)
        f1 = temp_project / "app.py"
        cache.update_file(f1)
        cache.save_cache()
        cache_file = temp_project / ".bck-nd" / "cache" / "delta.json"
        assert cache_file.exists()

        cache.clear()
        assert not cache_file.exists()
        assert cache_file.parent.is_dir()
        assert len(cache.signatures) == 0

    def test_cache_directory_is_created_only_when_persisting(self, temp_project):
        cache = DeltaCacheManager(temp_project)

        assert cache.cache_path == temp_project / ".bck-nd" / "cache" / "delta.json"
        assert not cache.cache_path.parent.exists()
        assert cache.save_cache() is True
        assert cache.cache_path.parent.is_dir()

    @pytest.mark.parametrize(
        "payload",
        [
            pytest.param(b"{not-json", id="invalid-json"),
            pytest.param(b"\xff\xfe\xfa", id="invalid-utf8"),
            pytest.param(
                b'{"signatures":[],"metadata":{}}',
                id="incompatible-structure",
            ),
        ],
    )
    def test_safe_invalid_cache_can_be_repaired_or_cleared(self, tmp_path, payload):
        cache_dir = tmp_path / ".bck-nd" / "cache"
        cache_dir.mkdir(parents=True)
        cache_file = cache_dir / "delta.json"
        cache_file.write_bytes(payload)

        manager = DeltaCacheManager(tmp_path)
        assert manager.load_cache() is False
        assert manager.signatures == {}
        assert manager.metadata == {}
        assert manager._loaded_cache_content == payload
        assert manager.save_cache() is True

        repaired = json.loads(cache_file.read_text(encoding="utf-8"))
        assert repaired["signatures"] == {}
        assert repaired["metadata"] == {}
        reloaded = DeltaCacheManager(tmp_path)
        assert reloaded.load_cache() is True

        cache_file.write_bytes(payload)
        clear_manager = DeltaCacheManager(tmp_path)
        assert clear_manager.load_cache() is False
        clear_manager.clear()
        assert not cache_file.exists()
        assert (cache_dir / ".delta.lock").exists()
        assert not list(cache_dir.glob(".*.tmp"))

    def test_corrupt_cache_race_and_oversized_source_remain_fail_closed(
        self,
        tmp_path,
        monkeypatch,
    ):
        cache_dir = tmp_path / ".bck-nd" / "cache"
        cache_dir.mkdir(parents=True)
        cache_file = cache_dir / "delta.json"
        corrupt = b"{broken-cache"
        cache_file.write_bytes(corrupt)

        manager = DeltaCacheManager(tmp_path)
        assert manager.load_cache() is False
        concurrent = b'{"concurrent":"winner"}\n'
        cache_file.write_bytes(concurrent)

        assert manager.save_cache() is False
        assert cache_file.read_bytes() == concurrent
        manager.clear()
        assert cache_file.read_bytes() == concurrent

        oversized_root = tmp_path / "oversized"
        oversized_dir = oversized_root / ".bck-nd" / "cache"
        oversized_dir.mkdir(parents=True)
        oversized_file = oversized_dir / "delta.json"
        oversized_payload = b"x" * 512
        oversized_file.write_bytes(oversized_payload)
        monkeypatch.setattr(delta_module, "MAX_DELTA_CACHE_BYTES", 128)

        oversized = DeltaCacheManager(oversized_root)
        assert len(oversized._serialize_cache()) < 128
        assert oversized.load_cache() is False
        assert oversized._loaded_cache_content is None
        assert oversized.save_cache() is False
        oversized.clear()
        assert oversized_file.read_bytes() == oversized_payload
        assert not list(oversized_dir.glob(".*.tmp"))


class TestOrchestratorCacheIntegration:
    def test_orchestrator_saves_cache_when_enabled(self, tmp_path):
        (tmp_path / "main.py").write_text("print('test')", encoding="utf-8")

        config = OrchestratorConfig(path=str(tmp_path), use_cache=True, tree=True)
        result = ScannerOrchestrator.run(config)

        assert result.delta_cache is not None
        cache_file = tmp_path / ".bck-nd" / "cache" / "delta.json"
        assert cache_file.exists()

    def test_orchestrator_bypasses_cache_when_disabled(self, tmp_path):
        (tmp_path / "main.py").write_text("print('test')", encoding="utf-8")

        config = OrchestratorConfig(path=str(tmp_path), use_cache=False, tree=True)
        result = ScannerOrchestrator.run(config)

        assert result.delta_cache is None
        cache_file = tmp_path / ".bck-nd" / "cache" / "delta.json"
        assert not cache_file.exists()


class TestCacheExclusions:
    def test_cache_excluded_from_tree(self, tmp_path):
        (tmp_path / "main.py").write_text("print('test')", encoding="utf-8")
        req_dir = tmp_path / ".bck-nd" / "requirements"
        req_dir.mkdir(parents=True)
        (req_dir / "US-001.md").write_text("# US-001 - Test", encoding="utf-8")
        cache = DeltaCacheManager(tmp_path)
        cache.update_file(tmp_path / "main.py")
        cache.save_cache()

        tree_str = generate_project_tree(str(tmp_path))
        assert ".bck-nd/" in tree_str
        assert "requirements/" in tree_str
        assert "US-001.md" in tree_str
        assert "cache/" not in tree_str
        assert "delta.json" not in tree_str

    def test_cache_excluded_from_context_dumper(self, tmp_path):
        (tmp_path / "main.py").write_text("print('test')", encoding="utf-8")
        req_dir = tmp_path / ".bck-nd" / "requirements"
        req_dir.mkdir(parents=True)
        (req_dir / "US-001.md").write_text(
            "# US-001 - Test\n\n- **Role**: User\n- **Want**: Test\n- **Benefit**: Confidence\n",
            encoding="utf-8",
        )
        cache = DeltaCacheManager(tmp_path)
        cache.update_file(tmp_path / "main.py")
        cache.save_cache()

        dumper = ContextDumper(path=str(tmp_path))
        dump_output = dumper.build()
        assert "delta.json" not in dump_output
        assert ".bck-nd/cache" not in dump_output
        assert "US-001" in dump_output
