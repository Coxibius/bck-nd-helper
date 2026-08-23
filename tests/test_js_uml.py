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
        cr = next(c for c in classes if c.name == "ConsumptionRecord")
        assert any("id" in attr for attr in cr.attributes)
        assert any("anxietyLevel" in attr for attr in cr.attributes)

        from bck_nd_hlpr.core.uml_parser import generate_mermaid_class_diagram
        mermaid_code = generate_mermaid_class_diagram(classes)
        assert "classDiagram" in mermaid_code
        assert "class ConsumptionRecord" in mermaid_code
        assert "+string id" in mermaid_code or "+id" in mermaid_code
        assert "+number anxietyLevel" in mermaid_code or "+anxietyLevel" in mermaid_code

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

    def test_regex_fallback_when_parser_is_none(self, tmp_path: Path, monkeypatch):
        """Verify that interfaces are still extracted even if parser is unavailable."""
        ts_file = tmp_path / "types.ts"
        ts_file.write_text(textwrap.dedent("""\
            export interface ConsumptionRecord {
                id: string;
                anxietyLevel: number;
            }
        """), encoding="utf-8")

        import bck_nd_hlpr.core.js_parser as jp
        monkeypatch.setattr(jp, "_parser_for_file", lambda f: None)

        classes = parse_project_for_js_uml(str(tmp_path), max_depth=1)
        names = [c.name for c in classes]
        assert "ConsumptionRecord" in names
        cr = next(c for c in classes if c.name == "ConsumptionRecord")
        assert any("id" in attr for attr in cr.attributes)
        assert any("anxietyLevel" in attr for attr in cr.attributes)


# ---------------------------------------------------------------------------
# Tests — Formatters & CLI Guard
# ---------------------------------------------------------------------------

class TestUMLFormatters:
    """Verify format_uml_diagram behavior for empty vs valid UML."""

    def test_format_uml_diagram_with_content(self):
        from bck_nd_hlpr.cli.formatters import format_uml_diagram
        content = "classDiagram\n    class User {\n        +string name\n    }"
        assert format_uml_diagram(content) == content

    def test_format_uml_diagram_empty_or_none(self):
        from bck_nd_hlpr.cli.formatters import format_uml_diagram
        assert format_uml_diagram(None) == "[--] No classes or TypeScript interfaces detected."
        assert format_uml_diagram("") == "[--] No classes or TypeScript interfaces detected."
        assert format_uml_diagram("classDiagram\n    note \"No classes found in scanned directories.\"") == "[--] No classes or TypeScript interfaces detected."

    def test_format_uml_diagram_keeps_class_names_starting_with_empty(self):
        from bck_nd_hlpr.cli.formatters import format_uml_diagram

        content = "classDiagram\n    class EmptyState {\n        +string reason\n    }"
        assert format_uml_diagram(content) == content

    @pytest.mark.parametrize("scan_args", [["--uml"], []])
    def test_cli_keeps_empty_prefixed_class_in_single_and_full_scan(
        self, tmp_path: Path, monkeypatch, scan_args: list[str]
    ):
        from typer.testing import CliRunner
        from bck_nd_hlpr.cli.cli import app
        from bck_nd_hlpr.core.orchestrator import OrchestratorResult, ScannerOrchestrator

        diagram = "classDiagram\n    class EmptyState {\n        +string reason\n    }"

        def fake_run(config):
            return OrchestratorResult(
                path=str(tmp_path),
                framework="Unknown",
                architecture="",
                features=[],
                summary="",
                uml=diagram,
                todos=[],
                requirements=[],
            )

        monkeypatch.setattr(ScannerOrchestrator, "run", staticmethod(fake_run))

        result = CliRunner().invoke(app, ["scan", str(tmp_path), *scan_args])

        assert result.exit_code == 0, result.exception
        assert "class EmptyState" in result.stdout
        assert "No classes or TypeScript interfaces detected" not in result.stdout


# ---------------------------------------------------------------------------
# Tests — Project Structure & Types Files Discovery
# ---------------------------------------------------------------------------

class TestProjectTypesDiscovery:
    """Verify that lib/types.ts, src/types.ts, and types/*.ts are discovered and parsed."""

    def test_lib_types_ts_scanned(self, tmp_path: Path):
        lib_dir = tmp_path / "lib"
        lib_dir.mkdir(parents=True, exist_ok=True)
        ts_file = lib_dir / "types.ts"
        ts_file.write_text(textwrap.dedent("""\
            export interface ConsumptionRecord {
                id: string;
                anxietyLevel: number;
            }
        """), encoding="utf-8")

        classes = parse_project_for_js_uml(str(tmp_path), max_depth=3)
        names = [c.name for c in classes]
        assert "ConsumptionRecord" in names
        cr = next(c for c in classes if c.name == "ConsumptionRecord")
        assert any("id" in attr for attr in cr.attributes)
        assert any("anxietyLevel" in attr for attr in cr.attributes)

    def test_types_directory_and_name_hints(self, tmp_path: Path):
        types_dir = tmp_path / "types"
        types_dir.mkdir(parents=True, exist_ok=True)
        ts_file = types_dir / "schema.ts"
        ts_file.write_text(textwrap.dedent("""\
            export interface UserEntity {
                id: string;
                email: string;
            }
        """), encoding="utf-8")

        other_file = tmp_path / "utils" / "helper.ts"
        other_file.parent.mkdir(parents=True, exist_ok=True)
        other_file.write_text(textwrap.dedent("""\
            export interface HelperConfig {
                verbose: boolean;
            }
        """), encoding="utf-8")

        # Scan with explicit name hints
        classes = parse_project_for_js_uml(
            str(tmp_path),
            max_depth=3,
            name_hints=["type", "types", "schema"]
        )
        names = [c.name for c in classes]
        assert "UserEntity" in names
        assert "HelperConfig" not in names

    def test_typescript_nextjs_types_extraction(self, tmp_path: Path):
        lib_dir = tmp_path / "lib"
        lib_dir.mkdir(parents=True, exist_ok=True)
        types_file = lib_dir / "types.ts"
        types_file.write_text(textwrap.dedent("""\
            export interface ConsumptionRecord {
              id: string;
              timestamp: number;
              anxietyLevel: number;
              trigger?: string;
            }

            export type UserProfile = {
              uid: string;
              email: string;
              dailyLimit: number;
            }
        """), encoding="utf-8")

        classes = parse_project_for_js_uml(str(tmp_path), max_depth=3)
        names = [c.name for c in classes]
        assert "ConsumptionRecord" in names
        assert "UserProfile" in names

        cr = next(c for c in classes if c.name == "ConsumptionRecord")
        assert "interface" in (getattr(cr, "stereotypes", None) or [])
        assert any("id" in attr and "string" in attr for attr in cr.attributes)
        assert any("timestamp" in attr and "number" in attr for attr in cr.attributes)
        assert any("anxietyLevel" in attr and "number" in attr for attr in cr.attributes)
        assert any("trigger" in attr and "string" in attr for attr in cr.attributes)
        assert not any("?" in attr for attr in cr.attributes)
        assert len(cr.attributes) == 4

        up = next(c for c in classes if c.name == "UserProfile")
        assert "type" in (getattr(up, "stereotypes", None) or [])
        assert any("uid" in attr and "string" in attr for attr in up.attributes)
        assert any("email" in attr and "string" in attr for attr in up.attributes)
        assert any("dailyLimit" in attr and "number" in attr for attr in up.attributes)
        assert len(up.attributes) == 3

    def test_typescript_generics_escaping(self, tmp_path: Path):
        lib_dir = tmp_path / "lib"
        lib_dir.mkdir(parents=True, exist_ok=True)
        types_file = lib_dir / "models.ts"
        types_file.write_text(textwrap.dedent("""\
            export interface ApiResponse {
              data: Promise<string>;
              items: Array<string>;
              fetchList?(tags: List<string>): Promise<Array<string>>;
            }
        """), encoding="utf-8")

        classes = parse_project_for_js_uml(str(tmp_path), max_depth=3)
        names = [c.name for c in classes]
        assert "ApiResponse" in names
        api = next(c for c in classes if c.name == "ApiResponse")
        for attr in api.attributes:
            assert "<" not in attr and ">" not in attr
        for meth in api.methods:
            assert "<" not in meth and ">" not in meth
            assert "?" not in meth
        assert any("Promise~string~" in attr for attr in api.attributes)
        assert any("Array~string~" in attr for attr in api.attributes)

    def test_parse_js_content_and_parse_file_for_js_uml(self, tmp_path: Path):
        from bck_nd_hlpr.core.js_parser import parse_js_content, parse_file_for_js_uml

        ts_code = textwrap.dedent("""\
            export interface AuthSession {
              token: string;
              expiresAt: number;
            }
        """)
        classes = parse_js_content(ts_code, "auth.ts")
        assert len(classes) == 1
        assert classes[0].name == "AuthSession"

        file_p = tmp_path / "auth.ts"
        file_p.write_text(ts_code, encoding="utf-8")
        file_classes = parse_file_for_js_uml(file_p)
        assert len(file_classes) == 1
        assert file_classes[0].name == "AuthSession"

    def test_regex_fallback_handles_complex_nested_types_and_generics(self, tmp_path: Path, monkeypatch):
        """Verify regex fallback extracts types with generics, nested types, and methods when parser is None."""
        import bck_nd_hlpr.core.js_parser as jp
        monkeypatch.setattr(jp, "_parser_for_file", lambda f: None)

        ts_file = tmp_path / "complex.ts"
        ts_file.write_text(textwrap.dedent("""\
            export interface User<T = any> extends BaseEntity, Auditable<T> {
              id: string;
              name: string;
              profile?: {
                bio: string;
                avatarUrl: string;
              };
              login(credentials: any): Promise<boolean>;
            }

            export type AppState<S> = {
              user: User | null;
              isLoading: boolean;
            };
        """), encoding="utf-8")

        classes = jp.parse_project_for_js_uml(str(tmp_path), max_depth=1)
        names = {c.name for c in classes}
        assert "User" in names
        assert "AppState" in names

        user = next(c for c in classes if c.name == "User")
        assert "BaseEntity" in user.bases
        assert "Auditable" in user.bases
        assert any("id" in a for a in user.attributes)
        assert any("login" in m for m in user.methods)

    def test_nextjs_full_project_simulation_with_scan_uml(self, tmp_path: Path):
        """Simulate real Next.js project structure and verify scan_uml generates diagram."""
        from bck_nd_hlpr.core.scanner import ProjectScanner

        lib_dir = tmp_path / "lib"
        lib_dir.mkdir(parents=True)
        (lib_dir / "types.ts").write_text(textwrap.dedent("""\
            export interface ConsumptionRecord {
              id: string;
              timestamp: number;
              anxietyLevel: number;
              trigger?: string;
            }

            export type UserProfile = {
              uid: string;
              email: string;
              dailyLimit: number;
            };
        """), encoding="utf-8")

        (lib_dir / "store.ts").write_text(textwrap.dedent("""\
            export interface AppState {
              version: number;
              reset(): void;
            }
        """), encoding="utf-8")

        app_dir = tmp_path / "app" / "dashboard"
        app_dir.mkdir(parents=True)
        (app_dir / "page.tsx").write_text(textwrap.dedent("""\
            interface DashboardProps {
              title: string;
            }
            export default function Dashboard({ title }: DashboardProps) {
              return <div>{title}</div>;
            }
        """), encoding="utf-8")

        scanner = ProjectScanner()
        uml = scanner.scan_uml(str(tmp_path), max_depth=4)

        assert "classDiagram" in uml
        assert "ConsumptionRecord" in uml
        assert "UserProfile" in uml
        assert "AppState" in uml
        assert "DashboardProps" in uml
        assert "[--] No classes" not in uml
