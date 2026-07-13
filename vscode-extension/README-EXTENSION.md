# Backend Helper VS Code Extension

Backend Helper is a Visual Studio Code extension that integrates the `bck-nd-hlpr` CLI directly into the editor, providing AI context generation, architecture visualization, UML/ER diagrams, project insights, and security auditing from a unified control panel.

> **Requires `bck-nd-hlpr` ≥ 2.0.0** — the extension consumes the decoupled CLI layer; all analysis runs through `bck-nd` commands.

## Quick Start

```bash
# 1. Install the CLI
pip install -U bck-nd-hlpr
bck-nd --help

# 2. Build the extension
cd vscode-extension
npm install && npm run compile

# 3. Press F5 in VS Code to launch the Extension Development Host
```

Open any backend project, click the **Backend Helper** icon in the Activity Bar, and generate diagrams or copy AI context.

## When to Use What

| Tool | Best for |
| --- | --- |
| **This extension** | In-editor diagram rendering, clipboard context, visual audits |
| `bck-nd scan` (terminal) | Full CLI with all flags, scripting, and CI/CD pipelines |
| `bck-nd prompt` | One-shot LLM context file without opening VS Code |
| `bck-nd-mcp` | Persistent MCP tools in Claude Desktop / Cursor |

See [CHANGELOG.md](../CHANGELOG.md#200) for v2.0.0 engine improvements (concurrency, fault tolerance, lazy loading).

## Features

### AI Context Generation

Generate and copy project context for AI assistants directly from VS Code.

### Architecture & Project Diagrams

Generate:

* UML Diagrams
* Entity Relationship (ER) Diagrams
* Route Maps
* Infrastructure Diagrams
* Flow Diagrams

All diagrams are rendered using Mermaid and automatically sanitized for compatibility.

### Security Auditing

Run security audits against your project and visualize findings through traceability diagrams.

### Project Insights

Quick access to:

* Project tree structure
* Routes overview
* Infrastructure mapping
* Architecture visualization
* Project health score (`--health`)
* Guided onboarding (`--teach`)
* API contract map (`--contract`)

### Native VS Code Integration

* Dedicated Activity Bar icon (`$(circuit-board)`)
* Collapsible sections
* Native VS Code theme support
* Webview-based diagram rendering

---

## Prerequisites

Install the Backend Helper CLI (v2.0.0+):

```bash
pip install -U bck-nd-hlpr
```

Verify installation:

```bash
bck-nd --help
bck-nd-mcp --help   # optional, for MCP integration
```

`bck-nd` must be available in your system PATH.

---

## Installation

### Install from Source

Clone or download the extension source code and run:

```bash
npm install
npm run compile
```

### Package the Extension

Install VSCE:

```bash
npm install -g @vscode/vsce
```

Create a VSIX package:

```bash
vsce package
```

This generates:

```text
bck-nd-vscode-1.0.0.vsix
```

Install the package:

```bash
code --install-extension bck-nd-vscode-1.0.0.vsix
```

Reload VS Code after installation.

---

## Development

### Project Structure

```text
vscode-extension/
├─ src/
│  └─ extension.ts
├─ package.json
├─ README-EXTENSION.md
├─ resources/
└─ ...
```

### Build

```bash
npm install
npm run compile
```

### Watch Mode

```bash
npm run watch
```

### Run Extension Host

Press `F5` — a new Extension Development Host window opens with the extension loaded.

---

## Usage

Open a project folder in VS Code. Click the Backend Helper icon in the Activity Bar.

### AI Context

Select **Copy AI Context**. The extension executes:

```bash
bck-nd prompt . -o .ai_context_tmp.txt
```

The generated context is copied to the clipboard automatically.

### Generate Diagrams

Use any diagram button (UML, ER, Routes, Infrastructure). The extension:

1. Executes the corresponding `bck-nd scan` command.
2. Extracts Mermaid blocks.
3. Sanitizes Mermaid syntax.
4. Renders the diagram inside a VS Code webview.

### Security Audit

Select **Security Audit**. The extension executes:

```bash
bck-nd scan . --audit
```

Results are displayed in the Output panel.

---

## Exporting Diagrams

From the terminal (outside the extension UI):

```bash
bck-nd scan . --uml -o classes.mmd
bck-nd scan . --er -o schema.mmd
```

ANSI escape codes are stripped automatically. See [ADVANCED.md](../ADVANCED.md) for details.

---

## Testing

1. Open the extension project and run `npm install && npm run compile`.
2. Press `F5` to launch the Extension Development Host.
3. Open a backend project and test diagram generation, AI context, and security audit.
4. To test error handling, temporarily uninstall the CLI (`pip uninstall bck-nd-hlpr`) — the extension should show a clear "CLI not found" error.

---

## Troubleshooting

### Mermaid Diagram Does Not Render

The extension sanitizes generic types, invalid identifiers, and unsupported Mermaid syntax. If rendering still fails, inspect the raw CLI output in the terminal.

### Activity Bar Icon Not Appearing

Run **Developer: Reload Window** and verify the extension is installed and enabled.

### CLI Not Found

```bash
bck-nd --help   # must work from a terminal
pip install -U bck-nd-hlpr
```

---

## Temporary Files

`.ai_context_tmp.txt` is created in the workspace root and automatically added to `.gitignore` when necessary.

---

## Documentation

- [README.md](../README.md) — Main CLI documentation
- [CHANGELOG.md](../CHANGELOG.md) — Release history
- [ADVANCED.md](../ADVANCED.md) — MCP setup, library API, architecture diagram

---

## License

MIT License — © 2024–2026 Coxibius
