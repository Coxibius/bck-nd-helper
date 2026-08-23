"""Polyglot monorepo detection tests for common frontend/backend layouts."""
from __future__ import annotations

import json
from pathlib import Path

from bck_nd_hlpr.core.detector import ArchitectureDetector


def _write_nextjs_project(path: Path) -> None:
    path.mkdir(parents=True)
    (path / "package.json").write_text(
        json.dumps({"dependencies": {"next": "^15.0.0", "react": "^19.0.0"}}),
        encoding="utf-8",
    )
    (path / "app").mkdir()


def _write_fastapi_project(path: Path) -> None:
    path.mkdir(parents=True)
    (path / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n",
        encoding="utf-8",
    )


def test_frontend_backend_monorepo_detects_both_frameworks(tmp_path: Path):
    _write_nextjs_project(tmp_path / "frontend")
    _write_fastapi_project(tmp_path / "backend")

    result = ArchitectureDetector().detect(str(tmp_path))

    assert result["architecture"] == "Monorepo (Polyglot)"
    assert "Next.js (frontend)" in result["framework"]
    assert "FastAPI (backend)" in result["framework"]


def test_apps_web_api_layout_is_supported(tmp_path: Path):
    _write_nextjs_project(tmp_path / "apps" / "web")
    _write_fastapi_project(tmp_path / "apps" / "api")

    result = ArchitectureDetector().detect(str(tmp_path))

    assert result["architecture"] == "Monorepo (Polyglot)"
    assert "Next.js (apps/web)" in result["framework"]
    assert "FastAPI (apps/api)" in result["framework"]


def test_single_framework_subdirectory_is_not_labeled_polyglot(tmp_path: Path):
    _write_fastapi_project(tmp_path / "backend")

    result = ArchitectureDetector().detect(str(tmp_path))

    assert result["architecture"] != "Monorepo (Polyglot)"
    assert result["framework"] == "FastAPI"


def test_monorepo_aggregates_docker_database_and_auth_features(tmp_path: Path):
    frontend = tmp_path / "frontend"
    backend = tmp_path / "backend"
    _write_nextjs_project(frontend)
    _write_fastapi_project(backend)
    (frontend / "Dockerfile").write_text("FROM node:22\n", encoding="utf-8")
    (backend / "auth.py").write_text(
        "from sqlalchemy import create_engine\nJWT_ALGORITHM = 'HS256'\n",
        encoding="utf-8",
    )

    result = ArchitectureDetector().detect(str(tmp_path))
    features = set(result["features"])

    assert "Docker" in features
    assert "Database" in features
    assert "Authentication" in features
