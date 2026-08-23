# Backend Helper for VS Code

Backend Helper brings the `bck-nd-hlpr` 2.4.2 Four Pillars and Requirements Intelligence workflow into VS Code. Generate AI-ready context, manage user stories, render architecture diagrams, and run quality checks without leaving the editor.

> Requires `bck-nd-hlpr` 2.4.2 or newer and the `bck-nd` executable in your system `PATH`.

## Sidebar at a Glance

The Backend Helper Activity Bar view is organized around four focused sections:

```text
🧠 AI Context Provider
   Instant Copy · Focused Context
📋 Requirements Intelligence
   List Stories · New Story (+) · Discovery Guide
📊 Visual Diagrams
   UML · ER · Routes · Docker Infrastructure
🛡️ DevSecOps & Quality
   Health Score · Scoped Debt · Security Audit · Onboarding
```

The sidebar uses VS Code theme colors and Codicons, so it stays consistent with light, dark, and high-contrast themes.

## Features

### 🧠 AI Context Provider

- **Instant Copy** runs `bck-nd prompt . -c` and copies a complete AI context directly to the system clipboard.
- **Focused Context** opens one of the following generated views in a new editor:
  - Complete project
  - Project tree
  - UML classes and TypeScript interfaces
  - Entity-relationship models
  - UML and ER diagrams together

The generated context is ready to paste into ChatGPT, Claude, or another coding assistant.

### 📋 Requirements Intelligence

- **List Stories** runs `bck-nd req list` and displays the result in the Backend Helper Output channel.
- **New Story (+)** asks for a Story ID such as `US-001`, scaffolds `.bck-nd/requirements/US-001.md`, and offers to open it immediately.
- **Discovery Guide** asks for a Story ID, generates the stakeholder interview guide with `bck-nd req discover`, and opens it in a new Markdown editor.

Requirement files remain versionable project knowledge under `.bck-nd/requirements/`; only `.bck-nd/cache/` should be ignored.

### 📊 Visual Diagrams

- **UML Classes** — Python classes plus TypeScript, TSX, and React declarations.
- **Entity Relationships** — ORM models, keys, and relationships.
- **Application Routes** — detected HTTP endpoints and route structure.
- **Docker Infrastructure** — services and dependencies from Docker Compose.

Mermaid diagrams open in a dedicated preview with copy and SVG export controls.

### 🛡️ DevSecOps & Quality

- **Health Score** — consolidated project health report card.
- **Scoped Debt** — TODO, FIXME, HACK, XXX, and BUG findings.
- **Security Audit** — exposed secrets, credentials, and insecure practices.
- **Onboarding** — a guided codebase walkthrough based on dependency heatmaps.

Text reports are written to the **Backend Helper** Output channel.

## Quick Start

```bash
# Install or upgrade the core engine
pip install -U bck-nd-hlpr
bck-nd --help

# Build the extension from source
cd vscode-extension
npm install
npm run compile
```

Press `F5` from the extension project to launch an Extension Development Host. Open a project, then select the **Backend Helper** icon in the Activity Bar.

## Command Palette

The extension contributes these commands:

- **Backend Helper: Copy AI Context to Clipboard** (`bck-nd-hlpr.copyContext`)
- **Backend Helper: List Requirements** (`bck-nd-hlpr.reqList`)
- **Backend Helper: Create New User Story** (`bck-nd-hlpr.reqInit`)
- **Backend Helper: Discover User Story** (`bck-nd-hlpr.reqDiscover`)
- **Backend Helper: Generate Architecture Diagram** (`bck-nd.generateDiagram`, retained for compatibility)

Each command uses the first open workspace folder as its project root. The extension shows a clear error if no folder is open or the CLI is unavailable.

## CLI Commands Used by the Sidebar

```bash
# AI context
bck-nd prompt . -c
bck-nd prompt . -o - --tree
bck-nd prompt . -o - --uml
bck-nd prompt . -o - --er

# Requirements
bck-nd req list
bck-nd req init US-001
bck-nd req discover US-001

# Diagrams
bck-nd scan . --uml --format mermaid
bck-nd scan . --er --format mermaid
bck-nd scan . --routes --format mermaid
bck-nd scan . --infra --format mermaid

# DevSecOps and quality
bck-nd scan . --health
bck-nd scan . --todo
bck-nd scan . --audit
bck-nd scan . --teach
```

## Installation

### Install from Source

```bash
cd vscode-extension
npm install
npm run compile
```

### Build and Install a VSIX

```bash
npm run package
code --install-extension bck-nd-vscode-1.1.0.vsix
```

Reload VS Code after installation.

## Development

```text
vscode-extension/
├─ resources/
│  └─ icon.svg
├─ src/
│  └─ extension.ts
├─ out/
├─ package.json
├─ README-EXTENSION.md
└─ tsconfig.json
```

Useful scripts:

```bash
npm run compile  # one-time TypeScript build
npm run watch    # rebuild on changes
npm run package  # compile and create the VSIX
```

## Verification Checklist

1. Run `npm run compile` and confirm zero TypeScript errors.
2. Press `F5` and open a project containing `.bck-nd/requirements/`.
3. Test Instant Copy and each Focused Context option.
4. Create a Story ID, open its generated Markdown file, then run its Discovery Guide.
5. Generate UML, ER, Routes, and Docker diagrams.
6. Run Health Score, Scoped Debt, Security Audit, and Onboarding.
7. Run `npm run package` before publishing a release.

## Troubleshooting

### CLI Not Found

```bash
pip install -U bck-nd-hlpr
bck-nd --help
```

Restart VS Code after changing your system `PATH`.

### Requirement Is Not Listed

Confirm the file is under `.bck-nd/requirements/` and follows one of the supported Markdown or JSON schemas documented in the main README.

### Mermaid Diagram Does Not Render

Run the matching `bck-nd scan` command in a terminal and inspect its raw Mermaid output. The extension strips ANSI escape sequences and sanitizes common incompatible syntax before rendering.

### Clipboard Command Fails

The CLI uses `clip.exe` on Windows, `pbcopy` on macOS, and `wl-copy` or `xclip` on Linux. Install one of the Linux clipboard tools when running outside a desktop environment.

## Documentation

- [Main README](../README.md) — CLI, MCP setup, Requirements schemas, and advanced configuration
- [Changelog](../CHANGELOG.md) — engine and extension release history

## License

MIT License — © 2024–2026 Coxibius
