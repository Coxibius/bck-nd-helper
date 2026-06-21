import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as os from 'os';
import * as path from 'path';
import * as fs from 'fs';

export function activate(context: vscode.ExtensionContext) {
    console.log('Backend Helper extension is now active!');

    let disposable = vscode.commands.registerCommand('bck-nd.generateDiagram', async () => {
        // Detect open workspace
        const workspaceFolders = vscode.workspace.workspaceFolders;
        if (!workspaceFolders || workspaceFolders.length === 0) {
            vscode.window.showErrorMessage('No workspace opened. Please open a project folder to scan.');
            return;
        }

        const workspacePath = workspaceFolders[0].uri.fsPath;
        
        // Define temporary output path for safety
        const tmpDir = os.tmpdir();
        const tmpFileName = `bck-nd-diagram-${Date.now()}.mmd`;
        const tmpFilePath = path.join(tmpDir, tmpFileName);

        vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: "Scanning architecture with bck-nd...",
            cancellable: false
        }, async (progress) => {
            return new Promise<void>((resolve, reject) => {
                // Command to execute: bck-nd scan <workspace> --format mermaid -o <tmpfile>
                // We use shell: true to allow it to find the bck-nd executable in the system PATH
                const scanCommand = `bck-nd scan "${workspacePath}" --format mermaid -o "${tmpFilePath}"`;

                cp.exec(scanCommand, { cwd: workspacePath }, (error, stdout, stderr) => {
                    if (error) {
                        console.error('Execution Error:', error);
                        console.error('Stderr:', stderr);
                        
                        // Check if bck-nd is not installed or not in PATH
                        if (error.message.includes('not found') || error.message.includes('is not recognized')) {
                            vscode.window.showErrorMessage("Error: 'bck-nd' command not found. Ensure bck-nd-hlpr is installed globally (e.g. pip install bck-nd-hlpr) and available in your system PATH.");
                        } else {
                            vscode.window.showErrorMessage(`Error scanning project: ${stderr || error.message}`);
                        }
                        reject(error);
                        return;
                    }

                    // Read the generated Mermaid file
                    if (!fs.existsSync(tmpFilePath)) {
                        vscode.window.showErrorMessage('Error: Diagram file was not generated.');
                        reject(new Error('File not found'));
                        return;
                    }

                    const mermaidData = fs.readFileSync(tmpFilePath, 'utf8');

                    // Create and show a new webview
                    const panel = vscode.window.createWebviewPanel(
                        'bckNdDiagram',
                        'Architecture Diagram',
                        vscode.ViewColumn.One,
                        {
                            enableScripts: true
                        }
                    );

                    panel.webview.html = getWebviewContent(mermaidData);
                    
                    vscode.window.showInformationMessage('Architecture diagram generated successfully!');
                    resolve();
                });
            });
        });
    });

    context.subscriptions.push(disposable);
}

export function deactivate() {}

// Renders the webview HTML injecting the Mermaid content via CDN
function getWebviewContent(mermaidCode: string) {
    // Strip markdown backticks if they were generated
    let cleanCode = mermaidCode.trim();
    if (cleanCode.startsWith('```mermaid')) {
        cleanCode = cleanCode.substring(10);
    }
    if (cleanCode.endsWith('```')) {
        cleanCode = cleanCode.substring(0, cleanCode.length - 3);
    }
    cleanCode = cleanCode.trim();

    return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Backend Helper Diagram</title>
    <!-- Use Mermaid CDN -->
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    <style>
        body {
            background-color: white; /* Ensure good contrast for diagram */
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
    </style>
</head>
<body>
    <div class="mermaid">
        ${cleanCode}
    </div>
    <script>
        mermaid.initialize({ startOnLoad: true, theme: 'default' });
    </script>
</body>
</html>`;
}
