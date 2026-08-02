"""
Unit tests for Pillar D: Client & MCP Integration (get_asg_graph, get_architecture_summary)
"""

import json
import pytest
from pathlib import Path

from bck_nd_hlpr.cli.mcp_server import get_asg_graph, get_architecture_summary
from bck_nd_hlpr.cli.formatters import format_asg_json
from bck_nd_hlpr.core.asg import ASGGraph, ASGNode, NodeKind, ASGEdge, EdgeKind


class TestMCPTools:
    @pytest.fixture
    def mock_project(self, tmp_path):
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
