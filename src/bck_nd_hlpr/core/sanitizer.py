
import re
from typing import List

# Patrones de secretos comunes
SECRET_PATTERNS = [
    r'(?i)(password|passwd|pwd|secret|api_key|token|auth_token|access_token|bearer)\s*[:=]\s*[\'"]?([^\s,;\'"}]+)[\'"]?',
    r'(?i)(db_pass|database_password|postgres_password|mysql_root_password)\s*[:=]\s*[\'"]?([^\s,;\'"}]+)[\'"]?',
    r'(?i)(database_url|connection_string|conn_str)\s*[:=]\s*[\'"]?([^\s,;\'"}]+)[\'"]?'
]

class Sanitizer:
    def __init__(self):
        self.patterns = [re.compile(p) for p in SECRET_PATTERNS]

    def sanitize(self, text: str) -> str:
        """
        Reemplaza secretos detectados por ***REDACTED***.
        """
        if not text:
            return ""
            
        sanitized_text = text
        for pattern in self.patterns:
            # Reemplazamos el grupo 2 (el valor) manteniendo el grupo 1 (la clave)
            # Pero re.sub es mas complejo con grupos. 
            # Simplificación: Buscar matches y reemplazar el valor.
            
            # Estrategia: Iterar sobre matches y reemplazar.
            # Para evitar problemas con indices al modificar el string, 
            # podemos hacer un pass replace simple si el regex captura todo.
            
            # Mejor estrategia para esta v1:
            # Usar una función de reemplazo en re.sub
            def redact_match(match):
                full_match = match.group(0)
                key = match.group(1)
                value = match.group(2)
                
                # Si el valor es muy corto (ej: "1"), tal vez falso positivo, pero seguridad ante todo.
                if value.strip().upper() == "REDACTED":
                    return full_match
                
                return f"{key}=***REDACTED***" # Asumimos formato key=value o key: value visual
               
                # Problema: El regex original captura el separador? 
                # El regex es (key)\s*[:=]\s*...
                # El grupo 0 es todo. 
                # Reconstruir con el separador original es dificil si no lo capturamos.
            
            # Ajustemos el regex para que sea mas facil de reemplazar usando sub
            # Pattern: (key\s*[:=]\s*[\'"]?)(value)([\'"]?)
            
            # Vamos a usar una logica mas robusta de reemplazo directo sobre el string
            sanitized_text = re.sub(
                pattern, 
                lambda m: f"{m.group(1).split(':')[0].split('=')[0].strip()}=***REDACTED***", 
                sanitized_text
            )
            # Espera, mi lambda es muy destructiva con el formato original.
            # Intento 2: Solo reemplazar el valor capturado.
            
        return self._apply_redaction(text)

    def _apply_redaction(self, text: str) -> str:
        """Aplicación directa de regex para redacción"""
        out = text
        for p in self.patterns:
            # Usamos sub con una funcion que reconstruye preservando la clave
            # Regex groups: 1=key, 2=value
            # Warning: Los regex definidos arriba asumen match completo de la asignacion
            
            def repl(m):
                # m.group(0) es todo "PASSWORD=admin"
                # m.span(2) son los indices del valor "admin"
                # No podemos usar indices facilmente en sub, pero podemos reconstruir
                
                # Vamos a simplificar: Detectar KEY=VALUE y devolver KEY=***REDACTED***
                # Esto puede cambiar "PASSWORD: admin" a "PASSWORD=***REDACTED***", cambiando el separador.
                # Para un MVP de seguridad es aceptable, pero intentemos respetar.
                
                full = m.group(0)
                key = m.group(1)
                val = m.group(2)
                
                # Encontrar donde empieza val dentro de full para preservar el separador
                sep_start = len(key)
                val_start = full.find(val, sep_start)
                
                separator_and_quotes = full[len(key):val_start]
                
                return f"{key}{separator_and_quotes}***REDACTED***" + full[val_start+len(val):]

            out = re.sub(p, repl, out)
        return out

def sanitize_text(text: str) -> str:
    """Helper global"""
    return Sanitizer().sanitize(text)
