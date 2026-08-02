"""
Standalone test runner that bypasses corrupted entry_points metadata.
Imports and runs the ASG test classes directly.
"""
import sys
import traceback

# Ensure src is on the path
sys.path.insert(0, "src")

def run_tests():
    from bck_nd_hlpr.core.asg import (
        NodeKind, EdgeKind, ASGNode, ASGEdge, ASGAttribute, ASGMethod,
        ASGGraph, ASGToMermaidRenderer, ASGToJsonExporter, ASGBuilder,
    )
    import json
    import threading

    passed = 0
    failed = 0
    errors = []

    def check(name, condition, msg=""):
        nonlocal passed, failed
        if condition:
            passed += 1
        else:
            failed += 1
            errors.append(f"FAIL: {name} — {msg}")
            print(f"  FAIL: {name} — {msg}")

    # ══════════════ ASGAttribute ══════════════
    print("\n--- ASGAttribute ---")
    attr = ASGAttribute(name="id")
    check("attr_defaults", attr.type_annotation == "" and attr.is_primary_key is False)

    attr2 = ASGAttribute(name="email", type_annotation="str", is_primary_key=False, is_nullable=False)
    d = attr2.to_dict()
    check("attr_to_dict", d["name"] == "email" and d["is_nullable"] is False)

    restored = ASGAttribute.from_dict(d)
    check("attr_roundtrip", restored.name == "email" and restored.is_nullable is False)

    empty = ASGAttribute.from_dict({})
    check("attr_from_empty", empty.name == "")

    # ══════════════ ASGMethod ══════════════
    print("--- ASGMethod ---")
    m = ASGMethod(name="save")
    check("method_defaults", m.parameters == [] and m.return_type == "Any")

    m2 = ASGMethod(name="find", parameters=["id"], return_type="User", visibility="private")
    d2 = m2.to_dict()
    check("method_to_dict", d2["visibility"] == "private")

    mr = ASGMethod.from_dict(d2)
    check("method_roundtrip", mr.name == "find" and mr.parameters == ["id"])

    # ══════════════ ASGNode ══════════════
    print("--- ASGNode ---")
    node = ASGNode(id="User", name="User", kind=NodeKind.CLASS)
    check("node_basic", node.module == "" and node.attributes == [])

    d3 = node.to_dict()
    check("node_to_dict", d3["kind"] == "CLASS")

    node2 = ASGNode(
        id="svc.OrderService", name="OrderService", kind=NodeKind.SERVICE,
        module="svc",
        attributes=[ASGAttribute(name="repo")],
        methods=[ASGMethod(name="place_order", parameters=["item_id"])],
        metadata={"framework": "fastapi"},
    )
    r2 = ASGNode.from_dict(node2.to_dict())
    check("node_roundtrip", r2.kind == NodeKind.SERVICE and r2.metadata["framework"] == "fastapi")

    bad = ASGNode.from_dict({"id": "x", "name": "x", "kind": "BANANA"})
    check("node_unknown_kind", bad.kind == NodeKind.CLASS)

    # ══════════════ ASGEdge ══════════════
    print("--- ASGEdge ---")
    edge = ASGEdge(source_id="A", target_id="B", kind=EdgeKind.INHERITS)
    check("edge_basic", edge.label is None)

    de = edge.to_dict()
    check("edge_to_dict", de["kind"] == "INHERITS")

    edge2 = ASGEdge(source_id="O", target_id="P", kind=EdgeKind.MANY_TO_MANY, label="products", metadata={"through": "op"})
    er = ASGEdge.from_dict(edge2.to_dict())
    check("edge_roundtrip", er.kind == EdgeKind.MANY_TO_MANY and er.label == "products")

    bad_e = ASGEdge.from_dict({"source_id": "A", "target_id": "B", "kind": "NOPE"})
    check("edge_unknown_kind", bad_e.kind == EdgeKind.DEPENDS_ON)

    # ══════════════ ASGGraph ══════════════
    print("--- ASGGraph ---")
    g = ASGGraph()
    n1 = ASGNode(id="User", name="User", kind=NodeKind.CLASS, attributes=[ASGAttribute(name="id")])
    g.add_node(n1)
    check("graph_add_get", g.get_node("User") is n1)
    check("graph_get_missing", g.get_node("Nope") is None)

    # Merge duplicate
    g.add_node(ASGNode(id="User", name="User", kind=NodeKind.CLASS,
                       attributes=[ASGAttribute(name="id"), ASGAttribute(name="email")],
                       methods=[ASGMethod(name="save")]))
    merged = g.get_node("User")
    check("graph_merge_attrs", {a.name for a in merged.attributes} == {"id", "email"})
    check("graph_merge_methods", {m.name for m in merged.methods} == {"save"})

    # Edge dedup
    g.add_edge(ASGEdge(source_id="A", target_id="B", kind=EdgeKind.INHERITS))
    g.add_edge(ASGEdge(source_id="A", target_id="B", kind=EdgeKind.INHERITS))
    check("graph_edge_dedup", len(g.edges) == 1)

    g.add_edge(ASGEdge(source_id="A", target_id="B", kind=EdgeKind.DEPENDS_ON))
    check("graph_edge_diff_kind", len(g.edges) == 2)

    # Filter by kind
    g2 = ASGGraph()
    g2.add_node(ASGNode(id="U", name="U", kind=NodeKind.CLASS))
    g2.add_node(ASGNode(id="P", name="P", kind=NodeKind.ENTITY))
    g2.add_node(ASGNode(id="C", name="C", kind=NodeKind.ENTITY))
    check("graph_by_kind", len(g2.get_nodes_by_kind(NodeKind.ENTITY)) == 2)

    # Outgoing/incoming
    g3 = ASGGraph()
    g3.add_edge(ASGEdge(source_id="A", target_id="B", kind=EdgeKind.INHERITS))
    g3.add_edge(ASGEdge(source_id="A", target_id="C", kind=EdgeKind.DEPENDS_ON))
    g3.add_edge(ASGEdge(source_id="B", target_id="C", kind=EdgeKind.CALLS))
    check("graph_outgoing", len(g3.get_outgoing_edges("A")) == 2)
    check("graph_incoming", len(g3.get_incoming_edges("C")) == 2)

    # Merge graphs
    ga = ASGGraph()
    ga.add_node(ASGNode(id="X", name="X", kind=NodeKind.CLASS))
    ga.add_edge(ASGEdge(source_id="X", target_id="Y", kind=EdgeKind.INHERITS))
    gb = ASGGraph()
    gb.add_node(ASGNode(id="Y", name="Y", kind=NodeKind.ENTITY))
    gb.add_edge(ASGEdge(source_id="Y", target_id="Z", kind=EdgeKind.HAS_MANY))
    ga.merge(gb)
    check("graph_merge", ga.get_node("Y") is not None and len(ga.edges) == 2)
    ga.merge(None)
    check("graph_merge_none", len(ga.nodes) == 2)

    # Serialization roundtrip
    gser = ASGGraph()
    gser.add_node(ASGNode(id="User", name="User", kind=NodeKind.ENTITY,
                          attributes=[ASGAttribute(name="id", type_annotation="int", is_primary_key=True)]))
    gser.add_node(ASGNode(id="Post", name="Post", kind=NodeKind.ENTITY))
    gser.add_edge(ASGEdge(source_id="User", target_id="Post", kind=EdgeKind.HAS_MANY, label="posts"))
    d_ser = gser.to_dict()
    grest = ASGGraph.from_dict(d_ser)
    check("graph_ser_roundtrip",
          grest.get_node("User") is not None
          and grest.get_node("User").attributes[0].is_primary_key is True
          and len(grest.edges) == 1
          and grest.edges[0].kind == EdgeKind.HAS_MANY)

    # Thread safety
    print("--- Thread Safety ---")
    gt = ASGGraph()
    thread_errors = []
    def worker(start):
        try:
            for i in range(50):
                nid = f"Node_{start}_{i}"
                gt.add_node(ASGNode(id=nid, name=nid, kind=NodeKind.CLASS))
                if i > 0:
                    prev = f"Node_{start}_{i - 1}"
                    gt.add_edge(ASGEdge(source_id=prev, target_id=nid, kind=EdgeKind.DEPENDS_ON))
        except Exception as exc:
            thread_errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()
    check("thread_safety_no_errors", thread_errors == [])
    check("thread_safety_node_count", len(gt.nodes) == 200)

    # ══════════════ ASGToMermaidRenderer ══════════════
    print("--- ASGToMermaidRenderer ---")
    ge = ASGGraph()
    check("mermaid_uml_empty", ASGToMermaidRenderer.render_uml(ge).startswith("classDiagram"))
    check("mermaid_er_empty", ASGToMermaidRenderer.render_er(ge).startswith("erDiagram"))

    gu = ASGGraph()
    gu.add_node(ASGNode(id="User", name="User", kind=NodeKind.CLASS,
                        attributes=[ASGAttribute(name="name", type_annotation="str")],
                        methods=[ASGMethod(name="save", return_type="None")]))
    uml_out = ASGToMermaidRenderer.render_uml(gu)
    check("mermaid_uml_class", "class User" in uml_out and "name" in uml_out and "save" in uml_out)

    gi = ASGGraph()
    gi.add_node(ASGNode(id="IRepo", name="IRepo", kind=NodeKind.INTERFACE))
    check("mermaid_uml_interface", "<<interface>>" in ASGToMermaidRenderer.render_uml(gi))

    ginh = ASGGraph()
    ginh.add_node(ASGNode(id="Animal", name="Animal", kind=NodeKind.CLASS))
    ginh.add_node(ASGNode(id="Dog", name="Dog", kind=NodeKind.CLASS))
    ginh.add_edge(ASGEdge(source_id="Dog", target_id="Animal", kind=EdgeKind.INHERITS))
    check("mermaid_uml_inherit", "Animal <|-- Dog" in ASGToMermaidRenderer.render_uml(ginh))

    gdep = ASGGraph()
    gdep.add_node(ASGNode(id="Svc", name="Svc", kind=NodeKind.SERVICE))
    gdep.add_node(ASGNode(id="Repo", name="Repo", kind=NodeKind.CLASS))
    gdep.add_edge(ASGEdge(source_id="Svc", target_id="Repo", kind=EdgeKind.DEPENDS_ON))
    check("mermaid_uml_depends", "Svc ..> Repo" in ASGToMermaidRenderer.render_uml(gdep))

    ger = ASGGraph()
    ger.add_node(ASGNode(id="User", name="User", kind=NodeKind.ENTITY,
                         attributes=[ASGAttribute(name="id", type_annotation="int", is_primary_key=True),
                                     ASGAttribute(name="email", type_annotation="string")]))
    er_out = ASGToMermaidRenderer.render_er(ger)
    check("mermaid_er_entity", "USER" in er_out and "int id PK" in er_out and "string email" in er_out)

    gfk = ASGGraph()
    gfk.add_node(ASGNode(id="Post", name="Post", kind=NodeKind.ENTITY,
                         attributes=[ASGAttribute(name="user_id", type_annotation="int")]))
    check("mermaid_er_fk", "FK" in ASGToMermaidRenderer.render_er(gfk))

    grel = ASGGraph()
    grel.add_node(ASGNode(id="User", name="User", kind=NodeKind.ENTITY))
    grel.add_node(ASGNode(id="Post", name="Post", kind=NodeKind.ENTITY))
    grel.add_edge(ASGEdge(source_id="User", target_id="Post", kind=EdgeKind.HAS_MANY, label="posts"))
    er_rel = ASGToMermaidRenderer.render_er(grel)
    check("mermaid_er_relationship", "USER ||--|{" in er_rel and '"posts"' in er_rel)

    # ══════════════ ASGToJsonExporter ══════════════
    print("--- ASGToJsonExporter ---")
    gj = ASGGraph()
    gj.add_node(ASGNode(id="X", name="X", kind=NodeKind.CLASS))
    gj.add_edge(ASGEdge(source_id="X", target_id="Y", kind=EdgeKind.DEPENDS_ON))
    raw_json = ASGToJsonExporter.export_json(gj)
    parsed = json.loads(raw_json)
    check("json_export_valid", "nodes" in parsed and "edges" in parsed and len(parsed["nodes"]) == 1)

    gm = ASGGraph()
    gm.add_node(ASGNode(id="A", name="A", kind=NodeKind.MODULE))
    check("json_to_dict", ASGToJsonExporter.to_dict(gm)["nodes"][0]["kind"] == "MODULE")

    # ══════════════ ASGBuilder ══════════════
    print("--- ASGBuilder ---")

    # from_uml_classes
    classes = [{
        "name": "UserService", "module": "app.services", "is_interface": False,
        "attributes": [{"name": "repo", "type_annotation": "UserRepo"}],
        "methods": [{"name": "create_user", "parameters": ["data"]}],
        "parents": ["BaseService"], "dependencies": ["UserRepo"],
    }]
    gb = ASGBuilder.from_uml_classes(classes)
    n = gb.get_node("app.services.UserService")
    check("builder_uml_node", n is not None and n.kind == NodeKind.CLASS)
    check("builder_uml_attrs", len(n.attributes) == 1)
    check("builder_uml_edges", len(gb.edges) == 2)
    edge_kinds = {e.kind for e in gb.edges}
    check("builder_uml_edge_kinds", EdgeKind.INHERITS in edge_kinds and EdgeKind.DEPENDS_ON in edge_kinds)

    # Interface
    ifc = [{"name": "IRepository", "is_interface": True, "parents": ["IBase"]}]
    gi2 = ASGBuilder.from_uml_classes(ifc)
    check("builder_interface", gi2.get_node("IRepository").kind == NodeKind.INTERFACE)
    check("builder_interface_edge", gi2.edges[0].kind == EdgeKind.IMPLEMENTS)

    # String attrs/methods
    simple = [{"name": "Simple", "attributes": ["x", "y"], "methods": ["run"]}]
    gs = ASGBuilder.from_uml_classes(simple)
    check("builder_string_attrs", len(gs.get_node("Simple").attributes) == 2)
    check("builder_string_methods", gs.get_node("Simple").methods[0].name == "run")

    # Skip empty name
    empty_name = [{"name": ""}, {"name": "Valid"}]
    ge2 = ASGBuilder.from_uml_classes(empty_name)
    check("builder_skip_empty", len(ge2.nodes) == 1)

    # Merge into existing graph
    gex = ASGGraph()
    gex.add_node(ASGNode(id="Existing", name="Existing", kind=NodeKind.CLASS))
    ASGBuilder.from_uml_classes([{"name": "New", "module": "pkg"}], graph=gex)
    check("builder_merge_existing", gex.get_node("Existing") is not None and gex.get_node("pkg.New") is not None)

    # from_er_entities
    entities = [
        {"name": "User", "columns": [
            {"name": "id", "type_annotation": "int", "is_primary_key": True},
            {"name": "email", "type_annotation": "varchar"}]},
        {"name": "Post", "columns": [{"name": "id"}]},
    ]
    rels = [{"source": "User", "target": "Post", "kind": "HAS_MANY", "label": "posts"}]
    ger2 = ASGBuilder.from_er_entities(entities, rels)
    check("builder_er_entity", ger2.get_node("User").kind == NodeKind.ENTITY)
    check("builder_er_pk", ger2.get_node("User").attributes[0].is_primary_key is True)
    check("builder_er_edge", len(ger2.edges) == 1 and ger2.edges[0].kind == EdgeKind.HAS_MANY)

    # String columns
    str_ents = [{"name": "Tag", "columns": ["id", "label"]}]
    gstr = ASGBuilder.from_er_entities(str_ents)
    check("builder_er_string_cols", len(gstr.get_node("Tag").attributes) == 2)

    # from_routes
    routes = [
        {"path": "/api/users", "method": "GET", "handler": "list_users", "file": "views.py"},
        {"path": "/api/users", "method": "POST", "handler": "create_user", "file": "views.py"},
    ]
    gr = ASGBuilder.from_routes(routes)
    check("builder_routes_count", len(gr.nodes) == 2)
    rn = gr.get_node("GET /api/users")
    check("builder_routes_endpoint", rn is not None and rn.kind == NodeKind.ENDPOINT)
    check("builder_routes_meta", rn.metadata["handler"] == "list_users")

    # Skip empty path
    empty_routes = [{"path": "", "method": "GET"}, {"path": "/ok", "method": "GET"}]
    ger3 = ASGBuilder.from_routes(empty_routes)
    check("builder_routes_skip_empty", len(ger3.nodes) == 1)

    # ══════════════ Integration Wiring ══════════════
    print("--- Integration Wiring ---")
    from bck_nd_hlpr.core.base_analyzer import ScanContext, AnalyzerResult
    ctx = ScanContext(path="/tmp")
    check("scancontext_asg", ctx.asg_graph is None)

    ar = AnalyzerResult()
    check("analyzerresult_asg", ar.asg_graph is None)
    ar.asg_graph = ASGGraph()
    check("analyzerresult_asg_set", ar.asg_graph is not None)

    from bck_nd_hlpr.core.orchestrator import OrchestratorResult
    orr = OrchestratorResult(path="/t", framework="t", architecture="t", features=[], summary="t")
    check("orchestrator_asg", orr.asg_graph is None)

    # ══════════════ Summary ══════════════
    total = passed + failed
    print(f"\n{'='*60}")
    print(f"  RESULTS: {passed}/{total} passed, {failed} failed")
    print(f"{'='*60}")
    if errors:
        print("\nFailures:")
        for e in errors:
            print(f"  ✗ {e}")
    else:
        print("\n  ✓ All tests passed!")
    
    return failed == 0

if __name__ == "__main__":
    try:
        success = run_tests()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        traceback.print_exc()
        sys.exit(2)
