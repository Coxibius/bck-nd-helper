"""Tests for TypeScript interface & type alias extraction in JS/TS UML parsing."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from bck_nd_hlpr.core.js_parser import (
    JSUMLVisitor,
    TS_PARSER,
    TSX_PARSER,
    PARSER,
    _parser_for_file,
    parse_project_for_js_uml,
)
from bck_nd_hlpr.core.uml_parser import UMLClassInfo

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_ts_source(source: str, *, ext: str = ".ts") -> list[UMLClassInfo]:
    """Parse a TypeScript source string and return extracted UML classes."""
    parser = _parser_for_file(f"test{ext}")
    assert parser is not None, f"No parser available for {ext} files"
    source_bytes = source.encode("utf-8")
    tree = parser.parse(source_bytes)
    visitor = JSUMLVisitor(source_bytes, "test_module")
    visitor.visit(tree.root_node)
    visitor._extract_ts_interfaces_and_types_from_source()
    return visitor.classes


# ---------------------------------------------------------------------------
# Tests — Grammar availability
# ---------------------------------------------------------------------------

class TestGrammarAvailability:
    """Verify that TypeScript grammars loaded successfully."""

    def test_ts_parser_loaded(self):
        assert TS_PARSER is not None, "tree-sitter-typescript parser should be available"

    def test_tsx_parser_loaded(self):
        assert TSX_PARSER is not None, "tree-sitter-typescript TSX parser should be available"

    def test_js_parser_loaded(self):
        assert PARSER is not None, "tree-sitter-javascript parser should be available"


# ---------------------------------------------------------------------------
# Tests — _parser_for_file routing
# ---------------------------------------------------------------------------

class TestParserRouting:
    """Verify that _parser_for_file selects the correct grammar."""

    def test_ts_file_uses_ts_parser(self):
        p = _parser_for_file("src/models/user.ts")
        assert p is TS_PARSER

    def test_tsx_file_uses_tsx_parser(self):
        p = _parser_for_file("components/App.tsx")
        assert p is TSX_PARSER

    def test_js_file_uses_js_parser(self):
        p = _parser_for_file("index.js")
        assert p is PARSER

    def test_jsx_file_uses_js_parser(self):
        p = _parser_for_file("App.jsx")
        assert p is PARSER


# ---------------------------------------------------------------------------
# Tests — Interface extraction
# ---------------------------------------------------------------------------

class TestInterfaceExtraction:
    """Verify that TypeScript interfaces are extracted as UMLClassInfo."""

    def test_simple_interface(self):
        source = textwrap.dedent("""\
            interface ConsumptionRecord {
                id: string;
                anxietyLevel: number;
            }
        """)
        classes = _parse_ts_source(source)
        names = [c.name for c in classes]
        assert "ConsumptionRecord" in names
        cr = next(c for c in classes if c.name == "ConsumptionRecord")
        assert "interface" in (getattr(cr, "stereotypes", None) or [])
        attr_text = " ".join(cr.attributes)
        assert "id" in attr_text
        assert "anxietyLevel" in attr_text

    def test_exported_interface(self):
        source = textwrap.dedent("""\
            export interface UserProfile {
                username: string;
                email: string;
                age: number;
            }
        """)
        classes = _parse_ts_source(source)
        names = [c.name for c in classes]
        assert "UserProfile" in names
        up = next(c for c in classes if c.name == "UserProfile")
        assert len(up.attributes) >= 3

    def test_interface_with_extends(self):
        source = textwrap.dedent("""\
            interface Animal {
                name: string;
            }
            interface Dog extends Animal {
                breed: string;
            }
        """)
        classes = _parse_ts_source(source)
        dog = next(c for c in classes if c.name == "Dog")
        assert "Animal" in dog.bases

    def test_interface_with_methods(self):
        source = textwrap.dedent("""\
            interface Repository {
                findById(id: string): Promise<Entity>;
                save(entity: Entity): void;
            }
        """)
        classes = _parse_ts_source(source)
        repo = next(c for c in classes if c.name == "Repository")
        assert len(repo.methods) >= 2


# ---------------------------------------------------------------------------
# Tests — Type alias extraction
# ---------------------------------------------------------------------------

class TestTypeAliasExtraction:
    """Verify that TypeScript type aliases with object shapes are extracted."""

    def test_simple_type_alias(self):
        source = textwrap.dedent("""\
            type Config = {
                host: string;
                port: number;
                debug: boolean;
            };
        """)
        classes = _parse_ts_source(source)
        names = [c.name for c in classes]
        assert "Config" in names
        cfg = next(c for c in classes if c.name == "Config")
        assert "type" in (getattr(cfg, "stereotypes", None) or [])
        assert len(cfg.attributes) >= 3

    def test_exported_type_alias(self):
        source = textwrap.dedent("""\
            export type ApiResponse = {
                status: number;
                data: any;
                error?: string;
            };
        """)
        classes = _parse_ts_source(source)
        names = [c.name for c in classes]
        assert "ApiResponse" in names


# ---------------------------------------------------------------------------
# Tests — Mixed TS file
# ---------------------------------------------------------------------------

class TestMixedTypeScriptFile:
    """Test a file containing classes, interfaces, and types together."""

    def test_all_constructs_extracted(self):
        source = textwrap.dedent("""\
            export class UserService {
                getUser(id: string): User {
                    return {} as User;
                }
            }

            export interface User {
                id: string;
                name: string;
            }

            export type CreateUserDto = {
                name: string;
                email: string;
            };
        """)
        classes = _parse_ts_source(source)
        names = {c.name for c in classes}
        assert "UserService" in names
        assert "User" in names
        assert "CreateUserDto" in names


# ---------------------------------------------------------------------------
# Tests — TSX files
# ---------------------------------------------------------------------------

class TestTSXExtraction:
    """Verify TypeScript extraction works in .tsx files."""

    def test_interface_in_tsx(self):
        source = textwrap.dedent("""\
            interface Props {
                title: string;
                count: number;
            }

            const MyComponent = (props: Props) => {
                return <div>{props.title}</div>;
            };
        """)
        classes = _parse_ts_source(source, ext=".tsx")
        names = [c.name for c in classes]
        assert "Props" in names


# ---------------------------------------------------------------------------
# Tests — Mermaid output integration
# ---------------------------------------------------------------------------

class TestMermaidIntegration:
    """Verify the end-to-end flow produces valid Mermaid classDiagram content."""

    def test_interface_produces_mermaid_class(self, tmp_path: Path):
        ts_file = tmp_path / "models.ts"
        ts_file.write_text(textwrap.dedent("""\
            interface ConsumptionRecord {
                id: string;
                anxietyLevel: number;
            }
        """), encoding="utf-8")

        classes = parse_project_for_js_uml(str(tmp_path), max_depth=1)
        names = [c.name for c in classes]
        assert "ConsumptionRecord" in names, (
            f"Expected ConsumptionRecord in {names}"
        )

    def test_exported_interface_produces_mermaid_class(self, tmp_path: Path):
        ts_file = tmp_path / "types.ts"
        ts_file.write_text(textwrap.dedent("""\
            export interface ConsumptionRecord {
                id: string;
                anxietyLevel: number;
            }
        """), encoding="utf-8")

        classes = parse_project_for_js_uml(str(tmp_path), max_depth=1)
        names = [c.name for c in classes]
        assert "ConsumptionRecord" in names

    def test_type_alias_produces_mermaid_class(self, tmp_path: Path):
        ts_file = tmp_path / "config.ts"
        ts_file.write_text(textwrap.dedent("""\
            export type AppConfig = {
                apiUrl: string;
                timeout: number;
            };
        """), encoding="utf-8")

        classes = parse_project_for_js_uml(str(tmp_path), max_depth=1)
        names = [c.name for c in classes]
        assert "AppConfig" in names

    def test_tsx_file_produces_mermaid_class(self, tmp_path: Path):
        tsx_file = tmp_path / "Component.tsx"
        tsx_file.write_text(textwrap.dedent("""\
            interface CardProps {
                title: string;
                description: string;
            }
            export const Card = ({ title, description }: CardProps) => {
                return <div>{title}</div>;
            };
        """), encoding="utf-8")

        classes = parse_project_for_js_uml(str(tmp_path), max_depth=1)
        names = [c.name for c in classes]
        assert "CardProps" in names
