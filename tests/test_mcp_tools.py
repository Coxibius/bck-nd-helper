"""MCP tool behavior and public response contracts."""

import json

import pytest

from bck_nd_hlpr.cli.formatters import format_asg_json
from bck_nd_hlpr.cli.mcp_server import (
    get_architecture_summary,
    get_asg_graph,
    get_requirements_summary,
)
from bck_nd_hlpr.core.asg import ASGGraph, ASGNode, NodeKind
from bck_nd_hlpr.core.sanitizer import REDACTION_MARKER


class TestMCPTools:
    @pytest.fixture
    def mock_project(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BCK_ND_MCP_ALLOWED_ROOTS", str(tmp_path))
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

    def test_get_requirements_summary_with_specs(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BCK_ND_MCP_ALLOWED_ROOTS", str(tmp_path))
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

    def test_get_requirements_summary_redacts_repository_credentials(
        self,
        tmp_path,
        monkeypatch,
    ):
        secret = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"
        req_dir = tmp_path / ".bck-nd" / "requirements"
        req_dir.mkdir(parents=True)
        requirement = {
            "story": {
                "id": "US-SECRET",
                "title": f"Title {secret}",
                "role": f"Role {secret}",
                "want": f"Want {secret}",
                "benefit": f"Benefit {secret}",
                "status": "TODO",
            },
            "business_rules": [{"id": "BR-1", "description": secret}],
            "acceptance_criteria": [
                {"id": "AC-1", "given": secret, "when": secret, "then": secret}
            ],
            "required_data": [{"token": secret}],
            "validations": [{"secret": secret}],
            "exceptions": [{"password": secret}],
            "open_questions": [secret],
        }
        source = req_dir / "US-SECRET.json"
        original = json.dumps(requirement, indent=2).encode("utf-8")
        source.write_bytes(original)
        monkeypatch.setenv("BCK_ND_MCP_ALLOWED_ROOTS", str(tmp_path))

        result = get_requirements_summary()

        assert secret not in result
        assert REDACTION_MARKER in result
        assert source.read_bytes() == original
        assert "one configured root" in get_requirements_summary.__doc__

    def test_get_requirements_summary_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BCK_ND_MCP_ALLOWED_ROOTS", str(tmp_path))
        result = get_requirements_summary(project_path=str(tmp_path))
        assert "No requirements found under .bck-nd/requirements/" in result
