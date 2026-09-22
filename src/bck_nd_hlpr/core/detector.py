"""
Detector for backend architecture types and frameworks.

Delegates framework detection to the :mod:`providers` registry when a
specific provider matches, falling back to the legacy file-scanning
heuristics for frameworks without a dedicated provider.
"""
import re
import os
import json
from pathlib import Path
from typing import Dict, List, Set, Any, Optional
from bck_nd_hlpr.core.utils.cache import FileCache
from bck_nd_hlpr.core.utils.gitignore_parser import GitIgnoreMatcher
from bck_nd_hlpr.core.utils.indexer import FileIndex, FileSystemIndexer
try:
    import tomllib as toml # Python 3.11+
except ImportError:
    try:
        import tomli as toml # Python 3.10 compatibility dependency
    except ImportError:
        toml = None # Fallback if installation fails/not present

class ArchitectureDetector:
    """Detects the backend type and architecture of the project."""
    
    DEFAULT_CONFIG = {
        "controllers": ["controller", "controllers"],
        "models": ["model", "models", "entities", "schemas"],
        "services": ["service", "services"],
        "routes": ["route", "routes", "router", "routers"]
    }

    MONOREPO_SUBPROJECTS = (
        "frontend",
        "backend",
        "client",
        "server",
        "apps/web",
        "apps/api",
        "packages/web",
        "packages/api",
        "web",
        "api",
    )
    
    def __init__(self):
        self.framework = None
        self.architecture_type = None
        self.features = set()
        self.connections = []
        self.config = self.DEFAULT_CONFIG.copy()
        # Provider pattern — populated by _detect_framework()
        self._matched_provider: Optional[object] = None
        self._file_index: Optional[FileIndex] = None

    def _load_config(self, root: Path):
        """Loads configuration from pyproject.toml if it exists."""
        config_file = self._indexed_file(root, "pyproject.toml")
        if config_file is None or toml is None:
            return

        try:
            data = toml.loads(FileCache.read_project_file(root, config_file))
            
            # Look for [tool.bck-nd] section
            tool_config = data.get("tool", {}).get("bck-nd", {})
            
            if tool_config:
                # Update allowed keys
                for key in self.config.keys():
                    if key in tool_config and isinstance(tool_config[key], list):
                        self.config[key] = tool_config[key]
                        # Normalize to lowercase
                        self.config[key] = [x.lower() for x in self.config[key]]
        except (OSError, UnicodeError, TypeError, ValueError):
            pass # If reading config fails, silently use defaults
        
    def _safe_walk(self, root: Path, extension: str = None):
        """Yield deterministic candidates exclusively from the trusted snapshot."""
        if self._file_index is None:
            return
        for file_path in self._file_index.all_files:
            try:
                file_path.relative_to(root)
            except ValueError:
                continue
            if extension is None or file_path.name.endswith(extension):
                yield file_path

    @staticmethod
    def _is_path_below(path: Path, directory: Path) -> bool:
        try:
            path.relative_to(directory)
            return True
        except ValueError:
            return False

    def _indexed_file(self, root: Path, relative_path: str) -> Optional[Path]:
        expected = relative_path.replace("\\", "/").strip("/").casefold()
        for path in self._safe_walk(root):
            try:
                relative = path.relative_to(root).as_posix().casefold()
            except ValueError:
                continue
            if relative == expected:
                return path
        return None

    def _indexed_directory(self, root: Path, relative_path: str) -> bool:
        candidate = root / Path(relative_path)
        if any(self._is_path_below(path, candidate) for path in self._safe_walk(root)):
            return True
        if not FileCache.is_project_directory(root, candidate):
            return False
        try:
            return not GitIgnoreMatcher(root).matches(candidate, is_dir=True)
        except (OSError, RuntimeError, ValueError):
            return False

    def detect(
        self,
        root_path: str,
        *,
        file_index: Optional[FileIndex] = None,
    ) -> Dict:
        """Analyzes the project and returns architectural information."""
        raw_root = Path(os.path.abspath(str(root_path)))
        try:
            if not FileCache.is_project_directory(raw_root, raw_root):
                raise OSError
            root = raw_root.resolve(strict=True)
            snapshot = file_index or FileSystemIndexer(
                str(root), max_depth=None
            ).build()
        except (OSError, RuntimeError):
            return {
                'framework': 'Unknown',
                'architecture': 'Single File',
                'features': [],
                'summary': "Unable to establish a trusted project snapshot."
            }
        self._file_index = snapshot

        # A detector instance may be reused by API consumers.  Reset all mutable
        # state so results from a previous project cannot leak into this scan.
        self.framework = None
        self.architecture_type = None
        self.features = set()
        self.connections = []
        self.config = self.DEFAULT_CONFIG.copy()
        self._matched_provider = None

        # Load custom configuration
        self._load_config(root)

        subprojects = self._detect_monorepo_subprojects(root)
        if subprojects:
            self.framework = " + ".join(
                f"{item['framework']} ({item['label']})" for item in subprojects
            )
            self.architecture_type = "Monorepo (Polyglot)"
            for item in subprojects:
                self.features.update(item["features"])
        else:
            # Detect framework and architecture for a conventional single root.
            self.framework = self._detect_framework(root)
            self.architecture_type = self._detect_architecture_type(root)

        # Detect specific features
        self._detect_features(root)
        
        return {
            'framework': self.framework,
            'architecture': self.architecture_type,
            'features': sorted(self.features),
            'summary': self._generate_summary()
        }

    def _detect_monorepo_subprojects(self, root: Path) -> List[Dict[str, Any]]:
        """Return distinct framework-bearing subprojects in common layouts.

        A repository is considered polyglot only when at least two discovered
        subprojects resolve to distinct frameworks.  This prevents a regular
        single-framework project with a directory named ``server`` from being
        mislabeled as a monorepo.
        """
        discovered: List[Dict[str, Any]] = []
        seen_paths: Set[Path] = set()

        for relative_name in self.MONOREPO_SUBPROJECTS:
            subproject = root.joinpath(*relative_name.split("/"))
            if not any(
                self._is_path_below(path, subproject)
                for path in (self._file_index.all_files if self._file_index else [])
            ):
                continue
            resolved = subproject
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)

            child = ArchitectureDetector()
            child._file_index = self._file_index
            child._load_config(subproject)
            framework = child._detect_framework(subproject)
            if framework == "Unknown":
                continue
            child._detect_features(subproject)
            discovered.append(
                {
                    "label": relative_name,
                    "path": subproject,
                    "framework": framework,
                    "features": set(child.features),
                }
            )

        distinct_frameworks = {
            str(item["framework"]).strip().casefold() for item in discovered
        }
        if len(distinct_frameworks) < 2:
            return []
        return discovered
    
    def _detect_framework(self, root: Path) -> str:
        """Detects the main framework.

        Tries the :class:`ProviderRegistry` first; falls back to the
        legacy file-scanning heuristics for uncovered frameworks.
        """
        # ── Provider-first detection ────────────────────────────────────
        try:
            from bck_nd_hlpr.core.providers.registry import ProviderRegistry, GenericProvider
            registry = ProviderRegistry.get_instance()
            provider = registry.detect_provider(root, file_index=self._file_index)
            if not isinstance(provider, GenericProvider):
                self._matched_provider = provider
                try:
                    info = provider.get_framework_info(root) or {}
                    self.features.update(info.get("features", []) or [])
                    orm = info.get("orm")
                    if orm:
                        self.features.add(f"{orm} ORM")
                    return str(info.get("framework") or provider.name)
                except Exception:
                    return provider.name
        except Exception:
            pass  # If the provider subsystem fails, fall through to legacy

        # ── Legacy heuristic scanning (frameworks without a provider) ───
        # Python Web Frameworks
        for py_file in self._safe_walk(root, ".py"):
            try:
                content = FileCache.read_project_file(root, py_file)
                
                # Flask
                if 'from flask import' in content or 'import flask' in content:
                    return 'Flask'
                
                # FastAPI
                if 'from fastapi import' in content or 'import fastapi' in content:
                    return 'FastAPI'
                
                # Django
                if 'django.conf' in content or 'DJANGO_SETTINGS_MODULE' in content:
                    return 'Django'
                
                # Quart (Async Flask)
                if 'from quart import' in content:
                    return 'Quart'
                    
            except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
                continue
        
        # Node.js Frameworks
        package_json = self._indexed_file(root, "package.json")
        if package_json is not None:
            try:
                data = json.loads(FileCache.read_project_file(root, package_json))
                deps = {**data.get('dependencies', {}), **data.get('devDependencies', {})}
                
                if 'next' in deps:
                    return 'Next.js'
                if 'express' in deps:
                    return 'Express.js'
                if 'fastify' in deps:
                    return 'Fastify'
                if 'koa' in deps:
                    return 'Koa'
                if 'nest' in deps or '@nestjs/core' in deps:
                    return 'NestJS'
            except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
                pass
        
        # Go
        go_mod = self._indexed_file(root, "go.mod")
        if go_mod is not None:
            try:
                content = FileCache.read_project_file(root, go_mod)
                if 'gin-gonic/gin' in content:
                    return 'Gin (Go)'
                if 'gofiber/fiber' in content:
                    return 'Fiber (Go)'
                return 'Go'
            except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
                pass
        
        # Rust
        cargo_toml = self._indexed_file(root, "Cargo.toml")
        if cargo_toml is not None:
            try:
                content = FileCache.read_project_file(root, cargo_toml)
                if 'actix-web' in content:
                    return 'Actix-web (Rust)'
                if 'rocket' in content:
                    return 'Rocket (Rust)'
                return 'Rust'
            except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
                pass
                
        # PHP
        composer_json = self._indexed_file(root, "composer.json")
        if composer_json is not None:
            try:
                data = json.loads(FileCache.read_project_file(root, composer_json))
                deps = {**data.get('require', {}), **data.get('require-dev', {})}
                
                if 'laravel/framework' in deps:
                    return 'Laravel'
                return 'PHP'
            except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
                pass
                
        # Java
        pom_xml = self._indexed_file(root, "pom.xml")
        if pom_xml is not None:
            try:
                content = FileCache.read_project_file(root, pom_xml)
                if 'spring-boot' in content:
                    return 'Spring Boot'
                return 'Java (Maven)'
            except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
                pass
        
        build_gradle = self._indexed_file(root, "build.gradle")
        if build_gradle is not None:
            try:
                content = FileCache.read_project_file(root, build_gradle)
                if 'spring-boot' in content:
                    return 'Spring Boot'
                return 'Java (Gradle)'
            except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
                pass
                
        # C# / .NET
        for file in self._safe_walk(root):
            if file.parent == root and file.suffix in {'.csproj', '.sln'}:
                return '.NET Core / C#'
        
        return 'Unknown'
    
    def _detect_architecture_type(self, root: Path) -> str:
        """Detects the architectural pattern."""
        if self.framework == 'Next.js':
            if self._indexed_directory(root, 'app') or self._indexed_directory(root, 'src/app'):
                return 'Next.js App Router'
            elif self._indexed_directory(root, 'pages') or self._indexed_directory(root, 'src/pages'):
                return 'Next.js Pages Router'
            return 'Next.js Project'

        has_controllers = False
        has_models = False
        has_services = False
        has_routes = False
        has_docker = False
        has_microservices = False
        
        directory_names = {
            part.casefold()
            for path in self._safe_walk(root)
            for part in path.relative_to(root).parent.parts
        }
        has_controllers = bool(directory_names & set(self.config['controllers'])) or any(
            self._indexed_directory(root, name)
            for name in self.config['controllers']
        )
        has_models = bool(directory_names & set(self.config['models'])) or any(
            self._indexed_directory(root, name)
            for name in self.config['models']
        )
        has_services = bool(directory_names & set(self.config['services'])) or any(
            self._indexed_directory(root, name)
            for name in self.config['services']
        )
        has_routes = bool(directory_names & set(self.config['routes'])) or any(
            self._indexed_directory(root, name)
            for name in self.config['routes']
        )
        
        # Detect Docker
        if (
            self._indexed_file(root, 'docker-compose.yml') is not None
            or self._indexed_file(root, 'docker-compose.yaml') is not None
            or self._indexed_file(root, 'Dockerfile') is not None
        ):
            has_docker = True
            
        # Detect microservices (multiple services in docker-compose)
        docker_compose = self._indexed_file(root, 'docker-compose.yml')
        if docker_compose is not None:
            try:
                content = FileCache.read_project_file(root, docker_compose)
                service_count = content.count('image:') + content.count('build:')
                if service_count > 2:
                    has_microservices = True
            except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
                pass
        
        # Determine type
        if has_microservices:
            return 'Microservices Architecture'
        elif has_controllers and has_models and has_services:
            return 'MVC + Services (Layered)'
        elif has_controllers and has_models:
            return 'MVC Pattern'
        elif has_routes and has_models:
            return 'REST API (Route-based)'
        elif has_docker:
            return 'Containerized Application'
        else:
            return 'Monolithic Application'
    
    def _detect_features(self, root: Path):
        """Detects additional features and technologies."""
        # Database
        for ext in ['.sql', '.db', '.sqlite']:
            # Verificar si existe alguno usando safe walk
            found = False
            for _ in self._safe_walk(root, ext):
                found = True
                break
            if found:
                self.features.add('Database')
                break
        
        # Docker
        if self._indexed_file(root, 'Dockerfile') is not None:
            self.features.add('Docker')
        if (
            self._indexed_file(root, 'docker-compose.yml') is not None
            or self._indexed_file(root, 'docker-compose.yaml') is not None
        ):
            self.features.add('Docker Compose')
        
        # CI/CD
        if self._indexed_directory(root, '.github/workflows'):
            self.features.add('GitHub Actions')
        if self._indexed_file(root, '.gitlab-ci.yml') is not None:
            self.features.add('GitLab CI')
        
        # Testing
        for py_file in self._safe_walk(root, ".py"):
            if py_file.name.startswith("test_") or py_file.name.endswith("_test.py"):
                self.features.add('Unit Tests')
                break

        # API Docs & Auth & ORM (Single Pass)
        for py_file in self._safe_walk(root, ".py"):
            try:
                content = FileCache.read_project_file(root, py_file)
                
                if '@swagger' in content or 'swagger' in content.lower():
                    self.features.add('Swagger/OpenAPI')
                
                if any(k in content for k in ['jwt', 'JWT', 'oauth', 'OAuth', 'auth']):
                    self.features.add('Authentication')
                
                if 'sqlalchemy' in content.lower():
                    self.features.add('SQLAlchemy ORM')
                if 'django.db' in content:
                    self.features.add('Django ORM')
            except (OSError, UnicodeError):
                continue

        # Polyglot feature pass.  This intentionally uses conservative tokens
        # and a file-size cap so large generated assets cannot dominate scans.
        text_extensions = {
            '.py', '.js', '.jsx', '.ts', '.tsx', '.go', '.rs', '.json',
            '.toml', '.yaml', '.yml', '.mod',
        }
        database_tokens = (
            'sqlalchemy', 'django.db', 'prisma', 'typeorm', 'sequelize',
            'mongoose', 'gorm.io', 'database/sql', 'sqlx', 'diesel',
        )
        auth_pattern = re.compile(
            r"\b(jwt|oauth2?|authentication|authorization|auth middleware)\b",
            re.IGNORECASE,
        )
        for source_file in self._safe_walk(root):
            if source_file.suffix.lower() not in text_extensions:
                continue
            try:
                content = FileCache.read_project_file(root, source_file)
            except (OSError, UnicodeError):
                continue
            lowered = content.lower()
            if any(token in lowered for token in database_tokens):
                self.features.add('Database')
            if (
                auth_pattern.search(content)
                or 'auth' in source_file.stem.lower()
            ):
                self.features.add('Authentication')
    
    def _generate_summary(self) -> str:
        """Generates a textual summary of the architecture."""
        parts = []
        
        if self.framework != 'Unknown':
            parts.append(f"{self.framework} application")
        
        if self.architecture_type:
            parts.append(f"using {self.architecture_type}")
        
        if self.features:
            features_str = ", ".join(sorted(self.features))
            parts.append(f"with {features_str}")
        
        if parts:
            return " ".join(parts) + "."
        else:
            return "Unable to determine architecture."
