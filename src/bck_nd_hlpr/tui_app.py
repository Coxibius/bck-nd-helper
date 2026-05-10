from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, DirectoryTree, Static, Markdown
from bck_nd_hlpr.scanner import ProjectScanner
from bck_nd_hlpr.router import Router
from bck_nd_hlpr.route_parser import parse_project_routes, generate_mermaid_sequence
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
                Static("Selecciona un archivo o directorio en el árbol para ver su análisis...", id="info_box"),
                id="main_view", classes="content"
            )
        )
        yield Footer()

    def action_toggle_dark(self) -> None:
        """Acción para cambiar el tema oscuro/claro."""
        self.dark = not self.dark

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        """Maneja cuando se selecciona un archivo individual."""
        path = str(event.path)
        info_box = self.query_one("#info_box", Static)
        
        try:
            if path.endswith(".py"):
                # Mostrar Imports/Flujo local
                flow = self.scanner.scan_file(path)
                
                # Mostrar rutas de API si existen
                routes = parse_project_routes(path, max_depth=1)
                
                output = f"[b]Archivo:[/b] {path}\n\n"
                
                if flow:
                    # Usamos el modo local text de narrator / ascii
                    # The Router generates ASCII rendering
                    ascii_diagram = self.router.render_ascii(flow)
                    output += "[b]Diagrama ASCII:[/b]\n"
                    output += ascii_diagram + "\n\n"
                else:
                    output += "[i]No se detectaron relaciones externas (importaciones locales).[/i]\n\n"
                
                if routes:
                    output += "[b]Rutas API Detectadas:[/b]\n"
                    seq_code = generate_mermaid_sequence(routes)
                    output += "```mermaid\n" + seq_code + "\n```\n(Copia para Mermaid)"
                
                info_box.update(output)
            else:
                # Intentar leer como archivo de texto plano
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # Limitar tamaño de visualización si es muy grande
                    if len(content) > 10000:
                        content = content[:10000] + "\n\n... [Contenido truncado. Archivo muy grande.]"
                        
                    output = f"[b]Vista previa ({path}):[/b]\n\n"
                    # Usamos escape para que Textual no intente interpretar
                    # caracteres especiales como rich markup inesperado
                    escaped_content = content.replace("[", "\\[")
                    output += escaped_content
                    info_box.update(output)

                except UnicodeDecodeError:
                    info_box.update(f"[b]Archivo seleccionado:[/b] {path}\n\n[yellow]⚠️ Archivo no legible (Binario o codificación no soportada).[/yellow]")
                 
        except Exception as e:
            info_box.update(f"[red]Error procesando archivo: {e}[/red]")

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        """Maneja cuando se selecciona un directorio."""
        path = str(event.path)
        info_box = self.query_one("#info_box", Static)
        
        try:
            # Escanear al nivel de directorio seleccionado
            output = f"[b]Directorio:[/b] {path}\n\n"
            flow = self.scanner.scan(path, max_depth=1) # Usamos depth bajo para no colapsar la app
            
            if flow:
                ascii_diagram = self.router.render_ascii(flow)
                output += "[b]Arquitectura del Directorio:[/b]\n"
                output += ascii_diagram
            else:
                output += "[i]Directorio vacío o sin código estructural.[/i]"
                
            info_box.update(output)
            
        except Exception as e:
            info_box.update(f"[red]Error procesando directorio: {e}[/red]")

if __name__ == "__main__":
    app = ArchitectureExplorer()
    app.run()
