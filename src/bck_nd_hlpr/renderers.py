"""ASCII Architect - Deterministic Renderers
Módulo encargado de generar las formas geométricas usando lógica matemática de strings.
Sustituye a la generación neuronal en el modo "Rápido/Standard".
"""

class BaseRenderer:
    @staticmethod
    def _wrap_text(text: str, max_width: int) -> list:
        """Divide el texto en líneas basándose en un ancho máximo."""
        words = text.split()
        lines = []
        current_line = []
        current_length = 0
        
        for word in words:
            if current_length + len(word) + len(current_line) > max_width:
                if current_line:
                    lines.append(" ".join(current_line))
                    current_line = [word]
                    current_length = len(word)
                else:
                    # Palabra más larga que max_width
                    lines.append(word)
            else:
                current_line.append(word)
                current_length += len(word)
        
        if current_line:
            lines.append(" ".join(current_line))
        return lines if lines else [text]

    @staticmethod
    def _center_text(lines: list, width: int) -> list:
        """Centra cada línea de texto en el ancho dado."""
        return [line.center(width) for line in lines]

class BoxRenderer(BaseRenderer):
    @staticmethod
    def render(text: str, padding: int = 2, max_width: int = 20) -> str:
        text_lines = BoxRenderer._wrap_text(text, max_width)
        content_width = max(len(line) for line in text_lines) + (padding * 2)
        
        # Unicode Box Drawing
        # ┌─────────────────┐
        # │      Text       │
        # └─────────────────┘
        top = "┌" + "─" * content_width + "┐"
        bottom = "└" + "─" * content_width + "┘"
        
        result = [top]
        for line in BoxRenderer._center_text(text_lines, content_width):
            result.append("│" + line + "│")
        result.append(bottom)
        
        return "\n".join(result)

class SoftBoxRenderer(BaseRenderer):
    @staticmethod
    def render(text: str, padding: int = 2, max_width: int = 20) -> str:
        text_lines = SoftBoxRenderer._wrap_text(text, max_width)
        content_width = max(len(line) for line in text_lines) + (padding * 2)
        
        # Rounded corners approach using Unicode arcs
        # ╭─────────────────╮
        # │      Text       │
        # ╰─────────────────╯
        top = "╭" + "─" * content_width + "╮"
        bottom = "╰" + "─" * content_width + "╯"
        
        result = [top]
        for line in SoftBoxRenderer._center_text(text_lines, content_width):
            result.append("│" + line + "│")
        result.append(bottom)
        
        return "\n".join(result)

class CylinderRenderer(BaseRenderer):
    @staticmethod
    def render(text: str, padding: int = 2, max_width: int = 20) -> str:
        text_lines = CylinderRenderer._wrap_text(text, max_width)
        content_width = max(len(line) for line in text_lines) + (padding * 2)
        
        # Cylinder visual
        #  .───────────────. 
        # (      Text       )
        #  '───────────────'
        
        # Top ellipse approximation
        top = " ." + "─" * (content_width - 2) + ". "
        
        # Unicode does not have perfect curved vertical lines for cylinders, using parens
        
        result = [top]
        for line in CylinderRenderer._center_text(text_lines, content_width):
            result.append("(" + line + ")")
            
        bottom = " '" + "─" * (content_width - 2) + "' "
        result.append(bottom)
        
        return "\n".join(result)

class DiamondRenderer(BaseRenderer):
    """
    Renderiza un Rombo con el 'Efecto Saturno'.
    
    PROBLEMA SOLUCIONADO: Evita que el rombo se estire verticalmente como un obelisco
    cuando hay mucho texto.
    
    SOLUCIÓN:
    - Top Cap: Fijo de 3 líneas.
    - Bottom Cap: Fijo de 3 líneas.
    - Body: Texto flotante (sin bordes laterales) centrado.
    
    VISUAL:
          /\\
         /  \\      <-- Fixed Cap
        /    \\
       USUARIO     <-- Text "Ring"
        \\    /
         \\  /      <-- Fixed Cap
          \\/
    """
    @staticmethod
    def render(text: str, max_width: int = 15) -> str:
        # Usamos el wrapping del BaseRenderer
        text_lines = DiamondRenderer._wrap_text(text, max_width)
        max_text_width = max(len(line) for line in text_lines)
        
        # --- CONFIGURACIÓN SATURNO ---
        cone_height = 3 
        cone_base_width = (cone_height * 2) + 1
        
        # El ancho total DEBE ser impar para que la punta central exista
        total_width = max(max_text_width, cone_base_width) + 2
        if total_width % 2 == 0:
            total_width += 1
            
        center_idx = total_width // 2

        # 1. Generar Top Cone (Manual center for exact alignment)
        # La punta '^' va exactamente en center_idx
        top_cone = [" " * center_idx + "^"]
        for i in range(cone_height):
            # i=0: inner=1, offset=1 -> / \ (espacios = center - 1)
            # i=1: inner=3, offset=2 -> /   \
            inner_space = " " * (i * 2 + 1)
            line = "/" + inner_space + "\\"
            # El centro de "line" es len(line)//2. Queremos que ese centro coincida con center_idx.
            # padding_left = center_idx - (total_chars_in_line // 2)
            padding_left = center_idx - (i + 1)
            top_cone.append(" " * padding_left + line)

        # 2. Generar Bottom Cone
        bottom_cone = []
        for i in range(cone_height - 1, -1, -1):
            inner_space = " " * (i * 2 + 1)
            line = "\\" + inner_space + "/"
            padding_left = center_idx - (i + 1)
            bottom_cone.append(" " * padding_left + line)
        bottom_cone.append(" " * center_idx + "v")

        # 3. Generar Cuerpo (Texto centrado)
        body = []
        for line in text_lines:
            # Para el texto, center() suele estar bien si el ancho es consistente, 
            # pero para ser seguros usamos el mismo center_idx
            padding_left = center_idx - (len(line) // 2)
            body.append(" " * padding_left + line)

        return "\n".join(top_cone + body + bottom_cone)

def get_renderer(shape_type: str):
    mapping = {
        "BOX": BoxRenderer,
        "SOFTBOX": SoftBoxRenderer,
        "CYLINDER": CylinderRenderer,
        "DIAMOND": DiamondRenderer
    }
    return mapping.get(shape_type.upper(), BoxRenderer)
