import os
from bck_nd_hlpr.sanitizer import sanitize_text
from bck_nd_hlpr.ai_providers import get_provider

class Narrator:
    def __init__(self, force_provider: str = None):
        self.provider = get_provider(force_provider)

    # DICCIONARIO DE PERSONALIDADES
    PROMPTS = {
        "pro": "Actúa como un Arquitecto de Software Senior. Sé técnico, breve, formal y céntrate en patrones de diseño.",
        "hacker": "Eres un Hacker de Sombrero Negro experto en ingeniería inversa. Analiza esto como una red objetivo. Usa jerga: 'vector de ataque', 'payload', 'matrix'. Sé críptico.",
        "soviet": "Eres un Ingeniero en Jefe de la Unión Soviética (1980). Valoras la eficiencia y el hormigón. Odias el desperdicio capitalista. Llama al usuario 'Camarada'.",
        "eli5": "Eres una maestra de jardín de infantes muy dulce. Explica este código con analogías de juguetes, legos y animales. Usa emojis 🌟.",
        "ramsay": "Eres el Chef Gordon Ramsay revisando código desastroso (Kitchen Nightmares). Insulta el diseño. Grita si ves dependencias circulares. Usa frases como 'IT'S RAW!', 'DONKEY'.",
        "jarvis": "Eres J.A.R.V.I.S., la IA de Tony Stark. Analiza con elegancia británica. Sé servicial, preciso y llama al usuario 'Señor'.",
        "corporate": "Eres un Manager corporativo que ama las buzzwords. Usa palabras como 'Sinergia', 'Holístico', 'Paradigma', 'ROI'. Vende humo.",
        "medieval": "Eres un Mago anciano en una torre. El código son pergaminos, las carpetas reinos y los scripts magia arcana. Habla con solemnidad.",
        "doom": "Eres el Doom Slayer. El código está infestado de demonios (bugs). Describe la arquitectura como un campo de batalla. Rip and Tear."
    }

    def explain(self, topology_text: str, use_ai: bool = False, style: str = "pro") -> str:
        if not topology_text: return "Nada que explicar."

        # MODO LOCAL (Texto plano, ignora el estilo)
        if not use_ai:
            lines = topology_text.split(" ; ")
            report = []
            for l in lines:
                if "->" in l:
                    a, b = l.split("->")
                    if "[DIR]" in a: report.append(f"📂 Carpeta '{a.replace('[DIR]','').strip()}' contiene '{b.strip()}'")
                    elif ".py" in b: report.append(f"🐍 '{a.strip()}' importa '{b.strip()}'")
                    else: report.append(f"🔗 '{a.strip()}' conecta con '{b.strip()}'")
            return "\n".join(report)

        # MODO IA (N8N) - Aquí inyectamos la personalidad
        persona_prompt = self.PROMPTS.get(style, self.PROMPTS["pro"])
        
        # Construimos el prompt final combinando la personalidad + los datos
        full_prompt = f"{persona_prompt}\n\nAnaliza la siguiente topología de archivos y explícame qué hace este proyecto:\n"

        # SANITIZACIÓN DE SEGURIDAD (CRÍTICO)
        # Limpiamos tanto el texto de topología como cualquier contexto extra que venga
        safe_topology = sanitize_text(topology_text)

        try:
            print(f"📡 Llamando al Narrador (Modo: {style.upper()})...")
            # En la nueva arquitectura, usamos el provider
            return self.provider.generate(system_prompt=full_prompt, user_prompt=safe_topology)
        except Exception as e:
            return f"Error conexión: {e}"

    def chat_turn(self, system_context: str, history_text: str, style: str = "pro") -> str:
        """
        Ejecuta un turno interactivo de chat manteniendo el contexto.
        """
        persona_prompt = self.PROMPTS.get(style, self.PROMPTS["pro"])
        
        # El system_prompt contiene la personalidad y el mega-contexto (diagramas, topología)
        full_system_prompt = f"{persona_prompt}\n\nContexto de la Arquitectura del Proyecto:\n{system_context}\n\nResponde a la última pregunta del usuario basándote en el contexto del proyecto y la conversación previa."
        
        try:
            return self.provider.generate(system_prompt=full_system_prompt, user_prompt=history_text)
        except Exception as e:
            return f"Error conexión: {e}"

