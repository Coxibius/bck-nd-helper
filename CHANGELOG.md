# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.5.0] - Pending publication (prepared 2026-09-07)

This release is prepared in the repository but has not been published to PyPI.

### Added

- **Local-first PRD Intelligence:** Human-authored Markdown product documents with YAML front matter under `.bck-nd/product/`, typed domain models, deterministic parsing, lifecycle-aware validation, and stable structured diagnostics.
- **PRD CLI workflow:** `bck-nd prd init`, `list`, `validate`, and `status`, including deterministic `prd validate --json` output and project selection through `--path` / `-p`.
- **Requirements workflow and scope discovery:** `bck-nd req init`, `list`, `show`, `validate`, `status`, `discover`, and `locations` provide copyable commands, concise briefs, complete story detail, safe lifecycle updates, and explicit discovery of independent root/nested collections without automatic merging.
- **Requirements linkage and Product scope:** Explicit requirement-ID resolution plus component-aware monorepo applicability through safe project-relative `applies_to` paths.
- **Canonical product renderer:** Trust-aware, deterministic `<product_context>` output with provenance, shared character budgeting, explicit truncation, and scope-local diagnostic filtering.
- **Prompt controls:** independent `--no-prd` and `--no-req` exclusions, `--max-product-chars` with a 6000-character default, and `--max-requirements-chars` with a 12000-character default; both budgets have a 256-character minimum.
- **Read-only MCP product context:** `get_product_context(project_path, target_path, max_chars)` for product scope, users, goals, and release decisions.
- **Compact diagnostic trust summary:** Product context retains the first applicable error code even at the minimum character budget.
- **Regression coverage:** Product models, parser, validator, service, CLI, renderer, prompt/MCP integration, path safety, serialization, atomic updates, context fidelity, and backward compatibility.

### Changed

- Focused `bck-nd prompt --uml`, `--er`, and `--tree` exports include applicable Product and Requirements context by default; `--no-prd --no-req` together produce strictly technical focused context.
- `scan` and `prompt` now share the canonical polyglot UML and ER aggregators, so equal project paths and depths use one analysis semantics across both commands.
- Requirements commands, scan, prompt, chat, and MCP expose the selected collection plus bounded metadata about omitted nested collections instead of silently merging independent scopes.
- Interactive chat includes applicable Product and Requirements context by default and supports the same independent `--no-prd` and `--no-req` exclusions.
- `<core_files>` selection now combines dependency impact with architectural and entry-point priorities instead of relying only on filenames.
- UML, ER, dependency, tree, and core-file discovery now load hierarchical `.gitignore` rules incrementally, prune ignored directories before descent, and apply pathname-aware wildcards with deterministic negation precedence.
- MCP and client documentation now covers Antigravity IDE/CLI installation and the product-context workflow.
- Corrected the declared Python floor from 3.9 to 3.10 to match the supported official MCP SDK runtime; supported classifiers are Python 3.10–3.13.

### Fixed

- The offline HTML portal now embeds the pinned Mermaid 11.17.2 browser renderer and MIT license instead of displaying diagram source as SVG text. UML, ER, infrastructure and sequence views produce actual geometry offline; invalid edits preserve the last valid diagram with an explicit warning. JavaScript-disabled viewers retain the complete source and an honest explanation. No CDN or Node/Python rendering dependency is required.
- Fresh installations no longer resolve the incompatible MCP SDK 2.x API; runtime compatibility is bounded to `mcp>=1.28.1,<2` for v2.5.0.
- Windows clipboard export now sends UTF-16LE to `clip.exe`, preserving non-ASCII and emoji content.
- UML/ER parsers no longer leak files excluded by `.gitignore` into diagrams or context.
- Core-context selection no longer over-prioritizes naively named files when dependency evidence is available.
- Product rendering now keeps unsafe or irrelevant diagnostics out of scoped narrative while preserving global and trust-critical findings.
- MCP client installation now rejects malformed or structurally invalid JSON without replacing it and detects concurrent configuration changes before atomic replacement.
- MCP configuration parsing now rejects exact duplicate JSON keys at any nesting depth instead of silently accepting the last value.
- Gitignore matching no longer lets single-star patterns cross directory separators; recursive matching is reserved for `**`.
- Gitignore parsing now follows Git semantics for unescaped versus escaped trailing spaces and preserves character-class ranges, negation, literal hyphens, and literal closing brackets without allowing classes to cross directories.
- Blank or whitespace-only `flow` input now fails with a controlled non-zero result instead of reporting a successful empty diagram.
- ContextDumper no longer selects one framework-specific UML/ER parser and lose valid entities or classes from another language in a polyglot workspace.
- Delta-cache recovery is conditional and recoverable: construction alone creates no cache directories, while successful saves use verified writes and preserve unrelated or concurrently changed content.
- Requirements briefs, detail views, diagnostics, scope guidance, and command suggestions now remain usable for project roots containing spaces.

### Security

- Product sources and updates are contained within `.bck-nd/product/`; external paths, traversal, symlinks, junctions, and Windows reparse points are rejected.
- YAML is loaded safely, with aliases and duplicate canonicalized keys rejected before domain use.
- Non-finite numbers and non-JSON-native structures are rejected instead of producing ambiguous or nondeterministic output.
- Exposed source paths, references, and `applies_to` values are sanitized to project-relative paths or `<outside-project>`.
- Status changes use minimal atomic replacement with concurrent-content modification detection and temporary-file cleanup.
- Product narrative redacts high-confidence credential, private-key, connection-string, and provider-token shapes before budgeting or serialization; this is output hygiene rather than secret governance.
- Product sources are bounded to 1 MiB, YAML front matter to 128 KiB, and YAML composition to 64 levels and 10,000 nodes.
- Requirement discovery and status updates use verified descriptor reads, containment and link/reparse checks, 1 MiB limits, and race-aware atomic replacement.
- Requirements collection loading is bounded to 512 supported sources, 8 MiB in aggregate, and 1 MiB per source; JSON is rejected beyond 64 nesting levels or 10,000 iteratively counted nodes. Prompt and MCP Requirements context now share a deterministic 12,000-character, sanitize-before-budget renderer with explicit truncation.
- All 23 filesystem-backed MCP tools now fail closed unless `BCK_ND_MCP_ALLOWED_ROOTS` is an explicit, completely valid list of absolute existing directories; the installer accepts repeatable `--allowed-root` values and injects the canonical list into Claude Desktop, Cursor, and Antigravity.
- MCP project resolution no longer depends on the server process working directory: relative paths resolve from the sole authorized root, while multiple authorized roots require an unambiguous absolute project path.
- MCP context and documentation generation now publish only to designated Backend Helper artifact locations, preserve unmarked user files, reject linked/reparse destinations, stage HTML outside the project, and use verified atomic replacement with path-neutral failures.
- CI initialization validates `.github`, the workflow, and `.gitignore` together before mutation; generated workflows carry a stable marker, foreign workflows are preserved, and minimal `.gitignore` updates retain BOM and line endings.
- MCP installation and requirement status updates now hold bounded Windows/POSIX system locks across the read, validation, backup/write, revalidation, and replacement workflow. Persistent lock files coordinate cooperative Backend Helper writers, and final revalidation detects observable changes before replacement; a minimal interval remains before the atomic syscall, so this is not an OS sandbox, RBAC, secret manager, or defense against malicious, privileged, or non-cooperating processes with the same permissions.
- Filesystem indexing, project-tree generation, and cached descriptor reads now reject symlinks, junctions, reparse points, and non-regular entries; verified reads abort without caching when identity, metadata, or content changes concurrently.
- A shared high-confidence credential registry now drives sanitizer and security-auditor detection for provider tokens, JWTs, private keys, credentialed connection strings, and sensitive assignments. AI context, requirements MCP summaries, and audit reports redact matched values as `***REDACTED***` while retaining useful finding metadata; this remains output hygiene rather than secret management.
- Root and nested `.gitignore` sources now load incrementally with bounded rules and line storage. Unsafe, unreadable, oversized, or incomplete policies block their governed scope with stable neutral diagnostics rather than applying a partial prefix or continuing without a trusted policy.
- A unified bounded read boundary supplies scanners, parsers, providers, dependency analysis, and ContextDumper from one verified snapshot; unsafe links, races, oversized reads, and paths outside the selected project fail closed rather than activating alternate traversal paths.
- Shared atomic writers provide no-clobber creation, verified replacement, temporary cleanup, and controlled failure exits for generated artifacts, cache state, Requirements, PRDs, MCP configuration, documentation, and CI setup.

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
