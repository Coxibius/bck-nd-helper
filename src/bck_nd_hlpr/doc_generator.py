import os
from pathlib import Path

from bck_nd_hlpr.infra_parser import parse_infra, parse_docker_compose, generate_mermaid_infra
from bck_nd_hlpr.route_parser import parse_project_routes, generate_mermaid_sequence
from bck_nd_hlpr.er_parser import parse_project_for_er, generate_mermaid_er
from bck_nd_hlpr.uml_parser import parse_file_for_uml, generate_mermaid_class_diagram
from bck_nd_hlpr.todo_hunter import scan_for_todos
from bck_nd_hlpr.scanner import ProjectScanner

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Project Documentation</title>
    <style>
        body { font-family: system-ui, -apple-system, sans-serif; background-color: #f4f4f9; color: #333; margin: 0; padding: 20px; }
        .container { max-width: 1400px; margin: auto; }
        h1 { color: #2c3e50; text-align: center; margin-bottom: 40px; }
        .card { background: #fff; padding: 20px; margin-bottom: 30px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
        .card h2 { margin-top: 0; border-bottom: 2px solid #eaeaea; padding-bottom: 10px; color: #2c3e50; }
        
        .editor-container { display: flex; gap: 20px; align-items: stretch; margin-top: 15px; }
        .editor-pane { flex: 1; min-width: 300px; display: flex; flex-direction: column; }
        .editor-pane textarea { 
            flex-grow: 1; min-height: 250px; font-family: monospace; padding: 12px; 
            border: 1px solid #ccc; border-radius: 4px; resize: vertical; white-space: pre; 
        }
        .preview-pane { 
            flex: 2; overflow: auto; background: #fdfdfd; border: 1px dashed #ccc; 
            padding: 20px; border-radius: 4px; display: flex; justify-content: center; align-items: center; min-height: 250px;
        }
        
        table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        th, td { border: 1px solid #ddd; padding: 12px; text-align: left; }
        th { background-color: #f8f9fa; font-weight: bold; }
        tr:nth-child(even) { background-color: #fcfcfc; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Project Architecture Documentation 🛠️</h1>

        <div class="card">
            <h2>Infrastructure Map</h2>
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
            <h2>API Routes (Sequence)</h2>
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
            <h2>UML Class Diagram</h2>
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
            <h2>Entity-Relationship Diagram</h2>
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
            <h2>Technical Debt & TODOs</h2>
            {todos_table}
        </div>
    </div>

    <script type="module">
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
        mermaid.initialize({ startOnLoad: false, theme: 'default' });

        async function updateDiagram(id) {
            const sourceText = document.getElementById(id + '-source').value;
            const viewElement = document.getElementById(id + '-view');
            try {
                // Render returns { svg, bindFunctions }
                const { svg } = await mermaid.render('mermaid-' + id, sourceText);
                viewElement.innerHTML = svg;
                viewElement.style.color = 'inherit';
            } catch (err) {
                // Just visually indicate error, mermaid usually leaves an error SVG, but just in case
                console.error("Mermaid syntax error:", err);
            }
        }

        // Initialize all diagrams on load
        ['infra', 'seq', 'er', 'uml'].forEach(id => {
            updateDiagram(id);
            // Listen to typing
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
