from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, DirectoryTree, Static, Markdown
from bck_nd_hlpr.core.scanner import ProjectScanner
from bck_nd_hlpr.core.router import Router
from bck_nd_hlpr.core.route_parser import parse_project_routes, generate_mermaid_sequence
import os

class ArchitectureExplorer(App):
    CSS = """
    Screen { layout: grid; grid-size: 2; grid-columns: 1fr 3fr; }
    .sidebar { border-right: solid green; }
    .content { padding: 1; }
    #info_box {
        width: 100%;
        height: 100%;
        color: auto;
    }
    """
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("d", "toggle_dark", "Toggle Dark Mode")
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.scanner = ProjectScanner()
        self.router = Router()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Horizontal(
            DirectoryTree("./", id="tree_view", classes="sidebar"),
            Vertical(
                Static("Select a file or directory in the tree to view its analysis...", id="info_box"),
                id="main_view", classes="content"
            )
        )
        yield Footer()

    def action_toggle_dark(self) -> None:
        """Action to toggle dark/light theme."""
        self.dark = not self.dark

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        """Handles when an individual file is selected."""
        path = str(event.path)
        info_box = self.query_one("#info_box", Static)
        
        try:
            if path.endswith(".py"):
                # Show Imports/Local flow
                flow = self.scanner.scan_file(path)
                
                # Show API routes if they exist
                routes = parse_project_routes(path, max_depth=1)
                
                output = f"[b]File:[/b] {path}\n\n"
                
                if flow:
                    # Use local text mode of narrator / ascii
                    # The Router generates ASCII rendering
                    ascii_diagram = self.router.render_ascii(flow)
                    output += "[b]ASCII Diagram:[/b]\n"
                    output += ascii_diagram + "\n\n"
                else:
                    output += "[i]No external dependencies or relationships detected...[/i]\n\n"
                
                if routes:
                    output += "[b]Detected API Routes:[/b]\n"
                    seq_code = generate_mermaid_sequence(routes)
                    output += "```mermaid\n" + seq_code + "\n```\n(Copy for Mermaid)"
                
                info_box.update(output)
            else:
                # Try to read as plain text file
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # Limit display size if the file is too large
                    if len(content) > 10000:
                        content = content[:10000] + "\n\n... [Content truncated. File too large.]"
                        
                    output = f"[b]Preview ({path}):[/b]\n\n"
                    # Use escape so Textual doesn't try to interpret
                    # special characters as unexpected rich markup
                    escaped_content = content.replace("[", "\\[")
                    output += escaped_content
                    info_box.update(output)

                except UnicodeDecodeError:
                    info_box.update(f"[b]Selected file:[/b] {path}\n\n[yellow]⚠️ Unreadable file (binary or unsupported encoding).[/yellow]")
                 
        except Exception as e:
            info_box.update(f"[red]Error processing file: {e}[/red]")

    def on_mount(self) -> None:
        """Dashboard initialization to show provider details and cache status."""
        self._update_dashboard_summary("./")

    def _update_dashboard_summary(self, path: str) -> None:
        info_box = self.query_one("#info_box", Static)
        try:
            from bck_nd_hlpr.core.detector import ArchitectureDetector
            from bck_nd_hlpr.core.providers.registry import ProviderRegistry
            from bck_nd_hlpr.core.utils.delta_cache import DeltaCacheManager
            from pathlib import Path

            detector = ArchitectureDetector()
            arch_info = detector.detect(path)
            provider = getattr(detector, "_matched_provider", None)
            if not provider:
                provider = ProviderRegistry.get_instance().detect_provider(Path(path))

            cache_mgr = DeltaCacheManager(path)
            cache_status = f"Active ({len(cache_mgr.signatures)} file signatures cached)" if cache_mgr.cache_path.exists() else "Ready (New cache will be created)"

            lines = []
            lines.append(f"[b]Architecture Explorer Dashboard — {os.path.abspath(path)}[/b]\n")
            lines.append(f"• [cyan]Framework:[/cyan] {arch_info.get('framework', 'Unknown')}")
            lines.append(f"• [blue]Architecture:[/blue] {arch_info.get('architecture', 'Unknown')}")

            if provider:
                lines.append(f"• [green]Detected Provider:[/green] {getattr(provider, 'name', 'generic')} (Lang: {getattr(provider, 'language', 'unknown')})")

            lines.append(f"• [yellow]Delta Cache Status:[/yellow] {cache_status}\n")
            lines.append("[i]Select a file or directory in the tree on the left to analyze...[/i]")

            info_box.update("\n".join(lines))
        except Exception as e:
            info_box.update(f"Select a file or directory in the tree to view its analysis... (Notice: {e})")

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        """Handles when a directory is selected."""
        path = str(event.path)
        info_box = self.query_one("#info_box", Static)
        
        try:
            from bck_nd_hlpr.core.utils.delta_cache import DeltaCacheManager
            cache_mgr = DeltaCacheManager(path)
            cache_info = f"Cache: {len(cache_mgr.signatures)} cached signatures" if cache_mgr.cache_path.exists() else "Cache: Initializing"

            # Scan at the selected directory level
            output = f"[b]Directory:[/b] {path}  |  [yellow]{cache_info}[/yellow]\n\n"
            flow = self.scanner.scan(path, max_depth=1) # Use low depth to avoid collapsing the app
            
            if flow:
                ascii_diagram = self.router.render_ascii(flow)
                output += "[b]Directory Architecture:[/b]\n"
                output += ascii_diagram
            else:
                output += "[i]Empty directory or no structural code found.[/i]"
                
            info_box.update(output)
            
        except Exception as e:
            info_box.update(f"[red]Error processing directory: {e}[/red]")

if __name__ == "__main__":
    app = ArchitectureExplorer()
    app.run()
