import html
import gzip
import re
from functools import lru_cache
from importlib import resources
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
from bck_nd_hlpr.core.utils.secure_write import (
    SecureWriteError,
    atomic_write_explicit_output,
    ensure_safe_explicit_directory,
)


DOC_GENERATOR_MARKER = b"<!-- bck-nd-hlpr generated documentation -->\n"
_LEGACY_DOC_FINGERPRINTS = (
    b"<title>Project Documentation</title>",
    b'id="copy-ai-context-btn"',
    b'id="ai-context-content"',
    b'data-renderer="offline-svg"',
    b"navigator.clipboard.writeText",
)


def _is_backend_helper_document(content: bytes) -> bool:
    return content.startswith(DOC_GENERATOR_MARKER) or (
        content.lstrip().startswith(b"<!DOCTYPE html>")
        and all(fingerprint in content for fingerprint in _LEGACY_DOC_FINGERPRINTS)
    )


MERMAID_VERSION = "11.17.2"


@lru_cache(maxsize=1)
def _mermaid_runtime_script() -> str:
    """Embed the pinned upstream renderer; no Node, CDN or network at runtime."""
    assets = resources.files("bck_nd_hlpr").joinpath("assets", "mermaid")
    runtime = gzip.decompress(assets.joinpath("mermaid.min.js.gz").read_bytes()).decode("utf-8")
    license_text = assets.joinpath("LICENSE").read_text(encoding="utf-8")
    # The vendor asset stays byte-for-byte recoverable; escaping only applies
    # when embedding JavaScript in an HTML raw-text element.
    runtime = re.sub(r"</script", r"<\\/script", runtime, flags=re.IGNORECASE)
    license_text = license_text.replace("*/", "* /")
    return (
        f'<script id="mermaid-runtime" data-version="{MERMAID_VERSION}">\n'
        f"/* Mermaid {MERMAID_VERSION}\n{license_text}*/\n{runtime}\n</script>"
    )


def _diagram_pending(title: str) -> str:
    """An honest non-JavaScript fallback, never source text posing as a graph."""
    return (
        '<p class="diagram-status" role="status" data-state="pending">'
        f'{html.escape(title)}: waiting for the embedded Mermaid renderer. '
        'JavaScript is required to draw the diagram; the complete source remains on the left.'
        '</p><div class="diagram-canvas"></div>'
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

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'">
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
            max-height: 640px;
            justify-content: flex-start;
        }
        
        table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
        th, td { border: 1px solid var(--border); padding: 1rem; text-align: left; }
        th { background-color: var(--textarea-bg); font-weight: 600; color: var(--text-muted); text-transform: uppercase; font-size: 0.75rem; letter-spacing: 0.05em; }
        tr:hover { background-color: rgba(0, 240, 255, 0.05); }
        [data-theme="dark"] tr:hover { background-color: rgba(0, 255, 102, 0.05); }
        .table-scroll { overflow-x: auto; }
        .status-badge { color: var(--primary); font-weight: 700; white-space: nowrap; }

        .diagram-canvas svg { display: block; max-width: none !important; }
        .diagram-controls { display: flex; gap: 0.4rem; align-items: center; margin-bottom: 0.75rem; }
        .diagram-controls button { cursor: pointer; border: 1px solid var(--border); border-radius: 4px;
            background: var(--card-bg); color: var(--text-main); padding: 0.25rem 0.6rem; }
        .diagram-controls output { color: var(--text-muted); font: 12px system-ui, sans-serif; }
        .diagram-status { color: var(--text-muted); max-width: 36rem; }
        .diagram-status[data-state="error"] { color: #ffb86c; }

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

    {mermaid_runtime}
    <script>
    (function () {
        const diagramIds = ['infra', 'seq', 'er', 'uml'];
        let renderSerial = 0;
        // Rendering is serialized, including rapid edits and theme changes.
        let renderQueue = Promise.resolve();
        const revisions = new Map();
        const zoomLevels = new Map();

        function resizeDiagram(id, requestedZoom) {
            const view = document.getElementById(id + '-view');
            const diagram = view.querySelector('svg');
            if (!diagram) return;
            const pane = view.closest('.preview-pane');
            const bounds = diagram.viewBox.baseVal;
            if (!(bounds.width > 0 && bounds.height > 0)) return;
            const fittingZoom = Math.min(1, Math.max(120, pane.clientWidth - 70) / bounds.width,
                Math.max(180, pane.clientHeight - 110) / bounds.height);
            const zoom = requestedZoom === 'fit' ? fittingZoom : Math.min(4, Math.max(0.001, requestedZoom));
            zoomLevels.set(id, zoom);
            diagram.style.width = bounds.width * zoom + 'px';
            diagram.style.height = bounds.height * zoom + 'px';
            view.querySelector('.diagram-controls output').textContent = (zoom * 100).toFixed(1) + '%';
            pane.scrollTop = 0;
            pane.scrollLeft = 0;
        }

        diagramIds.forEach(id => {
            const view = document.getElementById(id + '-view');
            const controls = document.createElement('div');
            controls.className = 'diagram-controls';
            for (const [label, action] of [['−', 'out'], ['Fit', 'fit'], ['+', 'in'], ['100%', 'actual']]) {
                const button = document.createElement('button');
                button.type = 'button';
                button.textContent = label;
                button.setAttribute('aria-label', id + ' diagram: ' + action);
                button.addEventListener('click', () => resizeDiagram(id, action === 'fit' ? 'fit'
                    : action === 'actual' ? 1 : (zoomLevels.get(id) || 1) * (action === 'in' ? 1.5 : 1 / 1.5)));
                controls.appendChild(button);
            }
            controls.appendChild(document.createElement('output'));
            view.prepend(controls);
        });

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
            try { return localStorage.getItem('theme') || 'dark'; }
            catch { return 'dark'; }
        }

        async function setTheme(theme) {
            html.setAttribute('data-theme', theme);
            try { localStorage.setItem('theme', theme); } catch { /* restricted file:// storage */ }
            themeIcon.textContent = theme === 'dark' ? '☀️' : '🌙';
            themeText.textContent = theme === 'dark' ? 'Light Mode' : 'Dark Mode';
            
            return Promise.all(diagramIds.map(id => updateDiagram(id)));
        }

        themeToggle.addEventListener('click', () => {
            const newTheme = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
            setTheme(newTheme);
        });

        function updateDiagram(id) {
            const revision = (revisions.get(id) || 0) + 1;
            revisions.set(id, revision);
            const sourceText = document.getElementById(id + '-source').value;
            const viewElement = document.getElementById(id + '-view');
            const status = viewElement.querySelector('.diagram-status');
            const canvas = viewElement.querySelector('.diagram-canvas');
            status.hidden = false;
            status.dataset.state = 'pending';
            status.textContent = 'Rendering diagram locally…';
            renderQueue = renderQueue.then(async () => {
                if (revisions.get(id) !== revision) return;
                try {
                    if (!window.mermaid || typeof window.mermaid.render !== 'function') {
                        throw new Error('Renderer unavailable');
                    }
                    window.mermaid.initialize({
                        startOnLoad: false,
                        securityLevel: 'strict',
                        suppressErrorRendering: true,
                        // Preview panes retain their Cyber-Dark background in both
                        // existing portal themes; keep connectors high-contrast.
                        theme: 'dark',
                        fontFamily: 'system-ui, sans-serif',
                        maxTextSize: 250000,
                        maxEdges: 2000,
                        secure: ['secure', 'securityLevel', 'startOnLoad', 'maxTextSize',
                                 'maxEdges', 'suppressErrorRendering'],
                    });
                    const { svg } = await window.mermaid.render('diagram-' + id + '-' + (++renderSerial), sourceText);
                    if (revisions.get(id) !== revision) return;
                    canvas.innerHTML = svg;
                    const diagram = canvas.querySelector('svg');
                    if (!diagram) throw new Error('No rendered diagram');
                    diagram.dataset.renderer = 'mermaid';
                    status.dataset.state = 'ready';
                    status.hidden = true;
                    // Show the whole map first; zoom/100% exposes readable detail
                    // without allocating an enormous page or hiding the graph offscreen.
                    resizeDiagram(id, 'fit');
                } catch {
                    if (revisions.get(id) !== revision) return;
                    status.dataset.state = 'error';
                    status.hidden = false;
                    status.textContent = canvas.querySelector('svg')
                        ? 'Could not render the current source. Showing the last valid diagram; the source remains on the left.'
                        : 'Could not render this diagram. Check its syntax or rendering limits; the complete source remains on the left.';
                }
            });
            return renderQueue;
        }

        // Initialize everything
        const initialTheme = getTheme();
        setTheme(initialTheme);

        diagramIds.forEach(id => {
            let editTimer;
            document.getElementById(id + '-source').addEventListener('input', () => {
                clearTimeout(editTimer);
                editTimer = setTimeout(() => updateDiagram(id), 180);
            });
        });
    })();
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

        # A missing/disabled runtime leaves an explicit status and full source.
        fallback_svgs = {
            "infra": _diagram_pending("Infrastructure Map"),
            "sequence": _diagram_pending("API Routes"),
            "uml": _diagram_pending("UML Class Diagram"),
            "er": _diagram_pending("Entity Relationship Diagram"),
        }

        # 6. AI Context dump (LLM-optimized XML) for clipboard copy
        try:
            ai_context = ContextDumper(path=root_path).build()
        except Exception:
            ai_context = "<!-- AI context unavailable safely. -->"
        ai_context_escaped = html.escape(ai_context)

        # Single-pass substitution prevents project content that resembles a
        # placeholder from being interpreted as another template directive.
        try:
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
                    "{mermaid_runtime}": _mermaid_runtime_script(),
                },
            )
            rendered = DOC_GENERATOR_MARKER + html_content.encode("utf-8")
        except Exception:
            return None

        requested_output = Path(output_dir) / "index.html"
        try:
            safe_output_dir = ensure_safe_explicit_directory(output_dir)
            atomic_write_explicit_output(
                safe_output_dir / "index.html",
                rendered,
                existing_validator=_is_backend_helper_document,
            )
            return str(requested_output)
        except SecureWriteError:
            return None
