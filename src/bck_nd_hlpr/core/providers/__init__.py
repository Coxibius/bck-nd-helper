"""
Provider package — auto-registers all built-in framework providers.

Usage::

    from bck_nd_hlpr.core.providers import ProviderRegistry, BaseArchitectureProvider

    registry = ProviderRegistry.get_instance()
    provider = registry.detect_provider(Path("/path/to/project"))
    info = provider.get_framework_info(Path("/path/to/project"))
"""
from bck_nd_hlpr.core.providers.base import BaseArchitectureProvider
from bck_nd_hlpr.core.providers.registry import ProviderRegistry, GenericProvider

# ── Import concrete providers (their classes are registered below) ───────────
from bck_nd_hlpr.core.providers.laravel import LaravelProvider
from bck_nd_hlpr.core.providers.fastapi import FastApiProvider
from bck_nd_hlpr.core.providers.django import DjangoProvider
from bck_nd_hlpr.core.providers.spring_boot import SpringBootProvider
from bck_nd_hlpr.core.providers.dotnet_ef import DotNetEFProvider
from bck_nd_hlpr.core.providers.node_js import NodeJsProvider

# ── Auto-register all built-in providers in priority order ──────────────────
# More specific frameworks should come before generic/broad ones so that
# detect_provider() returns the best match first.

_BUILTIN_PROVIDERS = [
    LaravelProvider,
    FastApiProvider,
    DjangoProvider,
    SpringBootProvider,
    DotNetEFProvider,
    NodeJsProvider,
]


def _auto_register() -> None:
    """Register all built-in providers with the global registry."""
    registry = ProviderRegistry.get_instance()
    for provider_cls in _BUILTIN_PROVIDERS:
        registry.register(provider_cls)


_auto_register()

__all__ = [
    "BaseArchitectureProvider",
    "ProviderRegistry",
    "GenericProvider",
    "LaravelProvider",
    "FastApiProvider",
    "DjangoProvider",
    "SpringBootProvider",
    "DotNetEFProvider",
    "NodeJsProvider",
]
