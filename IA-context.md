(Este es CRÍTICO para que, si usas una IA para programar sobre esto en el futuro, sepa que NO debe buscar PyTorch ni GPT-2).
code
Markdown
# 🧠 IA Context: Backend Helper (`bck-nd`)

> **System Note:** This document defines the "Lightweight/Corporate" version of the architecture project. DO NOT confuse this with "ASCII Architect Research". This project MUST NOT have heavy ML dependencies (PyTorch/Transformers).

---

## 1. Project Identity
**Name:** Backend Helper (`bck-nd-hlpr`)
**Command:** `bck-nd`
**Philosophy:** Speed, Stability, and Connectivity.
**Architecture:** Deterministic rendering + Direct AI Providers (BYO-Key) / Cloud AI (Webhook).

---

## 2. Technical Architecture

### A. The CLI Layer (`cli.py`)
- **Framework:** Typer.
- **Commands:** `scan` (auto-discovery), `flow` (manual diagram), `explore` (TUI), `docs` (HTML).
- **Constraint:** Must respond instantly (<100ms startup).

### B. The Router (`router.py`)
- **Logic:** 100% Deterministic.
- **Rendering:** Calls `renderers.py` exclusively.
- **Removal:** No "NeuralEngine" or "Hybrid Mode". If the user asks for a shape, math draws it.

### C. The Scanner (`scanner.py`)
- **Logic:** Regex-based file analysis.
- **Security:** Strict filtering of `node_modules`, `venv`, `.git`.
- **Context:** Reads `README.md` to send context to the AI Webhook.

### D. The AI Integration (`narrator.py` & `ai_providers.py`)
- **`ai_providers.py`**: A Factory pattern implementing `AIProvider` base class and concrete classes for OpenAI, Anthropic, Gemini, Ollama, and Webhook. This enables *BYO-Key (Bring Your Own Key)* support without heavy SDKs by performing direct REST calls.
- **`narrator.py`**: Orchestrates sending queries to the active AI provider, handles fallbacks, constructs complete system prompts from personalities, and returns the analysis.

### E. The Parsers (AST & Tree-Sitter)
- **`er_parser.py` & `route_parser.py`**: Python-native static analysis for ORMs, API Routes, and modern schemas. `er_parser.py` has been enhanced with custom high-speed regex/AST-based parsers to ingest **Prisma schemas (`schema.prisma`)**, **Drizzle ORMs (`.ts/.js`)**, and **raw SQL migrations/schemas (`.sql`)**.
- **`uml_parser.py`**: Generates full Class Diagrams (`classDiagram`) using a unified multi-language aggregator within `scanner.scan_uml()`.
- **`csharp_parser.py`**: Utilizes `tree-sitter-c-sharp` to robustly extract Entities, Classes, and Methods from .NET Core / Entity Framework projects.
- **`js_parser.py`**: Utilizes `tree-sitter-javascript` for Node.js/Express (Mongoose/Sequelize).
- **`java_parser.py`**: Utilizes `tree-sitter-java` for Spring Boot (JPA/Hibernate).
- **`php_parser.py`**: Utilizes `tree-sitter-php` for Laravel (Eloquent).
- **`django_parser.py`**: Uses Python's native `ast` specialized for Django models and classes.
- **Logic:** Pure static analysis, zero runtime imports, safe execution across multiple languages with intelligent deduplication and column merging on entity collisions.

### F. The Explorer TUI (`tui_app.py`)
- **Framework:** Textual.
- **Logic:** Provides an interactive `DirectoryTree` rendering architecture graphs and Mermaid routes statically.
- **Constraint:** Displayed as "Read-Only Explorer" -- intentionally not a code editor.

---

## 3. Development Rules (Strict)

1.  **NO Heavy Libs:** Do not add `numpy`, `pandas`, or `torch`.
2.  **Crash Safety:** If an AI Provider fails (e.g., missing API key, network error), print a clean error and show the ASCII diagram.
3.  **Windows/Linux:** Paths must be `pathlib` compatible.
4.  **Filesystem Safety:** NEVER use recursive globs (`rglob`) without filtering. Always respect `IGNORE_DIRS` (venv, node_modules) to avoid permissions errors.

## 4. The "Full-Stack Auditor" Features (Current State)

The project currently implements the following "Enterprise Edition" features:

### A. Entity-Relationship Diagrams (`--er`)
- **Logic:** Unified multi-language static analysis covering:
  - Prisma Schemas (`schema.prisma`)
  - Drizzle ORMs (`.ts/.js`)
  - Raw SQL Migrations/Schemas (`.sql`)
  - Python AST (SQLAlchemy, Django ORM)
  - C# Tree-Sitter (Entity Framework)
  - Java Tree-Sitter (Spring Boot / JPA)
  - PHP Tree-Sitter (Laravel / Eloquent)
  - JS/TS Tree-Sitter (Sequelize / Mongoose)
- **Output:** Mermaid `erDiagram`.
- **Safety:** Bulletproof syntax sanitizer ensures no rendering crashes, even with Generics like `List<T>`, nested parentheses, or special characters. Infers relationships (`||--o{`, `}o--||`) automatically, merging properties/columns cleanly in case of duplicate classes or namespace overlaps.

### B. API Route Mapping (`--routes`)
- **Logic:** Static AST analysis of Flask/FastAPI routes.
- **Output:** Mermaid `sequenceDiagram` showing HTTP methods and endpoints.
- **Safety:** Filters out imports and handles dynamic routes.

### C. Infrastructure Visualization (`--infra`)
- **Logic:** Parses `docker-compose.yml` and `Dockerfile`.
- **Output:** Mermaid `graph LR` showing services, volumes, and networks.
- **Safety:** Distinguishes between "Services" (Cylinders) and "Builds" (Boxes).

### D. Technical Debt Scanner (`--todo`)
- **Logic:** Scans for `TODO`, `FIXME`, `HACK`, `BUG` across all languages.
- **Output:** Rich table with Debt Score (EXCELLENT → CRITICAL).
- **Safety:** Ignores comments in `node_modules` and `venv`.

### E. Security Auditor (`--audit`)
- **Logic:** Scans for secrets (`PASSWORD`, `API_KEY`, `DATABASE_URL`).
- **Output:** Sanitized JSON report.
- **Safety:** Replaces secrets with `[REDACTED]` before showing them.

### F. Dependency Impact (`--impact`)
- **Logic:** Analyzes import graphs to find "High Impact" files.
- **Output:** Heatmap showing files that are imported by many others.
- **Safety:** Uses `pathlib` to avoid OS-specific path issues.

## 5. The "Documentation Portal" (Current State)

### A. Static HTML Generation (`--docs`)
- **Logic:** Generates a single `index.html` file containing all diagrams.
- **Components:**
    - **Infrastructure Map:** Mermaid `graph LR` from `docker-compose.yml`.
    - **API Routes:** Mermaid `sequenceDiagram` from Flask/FastAPI routes.
    - **UML Class Diagram:** Mermaid `classDiagram` from C# or Python source files.
    - **Entity-Relationship:** Mermaid `erDiagram` from ORM models.
    - **Technical Debt:** HTML table of TODOs found by the scanner.
- **Rendering:** Uses MermaidJS CDN for client-side rendering.
- **Safety:** Sanitizes secrets before injecting them into the HTML.

## 6. The "CI/CD Automation" (Current State)

### A. GitHub Actions (`.github/workflows/docs.yml`)
- **Trigger:** `push` to `main` branch.
- **Action:** Runs `bck-nd scan . --docs`.
- **Output:** Commits the generated `docs/index.html` to the repository.
- **Benefit:** Automatic documentation updates on every push.

### B. GitHub Pages Deployment
- **Action:** Uses `peaceiris/actions-gh-pages` to deploy the `docs` folder.
- **Result:** A live website (e.g., `https://yourusername.github.io/repo-name/`) with all architecture diagrams.
- **Benefit:** Shareable link for stakeholders and easy access for the team.

## 7. The "Enterprise Polish" (Current State)

### A. Output Sanitization (`--output`)
- **Logic:** Replaces secrets with `[REDACTED]` in all outputs (console and HTML).
- **Safety:** Prevents accidental exposure of API keys and passwords.
- **Benefit:** Secure documentation sharing.

### B. Deterministic Rendering
- **Logic:** Fixed color palettes and layout algorithms.
- **Benefit:** Consistent output every time the tool is run.

### C. Multi-Language Support
- **Logic:** AST parsers for Python, regex for Node.js, YAML parsing for Docker.
- **Benefit:** Works on diverse tech stacks.

## 8. The "AI Integration" (Current State)

### A. Webhook-Based Analysis (`--ai`)
- **Logic:** Sends project context to an external Webhook URL (default: local n8n).
- **Context Sent:**
    - `README.md` content
    - File tree structure
    - Git branch and commit info
    - Current directory path
- **Safety:** Sanitizes secrets before sending to the AI.
- **Benefit:** Allows for custom AI analysis without heavy dependencies.

### B. Multiple AI Styles
- **Logic:** Supports different analysis styles:
    - `hacker`: Technical, deep analysis.
    - `corporate`: Business-focused, high-level.
    - `ramsay`: Critical, "bloody hell" style.
    - `teacher`: Educational, step-by-step.
- **Benefit:** Flexible analysis for different audiences.

