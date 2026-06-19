# Backend Helper VS Code Extension (MVP)

## Overview

This extension provides a powerful **Control Panel** in the VS Code Activity Bar, replacing the previous Command Palette workflow. It integrates the `bck-nd-hlpr` Python CLI to offer:

- **AI Context** – copy AI context to the clipboard.
- **UML / ER / Flow Diagrams** – generate Mermaid diagrams directly from the CLI output.
- **Security Audits** – run security checks and view results.
- **Project Insights** – quick access to project tree, routes, and infrastructure diagrams.

All UI elements follow VS Code’s native theming using CSS variables like `--vscode-button-background` and are organized into three collapsible sections.

## Prerequisites

You must have the `bck-nd-hlpr` Python package installed globally or available in your system's `PATH`.

```bash
pip install bck-nd-hlpr
```

## Local Installation & Development

1. Open a terminal in the extension folder:
```bash
cd c:\bck-nd-hlpr\vscode-extension
```
2. Install dependencies:
```bash
npm install
```
3. Compile TypeScript:
```bash
npm run compile
```
4. (Optional) Watch for changes during development:
```bash
npm run watch
```
5. Package the extension (requires `vsce`):
```bash
npm install -g @vscode/vsce
vsce package
```
   This will generate a `bck-nd-vscode-0.1.0.vsix` file.
6. Install the extension in VS Code:
```bash
code --install-extension bck-nd-vscode-0.1.0.vsix
```

Reload the window (`Ctrl+Shift+P` → **Reload Window**).

## Usage

The extension adds a new **Backend Helper** icon to the Activity Bar. Click it to open the control panel.

### AI Context
- Click **🤖 Copiar Contexto IA al Portapapeles**.
- The extension runs:
```bash
bck-nd prompt . -o .ai_context_tmp.txt
```
- After the command finishes, the temporary file is read **inside the exec callback** (or after awaiting a promisified exec) to guarantee the file is ready, then its contents are copied to the clipboard.

### Generate Diagrams
- Use the diagram buttons (e.g., **🔧 Generar Diagrama UML**) to run the appropriate CLI command.
- The output is filtered through `extractMermaidDiagrams` and `sanitizeMermaidCode` before being rendered.

### Security Audit
- Click **🛡️ Ejecutar Auditoría de Seguridad** to run `bck-nd audit`.
- Results appear in the panel with a traceability diagram.

## Development

### Project Structure
```
vscode-extension/
├─ src/extension.ts          # Main extension implementation
├─ package.json              # Manifest (contributes, activationEvents)
├─ README.md                 # This documentation (merged)
├─ resources/                # (optional) icons – not required when using Codicons
└─ ...
```

### Building the Extension
```bash
npm install          # Install dependencies
npm run compile      # Compile TypeScript
npm run watch        # Watch for changes during development
```

### Testing
- Press `F5` in VS Code to launch a new Extension Development Host.
- Verify the **Backend Helper** view appears in the Activity Bar and all buttons function.

## FAQ

**Q:** *Why is the icon showing as a circuit board?*
**A:** The extension uses a VS Code **Codicon** (`$(circuit-board)`) which requires no external SVG file.

**Q:** *What if the generated Mermaid diagram fails to render?*
**A:** The extension sanitizes common syntax issues (generic types, hyphens, multi‑line signatures). If problems persist, check the CLI output for malformed Mermaid blocks.

**Q:** *Where are temporary files stored?*
**A:** Files like `.ai_context_tmp.txt` are created in the workspace root. They are added to `.gitignore` automatically if not already present.

## License

MIT © 2024‑2026 Coxibius


## Overview

This extension provides a powerful **Control Panel** in the VS Code Activity Bar, replacing the previous Command Palette workflow. It integrates the `bck-nd-hlpr` Python CLI to offer:

- **AI Context** – copy AI context to the clipboard.
- **UML / ER / Flow Diagrams** – generate Mermaid diagrams directly from the CLI output.
- **Security Audits** – run security checks and view results.
- **Project Insights** – quick access to project tree, routes, and infrastructure diagrams.

All UI elements follow VS Code’s native theming using CSS variables like `--vscode-button-background` and are organized into three collapsible sections.

## Features

- **Sidebar View** (`backendHelperView.controlPanel`) displayed in the Activity Bar with the `$(circuit-board)` codicon.
- **Collapsible Sections**:
  - **Inteligencia Artificial (IA)** – copy AI context.
  - **Diagramas** – generate UML, ER, routes, infra diagrams.
  - **Auditoría** – run security audit and view traceability.
- **Live Mermaid Rendering** – sanitizes CLI output to be compatible with Mermaid 10.9.6.
- **Async Execution** – ensures temporary files are fully written before reading.

## Installation

1. Open VS Code and go to **Extensions** (`Ctrl+Shift+X`).
2. Search for **Backend Helper** or install the folder manually:
   ```bash
   cd c:\bck-nd-hlpr\vscode-extension
   npm install
   npm run compile
   ```
3. Reload the window (`Ctrl+Shift+P` → **Reload Window**).

## Usage

The extension adds a new **Backend Helper** icon to the Activity Bar. Click it to open the control panel.

### AI Context

- Click **🤖 Copiar Contexto IA al Portapapeles**.
- The extension runs:
  ```bash
  bck-nd prompt . -o .ai_context_tmp.txt
  ```
- After the command finishes, the temporary file is read **inside the exec callback** (or after `await` on a promisified exec) to guarantee the file is ready, then its contents are copied to the clipboard.

### Generate Diagrams

- Use the **🔧 Generar Diagrama UML** button (or similar) to run the appropriate CLI command.
- The output is filtered through `extractMermaidDiagrams` and `sanitizeMermaidCode` before being rendered.

### Security Audit

- Click **🛡️ Ejecutar Auditoría de Seguridad** to run `bck-nd audit`.
- Results appear in the panel with a traceability diagram.

## Development

### Project Structure

```
vscode-extension/
├─ src/extension.ts          # Main extension implementation
├─ package.json              # Manifest (contributes, activationEvents)
├─ README.md                 # This documentation
├─ resources/                # (optional) icons – not required when using Codicons
└─ ...
```

### Building the Extension

```bash
npm install          # Install dependencies
npm run compile      # Compile TypeScript
npm run watch        # Watch for changes during development
```

### Testing

- Press `F5` in VS Code to launch a new Extension Development Host.
- Verify the **Backend Helper** view appears in the Activity Bar and all buttons function.

## FAQ

**Q:** *Why is the icon showing as a circuit board?*
**A:** The extension uses a VS Code **Codicon** (`$(circuit-board)`) which requires no external SVG file.

**Q:** *What if the generated Mermaid diagram fails to render?*
**A:** The extension sanitizes common syntax issues (generic types, hyphens, multi‑line signatures). If problems persist, check the CLI output for malformed Mermaid blocks.

**Q:** *Where are temporary files stored?*
**A:** Files like `.ai_context_tmp.txt` are created in the workspace root. They are added to `.gitignore` automatically if not already present.

## License

MIT © 2024‑2026 Coxibius
