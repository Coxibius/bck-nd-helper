import os
from bck_nd_hlpr.sanitizer import sanitize_text
from bck_nd_hlpr.ai_providers import get_provider, NoAPIKeyError


class Narrator:
    def __init__(self, force_provider: str = None):
        try:
            self.provider = get_provider(force_provider)
        except NoAPIKeyError as e:
            self.provider = None
            self._no_key_message = str(e)

    # DICCIONARIO DE PERSONALIDADES
    PROMPTS = {
        "pro": "Act as a Senior Software Architect. Be technical, brief, formal, and focus on design patterns.",
        "hacker": "You are an expert Black Hat Hacker in reverse engineering. Analyze this as a target network. Use jargon: 'attack vector', 'payload', 'matrix'. Be cryptic.",
        "soviet": "You are a Chief Engineer of the Soviet Union (1980). You value efficiency and concrete. You hate capitalist waste. Call the user 'Comrade'.",
        "eli5": "You are a very sweet kindergarten teacher. Explain this code with analogies of toys, legos, and animals. Use emojis 🌟.",
        "ramsay": "You are Chef Gordon Ramsay reviewing a disastrous code (Kitchen Nightmares). Insult the design. Yell if you see circular dependencies. Use phrases like 'IT'S RAW!', 'DONKEY'.",
        "jarvis": "You are J.A.R.V.I.S., Tony Stark's AI. Analyze with British elegance. Be helpful, precise, and call the user 'Sir'.",
        "corporate": "You are a corporate Manager who loves buzzwords. Use words like 'Synergy', 'Holistic', 'Paradigm', 'ROI'. Sell smoke.",
        "medieval": "You are an ancient Wizard in a tower. The code is scrolls, the folders are kingdoms, and the scripts are arcane magic. Speak with solemnity.",
        "doom": "You are the Doom Slayer. The code is infested with demons (bugs). Describe the architecture as a battlefield. Rip and Tear."
    }

    def _no_key_error_msg(self) -> str:
        """Returns the stored NoAPIKeyError message, or a generic fallback."""
        return getattr(self, "_no_key_message", (
            "No AI provider configured. Set OPENAI_API_KEY, ANTHROPIC_API_KEY, "
            "GOOGLE_API_KEY, OPENROUTER_API_KEY, or OLLAMA_HOST to enable AI analysis."
        ))

    def explain(self, topology_text: str, use_ai: bool = False, style: str = "pro") -> str:
        if not topology_text: return "Nothing to explain."

        # MODO LOCAL (Texto plano, ignora el estilo)
        if not use_ai:
            lines = topology_text.split(" ; ")
            report = []
            for l in lines:
                if "->" in l:
                    a, b = l.split("->")
                    if "[DIR]" in a: report.append(f"📂 Folder '{a.replace('[DIR]','').strip()}' contains '{b.strip()}'")
                    elif ".py" in b: report.append(f"🐍 '{a.strip()}' imports '{b.strip()}'")
                    else: report.append(f"🔗 '{a.strip()}' connects with '{b.strip()}'")
            return "\n".join(report)

        # MODO IA — Requires an active provider
        if not self.provider:
            raise NoAPIKeyError(self._no_key_error_msg())

        persona_prompt = self.PROMPTS.get(style, self.PROMPTS["pro"])

        # Construimos el prompt final combinando la personalidad + los datos
        full_prompt = f"{persona_prompt}\n\nAnalyze the following file topology and explain what this project does:\n"

        # SANITIZACIÓN DE SEGURIDAD (CRÍTICO)
        # Limpiamos tanto el texto de topología como cualquier contexto extra que venga
        safe_topology = sanitize_text(topology_text)

        try:
            print(f"📡 Calling the Narrator (Mode: {style.upper()})...")
            return self.provider.generate(system_prompt=full_prompt, user_prompt=safe_topology)
        except Exception as e:
            return f"Connection error: {e}"

    def chat_turn(self, system_context: str, history_text: str, style: str = "pro") -> str:
        """
        Ejecuta un turno interactivo de chat manteniendo el contexto.
        """
        if not self.provider:
            raise NoAPIKeyError(self._no_key_error_msg())

        persona_prompt = self.PROMPTS.get(style, self.PROMPTS["pro"])

        # El system_prompt contiene la personalidad y el mega-contexto (diagramas, topología)
        full_system_prompt = f"{persona_prompt}\n\nProject Architecture Context:\n{system_context}\n\nRespond to the user's last question based on the project context and previous conversation."

        try:
            return self.provider.generate(system_prompt=full_system_prompt, user_prompt=history_text)
        except Exception as e:
            return f"Connection error: {e}"
