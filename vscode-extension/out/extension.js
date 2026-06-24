"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.activate = activate;
exports.deactivate = deactivate;
const vscode = require("vscode");
const cp = require("child_process");
const path = require("path");
const fs = require("fs");
function activate(context) {
    console.log('Backend Helper extension is now active!');
    // Create a shared OutputChannel for text audit reports
    const outputChannel = vscode.window.createOutputChannel("Backend Helper");
    context.subscriptions.push(outputChannel);
    // Register Webview View Provider for the Sidebar
    const provider = new BackendHelperSidebarProvider(context.extensionUri, outputChannel);
    context.subscriptions.push(vscode.window.registerWebviewViewProvider(BackendHelperSidebarProvider.viewType, provider));
    // Keep the legacy command palette command active, binding it to the full architecture diagram
    let disposable = vscode.commands.registerCommand('bck-nd.generateDiagram', async () => {
        const workspaceFolders = vscode.workspace.workspaceFolders;
        if (!workspaceFolders || workspaceFolders.length === 0) {
            vscode.window.showErrorMessage('There is not a workspace open. Please open a folder to scan.');
            return;
        }
        const workspacePath = workspaceFolders[0].uri.fsPath;
        // Delegate to the provider's diagram logic
        provider.generateDiagramDirectly(workspacePath, 'arch');
    });
    context.subscriptions.push(disposable);
}
function deactivate() { }
class BackendHelperSidebarProvider {
    constructor(_extensionUri, _outputChannel) {
        this._extensionUri = _extensionUri;
        this._outputChannel = _outputChannel;
    }
    resolveWebviewView(webviewView, context, _token) {
        this._view = webviewView;
        // Enable scripts and restrict local resource roots to the extension directory
        webviewView.webview.options = {
            enableScripts: true,
            localResourceRoots: [this._extensionUri]
        };
        webviewView.webview.html = this._getHtmlForWebview(webviewView.webview);
        // Handle messages from the Webview Sidebar
        webviewView.webview.onDidReceiveMessage(async (data) => {
            const workspaceFolders = vscode.workspace.workspaceFolders;
            if (!workspaceFolders || workspaceFolders.length === 0) {
                vscode.window.showErrorMessage('Por favor, abre una carpeta de proyecto para usar esta extensión.');
                return;
            }
            const workspacePath = workspaceFolders[0].uri.fsPath;
            switch (data.command) {
                case 'copyContext':
                    await this._handleCopyContext(workspacePath);
                    break;
                case 'generateDiagram':
                    await this._handleGenerateDiagram(workspacePath, data.type);
                    break;
                case 'runAudit':
                    await this._handleRunAudit(workspacePath, data.type);
                    break;
            }
        });
    }
    // Public method to expose execution for command palette commands
    generateDiagramDirectly(workspacePath, type) {
        this._handleGenerateDiagram(workspacePath, type);
    }
    /**
     * SECTION 1: IA Context copy
     */
    async _handleCopyContext(workspacePath) {
        const tmpFileName = '.ai_context_tmp.txt';
        const tmpFilePath = path.join(workspacePath, tmpFileName);
        vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: "Generating AI context...",
            cancellable: false
        }, async () => {
            return new Promise((resolve) => {
                const cmd = `bck-nd prompt . -o "${tmpFileName}"`;
                // Execute command
                cp.exec(cmd, { cwd: workspacePath }, (error, stdout, stderr) => {
                    if (error) {
                        this._handleExecError(error, stderr);
                        resolve();
                        return;
                    }
                    // Read file strictly inside the success callback of child_process.exec
                    fs.readFile(tmpFilePath, 'utf8', (readErr, content) => {
                        if (readErr) {
                            vscode.window.showErrorMessage(`Error reading context file: ${readErr.message}`);
                            resolve();
                            return;
                        }
                        vscode.env.clipboard.writeText(content).then(() => {
                            vscode.window.showInformationMessage("🤖 Context copied!");
                            // Delete the temporary file asynchronously after copying
                            fs.unlink(tmpFilePath, (unlinkErr) => {
                                if (unlinkErr) {
                                    console.error('Error deleting temp context file:', unlinkErr);
                                }
                            });
                            resolve();
                        });
                    });
                });
            });
        });
    }
    /**
     * SECTION 2: Generate and Render Mermaid Diagrams
     */
    async _handleGenerateDiagram(workspacePath, type) {
        const cmdMap = {
            'arch': { title: 'Complete Architecture Diagram', cmd: 'bck-nd scan . --format mermaid' },
            'tree': { title: 'Project Structure Tree', cmd: 'bck-nd scan . --tree' },
            'uml': { title: 'UML Class Diagram', cmd: 'bck-nd scan . --uml --format mermaid' },
            'er': { title: 'Entity-Relationship Diagram (ER)', cmd: 'bck-nd scan . --er --format mermaid' },
            'trace': { title: 'Route-to-DB Map', cmd: 'bck-nd scan . --trace --format mermaid' },
            'prompt': { title: 'Complete AI Context (Prompt)', cmd: 'bck-nd prompt . -o -' }
        };
        const config = cmdMap[type];
        if (!config) {
            vscode.window.showErrorMessage(`Unknown diagram type: ${type}`);
            return;
        }
        vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: `Generating ${config.title}...`,
            cancellable: false
        }, async () => {
            return new Promise((resolve) => {
                cp.exec(config.cmd, { cwd: workspacePath }, (error, stdout, stderr) => {
                    if (error) {
                        this._handleExecError(error, stderr);
                        resolve();
                        return;
                    }
                    const panel = vscode.window.createWebviewPanel('bckNdDiagram', config.title, vscode.ViewColumn.One, {
                        enableScripts: true,
                        retainContextWhenHidden: true
                    });
                    // Choose webview layout depending on type
                    if (type === 'tree') {
                        panel.webview.html = getTreeWebviewContent(config.title, stdout);
                    }
                    else if (type === 'prompt') {
                        panel.webview.html = getPromptWebviewContent(config.title, stdout);
                    }
                    else {
                        panel.webview.html = getMermaidWebviewContent(config.title, stdout);
                    }
                    // Handle messages from webview
                    panel.webview.onDidReceiveMessage(async (msg) => {
                        switch (msg.command) {
                            case 'notifyInfo':
                                vscode.window.showInformationMessage(msg.message);
                                break;
                            case 'notifyError':
                                vscode.window.showErrorMessage(msg.message);
                                break;
                            case 'saveFile':
                                const uri = await vscode.window.showSaveDialog({
                                    defaultUri: vscode.workspace.workspaceFolders
                                        ? vscode.Uri.joinPath(vscode.workspace.workspaceFolders[0].uri, msg.defaultName)
                                        : undefined,
                                    filters: msg.defaultName.endsWith('.svg')
                                        ? { 'SVG Images': ['svg'] }
                                        : { 'Text Files': ['txt'] }
                                });
                                if (uri) {
                                    try {
                                        fs.writeFileSync(uri.fsPath, msg.content, 'utf8');
                                        vscode.window.showInformationMessage("File saved successfully!");
                                    }
                                    catch (err) {
                                        vscode.window.showErrorMessage(`Error saving file: ${err.message}`);
                                    }
                                }
                                break;
                        }
                    });
                    resolve();
                });
            });
        });
    }
    /**
     * SECTION 3: Quality Auditing & Local Docs Portal
     */
    async _handleRunAudit(workspacePath, type) {
        if (type === 'docs') {
            vscode.window.withProgress({
                location: vscode.ProgressLocation.Notification,
                title: "Generating Local HTML Portal...",
                cancellable: false
            }, async () => {
                return new Promise((resolve) => {
                    cp.exec('bck-nd docs .', { cwd: workspacePath }, (error, stdout, stderr) => {
                        if (error) {
                            this._handleExecError(error, stderr);
                            resolve();
                            return;
                        }
                        const openAction = 'Open in Browser';
                        vscode.window.showInformationMessage('Local HTML Portal generated successfully!', openAction).then(selection => {
                            if (selection === openAction) {
                                const docPath = path.join(workspacePath, 'docs', 'index.html');
                                if (fs.existsSync(docPath)) {
                                    vscode.env.openExternal(vscode.Uri.file(docPath));
                                }
                                else {
                                    vscode.window.showErrorMessage('Could not find the generated index.html under docs/index.html.');
                                }
                            }
                        });
                        resolve();
                    });
                });
            });
            return;
        }
        const cmdMap = {
            'security': { title: 'Security Audit', cmd: 'bck-nd scan . --audit' },
            'todo': { title: 'Technical Debt Scan', cmd: 'bck-nd scan . --todo' }
        };
        const config = cmdMap[type];
        if (!config) {
            vscode.window.showErrorMessage(`Unknown audit command: ${type}`);
            return;
        }
        // Show Output Channel and run command
        this._outputChannel.clear();
        this._outputChannel.show();
        this._outputChannel.appendLine(`>>> Starting ${config.title}...`);
        this._outputChannel.appendLine(`>>> Working directory: ${workspacePath}`);
        this._outputChannel.appendLine(`>>> Running: ${config.cmd}\n`);
        vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: `Running ${config.title}...`,
            cancellable: false
        }, async () => {
            return new Promise((resolve) => {
                cp.exec(config.cmd, { cwd: workspacePath }, (error, stdout, stderr) => {
                    if (stdout) {
                        this._outputChannel.append(stdout);
                    }
                    if (stderr) {
                        this._outputChannel.append('\n--- ERRORS / WARNINGS ---\n');
                        this._outputChannel.append(stderr);
                    }
                    if (error) {
                        this._outputChannel.appendLine(`\n>>> ERROR: Command failed with code ${error.code}`);
                        this._handleExecError(error, stderr);
                    }
                    else {
                        this._outputChannel.appendLine(`\n>>> Execution finished successfully.`);
                        vscode.window.showInformationMessage(`¡${config.title} completed! Results in the Backend Helper panel.`);
                    }
                    resolve();
                });
            });
        });
    }
    /**
     * Elegant Error Handler
     */
    _handleExecError(error, stderr) {
        console.error('Execution Error:', error);
        console.error('Stderr:', stderr);
        const errMsg = error.message || '';
        if (errMsg.includes('not found') || errMsg.includes('is not recognized') || error.code === 127) {
            vscode.window.showErrorMessage("The CLI 'bck-nd' is not installed or not available in your system PATH.", "Install with pip").then(selection => {
                if (selection === "Install with pip") {
                    const terminal = vscode.window.createTerminal("Install Backend Helper");
                    terminal.show();
                    terminal.sendText("pip install bck-nd-hlpr");
                }
            });
        }
        else {
            vscode.window.showErrorMessage(`Error executing command: ${stderr || error.message}`);
        }
    }
    /**
     * Sidebar UI html template (using VS Code CSS variables, micro-animations, and collapsible sections)
     */
    _getHtmlForWebview(webview) {
        return `<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Backend Helper</title>
    <style>
        body {
            padding: 12px 10px;
            color: var(--vscode-sideBar-foreground, #cccccc);
            font-family: var(--vscode-font-family, sans-serif);
            font-size: var(--vscode-font-size, 13px);
            background-color: var(--vscode-sideBar-background, #252526);
            margin: 0;
        }
        
        .header {
            margin-bottom: 16px;
            padding-bottom: 12px;
            border-bottom: 1px solid var(--vscode-sideBar-border, rgba(255, 255, 255, 0.1));
        }
        
        .header h2 {
            margin: 0 0 4px 0;
            font-size: 1.15rem;
            font-weight: 600;
            color: var(--vscode-sideBarTitle-foreground, #ffffff);
        }
        
        .header p {
            margin: 0;
            font-size: 0.8rem;
            opacity: 0.7;
        }

        details {
            margin-bottom: 12px;
            border: 1px solid var(--vscode-sideBar-border, rgba(255, 255, 255, 0.1));
            border-radius: 6px;
            overflow: hidden;
            background-color: rgba(255, 255, 255, 0.01);
            transition: border-color 0.25s ease;
        }

        details:hover {
            border-color: var(--vscode-focusBorder, #007acc);
        }

        summary {
            list-style: none;
            outline: none;
            cursor: pointer;
            font-weight: 600;
            font-size: 0.9rem;
            padding: 10px 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            background-color: var(--vscode-sideBarSectionHeader-background, #2d2d2d);
            color: var(--vscode-sideBarSectionHeader-foreground, #cccccc);
            user-select: none;
            transition: background-color 0.2s ease;
        }

        summary::-webkit-details-marker {
            display: none;
        }

        summary:hover {
            background-color: var(--vscode-list-hoverBackground, rgba(255, 255, 255, 0.05));
        }

        details[open] summary {
            border-bottom: 1px solid var(--vscode-sideBar-border, rgba(255, 255, 255, 0.1));
        }

        .chevron {
            transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1);
            width: 14px;
            height: 14px;
            opacity: 0.8;
            stroke: currentColor;
            stroke-width: 2.5;
            fill: none;
        }

        details[open] summary .chevron {
            transform: rotate(90deg);
        }

        .section-content {
            padding: 12px;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }

        .btn {
            background-color: var(--vscode-button-background, #007acc);
            color: var(--vscode-button-foreground, #ffffff);
            border: 1px solid var(--vscode-button-border, transparent);
            padding: 8px 12px;
            border-radius: 4px;
            cursor: pointer;
            width: 100%;
            display: flex;
            align-items: center;
            justify-content: flex-start;
            gap: 10px;
            font-size: var(--vscode-font-size, 13px);
            font-weight: 500;
            font-family: inherit;
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
            text-align: left;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
        }

        .btn:hover {
            background-color: var(--vscode-button-hoverBackground, #0062a3);
            transform: translateY(-1px);
            box-shadow: 0 3px 8px rgba(0, 0, 0, 0.2);
        }

        .btn:active {
            transform: translateY(1px);
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.1);
        }

        .btn-desc {
            margin: -4px 0 2px 0;
            font-size: 0.75rem;
            opacity: 0.6;
            line-height: 1.25;
            padding-left: 2px;
        }
    </style>
</head>
<body>
    <div class="header">
        <h2>Backend Helper</h2>
        <p>Architecture Control Panel</p>
    </div>

    <!-- SECTION 1: ARTIFICIAL INTELLIGENCE -->
    <details open>
        <summary>
            <span>🤖 Artificial Intelligence (AI)</span>
            <svg class="chevron" viewBox="0 0 24 24">
                <polyline points="9 18 15 12 9 6"></polyline>
            </svg>
        </summary>
        <div class="section-content">
            <button class="btn" onclick="copyContext()">
                <span>🤖</span> Copy Context to Clipboard
            </button>
            <p class="btn-desc">Generates a complete context dump optimized for ChatGPT and Claude.</p>

            <button class="btn" onclick="generateDiagram('prompt')">
                <span>📄</span> View AI Context in Editor
            </button>
            <p class="btn-desc">Generates the complete context dump and displays it in a tab for review and saving.</p>
        </div>
    </details>

    <!-- SECTION 2: DIAGRAMS -->
    <details open>
        <summary>
            <span>🗺️ Diagram Generation</span>
            <svg class="chevron" viewBox="0 0 24 24">
                <polyline points="9 18 15 12 9 6"></polyline>
            </svg>
        </summary>
        <div class="section-content">
            <button class="btn" onclick="generateDiagram('arch')">
                <span>🏗️</span> Complete Architecture Diagram
            </button>
            <p class="btn-desc">General structure of modules, dependencies, and folders.</p>
            
            <button class="btn" onclick="generateDiagram('tree')">
                <span>🌳</span> Project Tree
            </button>
            <p class="btn-desc">Tree of folders and files.</p>
            
            <button class="btn" onclick="generateDiagram('uml')">
                <span>🧬</span> UML Class Diagram
            </button>
            <p class="btn-desc">Modeling of classes, inheritance, and main methods.</p>
            
            <button class="btn" onclick="generateDiagram('er')">
                <span>🗄️</span> Entity-Relationship Diagram (ER)
            </button>
            <p class="btn-desc">Logical mapping of tables, keys, and database schemas.</p>
            
            <button class="btn" onclick="generateDiagram('trace')">
                <span>🛣️</span> Route-to-DB Map
            </button>
            <p class="btn-desc">Traceability of REST endpoints from the API to the database.</p>
        </div>
    </details>

    <!-- SECTION 3: AUDITING AND QUALITY -->
    <details open>
        <summary>
            <span>🛡️ Audit and Quality</span>
            <svg class="chevron" viewBox="0 0 24 24">
                <polyline points="9 18 15 12 9 6"></polyline>
            </svg>
        </summary>
        <div class="section-content">
            <button class="btn" onclick="runAudit('security')">
                <span>🛡️</span> Security Audit
            </button>
            <p class="btn-desc">Analysis of exposed keys, credentials, and bad practices.</p>
            
            <button class="btn" onclick="runAudit('todo')">
                <span>🧹</span> Scan Technical Debt
            </button>
            <p class="btn-desc">Identifies pending comments like TODO, FIXME, HACK, and BUG.</p>
            
            <button class="btn" onclick="runAudit('docs')">
                <span>🌐</span> Local HTML Portal
            </button>
            <p class="btn-desc">Creates a complete static site of interactive documentation.</p>
        </div>
    </details>

    <script>
        const vscode = acquireVsCodeApi();
        
        function copyContext() {
            vscode.postMessage({ command: 'copyContext' });
        }
        
        function generateDiagram(type) {
            vscode.postMessage({ command: 'generateDiagram', type: type });
        }
        
        function runAudit(type) {
            vscode.postMessage({ command: 'runAudit', type: type });
        }
    </script>
</body>
</html>`;
    }
}
BackendHelperSidebarProvider.viewType = 'backendHelperView.controlPanel';
/**
 * Cleans the Mermaid code from ANSI escape sequences before rendering.
 */
function cleanMermaidCode(mermaidCode) {
    let cleanCode = mermaidCode.replace(/[\u001b\u009b][[()#;?]*(?:[0-9]{1,4}(?:;[0-9]{0,4})*)?[0-9A-ORZcf-nqry=><]/g, '');
    cleanCode = cleanCode.trim();
    if (cleanCode.startsWith('```mermaid')) {
        cleanCode = cleanCode.substring(10);
    }
    if (cleanCode.endsWith('```')) {
        cleanCode = cleanCode.substring(0, cleanCode.length - 3);
    }
    return cleanCode.trim();
}
/**
 * Strips ANSI escape codes from text
 */
function stripAnsi(text) {
    return text.replace(/[\u001b\u009b][[()#;?]*(?:[0-9]{1,4}(?:;[0-9]{0,4})*)?[0-9A-ORZcf-nqry=><]/g, '');
}
/**
 * Extracts project tree text from the CLI stdout
 */
function extractProjectTree(stdout) {
    const clean = stripAnsi(stdout);
    const treeMarker = '[TREE]';
    const treeIdx = clean.indexOf(treeMarker);
    if (treeIdx === -1) {
        return null;
    }
    const afterMarker = clean.substring(treeIdx + treeMarker.length);
    const lines = afterMarker.split(/\r?\n/);
    const treeLines = [];
    let started = false;
    const nextSectionRegex = /^\[(UML|ER|API|INFRA|TODO|TREE)\]/;
    for (const line of lines) {
        const trimmed = line.trim();
        if (started && nextSectionRegex.test(trimmed)) {
            break;
        }
        if (!started && (trimmed.includes('/') || trimmed.includes('├') || trimmed.includes('└') || trimmed.includes('│'))) {
            started = true;
        }
        if (started && trimmed !== '') {
            treeLines.push(line);
        }
    }
    return treeLines.length > 0 ? treeLines.join('\n') : null;
}
/**
 * Webview HTML for the project tree (text-only, no Mermaid)
 */
function getTreeWebviewContent(title, rawStdout) {
    const clean = stripAnsi(rawStdout);
    const lines = clean.split(/\r?\n/);
    const treeLines = [];
    let started = false;
    for (const line of lines) {
        const trimmed = line.trim();
        if (!started && (trimmed.includes('/') || trimmed.includes('├') || trimmed.includes('└') || trimmed.includes('│'))) {
            started = true;
        }
        if (started) {
            treeLines.push(line);
        }
    }
    const treeText = treeLines.length > 0 ? treeLines.join('\n') : clean;
    const escaped = treeText.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    return `<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>${title}</title>
    <style>
        body {
            background-color: var(--vscode-editor-background, #1e1e1e);
            color: var(--vscode-editor-foreground, #d4d4d4);
            font-family: var(--vscode-font-family, sans-serif);
            margin: 0;
            display: flex;
            flex-direction: column;
            height: 100vh;
        }
        .header-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 18px;
            background-color: var(--vscode-sideBar-background, #252526);
            border-bottom: 1px solid var(--vscode-sideBar-border, rgba(255,255,255,0.1));
            flex-shrink: 0;
        }
        .header-bar h3 { margin: 0; font-size: 1rem; font-weight: 500; }
        .controls { display: flex; gap: 8px; }
        .btn {
            background-color: var(--vscode-button-background, #007acc);
            color: var(--vscode-button-foreground, #ffffff);
            border: none;
            padding: 6px 12px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.85rem;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .btn:hover { background-color: var(--vscode-button-hoverBackground, #0062a3); }
        .content-area { flex-grow: 1; overflow: auto; padding: 20px 24px; }
        pre {
            font-family: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', 'Consolas', monospace;
            font-size: 0.9rem;
            line-height: 1.6;
            padding: 1.5rem;
            background: rgba(255,255,255,0.03);
            border-radius: 8px;
            border: 1px solid var(--vscode-sideBar-border, rgba(255,255,255,0.1));
            overflow-x: auto;
            white-space: pre;
            margin: 0;
        }
    </style>
</head>
<body>
    <div class="header-bar">
        <h3>${title}</h3>
        <div class="controls">
            <button class="btn" onclick="copyTree()">📋 Copiar</button>
            <button class="btn" onclick="saveTree()">💾 Guardar TXT</button>
        </div>
    </div>
    <div class="content-area">
        <pre id="tree-content">${escaped}</pre>
    </div>
    <script>
        const vscode = acquireVsCodeApi();
        const treeText = document.getElementById('tree-content').textContent;
        function copyTree() {
            navigator.clipboard.writeText(treeText).then(() => {
                vscode.postMessage({ command: 'notifyInfo', message: '¡Árbol copiado al portapapeles!' });
            });
        }
        function saveTree() {
            vscode.postMessage({ command: 'saveFile', content: treeText, defaultName: 'project-tree.txt' });
        }
    </script>
</body>
</html>`;
}
/**
 * Extracts all Mermaid diagram blocks from the CLI stdout markdown report
 */
function extractMermaidDiagrams(stdout) {
    const diagrams = [];
    const regex = /```mermaid\s*([\s\S]*?)\s*```/g;
    let match;
    while ((match = regex.exec(stdout)) !== null) {
        diagrams.push(match[1].trim());
    }
    if (diagrams.length === 0) {
        const keywords = ['classDiagram', 'erDiagram', 'stateDiagram', 'flowchart', 'sequenceDiagram', 'graph'];
        const lines = stdout.split(/\r?\n/);
        const startIndex = lines.findIndex(line => keywords.some(kw => line.trim().startsWith(kw)));
        if (startIndex !== -1) {
            const filteredLines = lines.slice(startIndex).filter(line => {
                const t = line.trim();
                return t !== '' &&
                    !t.includes('Copy the above block') &&
                    !t.includes('Mermaid.live') &&
                    t !== '```';
            });
            diagrams.push(filteredLines.join('\n'));
        }
    }
    return diagrams;
}
/**
 * Shared CSS for the webview
 */
function getSharedWebviewCSS() {
    return `
        :root {
            --bg-color: var(--vscode-editor-background, #1e1e1e);
            --fg-color: var(--vscode-editor-foreground, #d4d4d4);
            --btn-bg: var(--vscode-button-background, #007acc);
            --btn-fg: var(--vscode-button-foreground, #ffffff);
            --btn-hover: var(--vscode-button-hoverBackground, #0062a3);
            --panel-bg: var(--vscode-sideBar-background, #252526);
            --border-color: var(--vscode-sideBar-border, rgba(255, 255, 255, 0.1));
            --active-tab-bg: var(--vscode-tab-activeBackground, #1e1e1e);
            --active-tab-fg: var(--vscode-tab-activeForeground, #ffffff);
            --inactive-tab-bg: var(--vscode-tab-inactiveBackground, #2d2d2d);
            --inactive-tab-fg: var(--vscode-tab-inactiveForeground, #8e8e8e);
        }
        body { background-color: var(--bg-color); color: var(--fg-color); font-family: var(--vscode-font-family, sans-serif); margin: 0; display: flex; flex-direction: column; height: 100vh; }
        .header-bar { display: flex; justify-content: space-between; align-items: center; padding: 10px 18px; background-color: var(--panel-bg); border-bottom: 1px solid var(--border-color); flex-shrink: 0; }
        .header-bar h3 { margin: 0; font-size: 1rem; font-weight: 500; }
        .controls { display: flex; gap: 8px; }
        .btn { background-color: var(--btn-bg); color: var(--btn-fg); border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer; font-size: 0.85rem; display: flex; align-items: center; gap: 6px; }
        .btn:hover { background-color: var(--btn-hover); }
        .tabs { display: flex; background-color: var(--panel-bg); border-bottom: 1px solid var(--border-color); flex-shrink: 0; overflow-x: auto; }
        .tab-btn { background: var(--inactive-tab-bg); color: var(--inactive-tab-fg); border: none; border-right: 1px solid var(--border-color); padding: 10px 16px; cursor: pointer; font-size: 0.85rem; white-space: nowrap; }
        .tab-btn.active { background: var(--active-tab-bg); color: var(--active-tab-fg); border-bottom: 2px solid var(--btn-bg); }
        .content-area { flex-grow: 1; overflow: auto; position: relative; }
        .tab-content { display: none; height: 100%; }
        .tab-content.active { display: block; }
        .mermaid-wrapper { padding: 20px; display: flex; justify-content: center; align-items: flex-start; min-height: 100%; background-color: var(--bg-color); }
        .tree-wrapper { padding: 20px 24px; }
        .tree-wrapper pre { font-family: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', 'Consolas', monospace; font-size: 0.9rem; line-height: 1.6; padding: 1.5rem; background: rgba(255,255,255,0.03); border-radius: 8px; border: 1px solid var(--border-color); overflow-x: auto; white-space: pre; color: var(--fg-color); margin: 0; }
    `;
}
/**
 * Webview HTML Template for Mermaid diagram previews.
 * For 'arch' mode, also includes the project tree as a tab.
 */
function getMermaidWebviewContent(title, rawStdout) {
    const diagrams = extractMermaidDiagrams(rawStdout);
    const projectTree = extractProjectTree(rawStdout);
    if (diagrams.length === 0 && !projectTree) {
        return `<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"><title>${title}</title><style>body{background-color:#1e1e1e;color:#d4d4d4;padding:20px;font-family:sans-serif;}pre{background:rgba(255,255,255,0.05);padding:15px;border-radius:6px;overflow:auto;}</style></head><body><h3>No se pudo extraer contenido válido</h3><pre>${rawStdout.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')}</pre></body></html>`;
    }
    const tabsData = [];
    if (projectTree)
        tabsData.push({ type: 'tree', title: '🌳 Estructura de Proyecto', code: projectTree });
    diagrams.forEach((diag, index) => {
        const cleaned = cleanMermaidCode(diag);
        let diagTitle = title;
        const firstLine = cleaned.split('\n')[0].trim();
        if (firstLine.startsWith('classDiagram'))
            diagTitle = '🧬 Diagrama UML de Clases';
        else if (firstLine.startsWith('erDiagram'))
            diagTitle = '🗄️ Diagrama Entidad-Relación (ER)';
        else if (firstLine.startsWith('sequenceDiagram'))
            diagTitle = '🛣️ Trazabilidad de Rutas';
        else if (firstLine.startsWith('flowchart') || firstLine.startsWith('graph'))
            diagTitle = '🏗️ Arquitectura de Flujo';
        else if (diagrams.length > 1)
            diagTitle = `📊 Diagrama #${index + 1}`;
        tabsData.push({ type: 'mermaid', title: diagTitle, code: cleaned });
    });
    const showTabs = tabsData.length > 1;
    let tabsHeaderHtml = showTabs ? '<div class="tabs">' : '';
    let tabsContentHtml = '';
    let textareasHtml = '';
    let mermaidIndexes = [];
    tabsData.forEach((tab, index) => {
        if (showTabs)
            tabsHeaderHtml += `<button class="tab-btn ${index === 0 ? 'active' : ''}" onclick="switchTab(${index})">${tab.title}</button>`;
        const activeClass = index === 0 ? 'active' : '';
        const wrapperStart = showTabs ? `<div class="tab-content ${activeClass}" id="tab-content-${index}">` : '';
        const wrapperEnd = showTabs ? `</div>` : '';
        if (tab.type === 'tree') {
            const escaped = tab.code.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            tabsContentHtml += `${wrapperStart}<div class="tree-wrapper"><pre>${escaped}</pre></div>${wrapperEnd}`;
            textareasHtml += `<textarea id="source-${index}" style="display:none;" data-type="tree">${escaped}</textarea>`;
        }
        else {
            tabsContentHtml += `${wrapperStart}<div class="mermaid-wrapper"><div id="mermaid-view-${index}"></div></div>${wrapperEnd}`;
            textareasHtml += `<textarea id="source-${index}" style="display:none;" data-type="mermaid">${tab.code.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</textarea>`;
            mermaidIndexes.push(index);
        }
    });
    if (showTabs)
        tabsHeaderHtml += '</div>';
    return `<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"><title>${title}</title><style>${getSharedWebviewCSS()}</style></head>
<body>
    <div class="header-bar">
        <h3 id="current-title">${tabsData[0].title}</h3>
        <div class="controls"><button class="btn" onclick="copyCode()">📋 Copiar</button><button class="btn" id="btn-save-svg" onclick="saveSvg()">💾 Guardar</button></div>
    </div>
    ${tabsHeaderHtml}<div class="content-area">${tabsContentHtml}</div>${textareasHtml}
    <script type="module">
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
        const vscode = acquireVsCodeApi();
        let currentTabIndex = 0;
        const tabTypes = ${JSON.stringify(tabsData.map(t => t.type))};
        mermaid.initialize({ startOnLoad: false, theme: 'dark', securityLevel: 'loose' });
        async function init() {
            const mermaidIndexes = ${JSON.stringify(mermaidIndexes)};
            for (const i of mermaidIndexes) {
                const sourceText = document.getElementById('source-' + i).value;
                const viewElement = document.getElementById('mermaid-view-' + i);
                try { const { svg } = await mermaid.render('mermaid-svg-' + i, sourceText); viewElement.innerHTML = svg; } catch (err) { viewElement.innerHTML = 'Error: ' + err.message; }
            }
            updateSaveButton();
        }
        function updateSaveButton() {
            document.getElementById('btn-save-svg').textContent = tabTypes[currentTabIndex] === 'tree' ? '💾 Guardar TXT' : '💾 Guardar SVG';
        }
        window.switchTab = function(index) {
            document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
            document.querySelectorAll('.tab-btn')[index].classList.add('active');
            document.getElementById('tab-content-' + index).classList.add('active');
            document.getElementById('current-title').textContent = ${JSON.stringify(tabsData.map(d => d.title))}[index];
            currentTabIndex = index;
            updateSaveButton();
        };
        window.copyCode = function() { navigator.clipboard.writeText(document.getElementById('source-' + currentTabIndex).value); };
        window.saveSvg = function() {
            if (tabTypes[currentTabIndex] === 'tree') vscode.postMessage({ command: 'saveFile', content: document.getElementById('source-' + currentTabIndex).value, defaultName: 'project-tree.txt' });
            else { const s = document.querySelector('#mermaid-view-' + currentTabIndex + ' svg'); if(s) vscode.postMessage({ command: 'saveFile', content: s.outerHTML, defaultName: 'diagrama.svg' }); }
        };
        init();
    </script>
</body></html>`;
}
/**
 * Webview HTML for the prompt dump (text-only XML context)
 */
function getPromptWebviewContent(title, rawStdout) {
    const clean = stripAnsi(rawStdout);
    const escaped = clean.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    return `<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>${title}</title>
    <style>
        body {
            background-color: var(--vscode-editor-background, #1e1e1e);
            color: var(--vscode-editor-foreground, #d4d4d4);
            font-family: var(--vscode-font-family, sans-serif);
            margin: 0;
            display: flex;
            flex-direction: column;
            height: 100vh;
        }
        .header-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 18px;
            background-color: var(--vscode-sideBar-background, #252526);
            border-bottom: 1px solid var(--vscode-sideBar-border, rgba(255,255,255,0.1));
            flex-shrink: 0;
        }
        .header-bar h3 { margin: 0; font-size: 1rem; font-weight: 500; }
        .controls { display: flex; gap: 8px; }
        .btn {
            background-color: var(--vscode-button-background, #007acc);
            color: var(--vscode-button-foreground, #ffffff);
            border: none;
            padding: 6px 12px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.85rem;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .btn:hover { background-color: var(--vscode-button-hoverBackground, #0062a3); }
        .content-area { flex-grow: 1; overflow: auto; padding: 20px 24px; }
        pre {
            font-family: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', 'Consolas', monospace;
            font-size: 0.9rem;
            line-height: 1.6;
            padding: 1.5rem;
            background: rgba(255,255,255,0.03);
            border-radius: 8px;
            border: 1px solid var(--vscode-sideBar-border, rgba(255,255,255,0.1));
            overflow-x: auto;
            white-space: pre-wrap;
            margin: 0;
        }
    </style>
</head>
<body>
    <div class="header-bar">
        <h3>${title}</h3>
        <div class="controls">
            <button class="btn" onclick="copyPrompt()">📋 Copy Context</button>
            <button class="btn" onclick="savePrompt()">💾 Save Context</button>
        </div>
    </div>
    <div class="content-area">
        <pre id="prompt-content">${escaped}</pre>
    </div>
    <script>
        const vscode = acquireVsCodeApi();
        const promptText = document.getElementById('prompt-content').textContent;
        function copyPrompt() {
            navigator.clipboard.writeText(promptText).then(() => {
                vscode.postMessage({ command: 'notifyInfo', message: 'AI Context copied to clipboard!' });
            });
        }
        function savePrompt() {
            vscode.postMessage({ command: 'saveFile', content: promptText, defaultName: 'ai-context-dump.txt' });
        }
    </script>
</body>
</html>`;
}
//# sourceMappingURL=extension.js.map