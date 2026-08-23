"""Go and Rust UML parity tests for the v2.4.3 compiled-backend sprint."""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from bck_nd_hlpr.core.asg.builder import ASGBuilder
from bck_nd_hlpr.core.asg.nodes import NodeKind
from bck_nd_hlpr.core.go_parser import (
    GoUMLVisitor,
    parse_go_content,
    parse_project_for_go_uml,
)
from bck_nd_hlpr.core.rust_parser import (
    RustUMLVisitor,
    parse_project_for_rust_uml,
    parse_rust_content,
)


GO_SOURCE = textwrap.dedent(
    """\
    package service

    import "database/sql"

    type UserService struct {
        db *sql.DB
        cache map[string]*User
    }

    func (s *UserService) GetUser(id string) (*User, error) {
        return nil, nil
    }

    type UserRepository interface {
        GetUser(id string) (*User, error)
        Save(user *User) error
    }
    """
)


RUST_SOURCE = textwrap.dedent(
    """\
    pub struct OrderService {
        repo: Repository,
        retries: usize,
    }

    impl OrderService {
        pub fn create_order(&self, amount: f64) -> Result<Order, Error> {
            todo!()
        }
    }

    pub enum OrderStatus {
        Pending,
        Paid,
        Failed(String),
    }

    pub trait OrderRepository {
        fn save(&self, order: Order) -> Result<(), Error>;
    }
    """
)


class _SourceNode:
    """Small tree-sitter node stand-in for visitor unit tests."""

    def __init__(self, source: bytes):
        self.start_byte = 0
        self.end_byte = len(source)


def test_go_struct_fields_and_receiver_method(tmp_path: Path):
    (tmp_path / "service.go").write_text(GO_SOURCE, encoding="utf-8")

    classes = parse_project_for_go_uml(str(tmp_path), max_depth=1)
    service = next(item for item in classes if item.name == "UserService")

    assert any("db" in attr and "sql.DB" in attr for attr in service.attributes)
    assert any("cache" in attr and "map[string]*User" in attr for attr in service.attributes)
    assert any(
        "GetUser" in method and "id string" in method and "*User" in method
        for method in service.methods
    )


def test_go_interface_is_emitted_as_interface_node():
    repository = next(
        item for item in parse_go_content(GO_SOURCE, "service")
        if item.name == "UserRepository"
    )

    assert repository.is_interface is True
    assert "interface" in repository.stereotypes
    assert any("GetUser" in method for method in repository.methods)
    assert any("Save" in method for method in repository.methods)


def test_go_balanced_fallback_ignores_fake_declarations_in_comments(monkeypatch):
    import bck_nd_hlpr.core.go_parser as go_parser

    monkeypatch.setattr(go_parser, "PARSER", None)
    source = textwrap.dedent(
        """\
        // type Fake struct { broken string }
        type Real struct {
            Label string `json:"label"`
        }
        func (r *Real) Render() string { return "}" }
        """
    )

    classes = go_parser.parse_go_content(source)
    assert [item.name for item in classes] == ["Real"]
    assert any("Label" in attr for attr in classes[0].attributes)
    assert any("Render" in method for method in classes[0].methods)


def test_go_tree_sitter_type_spec_visitor_accepts_keywordless_node():
    source = b"UserService struct { db *sql.DB }"
    visitor = GoUMLVisitor(source, "service")

    visitor.visit_type_spec(_SourceNode(source))

    service = visitor.finish()[0]
    assert service.name == "UserService"
    assert any("db" in attr and "sql.DB" in attr for attr in service.attributes)


def test_go_receiver_method_merges_across_package_files(tmp_path: Path):
    (tmp_path / "service.go").write_text(
        "package service\ntype UserService struct { db *sql.DB }\n",
        encoding="utf-8",
    )
    (tmp_path / "service_methods.go").write_text(
        "package service\nfunc (s *UserService) GetUser(id string) error { return nil }\n",
        encoding="utf-8",
    )

    classes = parse_project_for_go_uml(str(tmp_path), max_depth=1)
    service = next(item for item in classes if item.name == "UserService")

    assert any("GetUser" in method for method in service.methods)


def test_rust_struct_fields_and_impl_method(tmp_path: Path):
    (tmp_path / "service.rs").write_text(RUST_SOURCE, encoding="utf-8")

    classes = parse_project_for_rust_uml(str(tmp_path), max_depth=1)
    service = next(item for item in classes if item.name == "OrderService")

    assert any("repo" in attr and "Repository" in attr for attr in service.attributes)
    assert any(
        "create_order" in method
        and "amount: f64" in method
        and "Result<Order, Error>" in method
        for method in service.methods
    )


def test_rust_enum_and_trait_extraction():
    classes = parse_rust_content(RUST_SOURCE, "orders")
    status = next(item for item in classes if item.name == "OrderStatus")
    repository = next(item for item in classes if item.name == "OrderRepository")

    assert any("Pending" in attr for attr in status.attributes)
    assert any("Failed" in attr for attr in status.attributes)
    assert repository.is_interface is True
    assert "trait" in repository.stereotypes
    assert any("save" in method for method in repository.methods)


def test_rust_balanced_fallback_ignores_strings_and_comments(monkeypatch):
    import bck_nd_hlpr.core.rust_parser as rust_parser

    monkeypatch.setattr(rust_parser, "PARSER", None)
    source = textwrap.dedent(
        """\
        // struct Fake { value: String }
        pub struct Real { value: String }
        impl Real {
            pub fn render(&self) -> String { "}".to_string() }
        }
        """
    )

    classes = rust_parser.parse_rust_content(source)
    assert [item.name for item in classes] == ["Real"]
    assert any("render" in method for method in classes[0].methods)


def test_rust_tree_sitter_struct_visitor_emits_descriptor():
    source = b"pub struct OrderService { repo: Repository }"
    visitor = RustUMLVisitor(source, "orders")

    visitor.visit_struct_item(_SourceNode(source))

    service = visitor.finish()[0]
    assert service.name == "OrderService"
    assert any("repo" in attr and "Repository" in attr for attr in service.attributes)


def test_rust_impl_method_merges_across_module_files(tmp_path: Path):
    (tmp_path / "service.rs").write_text(
        "pub struct OrderService { repo: Repository }\n",
        encoding="utf-8",
    )
    (tmp_path / "service_impl.rs").write_text(
        "impl OrderService { pub fn create(&self) -> Result<(), Error> { todo!() } }\n",
        encoding="utf-8",
    )

    classes = parse_project_for_rust_uml(str(tmp_path), max_depth=1)
    service = next(item for item in classes if item.name == "OrderService")

    assert any("create" in method for method in service.methods)


def test_project_scanner_combines_go_and_rust_uml(tmp_path: Path):
    from bck_nd_hlpr.core.scanner import ProjectScanner

    (tmp_path / "service.go").write_text(GO_SOURCE, encoding="utf-8")
    (tmp_path / "orders.rs").write_text(RUST_SOURCE, encoding="utf-8")

    diagram = ProjectScanner().scan_uml(str(tmp_path), max_depth=1)
    assert "class UserService" in diagram
    assert "class OrderService" in diagram
    assert "GetUser" in diagram
    assert "create_order" in diagram


def test_go_and_rust_models_flow_into_asg():
    classes = parse_go_content(GO_SOURCE, "go.service")
    classes.extend(parse_rust_content(RUST_SOURCE, "rust.orders"))

    graph = ASGBuilder.from_uml_classes(classes)
    nodes = {node.name: node for node in graph.nodes.values()}

    assert nodes["UserService"].metadata["language"] == "go"
    assert nodes["OrderService"].metadata["language"] == "rust"
    assert nodes["UserRepository"].kind == NodeKind.INTERFACE
    assert nodes["OrderRepository"].kind == NodeKind.INTERFACE


def test_mcp_asg_graph_includes_compiled_models(tmp_path: Path):
    from bck_nd_hlpr.cli.mcp_server import get_asg_graph

    (tmp_path / "service.go").write_text(GO_SOURCE, encoding="utf-8")
    (tmp_path / "orders.rs").write_text(RUST_SOURCE, encoding="utf-8")

    payload = json.loads(get_asg_graph(root_path=str(tmp_path), depth=1))
    names = {node["name"] for node in payload["nodes"]}

    assert "UserService" in names
    assert "OrderService" in names


@pytest.mark.parametrize(
    ("framework", "family"),
    [
        ("gin", "go"),
        ("Fiber", "go"),
        ("Go", "go"),
        ("actix-web", "rust"),
        ("actix", "rust"),
        ("Rocket", "rust"),
        ("Rust", "rust"),
    ],
)
def test_compiled_frameworks_route_to_expected_uml_family(framework: str, family: str):
    from bck_nd_hlpr.core.analysis import _match_fw

    assert _match_fw(framework) == family
