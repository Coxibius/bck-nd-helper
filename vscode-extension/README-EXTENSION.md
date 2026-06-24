# Backend Helper VS Code Extension

Backend Helper is a Visual Studio Code extension that integrates the `bck-nd-hlpr` CLI directly into the editor, providing AI context generation, architecture visualization, UML/ER diagrams, project insights, and security auditing from a unified control panel.

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

### Native VS Code Integration

* Dedicated Activity Bar icon (`$(circuit-board)`)
* Collapsible sections
* Native VS Code theme support
* Webview-based diagram rendering

---

## Prerequisites

Install the Backend Helper CLI:

```bash
pip install bck-nd-hlpr
```

Verify installation:

```bash
bck-nd --help
```

The CLI must be available in your system PATH.

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
bck-nd-vscode-0.1.0.vsix
```

Install the package:

```bash
code --install-extension bck-nd-vscode-0.1.0.vsix
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
├─ README.md
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

Press:

```text
F5
```

A new Extension Development Host window will open with the extension loaded.

---

## Usage

Open a project folder in VS Code.

Click the Backend Helper icon in the Activity Bar.

### AI Context

Select:

```text
🤖 Copy AI Context
```

The extension executes:

```bash
bck-nd prompt . -o .ai_context_tmp.txt
```

The generated context is copied to the clipboard automatically after the command completes.

---

### Generate Diagrams

Use any diagram generation button:

```text
🔧 UML Diagram
🔧 ER Diagram
🔧 Routes Diagram
🔧 Infrastructure Diagram
```

The extension:

1. Executes the corresponding CLI command.
2. Extracts Mermaid blocks.
3. Sanitizes Mermaid syntax.
4. Renders the diagram inside a VS Code webview.

---

### Security Audit

Select:

```text
🛡️ Security Audit
```

The extension executes:

```bash
bck-nd audit
```

Results are displayed directly inside VS Code together with traceability information.

---

## Testing

### Launch Development Mode

1. Open the extension project.
2. Run:

```bash
npm install
npm run compile
```

3. Press:

```text
F5
```

4. A new Extension Development Host window opens.

---

### Test Diagram Generation

1. Open a backend project.
2. Open Backend Helper.
3. Generate any diagram.
4. Verify Mermaid rendering appears correctly.

---

### Test AI Context

1. Click:

```text
🤖 Copy AI Context
```

2. Paste the clipboard contents into any editor.
3. Verify project context was generated correctly.

---

### Test Security Audit

1. Click:

```text
🛡️ Security Audit
```

2. Confirm findings are displayed.

---

### Test Error Handling

Temporarily remove the CLI:

```bash
pip uninstall bck-nd-hlpr
```

Run any feature again.

The extension should display a clear error indicating that the `bck-nd` executable was not found.

---

## Troubleshooting

### Mermaid Diagram Does Not Render

The extension automatically sanitizes:

* Generic types
* Invalid identifiers
* Multi-line signatures
* Unsupported Mermaid syntax

If rendering still fails, inspect the raw CLI output.

### Activity Bar Icon Not Appearing

Reload VS Code:

```text
Developer: Reload Window
```

Verify the extension is installed and enabled.

### CLI Not Found

Ensure:

```bash
bck-nd --help
```

works from a terminal.

If not, reinstall:

```bash
pip install -U bck-nd-hlpr
```

---

## Temporary Files

Temporary files such as:

```text
.ai_context_tmp.txt
```

are created in the workspace root and automatically added to `.gitignore` when necessary.

---

## License

MIT License

© 2024–2026 Coxibius
