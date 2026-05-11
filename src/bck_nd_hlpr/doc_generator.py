import os
from pathlib import Path

from bck_nd_hlpr.infra_parser import parse_infra, parse_docker_compose, generate_mermaid_infra
from bck_nd_hlpr.route_parser import parse_project_routes, generate_mermaid_sequence
from bck_nd_hlpr.er_parser import parse_project_for_er, generate_mermaid_er
from bck_nd_hlpr.uml_parser import parse_file_for_uml, generate_mermaid_class_diagram
from bck_nd_hlpr.todo_hunter import scan_for_todos
from bck_nd_hlpr.scanner import ProjectScanner

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Project Documentation</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #f8fafc;
            --card-bg: #ffffff;
            --text-main: #1e293b;
            --text-muted: #64748b;
            --primary: #3b82f6;
            --border: #e2e8f0;
            --header-bg: #ffffff;
            --shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1);
            --textarea-bg: #f1f5f9;
            --textarea-text: #0f172a;
            --preview-bg: #ffffff;
        }

        [data-theme="dark"] {
            --bg-color: #0f172a;
            --card-bg: #1e293b;
            --text-main: #f1f5f9;
            --text-muted: #94a3b8;
            --primary: #60a5fa;
            --border: #334155;
            --header-bg: #1e293b;
            --shadow: 0 10px 15px -3px rgb(0 0 0 / 0.5);
            --textarea-bg: #0f172a;
            --textarea-text: #f1f5f9;
            --preview-bg: #0f172a;
        }

        * { box-sizing: border-box; transition: background-color 0.2s, color 0.2s, border-color 0.2s; }
        body { 
            font-family: 'Inter', system-ui, -apple-system, sans-serif; 
            background-color: var(--bg-color); 
            color: var(--text-main); 
            margin: 0; 
            padding: 0; 
            line-height: 1.5;
        }
        
        header {
            position: sticky;
            top: 0;
            z-index: 100;
            background: var(--header-bg);
            border-bottom: 1px solid var(--border);
            padding: 1rem 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            backdrop-filter: blur(8px);
        }

        h1 { margin: 0; font-size: 1.5rem; font-weight: 700; background: linear-gradient(to right, var(--primary), #8b5cf6); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }

        .theme-toggle {
            background: var(--border);
            border: none;
            padding: 0.5rem 1rem;
            border-radius: 9999px;
            cursor: pointer;
            font-weight: 600;
            color: var(--text-main);
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        .theme-toggle:hover { opacity: 0.8; }

        .container { max-width: 1400px; margin: 2rem auto; padding: 0 1rem; }
        
        .card { 
            background: var(--card-bg); 
            padding: 2rem; 
            margin-bottom: 2rem; 
            border-radius: 12px; 
            border: 1px solid var(--border);
            box-shadow: var(--shadow); 
        }
        
        .card h2 { 
            margin-top: 0; 
            font-size: 1.25rem;
            border-bottom: 1px solid var(--border); 
            padding-bottom: 1rem; 
            margin-bottom: 1.5rem;
            color: var(--text-main);
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }

        .editor-container { display: flex; gap: 1.5rem; align-items: stretch; flex-wrap: wrap; }
        .editor-pane { flex: 1; min-width: 300px; display: flex; flex-direction: column; }
        .editor-pane textarea { 
            flex-grow: 1; min-height: 300px; font-family: monospace; padding: 1rem; 
            background: var(--textarea-bg);
            color: var(--textarea-text);
            border: 1px solid var(--border); 
            border-radius: 8px; 
            resize: vertical; 
            font-size: 0.875rem;
            line-height: 1.4;
        }
        
        .preview-pane { 
            flex: 2; 
            overflow: auto; 
            background: var(--preview-bg); 
            border: 1px solid var(--border); 
            padding: 2rem; 
            border-radius: 8px; 
            display: flex; 
            justify-content: center; 
            align-items: flex-start; 
            min-height: 300px;
        }
        
        table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
        th, td { border: 1px solid var(--border); padding: 1rem; text-align: left; }
        th { background-color: var(--textarea-bg); font-weight: 600; color: var(--text-muted); text-transform: uppercase; font-size: 0.75rem; letter-spacing: 0.05em; }
        tr:hover { background-color: rgba(59, 130, 246, 0.05); }

        .badge {
            background: var(--primary);
            color: white;
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 700;
        }

        @media (max-width: 1024px) {
            .editor-container { flex-direction: column; }
            .preview-pane { width: 100%; }
        }
    </style>
</head>
<body>
    <header>
        <h1>Project Architecture Documentation 🛠️</h1>
        <button class="theme-toggle" id="theme-toggle">
            <span id="theme-icon">🌙</span>
            <span id="theme-text">Dark Mode</span>
        </button>
    </header>

    <div class="container">
        <div class="card">
            <h2><span class="badge">INFRA</span> Infrastructure Map</h2>
            <div class="editor-container">
                <div class="editor-pane">
                    <textarea id="infra-source" data-target="infra">{infra_diagram}</textarea>
                </div>
                <div class="preview-pane">
                    <div id="infra-view"></div>
                </div>
            </div>
        </div>

        <div class="card">
            <h2><span class="badge">API</span> API Routes (Sequence)</h2>
            <div class="editor-container">
                <div class="editor-pane">
                    <textarea id="seq-source" data-target="seq">{sequence_diagram}</textarea>
                </div>
                <div class="preview-pane">
                    <div id="seq-view"></div>
                </div>
            </div>
        </div>

        <div class="card">
            <h2><span class="badge">UML</span> UML Class Diagram</h2>
            <div class="editor-container">
                <div class="editor-pane">
                    <textarea id="uml-source" data-target="uml">{uml_diagram}</textarea>
                </div>
                <div class="preview-pane">
                    <div id="uml-view"></div>
                </div>
            </div>
        </div>

        <div class="card">
            <h2><span class="badge">ER</span> Entity-Relationship Diagram</h2>
            <div class="editor-container">
                <div class="editor-pane">
                    <textarea id="er-source" data-target="er">{er_diagram}</textarea>
                </div>
                <div class="preview-pane">
                    <div id="er-view"></div>
                </div>
            </div>
        </div>

        <div class="card">
            <h2><span class="badge">TODO</span> Technical Debt & TODOs</h2>
            <div style="overflow-x: auto;">
                {todos_table}
            </div>
        </div>
    </div>

    <script type="module">
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';

        const themeToggle = document.getElementById('theme-toggle');
        const themeIcon = document.getElementById('theme-icon');
        const themeText = document.getElementById('theme-text');
        const html = document.documentElement;

        function getTheme() {
            return localStorage.getItem('theme') || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
        }

        async function setTheme(theme) {
            html.setAttribute('data-theme', theme);
            localStorage.setItem('theme', theme);
            themeIcon.textContent = theme === 'dark' ? '☀️' : '🌙';
            themeText.textContent = theme === 'dark' ? 'Light Mode' : 'Dark Mode';
            
            // Initialize mermaid with new theme
            mermaid.initialize({ 
                startOnLoad: false, 
                theme: theme === 'dark' ? 'dark' : 'default',
                fontFamily: 'Inter'
            });
            
            // Re-render all diagrams
            const ids = ['infra', 'seq', 'er', 'uml'];
            for (const id of ids) {
                await updateDiagram(id);
            }
        }

        themeToggle.addEventListener('click', () => {
            const newTheme = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
            setTheme(newTheme);
        });

        async function updateDiagram(id) {
            const sourceText = document.getElementById(id + '-source').value;
            const viewElement = document.getElementById(id + '-view');
            try {
                viewElement.innerHTML = ''; // Clear previous
                const { svg } = await mermaid.render('mermaid-' + id + '-' + Date.now(), sourceText);
                viewElement.innerHTML = svg;
            } catch (err) {
                console.error("Mermaid syntax error for " + id + ":", err);
            }
        }

        // Initialize everything
        const initialTheme = getTheme();
        await setTheme(initialTheme);

        ['infra', 'seq', 'er', 'uml'].forEach(id => {
            document.getElementById(id + '-source').addEventListener('input', () => {
                updateDiagram(id);
            });
        });
    </script>
</body>
</html>
"""


class DocGenerator:
    def generate(self, root_path: str, output_dir: str = "docs"):
        scanner = ProjectScanner()
        arch_info = scanner.detect_architecture(root_path)
        is_csharp = arch_info.get('framework') == '.NET Core / C#'
        
        # 1. Infra
        compose_file = parse_infra(root_path)
        infra_diagram = "graph LR\n    empty[No data detected]"
        if compose_file:
            services = parse_docker_compose(compose_file)
            if services:
                infra_diagram = generate_mermaid_infra(services)
        
        # 2. Routes
        routes = parse_project_routes(root_path)
        sequence_diagram = "sequenceDiagram\n    participant None\n    Note over None: No data detected"
        if routes:
            gen_seq = generate_mermaid_sequence(routes)
            if gen_seq:
                sequence_diagram = gen_seq
                
        # 3. UML
        uml_diagram = "classDiagram\n    class Empty {\n      +No data detected\n    }"
        if is_csharp:
            from bck_nd_hlpr.csharp_parser import parse_project_for_csharp_uml
            classes = parse_project_for_csharp_uml(root_path)
            if classes:
                uml_diagram = generate_mermaid_class_diagram(classes)
        else:
            uml_code = scanner.scan_uml(root_path)
            if uml_code and "class Empty" not in uml_code:
                uml_diagram = uml_code
        
        # 4. ER
        er_diagram = "erDiagram\n    EMPTY ||--|| EMPTY : \"No data detected\""
        if is_csharp:
            from bck_nd_hlpr.csharp_parser import parse_project_for_csharp_er
            entities = parse_project_for_csharp_er(root_path)
        else:
            entities = parse_project_for_er(root_path)
            
        if entities:
            gen_er = generate_mermaid_er(entities)
            if gen_er:
                er_diagram = gen_er
        
        # 4. TODOs
        todos = scan_for_todos(root_path)
        if todos:
            todos_table = "<table><tr><th>File</th><th>Line</th><th>Type</th><th>Message</th></tr>\n"
            for t in todos:
                todos_table += f"<tr><td>{t.get('file', '')}</td><td>{t.get('line', '')}</td><td>{t.get('type', '')}</td><td>{t.get('message', '')}</td></tr>\n"
            todos_table += "</table>"
        else:
            todos_table = "<p>No data detected</p>"

        # Render HTML
        html_content = HTML_TEMPLATE.replace(
            "{infra_diagram}", infra_diagram
        ).replace(
            "{sequence_diagram}", sequence_diagram
        ).replace(
            "{uml_diagram}", uml_diagram
        ).replace(
            "{er_diagram}", er_diagram
        ).replace(
            "{todos_table}", todos_table
        )

        # Write to file
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        output_file = os.path.join(output_dir, "index.html")
        
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(html_content)
            
        return output_file
