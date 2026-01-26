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
**Architecture:** Deterministic rendering + Cloud AI (Webhook).

---

## 2. Technical Architecture

### A. The CLI Layer (`cli.py`)
- **Framework:** Typer.
- **Commands:** `scan` (auto-discovery), `flow` (manual diagram).
- **Constraint:** Must respond instantly (<100ms startup).

### B. The Router (`router.py`)
- **Logic:** 100% Deterministic.
- **Rendering:** Calls `renderers.py` exclusively.
- **Removal:** No "NeuralEngine" or "Hybrid Mode". If the user asks for a shape, math draws it.

### C. The Scanner (`scanner.py`)
- **Logic:** Regex-based file analysis.
- **Security:** Strict filtering of `node_modules`, `venv`, `.git`.
- **Context:** Reads `README.md` to send context to the AI Webhook.

### D. The Narrator (`narrator.py`)
- **Logic:** Stateless HTTP Client.
- **Action:** Sends JSON payload to a configured Webhook URL (defaulting to local n8n, but configurable).
- **Dependency:** Only uses `requests`. No `google-generativeai` SDK.

### E. The Parsers (New)
- **`er_parser.py`**: Static analysis (AST) for SQLAlchemy/Django models. Generates Mermaid `erDiagram`.
- **`route_parser.py`**: Static analysis (AST) for Flask/FastAPI routes. Generates Mermaid `sequenceDiagram`.
- **Logic:** Pure AST, no runtime imports to avoid side-effects.

---

## 3. Development Rules (Strict)

1.  **NO Heavy Libs:** Do not add `numpy`, `pandas`, or `torch`.
2.  **Crash Safety:** If the Webhook fails, print a clean error and show the ASCII diagram.
3.  **Windows/Linux:** Paths must be `pathlib` compatible.
4.  **Filesystem Safety:** NEVER use recursive globs (`rglob`) without filtering. Always respect `IGNORE_DIRS` (venv, node_modules) to avoid permissions errors.