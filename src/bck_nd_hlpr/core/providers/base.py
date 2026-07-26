"""
Abstract base class for framework architecture providers.

Each provider encapsulates detection logic and metadata for a single
framework/language ecosystem, enabling a plugin-style architecture
where new frameworks can be added without modifying the core detector.
"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, List, Optional


class BaseArchitectureProvider(ABC):
    """Abstract base class for framework architecture providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the framework (e.g. 'laravel', 'fastapi', 'django',
        'spring_boot', 'ef_core', 'express_typeorm')."""
        pass

    @property
    @abstractmethod
    def language(self) -> str:
        """Primary programming language
        ('php', 'python', 'java', 'csharp', 'javascript', 'typescript')."""
        pass

    @abstractmethod
    def detect(self, root_path: Path) -> bool:
        """Return True if this framework/architecture is present in *root_path*."""
        pass

    @abstractmethod
    def get_framework_info(self, root_path: Path) -> Dict[str, Any]:
        """Return architectural metadata dictionary containing at least:

        - ``framework``  : str
        - ``language``   : str
        - ``architecture_type`` : str  (e.g. 'MVC', 'REST API', 'Monolith')
        - ``orm``        : Optional[str]
        - ``features``   : List[str]
        """
        pass

    def find_model_files(self, root_path: Path) -> List[Path]:
        """Override to return paths to ORM / Database model files."""
        return []

    def find_route_files(self, root_path: Path) -> List[Path]:
        """Override to return paths to API / HTTP controllers or routers."""
        return []
