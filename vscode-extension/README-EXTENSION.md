# Backend Helper VS Code Extension (MVP)

This extension integrates the `bck-nd-hlpr` CLI tool directly into VS Code, allowing you to generate architecture diagrams of your workspace with a single click.

## Prerequisites

You must have the `bck-nd-hlpr` Python package installed globally or available in your system's `PATH`.

```bash
pip install bck-nd-hlpr
```

## Local Installation & Development

To build and install this extension locally:

1. **Install dependencies:**

   ```bash
   npm install
   ```
2. **Compile TypeScript:**

   ```bash
   npm run compile
   ```
3. **Package the extension (requires `vsce`):**

   ```bash
   npm install -g @vscode/vsce
   vsce package
   ```

   This will generate a `bck-nd-vscode-0.1.0.vsix` file.
4. **Install the extension in VS Code:**

   ```bash
   code --install-extension bck-nd-vscode-0.1.0.vsix
   ```

## Usage

1. Open a folder/workspace in VS Code.
2. Open the Command Palette (`Ctrl+Shift+P` or `Cmd+Shift+P`).
3. Run the command: **Backend Helper: Generate Architecture Diagram**.
4. A new tab will open showing the generated Mermaid architecture diagram of your project.
