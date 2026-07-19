# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
