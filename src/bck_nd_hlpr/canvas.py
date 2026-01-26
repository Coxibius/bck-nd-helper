class Canvas:
    def __init__(self, width=80, height=20):
        self.width = width
        self.height = height
        # Creamos una matriz llena de espacios vacíos
        # self.grid[y][x]
        self.grid = [[" " for _ in range(width)] for _ in range(height)]

    def put_char(self, x, y, char):
        """Escribe un solo carácter si está dentro de los límites."""
        if 0 <= x < self.width and 0 <= y < self.height:
            self.grid[y][x] = char

    def stamp(self, start_x, start_y, ascii_block, transparent=True):
        """
        Pega un bloque de texto (una caja o flecha) en la matriz.
        
        Args:
            start_x, start_y: Coordenada superior izquierda.
            ascii_block: El string multi-línea (output del modelo).
            transparent: Si es True, el carácter '░' no borra lo que hay debajo.
        """
        lines = ascii_block.split("\n")
        
        for i, line in enumerate(lines):
            current_y = start_y + i
            
            for j, char in enumerate(line):
                current_x = start_x + j
                
                # Lógica de Transparencia V18
                # Si el carácter es '░' (Alpha), NO dibujamos nada (dejamos lo que había).
                if transparent and char == "░":
                    continue
                
                # Si es un espacio normal " ", a veces queremos que borre y a veces no.
                # Por defecto en ASCII art, el espacio suele ser transparente también 
                # a menos que sea una caja sólida.
                
                self.put_char(current_x, current_y, char)

    def render(self):
        """Convierte la matriz en un solo string para imprimir."""
        output = []
        for row in self.grid:
            # Unimos la fila y eliminamos espacios extra a la derecha para limpiar
            output.append("".join(row).rstrip())
        return "\n".join(output)

    def clear(self):
        """Borra todo el canvas."""
        self.grid = [[" " for _ in range(self.width)] for _ in range(self.height)]

# --- PRUEBA UNITARIA (Solo si ejecutas este archivo) ---
if __name__ == "__main__":
    # Creamos un canvas de 40x10
    lienzo = Canvas(40, 10)
    
    # 1. Creamos una "Caja" simulada (como si viniera de la IA)
    # Usamos ░ para probar la transparencia
    caja_a = """+---N---+
|░░Hola░|
W░░░░░░░E
+---S---+"""

    # 2. La pegamos en (2, 2)
    lienzo.stamp(2, 2, caja_a)
    
    # 3. Pegamos otra caja a la derecha que se solape un poco
    # para ver si la transparencia funciona (la E de la primera no debe borrarse)
    caja_b = """+-------+
|░Mundo░|
+-------+"""
    
    lienzo.stamp(15, 3, caja_b)
    
    print("--- PRUEBA DE CANVAS ---")
    print(lienzo.render())
    print("------------------------")
