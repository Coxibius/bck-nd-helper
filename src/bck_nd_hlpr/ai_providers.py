import os
import sys
import requests
import json
from typing import Optional
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

class AIProvider:
    """Base class for all AI providers."""
    def __init__(self, api_key: str = None):
        self.api_key = api_key

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        raise NotImplementedError("Subclasses must implement generate()")


class OpenAILikeProvider(AIProvider):
    def __init__(self, api_key: str, base_url: str, default_model: str, name: str = "OpenAI"):
        super().__init__(api_key)
        self.base_url = base_url
        self.default_model = default_model
        self.name = name

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        data = {
            "model": self.default_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        }
        try:
            resp = requests.post(self.base_url, headers=headers, json=data, timeout=45)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            return f"Error {self.name}: {e}\nResponse: {resp.text if 'resp' in locals() else ''}"


class OpenAIProvider(OpenAILikeProvider):
    def __init__(self, api_key: str):
        super().__init__(api_key, "https://api.openai.com/v1/chat/completions", "gpt-4o-mini", "OpenAI")


class GroqProvider(OpenAILikeProvider):
    def __init__(self, api_key: str):
        super().__init__(api_key, "https://api.groq.com/openai/v1/chat/completions", "llama3-8b-8192", "Groq")


class DeepSeekProvider(OpenAILikeProvider):
    def __init__(self, api_key: str):
        super().__init__(api_key, "https://api.deepseek.com/chat/completions", "deepseek-chat", "DeepSeek")


class OpenRouterProvider(OpenAILikeProvider):
    def __init__(self, api_key: str):
        super().__init__(api_key, "https://openrouter.ai/api/v1/chat/completions", "openai/gpt-4o-mini", "OpenRouter")


class AnthropicProvider(AIProvider):
    # Endpoint: https://api.anthropic.com/v1/messages
    # Default model: claude-3-haiku-20240307
    def generate(self, system_prompt: str, user_prompt: str) -> str:
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        data = {
            "model": "claude-3-haiku-20240307",
            "max_tokens": 1024,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": user_prompt}
            ]
        }
        try:
            resp = requests.post(url, headers=headers, json=data, timeout=45)
            resp.raise_for_status()
            return resp.json()["content"][0]["text"]
        except Exception as e:
            return f"Error Anthropic: {e}"


class GeminiProvider(AIProvider):
    # Endpoint: https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent
    def generate(self, system_prompt: str, user_prompt: str) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.api_key}"
        headers = {
            "Content-Type": "application/json"
        }
        # Gemini handles system instructions specifically
        data = {
            "system_instruction": {
                "parts": [{"text": system_prompt}]
            },
            "contents": [
                {"parts": [{"text": user_prompt}]}
            ]
        }
        try:
            resp = requests.post(url, headers=headers, json=data, timeout=45)
            resp.raise_for_status()
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            return f"Error Gemini: {e}"


class OllamaProvider(AIProvider):
    def __init__(self, api_key: str = None):
        super().__init__(api_key)
        self.host = os.getenv("OLLAMA_HOST", "http://localhost:11434")

    # Endpoint: {self.host}/api/chat
    def generate(self, system_prompt: str, user_prompt: str) -> str:
        url = f"{self.host.rstrip('/')}/api/chat"
        data = {
            "model": "llama3",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False
        }
        try:
            resp = requests.post(url, json=data, timeout=45)
            resp.raise_for_status()
            return resp.json()["message"]["content"]
        except Exception as e:
            return f"Error Ollama: {e}"


class WebhookProvider(AIProvider):
    def __init__(self, api_key: str = None):
        super().__init__(api_key)
        self.webhook_url = os.getenv("BCK_ND_WEBHOOK_URL", "http://localhost:5678/webhook/explain")

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "text": user_prompt,
            "prompt": system_prompt
        }
        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=45)
            if resp.status_code == 200:
                try: 
                    d = resp.json()
                    return d.get('text', d.get('output', str(d)))
                except: 
                    return resp.text
            return f"Error n8n: {resp.status_code} - {resp.text}"
        except Exception as e:
            return f"Error conexión: {e}"


def get_provider(force_provider: Optional[str] = None) -> AIProvider:
    """
    Returns the appropriate AIProvider.
    Priority if force_provider is None: OpenAI -> Anthropic -> Gemini -> Groq -> DeepSeek -> OpenRouter -> Ollama -> Webhook
    If user forces a provider but passes no key gracefully exits/prints error.
    """
    if force_provider:
        force_provider = force_provider.strip().lower()
        if force_provider == "openai":
            key = os.getenv("OPENAI_API_KEY")
            if not key:
                print("Error: Missing environment variable OPENAI_API_KEY", file=sys.stderr)
                sys.exit(1)
            return OpenAIProvider(key)
        elif force_provider == "anthropic":
            key = os.getenv("ANTHROPIC_API_KEY")
            if not key:
                print("Error: Missing environment variable ANTHROPIC_API_KEY", file=sys.stderr)
                sys.exit(1)
            return AnthropicProvider(key)
        elif force_provider == "gemini":
            key = os.getenv("GOOGLE_API_KEY")
            if not key:
                print("Error: Missing environment variable GOOGLE_API_KEY", file=sys.stderr)
                sys.exit(1)
            return GeminiProvider(key)
        elif force_provider == "groq":
            key = os.getenv("GROQ_API_KEY")
            if not key:
                print("Error: Missing environment variable GROQ_API_KEY", file=sys.stderr)
                sys.exit(1)
            return GroqProvider(key)
        elif force_provider == "deepseek":
            key = os.getenv("DEEPSEEK_API_KEY")
            if not key:
                print("Error: Missing environment variable DEEPSEEK_API_KEY", file=sys.stderr)
                sys.exit(1)
            return DeepSeekProvider(key)
        elif force_provider == "openrouter":
            key = os.getenv("OPENROUTER_API_KEY")
            if not key:
                print("Error: Missing environment variable OPENROUTER_API_KEY", file=sys.stderr)
                sys.exit(1)
            return OpenRouterProvider(key)
        elif force_provider == "ollama":
            return OllamaProvider()
        elif force_provider == "webhook":
            return WebhookProvider()
        else:
            print(f"Error: Unknown provider '{force_provider}'. Using fallback Webhook.", file=sys.stderr)
            return WebhookProvider()

    # Default fallback priority
    if os.getenv("OPENAI_API_KEY"):
        return OpenAIProvider(os.getenv("OPENAI_API_KEY"))
    elif os.getenv("ANTHROPIC_API_KEY"):
        return AnthropicProvider(os.getenv("ANTHROPIC_API_KEY"))
    elif os.getenv("GOOGLE_API_KEY"):
        return GeminiProvider(os.getenv("GOOGLE_API_KEY"))
    elif os.getenv("GROQ_API_KEY"):
        return GroqProvider(os.getenv("GROQ_API_KEY"))
    elif os.getenv("DEEPSEEK_API_KEY"):
        return DeepSeekProvider(os.getenv("DEEPSEEK_API_KEY"))
    elif os.getenv("OPENROUTER_API_KEY"):
        return OpenRouterProvider(os.getenv("OPENROUTER_API_KEY"))
    elif os.getenv("OLLAMA_HOST"):
        return OllamaProvider()
    elif os.getenv("BCK_ND_WEBHOOK_URL"):
        return WebhookProvider()
        
    print("\n[!] BYOK (Bring Your Own Key) Error:", file=sys.stderr)
    print("No se encontró ninguna API Key para inicializar un proveedor de IA.", file=sys.stderr)
    print("Por favor, crea un archivo '.env' en tu proyecto con alguna de estas variables:\n", file=sys.stderr)
    print("  OPENAI_API_KEY=your_key", file=sys.stderr)
    print("  ANTHROPIC_API_KEY=your_key", file=sys.stderr)
    print("  GOOGLE_API_KEY=your_key", file=sys.stderr)
    print("  GROQ_API_KEY=your_key", file=sys.stderr)
    print("  DEEPSEEK_API_KEY=your_key", file=sys.stderr)
    print("  OPENROUTER_API_KEY=your_key\n", file=sys.stderr)
    print("O inicia Ollama localmente y configura OLLAMA_HOST.", file=sys.stderr)
    sys.exit(1)
