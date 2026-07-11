"""
base_analyzer — the Strategy/Registry contract for all scan modes.

This is the single interface every analysis (--todo, --health, --trace,
--uml, ...) implements. Analyzers self-register via @register, so the
orchestrator (ProjectScanner) NEVER needs an if/elif block: it just looks
the flag up in the registry and calls .run().

    ScanContext    -> immutable input snapshot
    AnalyzerResult -> uniform output envelope
    BaseAnalyzer   -> Strategy interface (one run() per mode)
    register       -> plug-and-play decorator (flag -> class)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, List, Optional, Type


@dataclass(frozen=True)
class ScanContext:
    """Immutable snapshot of everything an analyzer may need."""
    path: str
    depth: int = 5
    arch_info: Dict[str, Any] = field(default_factory=dict)
    plain: bool = False

    @property
    def framework(self) -> str:
        return str(self.arch_info.get("framework", ""))


@dataclass
class AnalyzerResult:
    """Uniform envelope returned by every analyzer."""
    content: Optional[str] = None
    title: str = "Result"
    warning: str = "Nothing found."
    warning_color: str = "yellow"
    raw: Any = None

    @property
    def ok(self) -> bool:
        return bool(self.content) or self.raw is not None


class BaseAnalyzer(ABC):
    """Strategy interface: one self-contained analysis per CLI flag."""
    flag: ClassVar[str] = ""
    banner: ClassVar[str] = ""
    banner_color: ClassVar[str] = "magenta"
    intro: ClassVar[str] = ""

    @abstractmethod
    def run(self, ctx: ScanContext) -> AnalyzerResult:
        """Execute the analysis and return a uniform result envelope."""


_REGISTRY: Dict[str, Type[BaseAnalyzer]] = {}


def register(cls: Type[BaseAnalyzer]) -> Type[BaseAnalyzer]:
    """Class decorator: plug an analyzer into the dispatcher."""
    if not cls.flag:
        raise ValueError(f"{cls.__name__} must define a non-empty 'flag'")
    if cls.flag in _REGISTRY:
        raise ValueError(f"Duplicate analyzer flag: '{cls.flag}'")
    _REGISTRY[cls.flag] = cls
    return cls


def get_analyzer(flag: str) -> Optional[BaseAnalyzer]:
    cls = _REGISTRY.get(flag)
    return cls() if cls else None


def available_flags() -> List[str]:
    return sorted(_REGISTRY)
