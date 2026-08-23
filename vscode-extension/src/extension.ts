import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as path from 'path';
import * as fs from 'fs';

export function activate(context: vscode.ExtensionContext) {
    console.log('Backend Helper extension is now active!');

    // Create a shared OutputChannel for text audit reports
    const outputChannel = vscode.window.createOutputChannel("Backend Helper");
    context.subscriptions.push(outputChannel);

    // Register Webview View Provider for the Sidebar
    const provider = new BackendHelperSidebarProvider(context.extensionUri, outputChannel);
    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider(BackendHelperSidebarProvider.viewType, provider)
    );

    const getWorkspacePath = (): string | undefined => {
        const workspaceFolders = vscode.workspace.workspaceFolders;
        if (!workspaceFolders || workspaceFolders.length === 0) {
            vscode.window.showErrorMessage('There is not a workspace open. Please open a folder to scan.');
            return undefined;
        }
        return workspaceFolders[0].uri.fsPath;
    };

    // Keep the legacy diagram command while exposing the Requirements layer in the Command Palette.
    context.subscriptions.push(vscode.commands.registerCommand('bck-nd.generateDiagram', async () => {
        const workspacePath = getWorkspacePath();
        if (workspacePath) {
            await provider.generateDiagramDirectly(workspacePath, 'arch');
        }
    }));

    context.subscriptions.push(vscode.commands.registerCommand('bck-nd-hlpr.reqList', async () => {
        const workspacePath = getWorkspacePath();
        if (workspacePath) {
            await provider.runCommandDirectly(workspacePath, 'reqList');
        }
    }));

    context.subscriptions.push(vscode.commands.registerCommand('bck-nd-hlpr.reqInit', async () => {
        const workspacePath = getWorkspacePath();
        if (workspacePath) {
            await provider.runCommandDirectly(workspacePath, 'reqInit');
        }
    }));

    context.subscriptions.push(vscode.commands.registerCommand('bck-nd-hlpr.reqDiscover', async () => {
        const workspacePath = getWorkspacePath();
        if (workspacePath) {
            await provider.runCommandDirectly(workspacePath, 'reqDiscover');
        }
    }));

    context.subscriptions.push(vscode.commands.registerCommand('bck-nd-hlpr.copyContext', async () => {
        const workspacePath = getWorkspacePath();
        if (workspacePath) {
            await provider.runCommandDirectly(workspacePath, 'copyContext');
        }
    }));
}

export function deactivate() { }

class BackendHelperSidebarProvider implements vscode.WebviewViewProvider {
    public static readonly viewType = 'backendHelperView.controlPanel';
    private _view?: vscode.WebviewView;

    constructor(
        private readonly _extensionUri: vscode.Uri,
        private readonly _outputChannel: vscode.OutputChannel
    ) { }

    public resolveWebviewView(
        webviewView: vscode.WebviewView,
        context: vscode.WebviewViewResolveContext,
        _token: vscode.CancellationToken
    ) {
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
                vscode.window.showErrorMessage('Please, open a project folder to use this extension.');
                return;
            }
            const workspacePath = workspaceFolders[0].uri.fsPath;

            switch (data.command) {
                case 'copyContext':
                    await this._handleCopyContext(workspacePath);
                    break;
                case 'focusedContext':
                    await this._handleFocusedContext(workspacePath, data.focus);
                    break;
                case 'reqList':
                    await this._handleReqList(workspacePath);
                    break;
                case 'reqInit':
                    await this._handleReqInit(workspacePath);
                    break;
                case 'reqDiscover':
                    await this._handleReqDiscover(workspacePath);
                    break;
                case 'generateDiagram':
                    await this._handleGenerateDiagram(workspacePath, data.type);
                    break;
                case 'runAudit':
                    await this._handleRunAudit(workspacePath, data.type);
                    break;
                case 'runHealth':
                    await this._handleRunHealth(workspacePath);
                    break;
                case 'runTeach':
                    await this._handleRunTeach(workspacePath);
                    break;
                case 'runContract':
                    await this._handleRunContract(workspacePath);
                    break;
                case 'runDataScience':
                    await this._handleGenerateDiagram(workspacePath, 'datascience');
                    break;
            }
        });
    }

    // Public method to expose execution for command palette commands
    public async generateDiagramDirectly(workspacePath: string, type: string): Promise<void> {
        await this._handleGenerateDiagram(workspacePath, type);
    }

    public async runCommandDirectly(
        workspacePath: string,
        command: 'copyContext' | 'reqList' | 'reqInit' | 'reqDiscover'
    ): Promise<void> {
        const handlers = {
            copyContext: () => this._handleCopyContext(workspacePath),
            reqList: () => this._handleReqList(workspacePath),
            reqInit: () => this._handleReqInit(workspacePath),
            reqDiscover: () => this._handleReqDiscover(workspacePath)
        };
        await handlers[command]();
    }

    /**
     * SECTION 1: AI Context and Requirements Intelligence
     */
    private async _handleCopyContext(workspacePath: string): Promise<void> {
        await vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: "Generating AI context...",
            cancellable: false
        }, async () => {
            try {
                await this._runCli(['prompt', '.', '-c'], workspacePath);
                vscode.window.showInformationMessage('$(clippy) AI Context copied to clipboard!');
            } catch (error) {
                this._handleCliFailure(error);
            }
        });
    }

    private async _handleFocusedContext(workspacePath: string, focus: unknown): Promise<void> {
        const focusMap: Record<string, { label: string, flags: string[] }> = {
            full: { label: 'Complete AI Context', flags: [] },
            tree: { label: 'Focused Context: Project Tree', flags: ['--tree'] },
            uml: { label: 'Focused Context: UML', flags: ['--uml'] },
            er: { label: 'Focused Context: ER', flags: ['--er'] },
            diagrams: { label: 'Focused Context: UML + ER', flags: ['--uml', '--er'] }
        };
        const config = focusMap[typeof focus === 'string' ? focus : 'full'] || focusMap.full;

        await vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: `Generating ${config.label}...`,
            cancellable: false
        }, async () => {
            try {
                const { stdout } = await this._runCli(
                    ['prompt', '.', '-o', '-', ...config.flags],
                    workspacePath
                );
                const document = await vscode.workspace.openTextDocument({
                    content: stripAnsi(stdout),
                    language: 'markdown'
                });
                await vscode.window.showTextDocument(document, { preview: false });
            } catch (error) {
                this._handleCliFailure(error);
            }
        });
    }

    private async _handleReqList(workspacePath: string): Promise<void> {
        this._outputChannel.clear();
        this._outputChannel.show();
        this._outputChannel.appendLine('>>> Running: bck-nd req list');
        this._outputChannel.appendLine(`>>> Working directory: ${workspacePath}\n`);

        await vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: 'Listing project requirements...',
            cancellable: false
        }, async () => {
            try {
                const { stdout, stderr } = await this._runCli(['req', 'list'], workspacePath);
                if (stdout) {
                    this._outputChannel.append(stripAnsi(stdout));
                }
                if (stderr) {
                    this._outputChannel.append(`\n--- WARNINGS ---\n${stripAnsi(stderr)}`);
                }
            } catch (error) {
                this._handleCliFailure(error, true);
            }
        });
    }

    private async _handleReqInit(workspacePath: string): Promise<void> {
        const storyId = await vscode.window.showInputBox({
            prompt: 'Enter Story ID (e.g. US-001)',
            placeHolder: 'US-001',
            ignoreFocusOut: true,
            validateInput: value => {
                const candidate = value.trim();
                return candidate && !/^[A-Za-z0-9][A-Za-z0-9_-]*$/.test(candidate)
                    ? 'Use only letters, numbers, hyphens, and underscores.'
                    : undefined;
            }
        });
        if (!storyId) {
            return;
        }

        const normalizedId = storyId.trim().toUpperCase();
        try {
            await this._runCli(['req', 'init', normalizedId], workspacePath);
            const openAction = 'Open User Story';
            const selection = await vscode.window.showInformationMessage(
                `Requirement ${normalizedId} created successfully.`,
                openAction
            );
            if (selection === openAction) {
                const requirementUri = vscode.Uri.file(
                    path.join(workspacePath, '.bck-nd', 'requirements', `${normalizedId}.md`)
                );
                const document = await vscode.workspace.openTextDocument(requirementUri);
                await vscode.window.showTextDocument(document, { preview: false });
            }
        } catch (error) {
            this._handleCliFailure(error);
        }
    }

    private async _handleReqDiscover(workspacePath: string): Promise<void> {
        const storyId = await vscode.window.showInputBox({
            prompt: 'Enter Story ID (e.g. US-001)',
            placeHolder: 'US-001',
            ignoreFocusOut: true
        });
        if (!storyId) {
            return;
        }

        try {
            const { stdout } = await this._runCli(
                ['req', 'discover', storyId.trim().toUpperCase()],
                workspacePath
            );
            const document = await vscode.workspace.openTextDocument({
                content: stripAnsi(stdout),
                language: 'markdown'
            });
            await vscode.window.showTextDocument(document, { preview: false });
        } catch (error) {
            this._handleCliFailure(error);
        }
    }

    private _runCli(
        args: string[],
        workspacePath: string
    ): Promise<{ stdout: string, stderr: string }> {
        return new Promise((resolve, reject) => {
            cp.execFile(
                'bck-nd',
                args,
                { cwd: workspacePath, maxBuffer: 20 * 1024 * 1024 },
                (error, stdout, stderr) => {
                    if (error) {
                        Object.assign(error, { stderr });
                        reject(error);
                        return;
                    }
                    resolve({ stdout, stderr });
                }
            );
        });
    }

    private _handleCliFailure(error: unknown, appendToOutput = false): void {
        const failure = error as Error & { stderr?: string };
        const stderr = failure.stderr || '';
        if (appendToOutput) {
            this._outputChannel.appendLine(`\n>>> ERROR: ${stripAnsi(stderr || failure.message)}`);
        }
        this._handleExecError(failure, stderr);
    }

    /**
     * SECTION 2: Generate and Render Mermaid Diagrams
     */
    private async _handleGenerateDiagram(workspacePath: string, type: string) {
        const cmdMap: { [key: string]: { title: string, cmd: string } } = {
            'arch': { title: 'Complete Architecture Diagram', cmd: 'bck-nd scan . --format mermaid' },
            'tree': { title: 'Project Structure Tree', cmd: 'bck-nd scan . --tree' },
            'uml': { title: 'UML Class Diagram', cmd: 'bck-nd scan . --uml --format mermaid' },
            'er': { title: 'Entity-Relationship Diagram (ER)', cmd: 'bck-nd scan . --er --format mermaid' },
            'routes': { title: 'Application Routes Diagram', cmd: 'bck-nd scan . --routes --format mermaid' },
            'infra': { title: 'Docker Infrastructure Diagram', cmd: 'bck-nd scan . --infra --format mermaid' },
            'trace': { title: 'Route-to-DB Map', cmd: 'bck-nd scan . --trace --format mermaid' },
            'prompt': { title: 'Complete AI Context (Prompt)', cmd: 'bck-nd prompt . -o -' },
            'datascience': { title: 'Data Lineage Map', cmd: 'bck-nd scan . --datascience' }
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
            return new Promise<void>((resolve) => {
                cp.exec(config.cmd, { cwd: workspacePath }, (error, stdout, stderr) => {
                    if (error) {
                        this._handleExecError(error, stderr);
                        resolve();
                        return;
                    }

                    const panel = vscode.window.createWebviewPanel(
                        'bckNdDiagram',
                        config.title,
                        vscode.ViewColumn.One,
                        {
                            enableScripts: true,
                            retainContextWhenHidden: true
                        }
                    );

                    // Choose webview layout depending on type
                    if (type === 'tree') {
                        panel.webview.html = getTreeWebviewContent(config.title, stdout);
                    } else if (type === 'prompt') {
                        panel.webview.html = getPromptWebviewContent(config.title, stdout);
                    } else {
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
                                    } catch (err: any) {
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
    private async _handleRunAudit(workspacePath: string, type: string) {
        if (type === 'docs') {
            vscode.window.withProgress({
                location: vscode.ProgressLocation.Notification,
                title: "Generating Local HTML Portal...",
                cancellable: false
            }, async () => {
                return new Promise<void>((resolve) => {
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
                                } else {
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

        const cmdMap: { [key: string]: { title: string, cmd: string } } = {
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
            return new Promise<void>((resolve) => {
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
                    } else {
                        this._outputChannel.appendLine(`\n>>> Execution finished successfully.`);
                        vscode.window.showInformationMessage(`${config.title} completed! Results in the Backend Helper panel.`);
                    }
                    resolve();
                });
            });
        });
    }

    private async _handleRunHealth(workspacePath: string) {
        this._outputChannel.clear();
        this._outputChannel.show();
        this._outputChannel.appendLine(`>>> Starting Project Health Score...`);
        this._outputChannel.appendLine(`>>> Working directory: ${workspacePath}`);
        this._outputChannel.appendLine(`>>> Running: bck-nd scan . --health\n`);

        vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: `Calculating Project Health Score...`,
            cancellable: false
        }, async () => {
            return new Promise<void>((resolve) => {
                cp.exec('bck-nd scan . --health', { cwd: workspacePath }, (error, stdout, stderr) => {
                    if (stdout) {
                        this._outputChannel.append(stripAnsi(stdout));
                    }
                    if (stderr) {
                        this._outputChannel.append('\n--- ERRORS / WARNINGS ---\n');
                        this._outputChannel.append(stripAnsi(stderr));
                    }

                    if (error) {
                        this._outputChannel.appendLine(`\n>>> ERROR: Command failed with code ${error.code}`);
                        this._handleExecError(error, stderr);
                    } else {
                        this._outputChannel.appendLine(`\n>>> Execution finished successfully.`);
                        vscode.window.showInformationMessage(`Project Health Score completed! Results in the Backend Helper panel.`);
                    }
                    resolve();
                });
            });
        });
    }

    private async _handleRunTeach(workspacePath: string) {
        this._outputChannel.clear();
        this._outputChannel.show();
        this._outputChannel.appendLine(`>>> Starting Guided Onboarding...`);
        this._outputChannel.appendLine(`>>> Working directory: ${workspacePath}`);
        this._outputChannel.appendLine(`>>> Running: bck-nd scan . --teach\n`);

        vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: `Generating Onboarding Path...`,
            cancellable: false
        }, async () => {
            return new Promise<void>((resolve) => {
                cp.exec('bck-nd scan . --teach', { cwd: workspacePath }, (error, stdout, stderr) => {
                    if (stdout) {
                        this._outputChannel.append(stripAnsi(stdout));
                    }
                    if (stderr) {
                        this._outputChannel.append('\n--- ERRORS / WARNINGS ---\n');
                        this._outputChannel.append(stripAnsi(stderr));
                    }

                    if (error) {
                        this._outputChannel.appendLine(`\n>>> ERROR: Command failed with code ${error.code}`);
                        this._handleExecError(error, stderr);
                    } else {
                        this._outputChannel.appendLine(`\n>>> Execution finished successfully.`);
                        vscode.window.showInformationMessage(`Guided Onboarding completed! Results in the Backend Helper panel.`);
                    }
                    resolve();
                });
            });
        });
    }

    private async _handleRunContract(workspacePath: string) {
        this._outputChannel.clear();
        this._outputChannel.show();
        this._outputChannel.appendLine(`>>> Starting API Contract Map...`);
        this._outputChannel.appendLine(`>>> Working directory: ${workspacePath}`);
        this._outputChannel.appendLine(`>>> Running: bck-nd scan . --contract\n`);

        vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: `Generating API Contract Map...`,
            cancellable: false
        }, async () => {
            return new Promise<void>((resolve) => {
                cp.exec('bck-nd scan . --contract', { cwd: workspacePath }, (error, stdout, stderr) => {
                    if (stdout) {
                        this._outputChannel.append(stripAnsi(stdout));
                    }
                    if (stderr) {
                        this._outputChannel.append('\n--- ERRORS / WARNINGS ---\n');
                        this._outputChannel.append(stripAnsi(stderr));
                    }

                    if (error) {
                        this._outputChannel.appendLine(`\n>>> ERROR: Command failed with code ${error.code}`);
                        this._handleExecError(error, stderr);
                    } else {
                        this._outputChannel.appendLine(`\n>>> Execution finished successfully.`);
                        vscode.window.showInformationMessage(`API Contract Map completed! Results in the Backend Helper panel.`);
                    }
                    resolve();
                });
            });
        });
    }

    /**
     * Elegant Error Handler
     */
    private _handleExecError(error: any, stderr: string) {
        console.error('Execution Error:', error);
        console.error('Stderr:', stderr);

        const errMsg = error.message || '';
        if (errMsg.includes('not found') || errMsg.includes('is not recognized') || error.code === 127) {
            vscode.window.showErrorMessage(
                "The CLI 'bck-nd' is not installed or not available in your system PATH.",
                "Install with pip"
            ).then(selection => {
                if (selection === "Install with pip") {
                    const terminal = vscode.window.createTerminal("Install Backend Helper");
                    terminal.show();
                    terminal.sendText("pip install bck-nd-hlpr");
                }
            });
        } else {
            vscode.window.showErrorMessage(`Error executing command: ${stderr || error.message}`);
        }
    }

    /**
     * Sidebar UI html template (using VS Code CSS variables, micro-animations, and collapsible sections)
     */
    private _getHtmlForWebview(webview: vscode.Webview): string {
        return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Backend Helper</title>
    <link rel="stylesheet" href="https://unpkg.com/@vscode/codicons@0.0.36/dist/codicon.css">
    <style>
        :root {
            --bg-color: var(--vscode-sideBar-background);
            --card-bg: var(--vscode-sideBarSectionHeader-background);
            --border-color: var(--vscode-sideBarSectionHeader-border, var(--vscode-panel-border));
            --text-main: var(--vscode-sideBar-foreground);
            --text-muted: var(--vscode-descriptionForeground);
            --accent: var(--vscode-focusBorder);
            --button-bg: var(--vscode-button-secondaryBackground);
            --button-hover: var(--vscode-button-secondaryHoverBackground);
        }
        body {
            padding: 12px 10px;
            color: var(--text-main);
            font-family: var(--vscode-font-family, sans-serif);
            font-size: var(--vscode-font-size, 13px);
            background-color: var(--bg-color);
            margin: 0;
        }
        
        .header {
            margin-bottom: 16px;
            padding-bottom: 12px;
            border-bottom: 1px solid var(--border-color);
        }
        
        .header h2 {
            margin: 0 0 4px 0;
            font-size: 1.15rem;
            font-weight: 600;
            color: var(--text-main);
            color: var(--vscode-sideBarTitle-foreground, var(--text-main));
        }
        
        .header p {
            margin: 0;
            font-size: 0.8rem;
            color: var(--text-muted);
        }

        details {
            margin-bottom: 12px;
            border: 1px solid var(--border-color);
            border-radius: 6px;
            overflow: hidden;
            background-color: var(--card-bg);
            transition: border-color 0.25s ease;
        }

        details:hover {
            border-color: var(--accent);
            box-shadow: 0 0 8px rgba(0, 240, 255, 0.2);
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
            background-color: var(--card-bg);
            color: var(--text-main);
            user-select: none;
            transition: background-color 0.2s ease;
        }

        summary::-webkit-details-marker {
            display: none;
        }

        summary:hover {
            background-color: rgba(255, 255, 255, 0.02);
        }

        details[open] summary {
            border-bottom: 1px solid var(--border-color);
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
            background-color: var(--button-bg);
            color: var(--text-main);
            border: 1px solid var(--border-color);
            padding: 8px 12px;
            border-radius: 6px;
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
        }

        .btn:hover {
            background-color: var(--button-hover);
            border-color: var(--accent);
            color: var(--text-main);
            box-shadow: 0 0 8px rgba(0, 240, 255, 0.3);
            text-shadow: 0 0 4px rgba(0, 240, 255, 0.3);
            transform: translateY(-1px);
        }

        .btn:active {
            transform: translateY(1px);
        }

        .btn-desc {
            margin: -4px 0 2px 0;
            font-size: 0.75rem;
            color: var(--text-muted);
            line-height: 1.25;
            padding-left: 2px;
        }

        .codicon {
            flex: 0 0 16px;
            color: var(--vscode-symbolIcon-functionForeground, var(--text-main));
        }

        .select-row {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 8px;
        }

        select {
            min-width: 0;
            color: var(--vscode-dropdown-foreground);
            background: var(--vscode-dropdown-background);
            border: 1px solid var(--vscode-dropdown-border);
            border-radius: 3px;
            padding: 7px 8px;
            font-family: inherit;
        }

        .select-row .btn {
            width: auto;
        }
    </style>
</head>
<body>
    <div class="header">
        <h2>Backend Helper</h2>
        <p>Four Pillars · Requirements Intelligence</p>
    </div>

    <!-- PILLAR 1: AI Context Provider -->
    <details open>
        <summary>
            <span>🧠 AI Context Provider</span>
            <svg class="chevron" viewBox="0 0 24 24">
                <polyline points="9 18 15 12 9 6"></polyline>
            </svg>
        </summary>
        <div class="section-content">
            <button class="btn" onclick="copyContext()">
                <span class="codicon codicon-copy"></span> Instant Copy
            </button>
            <p class="btn-desc">Generate and copy the full AI-ready project context in one step.</p>

            <label for="context-focus" class="btn-desc">Focused Context</label>
            <div class="select-row">
                <select id="context-focus" aria-label="Focused context type">
                    <option value="full">Complete project</option>
                    <option value="tree">Project tree</option>
                    <option value="uml">UML classes</option>
                    <option value="er">ER models</option>
                    <option value="diagrams">UML + ER diagrams</option>
                </select>
                <button class="btn" onclick="openFocusedContext()" title="Open focused context">
                    <span class="codicon codicon-open-preview"></span> Open
                </button>
            </div>
        </div>
    </details>

    <!-- PILLAR 2: Requirements Intelligence -->
    <details open>
        <summary>
            <span>📋 Requirements Intelligence</span>
            <svg class="chevron" viewBox="0 0 24 24">
                <polyline points="9 18 15 12 9 6"></polyline>
            </svg>
        </summary>
        <div class="section-content">
            <button class="btn" onclick="reqList()">
                <span class="codicon codicon-list-unordered"></span> List Stories
            </button>
            <p class="btn-desc">Inspect specifications stored in .bck-nd/requirements/.</p>

            <button class="btn" onclick="reqInit()">
                <span class="codicon codicon-new-file"></span> New Story (+)
            </button>
            <p class="btn-desc">Scaffold a standard Markdown requirement from a Story ID.</p>

            <button class="btn" onclick="reqDiscover()">
                <span class="codicon codicon-comment-discussion"></span> Discovery Guide
            </button>
            <p class="btn-desc">Open a stakeholder interview guide for an existing story.</p>
        </div>
    </details>

    <!-- PILLAR 3: Visual Diagrams -->
    <details open>
        <summary>
            <span>📊 Visual Diagrams</span>
            <svg class="chevron" viewBox="0 0 24 24">
                <polyline points="9 18 15 12 9 6"></polyline>
            </svg>
        </summary>
        <div class="section-content">
            <button class="btn" onclick="generateDiagram('uml')">
                <span class="codicon codicon-type-hierarchy"></span> UML Classes
            </button>
            <p class="btn-desc">Python, TypeScript, TSX, and React class/interface support.</p>

            <button class="btn" onclick="generateDiagram('er')">
                <span class="codicon codicon-database"></span> Entity Relationships
            </button>
            <p class="btn-desc">Visualize ORM models, keys, and database relationships.</p>

            <button class="btn" onclick="generateDiagram('routes')">
                <span class="codicon codicon-route"></span> Application Routes
            </button>
            <p class="btn-desc">Map discovered HTTP endpoints and route structure.</p>

            <button class="btn" onclick="generateDiagram('infra')">
                <span class="codicon codicon-server-environment"></span> Docker Infrastructure
            </button>
            <p class="btn-desc">Render services and dependencies from docker-compose.</p>
        </div>
    </details>

    <!-- PILLAR 4: DevSecOps & Quality -->
    <details open>
        <summary>
            <span>🛡️ DevSecOps & Quality</span>
            <svg class="chevron" viewBox="0 0 24 24">
                <polyline points="9 18 15 12 9 6"></polyline>
            </svg>
        </summary>
        <div class="section-content">
            <button class="btn" onclick="runHealth()">
                <span class="codicon codicon-heart"></span> Health Score
            </button>
            <p class="btn-desc">Calculate the consolidated project quality report card.</p>

            <button class="btn" onclick="runAudit('todo')">
                <span class="codicon codicon-checklist"></span> Scoped Debt
            </button>
            <p class="btn-desc">Identifies pending comments like TODO, FIXME, HACK, and BUG.</p>

            <button class="btn" onclick="runAudit('security')">
                <span class="codicon codicon-shield"></span> Security Audit
            </button>
            <p class="btn-desc">Detect exposed secrets, credentials, and insecure practices.</p>

            <button class="btn" onclick="runTeach()">
                <span class="codicon codicon-mortar-board"></span> Onboarding
            </button>
            <p class="btn-desc">Guided onboarding tour using the dependency heatmap.</p>
        </div>
    </details>

    <script>
        const vscode = acquireVsCodeApi();
        
        function copyContext() {
            vscode.postMessage({ command: 'copyContext' });
        }

        function openFocusedContext() {
            const focus = document.getElementById('context-focus').value;
            vscode.postMessage({ command: 'focusedContext', focus: focus });
        }

        function reqList() {
            vscode.postMessage({ command: 'reqList' });
        }

        function reqInit() {
            vscode.postMessage({ command: 'reqInit' });
        }

        function reqDiscover() {
            vscode.postMessage({ command: 'reqDiscover' });
        }
        
        function generateDiagram(type) {
            vscode.postMessage({ command: 'generateDiagram', type: type });
        }
        
        function runAudit(type) {
            vscode.postMessage({ command: 'runAudit', type: type });
        }

        function runHealth() {
            vscode.postMessage({ command: 'runHealth' });
        }

        function runTeach() {
            vscode.postMessage({ command: 'runTeach' });
        }

    </script>
</body>
</html>`;
    }
}

/**
 * Cleans the Mermaid code from ANSI escape sequences before rendering.
 */
function cleanMermaidCode(mermaidCode: string): string {
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
function stripAnsi(text: string): string {
    return text.replace(/[\u001b\u009b][[()#;?]*(?:[0-9]{1,4}(?:;[0-9]{0,4})*)?[0-9A-ORZcf-nqry=><]/g, '');
}

/**
 * Extracts project tree text from the CLI stdout
 */
function extractProjectTree(stdout: string): string | null {
    const clean = stripAnsi(stdout);
    const treeMarker = '[TREE]';
    const treeIdx = clean.indexOf(treeMarker);
    if (treeIdx === -1) { return null; }

    const afterMarker = clean.substring(treeIdx + treeMarker.length);
    const lines = afterMarker.split(/\r?\n/);

    const treeLines: string[] = [];
    let started = false;
    const nextSectionRegex = /^\[(UML|ER|API|INFRA|TODO|TREE)\]/;

    for (const line of lines) {
        const trimmed = line.trim();
        if (started && nextSectionRegex.test(trimmed)) { break; }
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
function getTreeWebviewContent(title: string, rawStdout: string): string {
    const clean = stripAnsi(rawStdout);
    const lines = clean.split(/\r?\n/);
    const treeLines: string[] = [];
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
        :root {
            --bg-color: #0d0e12;
            --fg-color: #e5e9f0;
            --border-color: #252936;
            --panel-bg: #151720;
            --accent: #00f0ff;
        }
        body {
            background-color: var(--bg-color);
            color: var(--fg-color);
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
            background-color: var(--panel-bg);
            border-bottom: 1px solid var(--border-color);
            flex-shrink: 0;
        }
        .header-bar h3 { margin: 0; font-size: 1rem; font-weight: 600; color: var(--fg-color); }
        .controls { display: flex; gap: 8px; }
        .btn {
            background-color: transparent;
            color: var(--fg-color);
            border: 1px solid var(--border-color);
            padding: 6px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.85rem;
            display: flex;
            align-items: center;
            gap: 6px;
            transition: all 0.2s ease;
        }
        .btn:hover {
            border-color: var(--accent);
            box-shadow: 0 0 8px rgba(0, 240, 255, 0.3);
            text-shadow: 0 0 4px rgba(0, 240, 255, 0.3);
        }
        .content-area { flex-grow: 1; overflow: auto; padding: 20px 24px; }
        pre {
            font-family: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', 'Consolas', monospace;
            font-size: 0.9rem;
            line-height: 1.6;
            padding: 1.5rem;
            background: rgba(255,255,255,0.02);
            border-radius: 8px;
            border: 1px solid var(--border-color);
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
function extractMermaidDiagrams(stdout: string): string[] {
    const diagrams: string[] = [];
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
function getSharedWebviewCSS(): string {
    return `
        :root {
            --bg-color: #0d0e12;
            --fg-color: #e5e9f0;
            --btn-bg: transparent;
            --btn-fg: #e5e9f0;
            --btn-border: #252936;
            --panel-bg: #151720;
            --border-color: #252936;
            --active-tab-bg: #0d0e12;
            --active-tab-fg: #e5e9f0;
            --inactive-tab-bg: #151720;
            --inactive-tab-fg: #8e96a7;
            --accent: #00f0ff;
        }
        body { background-color: var(--bg-color); color: var(--fg-color); font-family: var(--vscode-font-family, sans-serif); margin: 0; display: flex; flex-direction: column; height: 100vh; }
        .header-bar { display: flex; justify-content: space-between; align-items: center; padding: 10px 18px; background-color: var(--panel-bg); border-bottom: 1px solid var(--border-color); flex-shrink: 0; }
        .header-bar h3 { margin: 0; font-size: 1rem; font-weight: 600; color: var(--fg-color); }
        .controls { display: flex; gap: 8px; }
        .btn { background-color: var(--btn-bg); color: var(--btn-fg); border: 1px solid var(--btn-border); padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 0.85rem; display: flex; align-items: center; gap: 6px; transition: all 0.2s ease; }
        .btn:hover { border-color: var(--accent); box-shadow: 0 0 8px rgba(0, 240, 255, 0.3); text-shadow: 0 0 4px rgba(0, 240, 255, 0.3); }
        .tabs { display: flex; background-color: var(--panel-bg); border-bottom: 1px solid var(--border-color); flex-shrink: 0; overflow-x: auto; }
        .tab-btn { background: var(--inactive-tab-bg); color: var(--inactive-tab-fg); border: none; border-right: 1px solid var(--border-color); padding: 10px 16px; cursor: pointer; font-size: 0.85rem; white-space: nowrap; transition: all 0.2s ease; }
        .tab-btn.active { background: var(--active-tab-bg); color: var(--active-tab-fg); border-bottom: 2px solid var(--accent); }
        .content-area { flex-grow: 1; overflow: auto; position: relative; }
        .tab-content { display: none; height: 100%; }
        .tab-content.active { display: block; }
        .mermaid-wrapper { padding: 20px; display: flex; justify-content: center; align-items: flex-start; min-height: 100%; background-color: var(--bg-color); }
        .tree-wrapper { padding: 20px 24px; }
        .tree-wrapper pre { font-family: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', 'Consolas', monospace; font-size: 0.9rem; line-height: 1.6; padding: 1.5rem; background: rgba(255,255,255,0.02); border-radius: 8px; border: 1px solid var(--border-color); overflow-x: auto; white-space: pre; color: var(--fg-color); margin: 0; }
    `;
}

/**
 * Webview HTML Template for Mermaid diagram previews.
 * For 'arch' mode, also includes the project tree as a tab.
 */
function getMermaidWebviewContent(title: string, rawStdout: string) {
    const diagrams = extractMermaidDiagrams(rawStdout);
    const projectTree = extractProjectTree(rawStdout);

    if (diagrams.length === 0 && !projectTree) {
        return `<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"><title>${title}</title><style>body{background-color:#1e1e1e;color:#d4d4d4;padding:20px;font-family:sans-serif;}pre{background:rgba(255,255,255,0.05);padding:15px;border-radius:6px;overflow:auto;}</style></head><body><h3>No se pudo extraer contenido válido</h3><pre>${rawStdout.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')}</pre></body></html>`;
    }

    const tabsData: { type: string, title: string, code: string }[] = [];
    if (projectTree) tabsData.push({ type: 'tree', title: '🌳 Estructura de Proyecto', code: projectTree });
    diagrams.forEach((diag, index) => {
        const cleaned = cleanMermaidCode(diag);
        let diagTitle = title;
        const firstLine = cleaned.split('\n')[0].trim();
        if (firstLine.startsWith('classDiagram')) diagTitle = '🧬 Diagrama UML de Clases';
        else if (firstLine.startsWith('erDiagram')) diagTitle = '🗄️ Diagrama Entidad-Relación (ER)';
        else if (firstLine.startsWith('sequenceDiagram')) diagTitle = '🛣️ Trazabilidad de Rutas';
        else if (firstLine.startsWith('flowchart') || firstLine.startsWith('graph')) diagTitle = '🏗️ Arquitectura de Flujo';
        else if (diagrams.length > 1) diagTitle = `📊 Diagrama #${index + 1}`;
        tabsData.push({ type: 'mermaid', title: diagTitle, code: cleaned });
    });

    const showTabs = tabsData.length > 1;
    let tabsHeaderHtml = showTabs ? '<div class="tabs">' : '';
    let tabsContentHtml = '';
    let textareasHtml = '';
    let mermaidIndexes: number[] = [];

    tabsData.forEach((tab, index) => {
        if (showTabs) tabsHeaderHtml += `<button class="tab-btn ${index === 0 ? 'active' : ''}" onclick="switchTab(${index})">${tab.title}</button>`;
        const activeClass = index === 0 ? 'active' : '';
        const wrapperStart = showTabs ? `<div class="tab-content ${activeClass}" id="tab-content-${index}">` : '';
        const wrapperEnd = showTabs ? `</div>` : '';
        if (tab.type === 'tree') {
            const escaped = tab.code.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            tabsContentHtml += `${wrapperStart}<div class="tree-wrapper"><pre>${escaped}</pre></div>${wrapperEnd}`;
            textareasHtml += `<textarea id="source-${index}" style="display:none;" data-type="tree">${escaped}</textarea>`;
        } else {
            tabsContentHtml += `${wrapperStart}<div class="mermaid-wrapper"><div id="mermaid-view-${index}"></div></div>${wrapperEnd}`;
            textareasHtml += `<textarea id="source-${index}" style="display:none;" data-type="mermaid">${tab.code.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</textarea>`;
            mermaidIndexes.push(index);
        }
    });

    if (showTabs) tabsHeaderHtml += '</div>';

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
function getPromptWebviewContent(title: string, rawStdout: string): string {
    const clean = stripAnsi(rawStdout);
    const escaped = clean.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

    return `<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>${title}</title>
    <style>
        :root {
            --bg-color: #0d0e12;
            --fg-color: #e5e9f0;
            --border-color: #252936;
            --panel-bg: #151720;
            --accent: #00f0ff;
        }
        body {
            background-color: var(--bg-color);
            color: var(--fg-color);
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
            background-color: var(--panel-bg);
            border-bottom: 1px solid var(--border-color);
            flex-shrink: 0;
        }
        .header-bar h3 { margin: 0; font-size: 1rem; font-weight: 600; color: var(--fg-color); }
        .controls { display: flex; gap: 8px; }
        .btn {
            background-color: transparent;
            color: var(--fg-color);
            border: 1px solid var(--border-color);
            padding: 6px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.85rem;
            display: flex;
            align-items: center;
            gap: 6px;
            transition: all 0.2s ease;
        }
        .btn:hover {
            border-color: var(--accent);
            box-shadow: 0 0 8px rgba(0, 240, 255, 0.3);
            text-shadow: 0 0 4px rgba(0, 240, 255, 0.3);
        }
        .content-area { flex-grow: 1; overflow: auto; padding: 20px 24px; }
        pre {
            font-family: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', 'Consolas', monospace;
            font-size: 0.9rem;
            line-height: 1.6;
            padding: 1.5rem;
            background: rgba(255,255,255,0.02);
            border-radius: 8px;
            border: 1px solid var(--border-color);
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
