"""
Detector de tipos de arquitectura y frameworks backend.
"""
import re
import os
import json
from pathlib import Path
from bck_nd_hlpr.core.constants import GLOBAL_IGNORE_DIRS
from typing import Dict, List, Set, Any
try:
    import tomllib as toml # Python 3.11+
except ImportError:
    try:
        import toml as toml # standard for older python
    except ImportError:
        toml = None # Fallback if installation fails/not present

class ArchitectureDetector:
    """Detecta el tipo de backend y arquitectura del proyecto."""
    
    DEFAULT_CONFIG = {
        "controllers": ["controller", "controllers"],
        "models": ["model", "models", "entities", "schemas"],
        "services": ["service", "services"],
        "routes": ["route", "routes", "router", "routers"]
    }
    
    def __init__(self):
        self.framework = None
        self.architecture_type = None
        self.features = set()
        self.connections = []
        self.config = self.DEFAULT_CONFIG.copy()

    def _load_config(self, root: Path):
        """Carga configuración desde pyproject.toml si existe."""
        config_file = root / "pyproject.toml"
        if not config_file.exists() or toml is None:
            return

        try:
            with open(config_file, "rb") as f:
                data = toml.load(f)
            
            # Buscar sección [tool.bck-nd]
            tool_config = data.get("tool", {}).get("bck-nd", {})
            
            if tool_config:
                # Actualizar claves permitidas
                for key in self.config.keys():
                    if key in tool_config and isinstance(tool_config[key], list):
                        self.config[key] = tool_config[key]
                        # Normalizar a minusculas
                        self.config[key] = [x.lower() for x in self.config[key]]
        except Exception:
            pass # Si falla leer config, usamos defaults silenciosamente
        
    def _safe_walk(self, root: Path, extension: str = None):
        """Itera de forma segura sobre los archivos respetando GLOBAL_IGNORE_DIRS."""
        for root_dir, dirs, files in os.walk(root):
            # Filtramos directorios in-place para no descender en ellos
            dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS and not d.startswith('.')]
            
            for file in files:
                if extension:
                    if file.endswith(extension):
                        yield Path(root_dir) / file
                else:
                    yield Path(root_dir) / file

    def detect(self, root_path: str) -> Dict:
        """Analiza el proyecto y retorna información arquitectónica."""
        root = Path(root_path).resolve()
        if not root.is_dir():
            return {
                'framework': 'Unknown',
                'architecture': 'Single File',
                'features': [],
                'summary': f"Single file: {root.name}"
            }
        
        # Cargar configuración personalizada
        self._load_config(root)
        
        # Detectar framework
        self.framework = self._detect_framework(root)
        
        # Detectar tipo de arquitectura
        self.architecture_type = self._detect_architecture_type(root)
        
        # Detectar características específicas
        self._detect_features(root)
        
        return {
            'framework': self.framework,
            'architecture': self.architecture_type,
            'features': list(self.features),
            'summary': self._generate_summary()
        }
    
    def _detect_framework(self, root: Path) -> str:
        """Detecta el framework principal."""
        # Python Web Frameworks
        for py_file in self._safe_walk(root, ".py"):
            try:
                content = py_file.read_text(encoding='utf-8', errors='ignore')
                
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
                    
            except:
                continue
        
        # Node.js Frameworks
        package_json = root / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text())
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
            except:
                pass
        
        # Go
        go_mod = root / "go.mod"
        if go_mod.exists():
            try:
                content = go_mod.read_text()
                if 'gin-gonic/gin' in content:
                    return 'Gin (Go)'
                if 'gofiber/fiber' in content:
                    return 'Fiber (Go)'
                return 'Go'
            except:
                pass
        
        # Rust
        cargo_toml = root / "Cargo.toml"
        if cargo_toml.exists():
            try:
                content = cargo_toml.read_text()
                if 'actix-web' in content:
                    return 'Actix-web (Rust)'
                if 'rocket' in content:
                    return 'Rocket (Rust)'
                return 'Rust'
            except:
                pass
                
        # PHP
        composer_json = root / "composer.json"
        if composer_json.exists():
            try:
                data = json.loads(composer_json.read_text())
                deps = {**data.get('require', {}), **data.get('require-dev', {})}
                
                if 'laravel/framework' in deps:
                    return 'Laravel'
                return 'PHP'
            except:
                pass
                
        # Java
        pom_xml = root / "pom.xml"
        if pom_xml.exists():
            try:
                content = pom_xml.read_text()
                if 'spring-boot' in content:
                    return 'Spring Boot'
                return 'Java (Maven)'
            except:
                pass
        
        build_gradle = root / "build.gradle"
        if build_gradle.exists():
            try:
                content = build_gradle.read_text()
                if 'spring-boot' in content:
                    return 'Spring Boot'
                return 'Java (Gradle)'
            except:
                pass
                
        # C# / .NET
        for file in root.iterdir():
            if file.suffix == '.csproj' or file.suffix == '.sln':
                return '.NET Core / C#'
        
        return 'Unknown'
    
    def _detect_architecture_type(self, root: Path) -> str:
        """Detecta el patrón arquitectónico."""
        if self.framework == 'Next.js':
            if (root / 'app').exists() or (root / 'src' / 'app').exists():
                return 'Next.js App Router'
            elif (root / 'pages').exists() or (root / 'src' / 'pages').exists():
                return 'Next.js Pages Router'
            return 'Next.js Project'

        has_controllers = False
        has_models = False
        has_services = False
        has_routes = False
        has_docker = False
        has_microservices = False
        
        # Usamos os.walk para iterar directorios de forma segura
        for root_dir, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in GLOBAL_IGNORE_DIRS and not d.startswith('.')]
            
            # Verificar nombres de directorios actuales
            for dir_name in dirs:
                name_lower = dir_name.lower()
                
                if name_lower in self.config['controllers']:
                    has_controllers = True
                if name_lower in self.config['models']:
                    has_models = True
                if name_lower in self.config['services']:
                    has_services = True
                if name_lower in self.config['routes']:
                    has_routes = True
        
        # Detectar Docker
        if (root / 'docker-compose.yml').exists() or (root / 'Dockerfile').exists():
            has_docker = True
            
        # Detectar microservicios (múltiples services en docker-compose)
        docker_compose = root / 'docker-compose.yml'
        if docker_compose.exists():
            try:
                content = docker_compose.read_text()
                service_count = content.count('image:') + content.count('build:')
                if service_count > 2:
                    has_microservices = True
            except:
                pass
        
        # Determinar tipo
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
        """Detecta características y tecnologías adicionales."""
        # Base de datos
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
        if (root / 'Dockerfile').exists():
            self.features.add('Docker')
        if (root / 'docker-compose.yml').exists():
            self.features.add('Docker Compose')
        
        # CI/CD
        if (root / '.github' / 'workflows').exists():
            self.features.add('GitHub Actions')
        if (root / '.gitlab-ci.yml').exists():
            self.features.add('GitLab CI')
        
        # Testing
        for py_file in self._safe_walk(root, ".py"):
            if py_file.name.startswith("test_") or py_file.name.endswith("_test.py"):
                self.features.add('Unit Tests')
                break

        # API Docs & Auth & ORM (Single Pass)
        for py_file in self._safe_walk(root, ".py"):
            try:
                content = py_file.read_text(encoding='utf-8', errors='ignore')
                
                if '@swagger' in content or 'swagger' in content.lower():
                    self.features.add('Swagger/OpenAPI')
                
                if any(k in content for k in ['jwt', 'JWT', 'oauth', 'OAuth', 'auth']):
                    self.features.add('Authentication')
                
                if 'sqlalchemy' in content.lower():
                    self.features.add('SQLAlchemy ORM')
                if 'django.db' in content:
                    self.features.add('Django ORM')
            except:
                continue
    
    def _generate_summary(self) -> str:
        """Genera un resumen textual de la arquitectura."""
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
