# Testing the Backend Helper VS Code Extension

Follow these steps to test the extension locally.

## Prerequisites

1. Node.js installed.
2. `bck-nd-hlpr` CLI installed and available in your PATH.
   ```bash
   pip install bck-nd-hlpr
   ```

## Step-by-Step Test Guide

### 1. Open the Extension Project
Open the `vscode-extension` folder in VS Code:
```bash
cd vscode-extension
code .
```

### 2. Install Dependencies
Open the terminal in VS Code (`Ctrl+~`) and run:
```bash
npm install
```

### 3. Run the Extension in Debug Mode
1. Press **F5** (or go to `Run` -> `Start Debugging`).
2. A new VS Code window will open with the title **[Extension Development Host]**. This window has your extension loaded.

### 4. Test on a Sample Project
1. In the **[Extension Development Host]** window, open a sample backend project folder (e.g., `c:\bck-nd-hlpr` itself or another test API).
2. Open the Command Palette (`Ctrl+Shift+P` / `Cmd+Shift+P`).
3. Type and select **Backend Helper: Generate Architecture Diagram**.
4. You should see a progress notification "Scanning architecture with bck-nd...".
5. A new Webview panel will open titled "Architecture Diagram", rendering the Mermaid chart via CDN.

### 5. Test Error Handling
1. To test the error message, temporarily remove `bck-nd` from your PATH or uninstall it: `pip uninstall bck-nd-hlpr`.
2. Run the command again in the Development Host window.
3. You should see a clear error notification indicating that the binary was not found.
