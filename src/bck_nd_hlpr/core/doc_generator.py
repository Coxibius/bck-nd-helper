import html
import os
import re
from pathlib import Path

from bck_nd_hlpr.core.infra_parser import parse_infra, parse_docker_compose, generate_mermaid_infra
from bck_nd_hlpr.core.route_parser import parse_project_routes, generate_mermaid_sequence
from bck_nd_hlpr.core.er_parser import parse_project_for_er, generate_mermaid_er
from bck_nd_hlpr.core.uml_parser import (
    generate_mermaid_class_diagram,
    is_empty_mermaid_class_diagram,
    parse_file_for_uml,
)
from bck_nd_hlpr.core.todo_hunter import scan_for_todos
from bck_nd_hlpr.core.scanner import ProjectScanner
from bck_nd_hlpr.core.tree_generator import generate_project_tree
from bck_nd_hlpr.core.context_dumper import ContextDumper
from bck_nd_hlpr.core.requirements import RequirementsParser


def _offline_svg_preview(source: str, title: str) -> str:
    """Render a dependency-free SVG preview that remains visible offline."""
    lines = [line.rstrip() for line in source.splitlines() if line.strip()]
    visible_lines = lines[:120] or ["No diagram data detected"]
    if len(lines) > len(visible_lines):
        visible_lines.append(f"... {len(lines) - len(visible_lines)} additional lines")
    width = 1100
    line_height = 24
    height = max(180, 70 + (len(visible_lines) * line_height))
    safe_title = html.escape(title, quote=True)
    text_rows = []
    for index, line in enumerate(visible_lines):
        y = 58 + (index * line_height)
        safe_line = html.escape(line, quote=False)
        text_rows.append(
            f'<text x="24" y="{y}" xml:space="preserve">{safe_line}</text>'
        )
    return (
        f'<svg class="offline-diagram" data-renderer="offline-svg" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Offline preview: {safe_title}" '
        f'xmlns="http://www.w3.org/2000/svg">'
        '<rect width="100%" height="100%" rx="10" fill="#0d0e12"/>'
        f'<text class="offline-title" x="24" y="30">{safe_title} · Offline SVG</text>'
        '<g class="offline-source">'
        + "".join(text_rows)
        + "</g></svg>"
    )


def _requirements_section(root_path: str) -> str:
    """Build a safe, standalone requirements dashboard section when present."""
    specs = RequirementsParser.load_from_directory(root_path)
    if not specs:
        return ""

    rows = []
    for spec in specs:
        story = spec.story
        rows.append(
            "<tr>"
            f"<td><strong>{html.escape(str(story.id or 'N/A'))}</strong></td>"
            f"<td><span class=\"status-badge\">{html.escape(str(story.status or 'TODO'))}</span></td>"
            f"<td>{html.escape(str(story.title or 'Untitled'))}</td>"
            f"<td>{html.escape(str(story.role or '-'))}</td>"
            f"<td>{len(spec.acceptance_criteria)}</td>"
            f"<td>{len(spec.business_rules)}</td>"
            "</tr>"
        )
    return (
        '<section class="card" id="requirements">'
        '<h2><span><span class="badge">REQ</span> Project Requirements</span></h2>'
        '<div class="table-scroll"><table>'
        '<thead><tr><th>Story ID</th><th>Status</th><th>Title</th><th>Role</th>'
        '<th>Criteria</th><th>Rules</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>'
        '</section>'
    )


def _render_template(template: str, replacements: dict[str, str]) -> str:
    """Replace placeholders in one pass so inserted project text is never reprocessed."""
    pattern = re.compile("|".join(re.escape(key) for key in replacements))
    return pattern.sub(lambda match: replacements[match.group(0)], template)

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Project Documentation</title>
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

        .dashboard-nav {
            max-width: 1400px;
            margin: 1rem auto 0;
            padding: 0 1rem;
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
        }
        .dashboard-nav a {
            color: var(--text-main);
            text-decoration: none;
            border: 1px solid var(--border);
            border-radius: 999px;
            padding: 0.4rem 0.8rem;
            font-size: 0.8rem;
        }
        .dashboard-nav a:hover { border-color: var(--primary); color: var(--primary); }
        
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
        .table-scroll { overflow-x: auto; }
        .status-badge { color: var(--primary); font-weight: 700; white-space: nowrap; }

        .offline-diagram { width: 100%; min-width: 680px; height: auto; }
        .offline-title { fill: #00ff66; font: 700 16px system-ui, sans-serif; }
        .offline-source { fill: #e5e9f0; font: 13px ui-monospace, monospace; }

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
        @media (max-width: 640px) {
            header { position: static; align-items: flex-start; flex-direction: column; gap: 1rem; padding: 1rem; }
            .container { margin-top: 1rem; }
            .card { padding: 1rem; }
            .card h2 { align-items: flex-start; flex-direction: column; }
            .editor-pane { min-width: 100%; }
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

    <nav class="dashboard-nav" aria-label="Documentation sections">
        <a href="#tree">Structure</a><a href="#infra">Infrastructure</a>
        <a href="#routes">Routes</a><a href="#uml">UML</a><a href="#er">ER</a>
        {requirements_nav}<a href="#debt">Technical Debt</a>
    </nav>

    <div class="container">
        <section class="card" id="tree">
            <h2>
                <span style="display: flex; align-items: center; gap: 0.5rem;">
                    <span class="badge">TREE</span> Project Structure
                </span>
                <button class="copy-diagram-btn" id="copy-btn-tree" onclick="copyDiagram('tree')">📋 Copy Tree</button>
            </h2>
            <pre id="tree-code" style="font-family: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', monospace; font-size: 0.85rem; line-height: 1.6; padding: 1.5rem; background: var(--textarea-bg); border-radius: 8px; border: 1px solid var(--border); overflow-x: auto; white-space: pre; color: var(--text-main);">{project_tree}</pre>
        </section>

        <section class="card" id="infra">
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
                    <div id="infra-view">{infra_fallback_svg}</div>
                </div>
            </div>
        </section>

        <section class="card" id="routes">
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
                    <div id="seq-view">{sequence_fallback_svg}</div>
                </div>
            </div>
        </section>

        <section class="card" id="uml">
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
                    <div id="uml-view">{uml_fallback_svg}</div>
                </div>
            </div>
        </section>

        <section class="card" id="er">
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
                    <div id="er-view">{er_fallback_svg}</div>
                </div>
            </div>
        </section>

        {requirements_section}

        <section class="card" id="debt">
            <h2>
                <span style="display: flex; align-items: center; gap: 0.5rem;">
                    <span class="badge">TODO</span> Technical Debt & TODOs
                </span>
            </h2>
            <div style="overflow-x: auto;">
                {todos_table}
            </div>
        </section>
    </div>

    <script type="module">
        // Dependency-free Mermaid fallback. It renders the diagram source into
        // an accessible SVG so the portal remains useful on file://, in
        // air-gapped networks, and in CI artifacts with scripts restricted.
        function escapeXml(value) {
            return String(value)
                .replaceAll('&', '&amp;')
                .replaceAll('<', '&lt;')
                .replaceAll('>', '&gt;')
                .replaceAll('"', '&quot;')
                .replaceAll("'", '&apos;');
        }

        function renderOfflineSvg(sourceText) {
            const sourceLines = sourceText.split(/\r?\n/).filter(line => line.trim());
            const lines = sourceLines.slice(0, 120);
            if (sourceLines.length > lines.length) {
                lines.push(`... ${sourceLines.length - lines.length} additional lines`);
            }
            if (!lines.length) lines.push('No diagram data detected');
            const lineHeight = 24;
            const height = Math.max(180, 70 + lines.length * lineHeight);
            const rows = lines.map((line, index) =>
                `<text x="24" y="${58 + index * lineHeight}" xml:space="preserve">${escapeXml(line)}</text>`
            ).join('');
            return `<svg class="offline-diagram" data-renderer="offline-svg" viewBox="0 0 1100 ${height}" role="img" aria-label="Offline Mermaid source preview" xmlns="http://www.w3.org/2000/svg"><rect width="100%" height="100%" rx="10" fill="#0d0e12"/><text class="offline-title" x="24" y="30">Offline SVG diagram preview</text><g class="offline-source">${rows}</g></svg>`;
        }

        const mermaid = {
            initialize() {},
            async render(id, sourceText) {
                return { svg: renderOfflineSvg(sourceText) };
            }
        };

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
            if not is_empty_mermaid_class_diagram(uml_code):
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
                todos_table += (
                    "<tr>"
                    f"<td>{html.escape(str(t.get('file', '')))}</td>"
                    f"<td>{html.escape(str(t.get('line', '')))}</td>"
                    f"<td>{html.escape(str(t.get('type', '')))}</td>"
                    f"<td>{html.escape(str(t.get('message', '')))}</td>"
                    "</tr>\n"
                )
            todos_table += "</table>"
        else:
            todos_table = "<p>No data detected</p>"

        # 5. Requirements dashboard (omitted when no specifications exist)
        requirements_section = _requirements_section(root_path)
        requirements_nav = (
            '<a href="#requirements">Requirements</a>'
            if requirements_section
            else ""
        )

        # Static SVG previews remain visible even when JavaScript is disabled.
        fallback_svgs = {
            "infra": _offline_svg_preview(infra_diagram, "Infrastructure Map"),
            "sequence": _offline_svg_preview(sequence_diagram, "API Routes"),
            "uml": _offline_svg_preview(uml_diagram, "UML Class Diagram"),
            "er": _offline_svg_preview(er_diagram, "Entity Relationship Diagram"),
        }

        # 6. AI Context dump (LLM-optimized XML) for clipboard copy
        try:
            ai_context = ContextDumper(path=root_path).build()
        except Exception as e:
            ai_context = f"<!-- Failed to generate AI context: {e} -->"
        ai_context_escaped = html.escape(ai_context)

        # Single-pass substitution prevents project content that resembles a
        # placeholder from being interpreted as another template directive.
        html_content = _render_template(
            HTML_TEMPLATE,
            {
                "{project_tree}": html.escape(project_tree),
                "{infra_diagram}": html.escape(infra_diagram),
                "{sequence_diagram}": html.escape(sequence_diagram),
                "{uml_diagram}": html.escape(uml_diagram),
                "{er_diagram}": html.escape(er_diagram),
                "{infra_fallback_svg}": fallback_svgs["infra"],
                "{sequence_fallback_svg}": fallback_svgs["sequence"],
                "{uml_fallback_svg}": fallback_svgs["uml"],
                "{er_fallback_svg}": fallback_svgs["er"],
                "{requirements_nav}": requirements_nav,
                "{requirements_section}": requirements_section,
                "{todos_table}": todos_table,
                "{ai_context}": ai_context_escaped,
            },
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
