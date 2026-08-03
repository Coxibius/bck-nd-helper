"""
Provider registry — singleton that manages framework provider discovery.

Providers are registered at import time (see ``__init__.py``) and the
registry is queried by ``ArchitectureDetector`` to delegate framework
detection to the appropriate provider.
"""
from pathlib import Path
from typing import Dict, Any, List, Optional, Type

from bck_nd_hlpr.core.providers.base import BaseArchitectureProvider


# ── Built-in fallback provider ──────────────────────────────────────────────

class GenericProvider(BaseArchitectureProvider):
    """Fallback provider that matches any project with generic metadata."""

    @property
    def name(self) -> str:
        return "generic"

    @property
    def language(self) -> str:
        return "unknown"

    def detect(self, root_path: Path) -> bool:
        # Always matches — used as the last-resort fallback.
        return True

    def get_framework_info(self, root_path: Path) -> Dict[str, Any]:
        return {
            "framework": "Unknown",
            "language": "unknown",
            "architecture_type": "Monolithic Application",
            "orm": None,
            "features": [],
        }


# ── Registry ────────────────────────────────────────────────────────────────

class ProviderRegistry:
    """Singleton registry of :class:`BaseArchitectureProvider` classes."""

    _instance: Optional["ProviderRegistry"] = None
    _providers: List[Type[BaseArchitectureProvider]]

    def __init__(self) -> None:
        self._providers = []

    # -- Singleton accessor ---------------------------------------------------

    @classmethod
    def get_instance(cls) -> "ProviderRegistry":
        """Return the global registry instance (created on first call)."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton — useful for testing."""
        cls._instance = None

    # -- Registration ---------------------------------------------------------

    def register(self, provider_cls: Type[BaseArchitectureProvider]) -> None:
        """Register a provider class (duplicates are silently ignored)."""
        if provider_cls not in self._providers:
            self._providers.append(provider_cls)

    # -- Detection ------------------------------------------------------------

    def detect_provider(
        self, root_path: Path
    ) -> BaseArchitectureProvider:
        """Return the first matching provider instance, or a
        :class:`GenericProvider` if nothing specific matches."""
        root = Path(root_path)
        for provider_cls in self._providers:
            provider = provider_cls()
            try:
                if provider.detect(root):
                    return provider
            except Exception:
                continue
        return GenericProvider()

    def detect_all(
        self, root_path: Path
    ) -> List[BaseArchitectureProvider]:
        """Return *all* matching providers (for polyglot / multi-framework
        repositories).  Always includes a :class:`GenericProvider` at the
        end if no specific provider matched."""
        root = Path(root_path)
        matched: List[BaseArchitectureProvider] = []
        for provider_cls in self._providers:
            provider = provider_cls()
            try:
                if provider.detect(root):
                    matched.append(provider)
            except Exception:
                continue
        if not matched:
            matched.append(GenericProvider())
        return matched

    # -- Introspection --------------------------------------------------------

    def get_provider_by_name(self, name: str) -> Optional[BaseArchitectureProvider]:
        """Return a provider instance whose ``name`` matches *name* (case-insensitive).

        Iterates the registered provider classes, instantiates each one (defensive
        against misbehaving constructors), and compares ``provider.name`` using a
        case-insensitive match.  Returns the first matching instance or *None* if
        no provider has the requested name.
        """
        target = (name or "").strip().lower()
        if not target:
            return None
        for provider_cls in self._providers:
            try:
                provider = provider_cls()
            except Exception:
                continue
            try:
                if provider.name.strip().lower() == target:
                    return provider
            except Exception:
                continue
        return None

    def get_registered_names(self) -> List[str]:
        """Return the ``name`` property values of all registered providers."""
        names = []
        for provider_cls in self._providers:
            try:
                names.append(provider_cls().name)
            except Exception:
                pass
        return names

    def is_registered(self, name: str) -> bool:
        """Return *True* if a provider with the given *name* is registered."""
        return name in self.get_registered_names()
