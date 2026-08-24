"""CLI package with a lazy ``app`` export.

Keeping the import lazy prevents ``python -m bck_nd_hlpr.cli.cli`` from loading
the target module before :mod:`runpy` executes it, which otherwise emits a
spurious runtime warning on every module-style CLI invocation.
"""

__all__ = ["app"]


def __getattr__(name: str):
    if name == "app":
        from .cli import app

        return app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
