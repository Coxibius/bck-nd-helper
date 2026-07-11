import os
import sys
import requests
from typing import Optional
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class NoAPIKeyError(Exception):
    """Exception raised when no API key is found for an AI provider."""
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
    """
    OpenRouter provides access to hundreds of models via a single OpenAI-compatible API.
    Endpoint: https://openrouter.ai/api/v1/chat/completions
    Default model: openai/gpt-4o-mini (cost-effective, widely available)
    Get your free key at: https://openrouter.ai/keys
    """
    def __init__(self, api_key: str):
        super().__init__(
            api_key,
            "https://openrouter.ai/api/v1/chat/completions",
            "openai/gpt-4o-mini",
            "OpenRouter"
        )

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            # Optional but recommended by OpenRouter for attribution
            "HTTP-Referer": "https://github.com/Coxibius/bck-nd-helper",
            "X-Title": "bck-nd-hlpr",
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
            return f"Error OpenRouter: {e}\nResponse: {resp.text if 'resp' in locals() else ''}"


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


def get_provider(force_provider: Optional[str] = None) -> AIProvider:
    """
    Returns the appropriate AIProvider instance.

    Auto-detection priority (when force_provider is None):
      OpenAI -> Anthropic -> Gemini -> Groq -> DeepSeek -> OpenRouter -> Ollama

    If a provider is forced but its API key is missing, raises NoAPIKeyError.
    If no key is found at all, raises NoAPIKeyError with actionable guidance.
    """
    if force_provider:
        force_provider = force_provider.strip().lower()
        if force_provider == "openai":
            key = os.getenv("OPENAI_API_KEY")
            if not key:
                raise NoAPIKeyError("Missing environment variable OPENAI_API_KEY")
            return OpenAIProvider(key)
        elif force_provider == "anthropic":
            key = os.getenv("ANTHROPIC_API_KEY")
            if not key:
                raise NoAPIKeyError("Missing environment variable ANTHROPIC_API_KEY")
            return AnthropicProvider(key)
        elif force_provider == "gemini":
            key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            if not key:
                raise NoAPIKeyError("Missing environment variable GEMINI_API_KEY or GOOGLE_API_KEY")
            return GeminiProvider(key)
        elif force_provider == "groq":
            key = os.getenv("GROQ_API_KEY")
            if not key:
                raise NoAPIKeyError("Missing environment variable GROQ_API_KEY")
            return GroqProvider(key)
        elif force_provider == "deepseek":
            key = os.getenv("DEEPSEEK_API_KEY")
            if not key:
                raise NoAPIKeyError("Missing environment variable DEEPSEEK_API_KEY")
            return DeepSeekProvider(key)
        elif force_provider == "openrouter":
            key = os.getenv("OPENROUTER_API_KEY")
            if not key:
                raise NoAPIKeyError("Missing environment variable OPENROUTER_API_KEY")
            return OpenRouterProvider(key)
        elif force_provider == "ollama":
            return OllamaProvider()
        else:
            raise NoAPIKeyError(
                f"Unknown provider '{force_provider}'. "
                "Valid options: openai, anthropic, gemini, groq, deepseek, openrouter, ollama."
            )

    # Default auto-detection fallback priority
    if os.getenv("OPENAI_API_KEY"):
        return OpenAIProvider(os.getenv("OPENAI_API_KEY"))
    elif os.getenv("ANTHROPIC_API_KEY"):
        return AnthropicProvider(os.getenv("ANTHROPIC_API_KEY"))
    elif os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        return GeminiProvider(key)
    elif os.getenv("GROQ_API_KEY"):
        return GroqProvider(os.getenv("GROQ_API_KEY"))
    elif os.getenv("DEEPSEEK_API_KEY"):
        return DeepSeekProvider(os.getenv("DEEPSEEK_API_KEY"))
    elif os.getenv("OPENROUTER_API_KEY"):
        return OpenRouterProvider(os.getenv("OPENROUTER_API_KEY"))
    elif os.getenv("OLLAMA_HOST"):
        return OllamaProvider()

    raise NoAPIKeyError(
        "No AI provider configured. Please set one of the following environment variables:\n"
        "  OPENAI_API_KEY       — OpenAI (https://platform.openai.com/api-keys)\n"
        "  ANTHROPIC_API_KEY    — Anthropic Claude (https://console.anthropic.com/)\n"
        "  GOOGLE_API_KEY       — Google Gemini (https://aistudio.google.com/app/apikey)\n"
        "  OPENROUTER_API_KEY   — OpenRouter, 200+ models, free tier available (https://openrouter.ai/keys)\n"
        "  OLLAMA_HOST          — Local Ollama server, no key needed (https://ollama.com/)"
    )
