import html
import os
from pathlib import Path

from bck_nd_hlpr.core.infra_parser import parse_infra, parse_docker_compose, generate_mermaid_infra
from bck_nd_hlpr.core.route_parser import parse_project_routes, generate_mermaid_sequence
from bck_nd_hlpr.core.er_parser import parse_project_for_er, generate_mermaid_er
from bck_nd_hlpr.core.uml_parser import parse_file_for_uml, generate_mermaid_class_diagram
from bck_nd_hlpr.core.todo_hunter import scan_for_todos
from bck_nd_hlpr.core.scanner import ProjectScanner
from bck_nd_hlpr.core.tree_generator import generate_project_tree
from bck_nd_hlpr.core.context_dumper import ContextDumper

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Project Documentation</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0d0e12;
            --card-bg: #151720;
            --text-main: #e5e9f0;
            --text-muted: #8e96a7;
            --primary: #00f0ff; /* Electric Cyan */
            --border: #252936;
            --header-bg: #151720;
            --shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
            --textarea-bg: #0d0e12;
            --textarea-text: #e5e9f0;
            --preview-bg: #0d0e12;
            --badge-bg: rgba(0, 240, 255, 0.1);
            --gradient: linear-gradient(to right, #00f0ff, #00ff66);
        }

        [data-theme="dark"] {
            --bg-color: #0d0e12;
            --card-bg: #151720;
            --text-main: #e5e9f0;
            --text-muted: #8e96a7;
            --primary: #00ff66; /* Neon Cyber-Green */
            --border: #252936;
            --header-bg: #151720;
            --shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
            --textarea-bg: #0d0e12;
            --textarea-text: #e5e9f0;
            --preview-bg: #0d0e12;
            --badge-bg: rgba(0, 255, 102, 0.1);
            --gradient: linear-gradient(to right, #00ff66, #00f0ff);
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

        h1 { margin: 0; font-size: 1.5rem; font-weight: 700; background: var(--gradient); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }

        .header-actions {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            flex-wrap: wrap;
        }

        .theme-toggle, .copy-ai-btn, .copy-diagram-btn {
            background: transparent;
            border: 1px solid var(--border);
            padding: 0.5rem 1rem;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 600;
            color: var(--text-main);
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-family: inherit;
            font-size: 0.875rem;
            transition: all 0.2s ease;
        }
        .theme-toggle:hover, .copy-ai-btn:hover, .copy-diagram-btn:hover {
            border-color: var(--primary);
            color: var(--text-main);
            box-shadow: 0 0 8px rgba(0, 240, 255, 0.3);
            text-shadow: 0 0 4px rgba(0, 240, 255, 0.3);
        }
        
        [data-theme="dark"] .theme-toggle:hover, 
        [data-theme="dark"] .copy-ai-btn:hover, 
        [data-theme="dark"] .copy-diagram-btn:hover {
            box-shadow: 0 0 8px rgba(0, 255, 102, 0.3);
            text-shadow: 0 0 4px rgba(0, 255, 102, 0.3);
        }

        .copy-ai-btn {
            color: var(--text-main);
        }
        .copy-ai-btn.copied, .copy-diagram-btn.copied-highlight {
            border-color: #00ff66;
            color: #00ff66;
            box-shadow: 0 0 8px rgba(0, 255, 102, 0.4);
            text-shadow: 0 0 4px rgba(0, 255, 102, 0.4);
        }

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
            justify-content: space-between;
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
        tr:hover { background-color: rgba(0, 240, 255, 0.05); }
        [data-theme="dark"] tr:hover { background-color: rgba(0, 255, 102, 0.05); }

        .badge {
            background: var(--badge-bg);
            color: var(--primary);
            border: 1px solid var(--primary);
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 700;
            letter-spacing: 0.05em;
        }

        .copy-diagram-btn {
            padding: 0.4rem 0.8rem;
            font-size: 0.8rem;
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
        <div class="header-actions">
            <button class="copy-ai-btn" id="copy-ai-context-btn" type="button" title="Copy the full LLM-optimized project context to your clipboard">
                🤖 Copy Complete AI Context to Clipboard
            </button>
            <button class="theme-toggle" id="theme-toggle">
                <span id="theme-icon">🌙</span>
                <span id="theme-text">Dark Mode</span>
            </button>
        </div>
    </header>

    <textarea id="ai-context-content" style="display:none;" readonly aria-hidden="true">{ai_context}</textarea>

    <div class="container">
        <div class="card">
            <h2>
                <span style="display: flex; align-items: center; gap: 0.5rem;">
                    <span class="badge">TREE</span> Project Structure
                </span>
                <button class="copy-diagram-btn" id="copy-btn-tree" onclick="copyDiagram('tree')">📋 Copy Tree</button>
            </h2>
            <pre id="tree-code" style="font-family: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', monospace; font-size: 0.85rem; line-height: 1.6; padding: 1.5rem; background: var(--textarea-bg); border-radius: 8px; border: 1px solid var(--border); overflow-x: auto; white-space: pre; color: var(--text-main);">{project_tree}</pre>
        </div>

        <div class="card">
            <h2>
                <span style="display: flex; align-items: center; gap: 0.5rem;">
                    <span class="badge">INFRA</span> Infrastructure Map
                </span>
                <button class="copy-diagram-btn" id="copy-btn-infra" onclick="copyDiagram('infra')">📋 Copy Diagram</button>
            </h2>
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
            <h2>
                <span style="display: flex; align-items: center; gap: 0.5rem;">
                    <span class="badge">API</span> API Routes (Sequence)
                </span>
                <button class="copy-diagram-btn" id="copy-btn-seq" onclick="copyDiagram('seq')">📋 Copy Diagram</button>
            </h2>
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
            <h2>
                <span style="display: flex; align-items: center; gap: 0.5rem;">
                    <span class="badge">UML</span> UML Class Diagram
                </span>
                <button class="copy-diagram-btn" id="copy-btn-uml" onclick="copyDiagram('uml')">📋 Copy Diagram</button>
            </h2>
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
            <h2>
                <span style="display: flex; align-items: center; gap: 0.5rem;">
                    <span class="badge">ER</span> Entity-Relationship Diagram
                </span>
                <button class="copy-diagram-btn" id="copy-btn-er" onclick="copyDiagram('er')">📋 Copy Diagram</button>
            </h2>
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
            <h2>
                <span style="display: flex; align-items: center; gap: 0.5rem;">
                    <span class="badge">TODO</span> Technical Debt & TODOs
                </span>
            </h2>
            <div style="overflow-x: auto;">
                {todos_table}
            </div>
        </div>
    </div>

    <script type="module">
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';

        const copyAiBtn = document.getElementById('copy-ai-context-btn');
        const aiContextEl = document.getElementById('ai-context-content');
        const defaultCopyLabel = copyAiBtn.textContent;

        copyAiBtn.addEventListener('click', async () => {
            const text = aiContextEl.value;
            try {
                await navigator.clipboard.writeText(text);
            } catch (err) {
                // Fallback for file:// or restricted clipboard permissions
                aiContextEl.style.display = 'block';
                aiContextEl.select();
                document.execCommand('copy');
                aiContextEl.style.display = 'none';
            }
            copyAiBtn.textContent = 'Copied! 👍';
            copyAiBtn.classList.add('copied');
            setTimeout(() => {
                copyAiBtn.textContent = defaultCopyLabel;
                copyAiBtn.classList.remove('copied');
            }, 2000);
        });

        window.copyDiagram = async function(id) {
            const el = document.getElementById(id + '-source') || document.getElementById(id + '-code');
            const btn = document.getElementById('copy-btn-' + id);
            if (!el || !btn) return;
            const originalText = btn.innerHTML;
            const text = el.tagName === 'TEXTAREA' ? el.value : el.textContent;
            try {
                await navigator.clipboard.writeText(text);
            } catch (err) {
                // Fallback for restricted clipboards
                if (el.tagName === 'TEXTAREA') {
                    const prevDisplay = el.style.display;
                    el.style.display = 'block';
                    el.select();
                    document.execCommand('copy');
                    el.style.display = prevDisplay;
                } else {
                    const range = document.createRange();
                    range.selectNodeContents(el);
                    const sel = window.getSelection();
                    sel.removeAllRanges();
                    sel.addRange(range);
                    document.execCommand('copy');
                    sel.removeAllRanges();
                }
            }
            btn.innerHTML = 'Copied! ✔️';
            btn.classList.add('copied-highlight');
            setTimeout(() => {
                btn.innerHTML = originalText;
                btn.classList.remove('copied-highlight');
            }, 2000);
        };

        const themeToggle = document.getElementById('theme-toggle');
        const themeIcon = document.getElementById('theme-icon');
        const themeText = document.getElementById('theme-text');
        const html = document.documentElement;

        function getTheme() {
            return localStorage.getItem('theme') || 'dark';
        }

        async function setTheme(theme) {
            html.setAttribute('data-theme', theme);
            localStorage.setItem('theme', theme);
            themeIcon.textContent = theme === 'dark' ? '☀️' : '🌙';
            themeText.textContent = theme === 'dark' ? 'Light Mode' : 'Dark Mode';
            
            // Initialize mermaid with new theme (always dark theme for diagrams in Cyber-Dark)
            mermaid.initialize({ 
                startOnLoad: false, 
                theme: 'dark',
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
        framework = arch_info.get('framework', '')
        is_csharp = framework == '.NET Core / C#'
        is_express = framework == 'Express.js'
        is_nextjs = framework == 'Next.js'
        is_django = framework == 'Django'
        is_spring = framework in ['Spring Boot', 'Java (Maven)', 'Java (Gradle)']
        is_laravel = framework in ['Laravel', 'PHP']
        
        # 0. Project Tree
        project_tree = generate_project_tree(root_path)
        if not project_tree:
            project_tree = "No project structure detected."

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
            from bck_nd_hlpr.core.csharp_parser import parse_project_for_csharp_uml
            classes = parse_project_for_csharp_uml(root_path)
            if classes:
                uml_diagram = generate_mermaid_class_diagram(classes)
        elif is_express or is_nextjs:
            from bck_nd_hlpr.core.js_parser import parse_project_for_js_uml
            classes = parse_project_for_js_uml(root_path)
            if classes:
                uml_diagram = generate_mermaid_class_diagram(classes)
        elif is_django:
            from bck_nd_hlpr.core.django_parser import parse_project_for_django_uml
            classes = parse_project_for_django_uml(root_path)
            if classes:
                uml_diagram = generate_mermaid_class_diagram(classes)
        elif is_spring:
            from bck_nd_hlpr.core.java_parser import parse_project_for_java_uml
            classes = parse_project_for_java_uml(root_path)
            if classes:
                uml_diagram = generate_mermaid_class_diagram(classes)
        elif is_laravel:
            from bck_nd_hlpr.core.php_parser import parse_project_for_php_uml
            classes = parse_project_for_php_uml(root_path)
            if classes:
                uml_diagram = generate_mermaid_class_diagram(classes)
        else:
            uml_code = scanner.scan_uml(root_path)
            if uml_code and "class Empty" not in uml_code:
                uml_diagram = uml_code
        
        # 4. ER
        er_diagram = "erDiagram\n    EMPTY ||--|| EMPTY : \"No data detected\""
        if is_csharp:
            from bck_nd_hlpr.core.csharp_parser import parse_project_for_csharp_er
            entities = parse_project_for_csharp_er(root_path)
        elif is_express or is_nextjs:
            from bck_nd_hlpr.core.js_parser import parse_project_for_js_er
            entities = parse_project_for_js_er(root_path)
        elif is_django:
            from bck_nd_hlpr.core.django_parser import parse_project_for_django_er
            entities = parse_project_for_django_er(root_path)
        elif is_spring:
            from bck_nd_hlpr.core.java_parser import parse_project_for_java_er
            entities = parse_project_for_java_er(root_path)
        elif is_laravel:
            from bck_nd_hlpr.core.php_parser import parse_project_for_php_er
            entities = parse_project_for_php_er(root_path)
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

        # 5. AI Context dump (LLM-optimized XML) for clipboard copy
        try:
            ai_context = ContextDumper(path=root_path).build()
        except Exception as e:
            ai_context = f"<!-- Failed to generate AI context: {e} -->"
        ai_context_escaped = html.escape(ai_context)

        # Render HTML (ai_context last so dump content cannot collide with other placeholders)
        html_content = HTML_TEMPLATE.replace(
            "{project_tree}", project_tree
        ).replace(
            "{infra_diagram}", infra_diagram
        ).replace(
            "{sequence_diagram}", sequence_diagram
        ).replace(
            "{uml_diagram}", uml_diagram
        ).replace(
            "{er_diagram}", er_diagram
        ).replace(
            "{todos_table}", todos_table
        ).replace(
            "{ai_context}", ai_context_escaped
        )

        # Write to file
        try:
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            output_file = os.path.join(output_dir, "index.html")
            
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(html_content)
                
            return output_file
        except OSError as e:
            print(f"Error creating output directory or writing HTML file: {e}")
            return None
        except UnicodeEncodeError as e:
            print(f"Encoding error while writing HTML file: {e}")
            return None
        except Exception as e:
            print(f"Unexpected error generating documentation: {e}")
            return None
