"""
test_asg — Comprehensive unit tests for the Abstract Semantic Graph (ASG) module.

Covers:
  - ASGNode / ASGEdge creation and serialization (to_dict / from_dict round-trips)
  - ASGAttribute / ASGMethod serialization
  - ASGGraph operations (add, query, dedup, merge, thread-safety)
  - ASGToMermaidRenderer output for UML and ER diagrams
  - ASGToJsonExporter JSON serialization
  - ASGBuilder adapter conversions from UML classes, ER entities, and routes
"""

import json
import threading
import pytest

from bck_nd_hlpr.core.asg import (
    NodeKind,
    EdgeKind,
    ASGNode,
    ASGEdge,
    ASGAttribute,
    ASGMethod,
    ASGGraph,
    ASGToMermaidRenderer,
    ASGToJsonExporter,
    ASGBuilder,
)


# ─────────────────────────────────────────────────────────────
# ASGAttribute
# ─────────────────────────────────────────────────────────────
class TestASGAttribute:
    def test_defaults(self):
        attr = ASGAttribute(name="id")
        assert attr.name == "id"
        assert attr.type_annotation == ""
        assert attr.is_primary_key is False
        assert attr.is_nullable is True

    def test_to_dict(self):
        attr = ASGAttribute(name="email", type_annotation="str", is_primary_key=False, is_nullable=False)
        d = attr.to_dict()
        assert d == {
            "name": "email",
            "type_annotation": "str",
            "is_primary_key": False,
            "is_nullable": False,
        }

    def test_from_dict_roundtrip(self):
        original = ASGAttribute(name="age", type_annotation="int", is_primary_key=True, is_nullable=False)
        restored = ASGAttribute.from_dict(original.to_dict())
        assert restored.name == original.name
        assert restored.type_annotation == original.type_annotation
        assert restored.is_primary_key == original.is_primary_key
        assert restored.is_nullable == original.is_nullable

    def test_from_dict_missing_keys(self):
        attr = ASGAttribute.from_dict({})
        assert attr.name == ""
        assert attr.type_annotation == ""


# ─────────────────────────────────────────────────────────────
# ASGMethod
# ─────────────────────────────────────────────────────────────
class TestASGMethod:
    def test_defaults(self):
        m = ASGMethod(name="save")
        assert m.name == "save"
        assert m.parameters == []
        assert m.return_type == "Any"
        assert m.visibility == "public"

    def test_to_dict(self):
        m = ASGMethod(name="get_by_id", parameters=["id: int"], return_type="User", visibility="private")
        d = m.to_dict()
        assert d["name"] == "get_by_id"
        assert d["parameters"] == ["id: int"]
        assert d["return_type"] == "User"
        assert d["visibility"] == "private"

    def test_from_dict_roundtrip(self):
        original = ASGMethod(name="create", parameters=["data: dict"], return_type="None", visibility="protected")
        restored = ASGMethod.from_dict(original.to_dict())
        assert restored.name == original.name
        assert restored.parameters == original.parameters
        assert restored.return_type == original.return_type
        assert restored.visibility == original.visibility


# ─────────────────────────────────────────────────────────────
# ASGNode
# ─────────────────────────────────────────────────────────────
class TestASGNode:
    def test_basic_creation(self):
        node = ASGNode(id="models.User", name="User", kind=NodeKind.CLASS)
        assert node.id == "models.User"
        assert node.name == "User"
        assert node.kind == NodeKind.CLASS
        assert node.module == ""
        assert node.attributes == []
        assert node.methods == []
        assert node.metadata == {}

    def test_full_creation(self):
        attrs = [ASGAttribute(name="id", type_annotation="int", is_primary_key=True)]
        methods = [ASGMethod(name="save")]
        node = ASGNode(
            id="app.models.User",
            name="User",
            kind=NodeKind.ENTITY,
            module="app.models",
            attributes=attrs,
            methods=methods,
            metadata={"source": "django"},
        )
        assert node.kind == NodeKind.ENTITY
        assert len(node.attributes) == 1
        assert node.attributes[0].is_primary_key is True
        assert node.metadata["source"] == "django"

    def test_to_dict(self):
        node = ASGNode(
            id="User",
            name="User",
            kind=NodeKind.CLASS,
            attributes=[ASGAttribute(name="name", type_annotation="str")],
            methods=[ASGMethod(name="greet")],
        )
        d = node.to_dict()
        assert d["id"] == "User"
        assert d["kind"] == "CLASS"
        assert len(d["attributes"]) == 1
        assert len(d["methods"]) == 1

    def test_from_dict_roundtrip(self):
        original = ASGNode(
            id="svc.OrderService",
            name="OrderService",
            kind=NodeKind.SERVICE,
            module="svc",
            attributes=[ASGAttribute(name="repo")],
            methods=[ASGMethod(name="place_order", parameters=["item_id"])],
            metadata={"framework": "fastapi"},
        )
        d = original.to_dict()
        restored = ASGNode.from_dict(d)
        assert restored.id == original.id
        assert restored.kind == NodeKind.SERVICE
        assert restored.attributes[0].name == "repo"
        assert restored.methods[0].name == "place_order"
        assert restored.metadata["framework"] == "fastapi"

    def test_from_dict_unknown_kind_defaults_to_class(self):
        d = {"id": "x", "name": "x", "kind": "UNKNOWN_STUFF"}
        node = ASGNode.from_dict(d)
        assert node.kind == NodeKind.CLASS


# ─────────────────────────────────────────────────────────────
# ASGEdge
# ─────────────────────────────────────────────────────────────
class TestASGEdge:
    def test_basic_creation(self):
        edge = ASGEdge(source_id="A", target_id="B", kind=EdgeKind.INHERITS)
        assert edge.source_id == "A"
        assert edge.target_id == "B"
        assert edge.kind == EdgeKind.INHERITS
        assert edge.label is None
        assert edge.metadata == {}

    def test_to_dict(self):
        edge = ASGEdge(source_id="User", target_id="Post", kind=EdgeKind.HAS_MANY, label="posts")
        d = edge.to_dict()
        assert d["kind"] == "HAS_MANY"
        assert d["label"] == "posts"

    def test_from_dict_roundtrip(self):
        original = ASGEdge(
            source_id="Order",
            target_id="Product",
            kind=EdgeKind.MANY_TO_MANY,
            label="products",
            metadata={"through": "order_product"},
        )
        restored = ASGEdge.from_dict(original.to_dict())
        assert restored.source_id == original.source_id
        assert restored.target_id == original.target_id
        assert restored.kind == EdgeKind.MANY_TO_MANY
        assert restored.label == "products"
        assert restored.metadata["through"] == "order_product"

    def test_from_dict_unknown_kind_defaults_to_depends_on(self):
        d = {"source_id": "A", "target_id": "B", "kind": "BANANA"}
        edge = ASGEdge.from_dict(d)
        assert edge.kind == EdgeKind.DEPENDS_ON


# ─────────────────────────────────────────────────────────────
# ASGGraph
# ─────────────────────────────────────────────────────────────
class TestASGGraph:
    def _make_node(self, nid, kind=NodeKind.CLASS, attrs=None, methods=None):
        return ASGNode(
            id=nid,
            name=nid.split(".")[-1],
            kind=kind,
            attributes=attrs or [],
            methods=methods or [],
        )

    def test_add_and_get_node(self):
        g = ASGGraph()
        node = self._make_node("User")
        g.add_node(node)
        assert g.get_node("User") is node
        assert g.get_node("Missing") is None

    def test_add_duplicate_node_merges(self):
        g = ASGGraph()
        g.add_node(ASGNode(
            id="User", name="User", kind=NodeKind.CLASS,
            attributes=[ASGAttribute(name="id")],
            methods=[ASGMethod(name="save")],
        ))
        # Add second node with same ID but different attrs/methods
        g.add_node(ASGNode(
            id="User", name="User", kind=NodeKind.CLASS,
            attributes=[ASGAttribute(name="id"), ASGAttribute(name="email")],
            methods=[ASGMethod(name="save"), ASGMethod(name="delete")],
        ))
        merged = g.get_node("User")
        attr_names = {a.name for a in merged.attributes}
        method_names = {m.name for m in merged.methods}
        assert attr_names == {"id", "email"}
        assert method_names == {"save", "delete"}

    def test_add_edge_dedup(self):
        g = ASGGraph()
        edge = ASGEdge(source_id="A", target_id="B", kind=EdgeKind.INHERITS)
        g.add_edge(edge)
        g.add_edge(ASGEdge(source_id="A", target_id="B", kind=EdgeKind.INHERITS))
        assert len(g.edges) == 1

    def test_add_edge_different_kinds_not_deduped(self):
        g = ASGGraph()
        g.add_edge(ASGEdge(source_id="A", target_id="B", kind=EdgeKind.INHERITS))
        g.add_edge(ASGEdge(source_id="A", target_id="B", kind=EdgeKind.DEPENDS_ON))
        assert len(g.edges) == 2

    def test_get_nodes_by_kind(self):
        g = ASGGraph()
        g.add_node(self._make_node("User", NodeKind.CLASS))
        g.add_node(self._make_node("Post", NodeKind.ENTITY))
        g.add_node(self._make_node("Comment", NodeKind.ENTITY))
        entities = g.get_nodes_by_kind(NodeKind.ENTITY)
        assert len(entities) == 2
        assert all(n.kind == NodeKind.ENTITY for n in entities)

    def test_get_outgoing_incoming_edges(self):
        g = ASGGraph()
        g.add_edge(ASGEdge(source_id="A", target_id="B", kind=EdgeKind.INHERITS))
        g.add_edge(ASGEdge(source_id="A", target_id="C", kind=EdgeKind.DEPENDS_ON))
        g.add_edge(ASGEdge(source_id="B", target_id="C", kind=EdgeKind.CALLS))
        assert len(g.get_outgoing_edges("A")) == 2
        assert len(g.get_outgoing_edges("B")) == 1
        assert len(g.get_incoming_edges("C")) == 2
        assert len(g.get_incoming_edges("A")) == 0

    def test_merge(self):
        g1 = ASGGraph()
        g1.add_node(self._make_node("User", NodeKind.CLASS))
        g1.add_edge(ASGEdge(source_id="User", target_id="Base", kind=EdgeKind.INHERITS))

        g2 = ASGGraph()
        g2.add_node(self._make_node("Post", NodeKind.ENTITY))
        g2.add_edge(ASGEdge(source_id="User", target_id="Post", kind=EdgeKind.HAS_MANY))

        g1.merge(g2)
        assert g1.get_node("User") is not None
        assert g1.get_node("Post") is not None
        assert len(g1.edges) == 2

    def test_merge_none_is_safe(self):
        g = ASGGraph()
        g.add_node(self._make_node("X"))
        g.merge(None)
        assert len(g.nodes) == 1

    def test_to_dict_from_dict_roundtrip(self):
        g = ASGGraph()
        g.add_node(ASGNode(
            id="User", name="User", kind=NodeKind.ENTITY,
            attributes=[ASGAttribute(name="id", type_annotation="int", is_primary_key=True)],
        ))
        g.add_node(ASGNode(id="Post", name="Post", kind=NodeKind.ENTITY))
        g.add_edge(ASGEdge(source_id="User", target_id="Post", kind=EdgeKind.HAS_MANY, label="posts"))

        d = g.to_dict()
        restored = ASGGraph.from_dict(d)

        assert restored.get_node("User") is not None
        assert restored.get_node("Post") is not None
        assert restored.get_node("User").attributes[0].is_primary_key is True
        assert len(restored.edges) == 1
        assert restored.edges[0].kind == EdgeKind.HAS_MANY

    def test_thread_safety(self):
        """Multiple threads adding nodes/edges concurrently should not raise."""
        g = ASGGraph()
        errors = []

        def worker(start):
            try:
                for i in range(50):
                    nid = f"Node_{start}_{i}"
                    g.add_node(ASGNode(id=nid, name=nid, kind=NodeKind.CLASS))
                    if i > 0:
                        prev = f"Node_{start}_{i - 1}"
                        g.add_edge(ASGEdge(source_id=prev, target_id=nid, kind=EdgeKind.DEPENDS_ON))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread safety violation: {errors}"
        # 4 threads × 50 nodes = 200 unique nodes
        assert len(g.nodes) == 200


# ─────────────────────────────────────────────────────────────
# ASGToMermaidRenderer
# ─────────────────────────────────────────────────────────────
class TestASGToMermaidRenderer:
    def test_render_uml_empty(self):
        g = ASGGraph()
        output = ASGToMermaidRenderer.render_uml(g)
        assert output.startswith("classDiagram")

    def test_render_uml_with_class(self):
        g = ASGGraph()
        g.add_node(ASGNode(
            id="User",
            name="User",
            kind=NodeKind.CLASS,
            attributes=[ASGAttribute(name="name", type_annotation="str")],
            methods=[ASGMethod(name="save", return_type="None")],
        ))
        output = ASGToMermaidRenderer.render_uml(g)
        assert "class User" in output
        assert "name" in output
        assert "save" in output

    def test_render_uml_with_interface(self):
        g = ASGGraph()
        g.add_node(ASGNode(id="IRepo", name="IRepo", kind=NodeKind.INTERFACE))
        output = ASGToMermaidRenderer.render_uml(g)
        assert "<<interface>>" in output

    def test_render_uml_with_inheritance_edge(self):
        g = ASGGraph()
        g.add_node(ASGNode(id="Animal", name="Animal", kind=NodeKind.CLASS))
        g.add_node(ASGNode(id="Dog", name="Dog", kind=NodeKind.CLASS))
        g.add_edge(ASGEdge(source_id="Dog", target_id="Animal", kind=EdgeKind.INHERITS))
        output = ASGToMermaidRenderer.render_uml(g)
        assert "Animal <|-- Dog" in output

    def test_render_uml_with_dependency_edge(self):
        g = ASGGraph()
        g.add_node(ASGNode(id="Svc", name="Svc", kind=NodeKind.SERVICE))
        g.add_node(ASGNode(id="Repo", name="Repo", kind=NodeKind.CLASS))
        g.add_edge(ASGEdge(source_id="Svc", target_id="Repo", kind=EdgeKind.DEPENDS_ON))
        output = ASGToMermaidRenderer.render_uml(g)
        assert "Svc ..> Repo" in output

    def test_render_er_empty(self):
        g = ASGGraph()
        output = ASGToMermaidRenderer.render_er(g)
        assert output.startswith("erDiagram")

    def test_render_er_with_entity(self):
        g = ASGGraph()
        g.add_node(ASGNode(
            id="User",
            name="User",
            kind=NodeKind.ENTITY,
            attributes=[
                ASGAttribute(name="id", type_annotation="int", is_primary_key=True),
                ASGAttribute(name="email", type_annotation="string"),
            ],
        ))
        output = ASGToMermaidRenderer.render_er(g)
        assert "USER" in output
        assert "int id PK" in output
        assert "string email" in output

    def test_render_er_with_fk_detection(self):
        g = ASGGraph()
        g.add_node(ASGNode(
            id="Post",
            name="Post",
            kind=NodeKind.ENTITY,
            attributes=[ASGAttribute(name="user_id", type_annotation="int")],
        ))
        output = ASGToMermaidRenderer.render_er(g)
        assert "FK" in output

    def test_render_er_with_relationship_edge(self):
        g = ASGGraph()
        g.add_node(ASGNode(id="User", name="User", kind=NodeKind.ENTITY))
        g.add_node(ASGNode(id="Post", name="Post", kind=NodeKind.ENTITY))
        g.add_edge(ASGEdge(source_id="User", target_id="Post", kind=EdgeKind.HAS_MANY, label="posts"))
        output = ASGToMermaidRenderer.render_er(g)
        assert "USER ||--|{" in output
        assert '"posts"' in output


# ─────────────────────────────────────────────────────────────
# ASGToJsonExporter
# ─────────────────────────────────────────────────────────────
class TestASGToJsonExporter:
    def test_export_json_is_valid(self):
        g = ASGGraph()
        g.add_node(ASGNode(id="X", name="X", kind=NodeKind.CLASS))
        g.add_edge(ASGEdge(source_id="X", target_id="Y", kind=EdgeKind.DEPENDS_ON))
        raw = ASGToJsonExporter.export_json(g)
        parsed = json.loads(raw)
        assert "nodes" in parsed
        assert "edges" in parsed
        assert len(parsed["nodes"]) == 1
        assert len(parsed["edges"]) == 1

    def test_to_dict(self):
        g = ASGGraph()
        g.add_node(ASGNode(id="A", name="A", kind=NodeKind.MODULE))
        d = ASGToJsonExporter.to_dict(g)
        assert isinstance(d, dict)
        assert d["nodes"][0]["kind"] == "MODULE"


# ─────────────────────────────────────────────────────────────
# ASGBuilder
# ─────────────────────────────────────────────────────────────
class TestASGBuilder:
    def test_from_uml_classes_with_dicts(self):
        classes = [
            {
                "name": "UserService",
                "module": "app.services",
                "is_interface": False,
                "attributes": [{"name": "repo", "type_annotation": "UserRepo"}],
                "methods": [{"name": "create_user", "parameters": ["data"]}],
                "parents": ["BaseService"],
                "dependencies": ["UserRepo"],
            },
        ]
        g = ASGBuilder.from_uml_classes(classes)
        node = g.get_node("app.services.UserService")
        assert node is not None
        assert node.kind == NodeKind.CLASS
        assert len(node.attributes) == 1
        assert len(node.methods) == 1
        # Inheritance + dependency edges
        assert len(g.edges) == 2
        kinds = {e.kind for e in g.edges}
        assert EdgeKind.INHERITS in kinds
        assert EdgeKind.DEPENDS_ON in kinds

    def test_from_uml_classes_interface(self):
        classes = [{"name": "IRepository", "is_interface": True, "parents": ["IBase"]}]
        g = ASGBuilder.from_uml_classes(classes)
        node = g.get_node("IRepository")
        assert node.kind == NodeKind.INTERFACE
        # Interface parent uses IMPLEMENTS
        assert g.edges[0].kind == EdgeKind.IMPLEMENTS

    def test_from_uml_classes_with_string_attrs(self):
        classes = [{"name": "Simple", "attributes": ["x", "y"], "methods": ["run"]}]
        g = ASGBuilder.from_uml_classes(classes)
        node = g.get_node("Simple")
        assert len(node.attributes) == 2
        assert node.attributes[0].name == "x"
        assert len(node.methods) == 1
        assert node.methods[0].name == "run"

    def test_from_uml_classes_skips_empty_name(self):
        classes = [{"name": ""}, {"name": "Valid"}]
        g = ASGBuilder.from_uml_classes(classes)
        assert len(g.nodes) == 1

    def test_from_uml_classes_merges_into_existing_graph(self):
        g = ASGGraph()
        g.add_node(ASGNode(id="Existing", name="Existing", kind=NodeKind.CLASS))
        classes = [{"name": "New", "module": "pkg"}]
        ASGBuilder.from_uml_classes(classes, graph=g)
        assert g.get_node("Existing") is not None
        assert g.get_node("pkg.New") is not None

    def test_from_er_entities_with_dicts(self):
        entities = [
            {
                "name": "User",
                "columns": [
                    {"name": "id", "type_annotation": "int", "is_primary_key": True},
                    {"name": "email", "type_annotation": "varchar"},
                ],
            },
            {"name": "Post", "columns": [{"name": "id"}]},
        ]
        relationships = [
            {"source": "User", "target": "Post", "kind": "HAS_MANY", "label": "posts"},
        ]
        g = ASGBuilder.from_er_entities(entities, relationships)
        assert g.get_node("User").kind == NodeKind.ENTITY
        assert g.get_node("User").attributes[0].is_primary_key is True
        assert len(g.edges) == 1
        assert g.edges[0].kind == EdgeKind.HAS_MANY

    def test_from_er_entities_with_string_columns(self):
        entities = [{"name": "Tag", "columns": ["id", "label"]}]
        g = ASGBuilder.from_er_entities(entities)
        node = g.get_node("Tag")
        assert len(node.attributes) == 2

    def test_from_routes(self):
        routes = [
            {"path": "/api/users", "method": "GET", "handler": "list_users", "file": "views.py"},
            {"path": "/api/users", "method": "POST", "handler": "create_user", "file": "views.py"},
        ]
        g = ASGBuilder.from_routes(routes)
        assert len(g.nodes) == 2
        node = g.get_node("GET /api/users")
        assert node is not None
        assert node.kind == NodeKind.ENDPOINT
        assert node.metadata["handler"] == "list_users"

    def test_from_routes_skips_empty_path(self):
        routes = [{"path": "", "method": "GET"}, {"path": "/ok", "method": "GET"}]
        g = ASGBuilder.from_routes(routes)
        assert len(g.nodes) == 1


# ─────────────────────────────────────────────────────────────
# Integration Wiring (ScanContext / AnalyzerResult / OrchestratorResult)
# ─────────────────────────────────────────────────────────────
class TestIntegrationWiring:
    def test_scan_context_has_asg_graph_field(self):
        from bck_nd_hlpr.core.base_analyzer import ScanContext
        ctx = ScanContext(path="/tmp")
        assert ctx.asg_graph is None

    def test_analyzer_result_has_asg_graph_field(self):
        from bck_nd_hlpr.core.base_analyzer import AnalyzerResult
        r = AnalyzerResult()
        assert r.asg_graph is None
        # Can assign
        g = ASGGraph()
        r.asg_graph = g
        assert r.asg_graph is g

    def test_orchestrator_result_has_asg_graph_field(self):
        from bck_nd_hlpr.core.orchestrator import OrchestratorResult
        r = OrchestratorResult(
            path="/tmp",
            framework="test",
            architecture="test",
            features=[],
            summary="test",
        )
        assert r.asg_graph is None
