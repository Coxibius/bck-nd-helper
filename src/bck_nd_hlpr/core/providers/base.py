"""
Abstract base class for framework architecture providers.

Each provider encapsulates detection logic and metadata for a single
framework/language ecosystem, enabling a plugin-style architecture
where new frameworks can be added without modifying the core detector.
"""
# TODO(audit): Document and implement support for future framework expansion candidates:
# TODO(audit):   - Go: Gin (web router) + GORM (ORM) provider with go.mod detection
# TODO(audit):   - Rust: Actix-web (framework) + Diesel ORM with Cargo.toml detection
# TODO(audit):   - Ruby on Rails: ActiveRecord ORM with Gemfile + app/models/ detection
# TODO(audit):   - Java Quarkus: RESTEasy Reactive + Panache ORM with pom.xml/gradle.build detection
# TODO(audit): Each new provider subclass should follow the BaseArchitectureProvider ABC contract below
# TODO(audit): and register itself via the ProviderRegistry plugin mechanism.
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

    def get_supported_extensions(self) -> List[str]:
        """Return default source file extensions for this provider's language.

        The base implementation derives a sensible default from the ``language``
        property so callers always receive a non-empty list.  Subclasses may
        override to return a precise set of extensions.

        Example::

            provider.get_supported_extensions()  # ['.java'] for a Spring Boot provider
        """
        # TODO(audit): Document and implement support for future framework expansion candidates:
        # TODO(audit):   - Go: Gin (web router) + GORM (ORM) provider with go.mod detection
        # TODO(audit):   - Rust: Actix-web (framework) + Diesel ORM with Cargo.toml detection
        # TODO(audit):   - Ruby on Rails: ActiveRecord ORM with Gemfile + app/models/ detection
        # TODO(audit):   - Java Quarkus: RESTEasy Reactive + Panache ORM with pom.xml/gradle.build detection
        # TODO(audit): Each new provider subclass should follow the BaseArchitectureProvider ABC contract below
        # TODO(audit): and register itself via the ProviderRegistry plugin mechanism.
        _language_extension_map: dict[str, List[str]] = {
            "python":     [".py"],
            "php":        [".php"],
            "java":       [".java"],
            "csharp":     [".cs"],
            "javascript": [".js", ".jsx"],
            "typescript": [".ts", ".tsx"],
            "go":         [".go"],
            "rust":       [".rs"],
            "ruby":       [".rb"],
        }
        try:
            lang = self.language.lower()
        except Exception:
            lang = ""
        return _language_extension_map.get(lang, [])
