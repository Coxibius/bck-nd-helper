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
            vscode.window.showErrorMessage('No hay ningún espacio de trabajo abierto. Abre una carpeta para escanear.');
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
            title: "Generando contexto IA...",
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
                            vscode.window.showErrorMessage(`Error al leer el archivo de contexto: ${readErr.message}`);
                            resolve();
                            return;
                        }
                        vscode.env.clipboard.writeText(content).then(() => {
                            vscode.window.showInformationMessage("🤖 ¡Contexto copiado!");
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
            'arch': { title: 'Diagrama Completo de Arquitectura', cmd: 'bck-nd scan . --format mermaid' },
            'uml': { title: 'Diagrama UML de Clases', cmd: 'bck-nd scan . --uml --format mermaid' },
            'er': { title: 'Diagrama Entidad-Relación (ER)', cmd: 'bck-nd scan . --er --format mermaid' },
            'trace': { title: 'Mapa de Rutas a DB', cmd: 'bck-nd scan . --trace --format mermaid' }
        };
        const config = cmdMap[type];
        if (!config) {
            vscode.window.showErrorMessage(`Tipo de diagrama desconocido: ${type}`);
            return;
        }
        vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: `Generando ${config.title}...`,
            cancellable: false
        }, async () => {
            return new Promise((resolve) => {
                cp.exec(config.cmd, { cwd: workspacePath }, (error, stdout, stderr) => {
                    if (error) {
                        this._handleExecError(error, stderr);
                        resolve();
                        return;
                    }
                    // Create Webview Panel for rendering Mermaid diagram
                    const panel = vscode.window.createWebviewPanel('bckNdDiagram', config.title, vscode.ViewColumn.One, {
                        enableScripts: true,
                        retainContextWhenHidden: true
                    });
                    panel.webview.html = getMermaidWebviewContent(config.title, stdout);
                    // Handle messages from Mermaid webview
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
                                    filters: { 'SVG Images': ['svg'] }
                                });
                                if (uri) {
                                    try {
                                        fs.writeFileSync(uri.fsPath, msg.content, 'utf8');
                                        vscode.window.showInformationMessage("¡Diagrama SVG guardado con éxito!");
                                    }
                                    catch (err) {
                                        vscode.window.showErrorMessage(`Error al guardar archivo SVG: ${err.message}`);
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
                title: "Generando Portal HTML Local...",
                cancellable: false
            }, async () => {
                return new Promise((resolve) => {
                    cp.exec('bck-nd docs .', { cwd: workspacePath }, (error, stdout, stderr) => {
                        if (error) {
                            this._handleExecError(error, stderr);
                            resolve();
                            return;
                        }
                        const openAction = 'Abrir en Navegador';
                        vscode.window.showInformationMessage('¡Portal HTML Local generado con éxito!', openAction).then(selection => {
                            if (selection === openAction) {
                                const docPath = path.join(workspacePath, 'index.html');
                                if (fs.existsSync(docPath)) {
                                    vscode.env.openExternal(vscode.Uri.file(docPath));
                                }
                                else {
                                    vscode.window.showErrorMessage('No se encontró el archivo index.html generado.');
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
            'security': { title: 'Auditoría de Seguridad', cmd: 'bck-nd scan . --audit' },
            'todo': { title: 'Escaneo de Deuda Técnica', cmd: 'bck-nd scan . --todo' }
        };
        const config = cmdMap[type];
        if (!config) {
            vscode.window.showErrorMessage(`Comando de auditoría desconocido: ${type}`);
            return;
        }
        // Show Output Channel and run command
        this._outputChannel.clear();
        this._outputChannel.show();
        this._outputChannel.appendLine(`>>> Iniciando ${config.title}...`);
        this._outputChannel.appendLine(`>>> Directorio de trabajo: ${workspacePath}`);
        this._outputChannel.appendLine(`>>> Ejecutando: ${config.cmd}\n`);
        vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: `Ejecutando ${config.title}...`,
            cancellable: false
        }, async () => {
            return new Promise((resolve) => {
                cp.exec(config.cmd, { cwd: workspacePath }, (error, stdout, stderr) => {
                    if (stdout) {
                        this._outputChannel.append(stdout);
                    }
                    if (stderr) {
                        this._outputChannel.append('\n--- ERRORES / ADVERTENCIAS ---\n');
                        this._outputChannel.append(stderr);
                    }
                    if (error) {
                        this._outputChannel.appendLine(`\n>>> ERROR: El comando falló con código ${error.code}`);
                        this._handleExecError(error, stderr);
                    }
                    else {
                        this._outputChannel.appendLine(`\n>>> Ejecución finalizada con éxito.`);
                        vscode.window.showInformationMessage(`¡${config.title} completada! Resultados en panel Backend Helper.`);
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
            vscode.window.showErrorMessage("El CLI 'bck-nd' no se encuentra instalado o no está disponible en tu sistema PATH.", "Instalar con pip").then(selection => {
                if (selection === "Instalar con pip") {
                    const terminal = vscode.window.createTerminal("Instalar Backend Helper");
                    terminal.show();
                    terminal.sendText("pip install bck-nd-hlpr");
                }
            });
        }
        else {
            vscode.window.showErrorMessage(`Error ejecutando comando: ${stderr || error.message}`);
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
        <p>Panel de Control de Arquitectura</p>
    </div>

    <!-- SECCIÓN 1: INTELIGENCIA ARTIFICIAL -->
    <details open>
        <summary>
            <span>🤖 Inteligencia Artificial (IA)</span>
            <svg class="chevron" viewBox="0 0 24 24">
                <polyline points="9 18 15 12 9 6"></polyline>
            </svg>
        </summary>
        <div class="section-content">
            <button class="btn" onclick="copyContext()">
                <span>🤖</span> Copiar Contexto al Portapapeles
            </button>
            <p class="btn-desc">Genera un volcado completo de contexto optimizado para ChatGPT y Claude.</p>
        </div>
    </details>

    <!-- SECCIÓN 2: DIAGRAMAS -->
    <details open>
        <summary>
            <span>🗺️ Generación de Diagramas</span>
            <svg class="chevron" viewBox="0 0 24 24">
                <polyline points="9 18 15 12 9 6"></polyline>
            </svg>
        </summary>
        <div class="section-content">
            <button class="btn" onclick="generateDiagram('arch')">
                <span>🏗️</span> Diagrama Completo de Arquitectura
            </button>
            <p class="btn-desc">Estructura general de módulos, dependencias y carpetas.</p>
            
            <button class="btn" onclick="generateDiagram('uml')">
                <span>🧬</span> Diagrama UML de Clases
            </button>
            <p class="btn-desc">Modelado de clases, herencias y métodos principales.</p>
            
            <button class="btn" onclick="generateDiagram('er')">
                <span>🗄️</span> Diagrama Entidad-Relación (ER)
            </button>
            <p class="btn-desc">Mapeo lógico de tablas, llaves y esquemas de base de datos.</p>
            
            <button class="btn" onclick="generateDiagram('trace')">
                <span>🛣️</span> Mapa de Rutas a DB
            </button>
            <p class="btn-desc">Trazabilidad de endpoints REST de la API hacia la base de datos.</p>
        </div>
    </details>

    <!-- SECCIÓN 3: AUDITORÍA Y CALIDAD -->
    <details open>
        <summary>
            <span>🛡️ Auditoría y Calidad</span>
            <svg class="chevron" viewBox="0 0 24 24">
                <polyline points="9 18 15 12 9 6"></polyline>
            </svg>
        </summary>
        <div class="section-content">
            <button class="btn" onclick="runAudit('security')">
                <span>🛡️</span> Auditoría de Seguridad
            </button>
            <p class="btn-desc">Análisis de claves expuestas, credenciales y malas prácticas.</p>
            
            <button class="btn" onclick="runAudit('todo')">
                <span>🧹</span> Escanear Deuda Técnica
            </button>
            <p class="btn-desc">Identifica comentarios pendientes como TODO, FIXME, HACK y BUG.</p>
            
            <button class="btn" onclick="runAudit('docs')">
                <span>🌐</span> Portal HTML Local
            </button>
            <p class="btn-desc">Crea un sitio estático completo de documentación interactiva.</p>
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
 * Webview HTML Template for Mermaid diagram previews (CDN loaded, interactive dark/light themes, code copying and SVG saving)
 */
function sanitizeMermaidCode(mermaidCode) {
    let cleanCode = mermaidCode.trim();
    if (cleanCode.startsWith('```mermaid')) {
        cleanCode = cleanCode.substring(10);
    }
    if (cleanCode.endsWith('```')) {
        cleanCode = cleanCode.substring(0, cleanCode.length - 3);
    }
    cleanCode = cleanCode.trim();
    const lines = cleanCode.split(/\r?\n/);
    const sanitizedLines = [];
    let inClassBlock = false;
    let i = 0;
    while (i < lines.length) {
        let line = lines[i];
        const trimmed = line.trim();
        // 1. Sanitize namespace names (replace hyphens with underscores)
        if (trimmed.startsWith('namespace ')) {
            line = line.replace(/namespace\s+([a-zA-Z0-9_-]+)/g, (match, nsName) => {
                return 'namespace ' + nsName.replace(/-/g, '_');
            });
        }
        // 2. Track class block
        if (trimmed.startsWith('class ') && trimmed.endsWith('{')) {
            inClassBlock = true;
            // Sanitize class name in declaration
            line = line.replace(/class\s+([a-zA-Z0-9_-]+)/g, (match, clsName) => {
                return 'class ' + clsName.replace(/-/g, '_');
            });
            sanitizedLines.push(line);
            i++;
            continue;
        }
        if (inClassBlock && trimmed === '}') {
            inClassBlock = false;
            sanitizedLines.push(line);
            i++;
            continue;
        }
        if (inClassBlock) {
            // Check for unclosed parenthesis (multi-line signature)
            let openParenCount = (line.match(/\(/g) || []).length;
            let closeParenCount = (line.match(/\)/g) || []).length;
            while (openParenCount > closeParenCount && i + 1 < lines.length) {
                i++;
                const nextLine = lines[i].trim();
                line = line.trim() + ' ' + nextLine;
                openParenCount = (line.match(/\(/g) || []).length;
                closeParenCount = (line.match(/\)/g) || []).length;
                if (nextLine === '}') {
                    inClassBlock = false;
                    break;
                }
            }
            // 3. Sanitize class member syntax
            // Replace generic types like List<Post> with List~Post~ (Mermaid standard)
            line = line.replace(/<([^>]+)>/g, '~$1~');
            // Simplify spacing
            line = line.replace(/\s+/g, ' ');
            // Restore indentation
            line = '        ' + line.trim();
        }
        else {
            // Outside class block: sanitize relation lines that might contain hyphenated names
            const relationPattern = /^([\w-]+)\s+(<\|--|--\|>|-->|<--|--|..>|<..|o--|--o|\*--|--\*)\s+([\w-]+)$/;
            if (relationPattern.test(trimmed)) {
                line = line.replace(relationPattern, (match, left, arrow, right) => {
                    return `${left.replace(/-/g, '_')} ${arrow} ${right.replace(/-/g, '_')}`;
                });
            }
        }
        sanitizedLines.push(line);
        i++;
    }
    return sanitizedLines.join('\n');
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
    // Fallback: if there are no backtick blocks, but the text starts with classDiagram or erDiagram
    if (diagrams.length === 0) {
        const clean = stdout.trim();
        if (clean.startsWith('classDiagram') || clean.startsWith('erDiagram') || clean.startsWith('stateDiagram') || clean.startsWith('flowchart') || clean.startsWith('sequenceDiagram') || clean.startsWith('graph')) {
            const lines = clean.split(/\r?\n/);
            const filteredLines = lines.filter(line => {
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
 * Webview HTML Template for Mermaid diagram previews (CDN loaded, interactive dark/light themes, code copying and SVG saving)
 * Supports multiple diagrams rendered in beautiful, VS Code-native tabs
 */
function getMermaidWebviewContent(title, rawStdout) {
    const diagrams = extractMermaidDiagrams(rawStdout);
    if (diagrams.length === 0) {
        // Fallback: show raw stdout in a pre block if parsing failed completely
        return `<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>${title}</title>
    <style>
        body {
            background-color: var(--vscode-editor-background, #1e1e1e);
            color: var(--vscode-editor-foreground, #d4d4d4);
            padding: 20px;
            font-family: var(--vscode-font-family, sans-serif);
        }
        pre {
            background-color: rgba(255,255,255,0.05);
            padding: 15px;
            border-radius: 6px;
            overflow: auto;
        }
    </style>
</head>
<body>
    <h3>No se pudo extraer un diagrama Mermaid válido</h3>
    <p>Salida original del CLI:</p>
    <pre>${rawStdout.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')}</pre>
</body>
</html>`;
    }
    // Process and sanitize each diagram
    const diagramsData = [];
    diagrams.forEach((diag, index) => {
        const sanitized = sanitizeMermaidCode(diag);
        let diagTitle = title;
        if (diagrams.length > 1) {
            const firstLine = sanitized.split('\n')[0].trim();
            if (firstLine.startsWith('classDiagram')) {
                diagTitle = '🧬 Diagrama de Clases (UML)';
            }
            else if (firstLine.startsWith('erDiagram')) {
                diagTitle = '🗄️ Diagrama Entidad-Relación (ER)';
            }
            else if (firstLine.startsWith('sequenceDiagram')) {
                diagTitle = '🛣️ Trazabilidad de Rutas';
            }
            else if (firstLine.startsWith('flowchart') || firstLine.startsWith('graph')) {
                diagTitle = '🏗️ Arquitectura de Flujo';
            }
            else {
                diagTitle = `📊 Diagrama #${index + 1}`;
            }
        }
        diagramsData.push({ title: diagTitle, code: sanitized });
    });
    let tabsHeaderHtml = '';
    let tabsContentHtml = '';
    if (diagramsData.length > 1) {
        tabsHeaderHtml = '<div class="tabs">';
        diagramsData.forEach((diag, index) => {
            tabsHeaderHtml += `<button class="tab-btn ${index === 0 ? 'active' : ''}" onclick="switchTab(${index})">${diag.title}</button>`;
            tabsContentHtml += `
            <div class="tab-content ${index === 0 ? 'active' : ''}" id="tab-content-${index}">
                <div class="mermaid-wrapper">
                    <div class="mermaid" id="mermaid-diag-${index}">
                        ${diag.code.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')}
                    </div>
                </div>
            </div>`;
        });
        tabsHeaderHtml += '</div>';
    }
    else {
        // Only one diagram, no tabs needed
        tabsContentHtml = `
        <div class="mermaid-wrapper">
            <div class="mermaid" id="mermaid-diag-0">
                ${diagramsData[0].code.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')}
            </div>
        </div>`;
    }
    return `<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>${title}</title>
    <!-- Mermaid CDN -->
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    <style>
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
        body {
            background-color: var(--bg-color);
            color: var(--fg-color);
            font-family: var(--vscode-font-family, sans-serif);
            margin: 0;
            padding: 0;
            display: flex;
            flex-direction: column;
            height: 100vh;
            overflow: hidden;
        }
        .header-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 18px;
            background-color: var(--panel-bg);
            border-bottom: 1px solid var(--border-color);
            flex-shrink: 0;
        }
        .header-bar h3 {
            margin: 0;
            font-size: 1rem;
            font-weight: 500;
        }
        .controls {
            display: flex;
            gap: 8px;
        }
        .btn {
            background-color: var(--btn-bg);
            color: var(--btn-fg);
            border: none;
            padding: 6px 12px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.85rem;
            display: flex;
            align-items: center;
            gap: 6px;
            transition: background-color 0.2s ease;
        }
        .btn:hover {
            background-color: var(--btn-hover);
        }
        
        /* Tabs navigation */
        .tabs {
            display: flex;
            background-color: var(--panel-bg);
            border-bottom: 1px solid var(--border-color);
            flex-shrink: 0;
        }
        .tab-btn {
            background-color: var(--inactive-tab-bg);
            color: var(--inactive-tab-fg);
            border: none;
            border-right: 1px solid var(--border-color);
            padding: 8px 16px;
            cursor: pointer;
            font-size: 0.85rem;
            font-family: inherit;
            transition: all 0.2s;
        }
        .tab-btn:hover {
            color: var(--active-tab-fg);
            background-color: rgba(255, 255, 255, 0.05);
        }
        .tab-btn.active {
            background-color: var(--active-tab-bg);
            color: var(--active-tab-fg);
            font-weight: 600;
        }
        
        .main-container {
            flex: 1;
            overflow: auto;
            position: relative;
        }
        
        .tab-content {
            display: none;
            width: 100%;
            height: 100%;
            box-sizing: border-box;
        }
        .tab-content.active {
            display: block;
        }
        
        .mermaid-wrapper {
            padding: 30px;
            display: flex;
            justify-content: center;
            align-items: flex-start;
            box-sizing: border-box;
            min-height: 100%;
        }
        
        .mermaid {
            background-color: transparent;
            width: 100%;
            display: flex;
            justify-content: center;
        }
        .mermaid svg {
            max-width: 100%;
            height: auto;
        }
    </style>
</head>
<body class="vscode-body">
    <div class="header-bar">
        <h3>${title}</h3>
        <div class="controls">
            <button class="btn" onclick="copyActiveRawCode()">📋 Copiar Código</button>
            <button class="btn" onclick="exportActiveSvg()">💾 Guardar SVG</button>
        </div>
    </div>
    
    ${tabsHeaderHtml}
    
    <div class="main-container">
        ${tabsContentHtml}
    </div>

    <script>
        const vscode = acquireVsCodeApi();
        
        // Load diagrams data structure
        const diagramsData = ${JSON.stringify(diagramsData)};
        let activeIndex = 0;
        
        // Detect dark theme
        const isDark = document.body.classList.contains('vscode-dark') || 
                       document.body.classList.contains('vscode-high-contrast') && 
                       !document.body.classList.contains('vscode-high-contrast-light');
        
        mermaid.initialize({
            startOnLoad: true,
            theme: isDark ? 'dark' : 'default',
            securityLevel: 'loose',
            flowchart: { useMaxWidth: false, htmlLabels: true }
        });

        function switchTab(index) {
            activeIndex = index;
            
            // Switch tabs classes
            const buttons = document.querySelectorAll('.tab-btn');
            buttons.forEach((btn, idx) => {
                if (idx === index) btn.classList.add('active');
                else btn.classList.remove('active');
            });
            
            // Switch content classes
            const contents = document.querySelectorAll('.tab-content');
            contents.forEach((content, idx) => {
                if (idx === index) content.classList.add('active');
                else content.classList.remove('active');
            });
        }

        function copyActiveRawCode() {
            const code = diagramsData[activeIndex].code;
            navigator.clipboard.writeText(code).then(() => {
                vscode.postMessage({ command: 'notifyInfo', message: '¡Código Mermaid copiado al portapapeles!' });
            });
        }

        function exportActiveSvg() {
            try {
                const activeContent = document.getElementById('tab-content-' + activeIndex) || document.querySelector('.main-container');
                const svgEl = activeContent ? activeContent.querySelector('.mermaid svg') : document.querySelector('.mermaid svg');
                
                if (!svgEl) {
                    vscode.postMessage({ command: 'notifyError', message: 'No se pudo encontrar el SVG del diagrama activo.' });
                    return;
                }
                const serializer = new XMLSerializer();
                const svgString = serializer.serializeToString(svgEl);
                vscode.postMessage({ command: 'saveFile', content: svgString, defaultName: 'diagrama.svg' });
            } catch (err) {
                vscode.postMessage({ command: 'notifyError', message: 'Error exportando SVG: ' + err.message });
            }
        }
    </script>
</body>
</html>`;
}
//# sourceMappingURL=extension.js.map