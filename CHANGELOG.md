# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.5.0] - 2026-08-27

### Added

- **Local-first PRD Intelligence:** Human-authored Markdown product documents with YAML front matter under `.bck-nd/product/`, typed domain models, deterministic parsing, lifecycle-aware validation, and stable structured diagnostics.
- **PRD CLI workflow:** `bck-nd prd init`, `list`, `validate`, and `status`, including deterministic `prd validate --json` output and project selection through `--path` / `-p`.
- **Requirements linkage and scope:** Explicit requirement-ID resolution plus component-aware monorepo applicability through safe project-relative `applies_to` paths.
- **Canonical product renderer:** Trust-aware, deterministic `<product_context>` output with provenance, shared character budgeting, explicit truncation, and scope-local diagnostic filtering.
- **Prompt controls:** `--max-product-chars` with a 6000-character default and 256-character minimum, plus `--no-prd` to prevent product-context loading and output.
- **Read-only MCP product context:** `get_product_context(project_path, target_path, max_chars)` for product scope, users, goals, and release decisions.
- **Regression coverage:** Product models, parser, validator, service, CLI, renderer, prompt/MCP integration, path safety, serialization, atomic updates, context fidelity, and backward compatibility.

### Changed

- Focused `bck-nd prompt --uml`, `--er`, and `--tree` exports are product-aware by default; `--no-prd` produces strictly technical focused context.
- `<core_files>` selection now combines dependency impact with architectural and entry-point priorities instead of relying only on filenames.
- UML and ER discovery now respect project `.gitignore` rules consistently.
- MCP and client documentation now covers Antigravity IDE/CLI installation and the product-context workflow.
- Corrected the declared Python floor from 3.9 to 3.10 to match the supported official MCP SDK runtime; supported classifiers are Python 3.10–3.13.

### Fixed

- Fresh installations no longer resolve the incompatible MCP SDK 2.x API; runtime compatibility is bounded to `mcp>=1.28.1,<2` for v2.5.0.
- Windows clipboard export now sends UTF-16LE to `clip.exe`, preserving non-ASCII and emoji content.
- UML/ER parsers no longer leak files excluded by `.gitignore` into diagrams or context.
- Core-context selection no longer over-prioritizes naively named files when dependency evidence is available.
- Product rendering now keeps unsafe or irrelevant diagnostics out of scoped narrative while preserving global and trust-critical findings.

### Security

- Product sources and updates are contained within `.bck-nd/product/`; external paths, traversal, symlinks, junctions, and Windows reparse points are rejected.
- YAML is loaded safely, with aliases and duplicate canonicalized keys rejected before domain use.
- Non-finite numbers and non-JSON-native structures are rejected instead of producing ambiguous or nondeterministic output.
- Exposed source paths, references, and `applies_to` values are sanitized to project-relative paths or `<outside-project>`.
- Status changes use minimal atomic replacement with concurrent-content modification detection and temporary-file cleanup.

## [2.4.3] - 2026-08-22

### Added

- **Compiled Backend UML**: Full extraction of Go structs, receiver methods, interfaces and Rust structs, enums, impl blocks, and traits.
- **Polyglot Monorepo Detector**: Automatic detection and feature aggregation for workspaces containing distinct frontend (Next.js/React) and backend (FastAPI/Go/Django) subdirectories.
- **Requirement Status Workflow**: `bck-nd req status <STORY_ID> <STATUS>` (alias `set-status`) to transition story states directly from the terminal.
- **AI Context Metrics**: Token estimation (~3.5 chars/token), context sizing, raw codebase size, and percentage savings printed on every `bck-nd prompt` execution.
- **Programmatic `--json` Mode**: Stable machine-readable JSON output for single reports or consolidated full scan payloads, compatible with CI/CD and `jq`.
- **Offline Documentation Portal**: Responsive single-file dashboard in `bck-nd docs` with embedded SVG diagram previews and safe requirements escaping (no CDN/font dependencies).

## [2.4.2] - 2026-08-22

### Added

- Zero-dependency `--copy` / `-c` clipboard export for `bck-nd prompt`.
- `bck-nd req init <STORY_ID>` requirement template scaffolder.
- Integrated requirements summary table directly into standard `bck-nd scan .` output.

### Changed

- Consolidated project metadata and delta cache under `.bck-nd/` (`.bck-nd/cache/delta.json` and `.bck-nd/requirements/`).
- Merged `ADVANCED.md` into the canonical `README.md`.

### Fixed

- TypeScript, Next.js, and React UML and ER extraction for `interface` and `type` declarations.
- False-positive empty UML diagram filtering on components named `Empty` (for example, Shadcn UI components).
- Missing `Optional` typing import in `formatters.py`.

## [2.1.0] - 2026-07-18

### Added

- **Focused prompt export (`--uml`, `--er`, `--tree`):** `bck-nd prompt` now supports three boolean flags to generate lightweight context files containing only the requested diagram sections (UML, ER, or project tree).
- **Dynamic default filenames:** When using focused flags, the output filename adapts automatically — `ai_context_uml.txt`, `ai_context_er.txt`, `ai_context_tree.txt`, or `ai_context_diagrams.txt` for combinations.
- **`ContextDumper.build_focused()` method:** New core engine method for surgical diagram-only context assembly, reusing existing UML/ER/tree generators.

## [2.0.0] - 2026-07-12

### Added

- **Decoupled architecture (`core/` vs `cli/`):** Analysis engine is fully independent of terminal libraries (`rich`, `typer`). Safe to embed as a pure Python library or in async servers.
- **`ScannerOrchestrator` facade:** Single entry point accepting `OrchestratorConfig` and returning a serializable `OrchestratorResult`.
- **Concurrent orchestrator:** Independent analyzers (Tech Debt, Security Audit, Infrastructure) run in parallel via `ThreadPoolExecutor`.
- **Thread-safe in-memory file cache:** Reduces redundant disk I/O across concurrent analyzer threads.
- **Lazy loading:** Tree-Sitter parsers for C#, Java, PHP, and JS/TS load only when the target language is detected.
- **Fault tolerance:** Isolated `try-except` per orchestrator task; failures are collected in `execution_warnings` without aborting the scan.
- **Direct Mermaid export (`.mmd`):** `bck-nd scan . --er -o schema.mmd` writes clean files with ANSI codes stripped.
- **Packaged MCP entry point:** `bck-nd-mcp` replaces the legacy root-level `mcp_server.py` shim.

### Changed

- **BREAKING:** MCP server module moved to `bck_nd_hlpr.cli.mcp_server`. Use `bck-nd-mcp` instead of `python -m bck_nd_hlpr.mcp_server`.
- **BREAKING:** Core engine no longer imports or depends on `rich` or `typer`.
- CLI presentation logic (tables, progress bars, TUI) lives exclusively in `cli/`.

### Fixed

- Parser failures on individual files no longer halt the entire scan pipeline.

[2.0.0]: https://github.com/Coxibius/bck-nd-helper/releases/tag/v2.0.0
[2.4.2]: https://github.com/Coxibius/bck-nd-helper/releases/tag/v2.4.2
[2.4.3]: https://github.com/Coxibius/bck-nd-helper/releases/tag/v2.4.3
[2.5.0]: https://github.com/Coxibius/bck-nd-helper/releases/tag/v2.5.0
