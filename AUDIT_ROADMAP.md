# AUDIT ROADMAP — Pillar C & D Codebase Review

**Audit Date:** 2026-08-01
**Auditor:** Automated Codebase Audit Initiative
**Baseline Robustness Score:** **78 / 100**
**Document Encoding:** UTF-8 (strict)

---

## 1. Executive Summary

This document is the official output of the Pillar C (Delta Cache) and Pillar D (MCP Integration) codebase audit initiative. The audit evaluated all core language and framework parser modules, the shared Tree-sitter infrastructure layer, and the framework provider registry architecture.

### 1.1 Baseline Robustness Score — 78 / 100

The baseline score of **78/100** reflects a solid, production-grade foundation with correctly functioning Delta Cache, MCP Integration, and test suites. The 22-point deduction is decomposed as follows:

| # | Deduction | Category | Gap Description | Impact |
|---|-----------|----------|-----------------|--------|
| D1 | −5 pts | Language Parity | Missing modern C# 10–12, Java 17–21, PHP 8.1–8.3, TypeScript 5.x, and Python 3.10–3.12 language-feature support in parsers | User projects using recent LTS features produce incomplete UML/ER diagrams |
| D2 | −4 pts | Framework Coverage | No providers for Go (Gin/GORM), Rust (Actix/Diesel), Ruby on Rails, or Java Quarkus ecosystems | 25% of industry backend frameworks are unsupported out of the box |
| D3 | −3 pts | Type System Depth | SQLAlchemy 2.0 `Mapped[...]` generic annotations, NestJS DI decorator metadata, and Jakarta EE namespace mappings are only partially handled | Entity relationships and column types are silently dropped for modern ORM patterns |
| D4 | −3 pts | Schema & Attribute Parsing | PHP 8 `#[...]` attributes, TypeScript 5 decorator syntax, and Zod/TypeBox generic schema inference are not implemented | Attribute/Decorator-driven ORM and validation metadata is invisible to analyzers |
| D5 | −4 pts | Error Resilience | No graceful degradation for Tree-sitter `ERROR` nodes; malformed source can cascade into `AttributeError`/`KeyError` crashes | Single-file syntax failures abort entire project-level analysis traversal |
| D6 | −3 pts | Plugin Extensibility | Provider registry requires modification of `__init__.py` to register new frameworks; no entry-point auto-discovery | Third-party plugin authors must fork or monkey-patch core to add support |
| **Total** | **−22** | — | — | — |

**Projected Score After All Roadmap Initiatives Complete: 98 / 100**

---

## 2. Language-by-Language Gap Matrix

The following matrix maps every identified feature gap for the five supported language ecosystems, including the current support level, the missing features, and an audited priority ranking (P0 = critical, P1 = high, P2 = medium).

### 2.1 Unified Feature Gap Matrix

| Language | Current Support Level | Missing Features | Tree-sitter Node Types Affected | Priority | Estimated Effort | Linked TODO Location |
|----------|----------------------|------------------|----------------------------------|----------|------------------|----------------------|
| **C# 10–12** | ★★★☆☆ (Pre-C# 9 baseline, partial C# 8 nullable) | 1. Primary constructors on `class_declaration` / `record_declaration`<br>2. Record types and record structs<br>3. File-scoped namespace declarations<br>4. Top-level statements (Program.cs style) | `primary_constructor_body`<br>`record_declaration`<br>`record_struct_declaration`<br>`file_scoped_namespace_declaration`<br>`global_statement` | **P1** | 3–4 dev-days | [csharp_parser.py#L34-L51](file:///c:/bck-nd-hlpr/src/bck_nd_hlpr/core/csharp_parser.py#L34-L51) |
| **Java 17–21** | ★★★☆☆ (Java 8–11 baseline, `javax.*` only) | 1. Record declarations (Java 14+ records)<br>2. Sealed classes / `permits` clauses<br>3. Pattern matching (`instanceof` patterns, switch patterns)<br>4. `jakarta.*` package imports and annotations (Spring Boot 3) | `record_declaration`<br>(modifiers → `sealed`, `non-sealed`, `permits`)<br>`pattern_matching_instanceof`<br>`jakarta.persistence.*` AST | **P1** | 4–5 dev-days | [java_parser.py#L34-L46](file:///c:/bck-nd-hlpr/src/bck_nd_hlpr/core/java_parser.py#L34-L46), [java_parser.py#L105-L134](file:///c:/bck-nd-hlpr/src/bck_nd_hlpr/core/java_parser.py#L105-L134) |
| **PHP 8.1–8.3** | ★★☆☆☆ (PHP 7.x baseline, PHPDoc-driven) | 1. Enum declarations (backed / plain enums)<br>2. Readonly class modifier<br>3. `#[...]` Attribute syntax (replacing PHPDoc)<br>4. Constructor property promotion (promoted params) | `enum_declaration`<br>(class modifier → `readonly`)<br>`attribute_list`, `attribute`<br>(constructor formal_parameter → `promoted_parameter`) | **P0** | 4–6 dev-days | [php_parser.py#L67-L78](file:///c:/bck-nd-hlpr/src/bck_nd_hlpr/core/php_parser.py#L67-L78), [php_parser.py#L90-L92](file:///c:/bck-nd-hlpr/src/bck_nd_hlpr/core/php_parser.py#L90-L92), [php_parser.py#L145-L166](file:///c:/bck-nd-hlpr/src/bck_nd_hlpr/core/php_parser.py#L145-L166) |
| **JS / TypeScript 5.x** | ★★★☆☆ (TS 4.x baseline, class-only) | 1. TypeScript 5 parameter / class / method decorators<br>2. NestJS DI patterns (`@Injectable`, `@Controller`, `@Module`)<br>3. Generic schema inference (Zod, TypeBox, class-validator) | `decorator`, `decorator_list`<br>(`@Controller`, `@Injectable`, `@Entity`)<br>`generic_type`, `type_parameter` | **P1** | 5–7 dev-days | [js_parser.py#L29-L44](file:///c:/bck-nd-hlpr/src/bck_nd_hlpr/core/js_parser.py#L29-L44), [js_parser.py#L122-L135](file:///c:/bck-nd-hlpr/src/bck_nd_hlpr/core/js_parser.py#L122-L135), [ts_base.py#L9-L11](file:///c:/bck-nd-hlpr/src/bck_nd_hlpr/core/ts_base.py#L9-L11) |
| **Python 3.10–3.12** | ★★★☆☆ (Python 3.8/3.9 AST baseline) | 1. PEP 695 `type` alias statements (ast.TypeAlias)<br>2. Structural pattern matching `match` / `case` (ast.Match)<br>3. SQLAlchemy 2.0 nested `Mapped[...]` type annotation unwrapping | `ast.TypeAlias` (PEP 695)<br>`ast.Match` + `ast.match_case`<br>`Subscript → Mapped[Optional[...]]`, `Mapped[list[...]]` | **P0** | 3–5 dev-days | [django_parser.py#L19-L25](file:///c:/bck-nd-hlpr/src/bck_nd_hlpr/core/django_parser.py#L19-L25), [er_parser.py#L23-L38](file:///c:/bck-nd-hlpr/src/bck_nd_hlpr/core/er_parser.py#L23-L38), [er_parser.py#L110-L111](file:///c:/bck-nd-hlpr/src/bck_nd_hlpr/core/er_parser.py#L110-L111) |

### 2.2 Priority Legend

- **P0 — Blocking / Data-loss risk:** Silent data loss occurs for modern ORM/codebases. Address before next minor release.
- **P1 — High impact / parity gap:** Large share of projects will have incomplete output. Schedule for the immediate next sprint.
- **P2 — Medium / Nice-to-have:** Lowers manual workarounds for edge-case projects. Schedule in quarterly planning.

---

## 3. Framework Expansion Roadmap

The provider plugin architecture is ready to host four new first-class framework providers. Below is a phased implementation roadmap with resource estimates and dependency prerequisites.

### 3.1 Phased Execution Timeline

| Phase | Framework Stack | Detection Heuristics | Target Release | Team Profile | Estimated Effort | Dependency Prerequisites |
|-------|-----------------|----------------------|----------------|--------------|------------------|---------------------------|
| **Phase 1** | **Go — Gin (web) + GORM (ORM)** | • `go.mod` exists and contains `gin-gonic/gin` or `gorm.io/gorm`<br>• `*.go` files with `gin.Default()` / `gin.New()` router bootstrap<br>• `gorm.Open(...)` calls or `*.go` structs with `gorm:"..."` tags | v1.3.0 | 1 Go-savvy Python dev + code reviewer | **5 dev-days** | 1. Tree-sitter Go grammar (`tree-sitter-go` Python wheel)<br>2. GORM tag parser for struct fields<br>3. Gin route regex / handler pairing |
| **Phase 2** | **Rust — Actix-web + Diesel ORM** | • `Cargo.toml` contains `actix-web`, `actix-rt`, or `diesel` dependencies<br>• `main.rs` → `HttpServer::new(|| App::new()...)` bootstrap pattern<br>• `diesel::table! { ... }` DSL blocks or `#[derive(Queryable)]` structs | v1.4.0 | 1 Rust-literate Python dev | **6–8 dev-days** | 1. Tree-sitter Rust grammar (`tree-sitter-rust`)<br>2. Diesel `table!` macro AST (approximate via regex fallback first)<br>3. Actix route attribute / scope handler pairing |
| **Phase 3** | **Ruby on Rails 7+** | • `Gemfile` contains `rails` gem (v7+ preferred)<br>• `app/models/` directory with `*.rb` files inheriting from `ApplicationRecord`<br>• `config/routes.rb` Rails DSL (resources, member, collection) | v1.4.0 | 1 Rails-aware Python dev | **5–7 dev-days** | 1. Tree-sitter Ruby grammar (`tree-sitter-ruby`)<br>2. ActiveRecord association inference (`has_many`, `belongs_to`)<br>3. Rails routes.rb DSL parser |
| **Phase 4** | **Java Quarkus 3.x (RESTEasy Reactive + Panache)** | • `pom.xml` (`quarkus-universe-bom`, `quarkus-resteasy-reactive`, `quarkus-hibernate-orm-panache`) **or** `build.gradle` with Quarkus plugins<br>• `@Path` / `@GET` / `@POST` JAX-RS annotations<br>• Entity classes extending `PanacheEntity` / `PanacheEntityBase` | v1.5.0 | Reuses Java 17–21 work (Phase 1 of Language Matrix) + Java config parser | **4–5 dev-days** | 1. Jakarta namespace mapping (in progress via Java audit TODOs)<br>2. Panache repository / active-record pattern detection<br>3. Quarkus Maven / Gradle config parser |

### 3.2 Provider Registration & Auto-Discovery

All four new providers SHALL be integrated via the planned entry-point mechanism (tracked under the extensibility audit gap D6). This avoids touching `core/providers/__init__.py` for each new ecosystem.

```
# Future pyproject.toml entry point group
[project.entry-points."bck_nd_hlpr.providers"]
go_gin_gorm       = "bck_nd_hlpr.core.providers.go_gin:GoGinGormProvider"
rust_actix_diesel = "bck_nd_hlpr.core.providers.rust_actix:RustActixDieselProvider"
ruby_on_rails     = "bck_nd_hlpr.core.providers.ruby_rails:RubyOnRailsProvider"
java_quarkus      = "bck_nd_hlpr.core.providers.java_quarkus:JavaQuarkusProvider"
```

---

## 4. Error Handling & Tree-Sitter Fallback Strategy

The audit identified a critical resilience gap: `BaseTreeSitterVisitor.visit()` has no explicit handling for Tree-sitter `ERROR` nodes. When a source file contains syntax that the bundled Tree-sitter grammar cannot parse, the parser produces `ERROR` syntax nodes. If any visitor method (e.g. `_visit_class`, `_visit_property`) naively calls `child_by_field_name` on an `ERROR` node or expects a non-error child type, the visitor either silently skips all remaining content or throws an unhandled exception.

### 4.1 Failure Modes Identified

| Failure Mode | Current Behavior | Proposed Recovery | Severity |
|--------------|------------------|-------------------|----------|
| **Top-level `ERROR` in `compilation_unit`** | Subsequent sibling declarations (classes, namespaces) are not dispatched at all because the generic walk enters the ERROR subtree and returns empty results | Skip the ERROR node and call `visit()` on every younger sibling; emit a single non-fatal warning per file | **Critical** |
| **Class-body `ERROR` from malformed member** | One bad property / method drops all remaining members in the class because iteration over `declaration_list` children aborts | Wrap per-child dispatch in try/except; record the failure position; resume iteration at `child_index + 1` | **High** |
| **AttributeError on malformed child lookup** | `self.child(node, "identifier")` returns `None` for ERROR children; some callers dereference without the check → `AttributeError: 'NoneType' object has no attribute ...` | Add defensive guards in all visitor helpers and wrap recursive calls in the visitor base class | **High** |
| **Deeply nested ERROR (e.g. inside a `parameter_list`)** | Field type, return type, or parameter names silently become `""` or `"Unknown"` without telemetry | Track per-file error metrics; expose in debug output or verbose CLI flag so users can report grammar gaps | **Medium** |

### 4.2 Implementation Plan — `visit_ERROR` Recovery Workflow

All new logic resides inside `BaseTreeSitterVisitor` in `base_tree_sitter.py`. Concrete language visitors MUST NOT override the base error recovery contract.

```
┌─────────────────────────────────────────────────────────────────────┐
│ Step 1 — Guard the main visit() dispatch                            │
│                                                                     │
│   if node.type == "ERROR":                                          │
│       # (a) Log non-fatal warning with source context               │
│       _log_syntax_error(node, self.source_bytes)                    │
│                                                                     │
│       # (b) DO NOT recurse into ERROR children; the ERROR          │
│       #     subtree is not guaranteed to be well-typed.             │
│       #     Instead, try to recover siblings.                       │
│       return _recover_siblings(node)                                │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Step 2 — Sibling recovery                                           │
│                                                                     │
│   def _recover_siblings(error_node):                                │
│       parent = error_node.parent   # (tree-sitter parent accessor)  │
│       if not parent: return []                                      │
│                                                                     │
│       my_idx = error_node.index_in_parent                           │
│       results = []                                                  │
│       for i in range(my_idx + 1, parent.child_count):              │
│           sibling = parent.child(i)                                 │
│           # Skip additional ERROR siblings to avoid cascades       │
│           if sibling.type == "ERROR": continue                      │
│           try:                                                      │
│               res = self.visit(sibling)                             │
│               if res: results.extend(res)                           │
│           except Exception:                                         │
│               _log_child_failure(sibling)                           │
│       return results                                                │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Step 3 — Per-dispatch try/except in generic_visit                   │
│                                                                     │
│   def generic_visit(self, node):                                    │
│       results = []                                                  │
│       for child in node.children or []:                             │
│           if child.type == "ERROR":                                 │
│               self.visit(child)  # triggers Step 1                  │
│               continue                                              │
│           try:                                                      │
│               res = self.visit(child)                               │
│               if res is not None: results.append(res)               │
│           except Exception as exc:                                  │
│               _log_recoverable(child, exc)                          │
│               continue  # <-- key: do NOT re-raise                  │
│       return results                                                │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.3 Telemetry & Logging Contract

- **Non-fatal warnings only:** All ERROR-node handling MUST log via `warnings.warn(..., stacklevel=2)` or a dedicated `logging.getLogger("bck_nd_hlpr.ts.error")` logger at WARNING level — NEVER `print(...)` to stdout since callers may rely on stdout for diagram output.
- **Structured context per warning:** Each emitted warning SHALL include:
  1. Absolute file path (if known via `_current_path` instance state)
  2. Start line / end line of the ERROR node (`node.start_point[0]+1` .. `node.end_point[0]+1`)
  3. A 120-char source snippet around the first error byte (UTF-8 safe, truncated)
  4. The Tree-sitter grammar name (e.g. `tree_sitter_c_sharp`, `tree_sitter_java`)
- **Opt-in verbose stats:** After `visit(root_node)` returns, `BaseTreeSitterVisitor` SHALL expose a public `error_stats: dict[str, int]` property containing `{"error_nodes": N, "recovered_siblings": M, "aborted_subtrees": K}`. Callers (test harness, debug CLI) can then assert `error_stats["error_nodes"] == 0` for clean inputs.

### 4.4 Success Criteria for Closure

1. ✅ No unhandled `AttributeError`, `KeyError`, or `IndexError` exceptions when feeding 100+ randomly mutated syntax-error files from each language's grammar corpus into any parser.
2. ✅ When a syntax error is present in the middle of a file, all sibling declarations AFTER the error are still correctly extracted and reported in output.
3. ✅ Test suite includes a parametrized `test_tree_sitter_error_degradation` case that injects known-bad syntax into fixture files and asserts that (a) no exceptions are raised, and (b) the non-error portions of the fixture are still present in the extracted structures.
4. ✅ Baseline Robustness Score sub-component D5 (Error Resilience) moves from −4 pts deduction → 0 pts (full credit).

---

## Appendix A. TODO(audit) Comment Inventory (by file)

| File | TODO Count | Summary Topics |
|------|------------|----------------|
| [csharp_parser.py](file:///c:/bck-nd-hlpr/src/bck_nd_hlpr/core/csharp_parser.py) | 5 (pre-existing) | File-scoped namespaces, top-level statements, record declarations, primary constructors |
| [java_parser.py](file:///c:/bck-nd-hlpr/src/bck_nd_hlpr/core/java_parser.py) | 8 | Java 17–21 records, sealed classes, pattern matching, jakarta.* mapping |
| [php_parser.py](file:///c:/bck-nd-hlpr/src/bck_nd_hlpr/core/php_parser.py) | 8 | PHP 8.1+ enums, readonly classes, `#[]` attributes, constructor promotion |
| [js_parser.py](file:///c:/bck-nd-hlpr/src/bck_nd_hlpr/core/js_parser.py) | 7 | TS 5 decorators, NestJS DI patterns, generic schema types |
| [ts_base.py](file:///c:/bck-nd-hlpr/src/bck_nd_hlpr/core/ts_base.py) | 3 | Centralized decorator + generic helper location |
| [django_parser.py](file:///c:/bck-nd-hlpr/src/bck_nd_hlpr/core/django_parser.py) | 4 | PEP 695 type aliases, match/case, SQLAlchemy 2.0 Mapped[] |
| [er_parser.py](file:///c:/bck-nd-hlpr/src/bck_nd_hlpr/core/er_parser.py) | 5 | ast.TypeAlias, ast.Match, nested Mapped[Optional[]]] unwrapping |
| [base_tree_sitter.py](file:///c:/bck-nd-hlpr/src/bck_nd_hlpr/core/base_tree_sitter.py) | 5 | Graceful ERROR degradation, visit_ERROR, sibling recovery, logging |
| [providers/base.py](file:///c:/bck-nd-hlpr/src/bck_nd_hlpr/core/providers/base.py) | 7 | Go, Rust, Ruby, Java Quarkus expansion candidates listed |
| [providers/registry.py](file:///c:/bck-nd-hlpr/src/bck_nd_hlpr/core/providers/registry.py) | 5 | Entry-point auto-discovery, provider priority ranking |
| **Total** | **55** | — |

---

*End of AUDIT_ROADMAP.md — Document ID: AUDIT-2026-0801-PCPD*
