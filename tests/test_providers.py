"""
Test suite for the Autonomous Provider Pattern (Pillar B).

Tests detection, metadata extraction, registry behavior, fallback, and
backward compatibility with the existing ArchitectureDetector output schema.
"""
import json
import pytest
from pathlib import Path

from bck_nd_hlpr.core.providers.base import BaseArchitectureProvider
from bck_nd_hlpr.core.providers.registry import ProviderRegistry, GenericProvider
from bck_nd_hlpr.core.providers.laravel import LaravelProvider
from bck_nd_hlpr.core.providers.fastapi import FastApiProvider
from bck_nd_hlpr.core.providers.django import DjangoProvider
from bck_nd_hlpr.core.providers.spring_boot import SpringBootProvider
from bck_nd_hlpr.core.providers.dotnet_ef import DotNetEFProvider
from bck_nd_hlpr.core.providers.node_js import NodeJsProvider


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _reset_registry():
    """Reset the singleton before every test to avoid cross-contamination."""
    ProviderRegistry.reset()
    yield
    ProviderRegistry.reset()


def _register_all_builtins():
    """Helper to register all built-in providers in priority order."""
    registry = ProviderRegistry.get_instance()
    for cls in [
        LaravelProvider,
        FastApiProvider,
        DjangoProvider,
        SpringBootProvider,
        DotNetEFProvider,
        NodeJsProvider,
    ]:
        registry.register(cls)
    return registry


# ═══════════════════════════════════════════════════════════════════════════
# 1. Individual Provider — detect() + get_framework_info()
# ═══════════════════════════════════════════════════════════════════════════

class TestLaravelProvider:
    def test_detect_artisan(self, tmp_path: Path):
        (tmp_path / "artisan").write_text("#!/usr/bin/env php\n")
        provider = LaravelProvider()
        assert provider.detect(tmp_path) is True

    def test_detect_composer_json(self, tmp_path: Path):
        (tmp_path / "composer.json").write_text(
            json.dumps({"require": {"laravel/framework": "^10.0"}})
        )
        provider = LaravelProvider()
        assert provider.detect(tmp_path) is True

    def test_detect_app_models_dir(self, tmp_path: Path):
        (tmp_path / "app" / "Models").mkdir(parents=True)
        provider = LaravelProvider()
        assert provider.detect(tmp_path) is True

    def test_no_detect_empty(self, tmp_path: Path):
        provider = LaravelProvider()
        assert provider.detect(tmp_path) is False

    def test_framework_info(self, tmp_path: Path):
        (tmp_path / "artisan").write_text("")
        (tmp_path / "routes").mkdir()
        (tmp_path / "routes" / "api.php").write_text("")
        (tmp_path / "routes" / "web.php").write_text("")
        provider = LaravelProvider()
        info = provider.get_framework_info(tmp_path)
        assert info["framework"] == "Laravel"
        assert info["language"] == "php"
        assert info["orm"] == "Eloquent"
        assert info["architecture_type"] == "MVC Pattern"
        assert "API Routes" in info["features"]
        assert "Web Routes" in info["features"]

    def test_find_model_files(self, tmp_path: Path):
        models_dir = tmp_path / "app" / "Models"
        models_dir.mkdir(parents=True)
        (models_dir / "User.php").write_text("<?php\n")
        (models_dir / "Post.php").write_text("<?php\n")
        provider = LaravelProvider()
        result = provider.find_model_files(tmp_path)
        assert len(result) == 2
        assert all(p.suffix == ".php" for p in result)

    def test_find_route_files(self, tmp_path: Path):
        routes_dir = tmp_path / "routes"
        routes_dir.mkdir()
        (routes_dir / "web.php").write_text("")
        (routes_dir / "api.php").write_text("")
        provider = LaravelProvider()
        result = provider.find_route_files(tmp_path)
        assert len(result) == 2


class TestFastApiProvider:
    def test_detect_requirements(self, tmp_path: Path):
        (tmp_path / "requirements.txt").write_text("fastapi==0.100.0\nuvicorn\n")
        provider = FastApiProvider()
        assert provider.detect(tmp_path) is True

    def test_detect_pyproject(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\ndependencies = ["fastapi>=0.100"]\n'
        )
        provider = FastApiProvider()
        assert provider.detect(tmp_path) is True

    def test_detect_import_in_py(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
        provider = FastApiProvider()
        assert provider.detect(tmp_path) is True

    def test_no_detect_empty(self, tmp_path: Path):
        provider = FastApiProvider()
        assert provider.detect(tmp_path) is False

    def test_framework_info_sqlalchemy(self, tmp_path: Path):
        (tmp_path / "requirements.txt").write_text("fastapi\nsqlalchemy\n")
        provider = FastApiProvider()
        info = provider.get_framework_info(tmp_path)
        assert info["framework"] == "FastAPI"
        assert info["language"] == "python"
        assert info["orm"] == "SQLAlchemy"
        assert info["architecture_type"] == "REST API"

    def test_framework_info_tortoise(self, tmp_path: Path):
        (tmp_path / "requirements.txt").write_text("fastapi\ntortoise-orm\n")
        provider = FastApiProvider()
        info = provider.get_framework_info(tmp_path)
        assert info["orm"] == "Tortoise-ORM"

    def test_framework_info_no_orm(self, tmp_path: Path):
        (tmp_path / "requirements.txt").write_text("fastapi\n")
        provider = FastApiProvider()
        info = provider.get_framework_info(tmp_path)
        assert info["orm"] is None


class TestDjangoProvider:
    def test_detect_manage_py(self, tmp_path: Path):
        (tmp_path / "manage.py").write_text(
            "#!/usr/bin/env python\nimport django\n"
        )
        provider = DjangoProvider()
        assert provider.detect(tmp_path) is True

    def test_detect_settings_py(self, tmp_path: Path):
        app_dir = tmp_path / "myapp"
        app_dir.mkdir()
        (app_dir / "settings.py").write_text("INSTALLED_APPS = ['django.contrib.admin']\n")
        provider = DjangoProvider()
        assert provider.detect(tmp_path) is True

    def test_no_detect_empty(self, tmp_path: Path):
        provider = DjangoProvider()
        assert provider.detect(tmp_path) is False

    def test_framework_info(self, tmp_path: Path):
        provider = DjangoProvider()
        info = provider.get_framework_info(tmp_path)
        assert info["framework"] == "Django"
        assert info["language"] == "python"
        assert info["orm"] == "Django ORM"
        assert info["architecture_type"] == "MVC + Services (Layered)"

    def test_find_model_files(self, tmp_path: Path):
        app = tmp_path / "blog"
        app.mkdir()
        (app / "models.py").write_text("class Post(models.Model): pass\n")
        provider = DjangoProvider()
        result = provider.find_model_files(tmp_path)
        assert len(result) == 1
        assert result[0].name == "models.py"


class TestSpringBootProvider:
    def test_detect_pom_xml(self, tmp_path: Path):
        (tmp_path / "pom.xml").write_text(
            "<project><parent><artifactId>spring-boot-starter-parent</artifactId></parent></project>"
        )
        provider = SpringBootProvider()
        assert provider.detect(tmp_path) is True

    def test_detect_build_gradle(self, tmp_path: Path):
        (tmp_path / "build.gradle").write_text(
            "plugins { id 'org.springframework.boot' version '3.0.0' }\n"
            "dependencies { implementation 'org.springframework.boot:spring-boot-starter-web' }\n"
        )
        provider = SpringBootProvider()
        assert provider.detect(tmp_path) is True

    def test_no_detect_plain_java(self, tmp_path: Path):
        (tmp_path / "pom.xml").write_text("<project><artifactId>myapp</artifactId></project>")
        provider = SpringBootProvider()
        assert provider.detect(tmp_path) is False

    def test_framework_info_with_jpa(self, tmp_path: Path):
        (tmp_path / "pom.xml").write_text(
            "<project><dependencies>"
            "<dependency><artifactId>spring-boot-starter-data-jpa</artifactId></dependency>"
            "</dependencies></project>"
        )
        provider = SpringBootProvider()
        info = provider.get_framework_info(tmp_path)
        assert info["framework"] == "Spring Boot"
        assert info["language"] == "java"
        assert info["orm"] == "Spring Data JPA / Hibernate"


class TestDotNetEFProvider:
    def test_detect_csproj(self, tmp_path: Path):
        (tmp_path / "MyApp.csproj").write_text(
            '<Project Sdk="Microsoft.NET.Sdk.Web">\n'
            '  <ItemGroup>\n'
            '    <PackageReference Include="Microsoft.EntityFrameworkCore" Version="7.0.0" />\n'
            '  </ItemGroup>\n'
            '</Project>'
        )
        provider = DotNetEFProvider()
        assert provider.detect(tmp_path) is True

    def test_detect_sln(self, tmp_path: Path):
        (tmp_path / "MyApp.sln").write_text("Microsoft Visual Studio Solution File\n")
        provider = DotNetEFProvider()
        assert provider.detect(tmp_path) is True

    def test_no_detect_empty(self, tmp_path: Path):
        provider = DotNetEFProvider()
        assert provider.detect(tmp_path) is False

    def test_framework_info_ef_core(self, tmp_path: Path):
        (tmp_path / "MyApp.csproj").write_text(
            '<PackageReference Include="Microsoft.EntityFrameworkCore" />'
        )
        provider = DotNetEFProvider()
        info = provider.get_framework_info(tmp_path)
        assert info["framework"] == ".NET Core / C#"
        assert info["language"] == "csharp"
        assert info["orm"] == "EF Core"


class TestNodeJsProvider:
    def test_detect_express(self, tmp_path: Path):
        (tmp_path / "package.json").write_text(
            json.dumps({"dependencies": {"express": "^4.18.0"}})
        )
        provider = NodeJsProvider()
        assert provider.detect(tmp_path) is True

    def test_detect_nestjs(self, tmp_path: Path):
        (tmp_path / "package.json").write_text(
            json.dumps({"dependencies": {"@nestjs/core": "^10.0.0"}})
        )
        provider = NodeJsProvider()
        assert provider.detect(tmp_path) is True

    def test_no_detect_empty_package(self, tmp_path: Path):
        (tmp_path / "package.json").write_text(json.dumps({"name": "my-lib"}))
        provider = NodeJsProvider()
        assert provider.detect(tmp_path) is False

    def test_no_detect_no_package(self, tmp_path: Path):
        provider = NodeJsProvider()
        assert provider.detect(tmp_path) is False

    def test_framework_info_express_prisma(self, tmp_path: Path):
        (tmp_path / "package.json").write_text(
            json.dumps({
                "dependencies": {"express": "^4.18.0", "@prisma/client": "^5.0.0"},
            })
        )
        provider = NodeJsProvider()
        info = provider.get_framework_info(tmp_path)
        assert info["framework"] == "Express.js"
        assert info["orm"] == "Prisma"
        assert info["architecture_type"] == "REST API"

    def test_framework_info_nestjs_typeorm(self, tmp_path: Path):
        (tmp_path / "package.json").write_text(
            json.dumps({
                "dependencies": {"@nestjs/core": "^10.0.0", "typeorm": "^0.3.0"},
            })
        )
        (tmp_path / "tsconfig.json").write_text("{}")
        provider = NodeJsProvider()
        info = provider.get_framework_info(tmp_path)
        assert info["framework"] == "NestJS"
        assert info["orm"] == "TypeORM"
        assert "TypeScript" in info["features"]
        assert info["language"] == "typescript"

    def test_framework_info_nextjs_app_router(self, tmp_path: Path):
        (tmp_path / "package.json").write_text(
            json.dumps({"dependencies": {"next": "^14.0.0"}})
        )
        (tmp_path / "app").mkdir()
        provider = NodeJsProvider()
        info = provider.get_framework_info(tmp_path)
        assert info["framework"] == "Next.js"
        assert info["architecture_type"] == "Next.js App Router"


# ═══════════════════════════════════════════════════════════════════════════
# 2. ProviderRegistry — detect_provider() / detect_all()
# ═══════════════════════════════════════════════════════════════════════════

class TestProviderRegistry:
    def test_singleton(self):
        r1 = ProviderRegistry.get_instance()
        r2 = ProviderRegistry.get_instance()
        assert r1 is r2

    def test_reset(self):
        r1 = ProviderRegistry.get_instance()
        ProviderRegistry.reset()
        r2 = ProviderRegistry.get_instance()
        assert r1 is not r2

    def test_register_dedup(self):
        registry = ProviderRegistry.get_instance()
        registry.register(LaravelProvider)
        registry.register(LaravelProvider)
        assert registry._providers.count(LaravelProvider) == 1

    def test_detect_provider_laravel(self, tmp_path: Path):
        registry = _register_all_builtins()
        (tmp_path / "artisan").write_text("")
        provider = registry.detect_provider(tmp_path)
        assert isinstance(provider, LaravelProvider)

    def test_detect_provider_fastapi(self, tmp_path: Path):
        registry = _register_all_builtins()
        (tmp_path / "requirements.txt").write_text("fastapi\n")
        provider = registry.detect_provider(tmp_path)
        assert isinstance(provider, FastApiProvider)

    def test_detect_provider_django(self, tmp_path: Path):
        registry = _register_all_builtins()
        (tmp_path / "manage.py").write_text("import django\n")
        provider = registry.detect_provider(tmp_path)
        assert isinstance(provider, DjangoProvider)

    def test_detect_provider_spring_boot(self, tmp_path: Path):
        registry = _register_all_builtins()
        (tmp_path / "pom.xml").write_text("<spring-boot/>")
        provider = registry.detect_provider(tmp_path)
        assert isinstance(provider, SpringBootProvider)

    def test_detect_provider_dotnet(self, tmp_path: Path):
        registry = _register_all_builtins()
        (tmp_path / "App.csproj").write_text("Microsoft.EntityFrameworkCore")
        provider = registry.detect_provider(tmp_path)
        assert isinstance(provider, DotNetEFProvider)

    def test_detect_provider_express(self, tmp_path: Path):
        registry = _register_all_builtins()
        (tmp_path / "package.json").write_text(
            json.dumps({"dependencies": {"express": "^4.0"}})
        )
        provider = registry.detect_provider(tmp_path)
        assert isinstance(provider, NodeJsProvider)

    def test_detect_all_polyglot(self, tmp_path: Path):
        """A repo with both Laravel and Node.js deps should return both."""
        registry = _register_all_builtins()
        (tmp_path / "artisan").write_text("")
        (tmp_path / "package.json").write_text(
            json.dumps({"dependencies": {"express": "^4.0"}})
        )
        providers = registry.detect_all(tmp_path)
        names = {type(p).__name__ for p in providers}
        assert "LaravelProvider" in names
        assert "NodeJsProvider" in names


# ═══════════════════════════════════════════════════════════════════════════
# 3. Fallback behavior — empty / unknown project
# ═══════════════════════════════════════════════════════════════════════════

class TestFallback:
    def test_empty_directory_returns_generic(self, tmp_path: Path):
        registry = _register_all_builtins()
        provider = registry.detect_provider(tmp_path)
        assert isinstance(provider, GenericProvider)

    def test_generic_provider_metadata(self, tmp_path: Path):
        provider = GenericProvider()
        assert provider.detect(tmp_path) is True
        info = provider.get_framework_info(tmp_path)
        assert info["framework"] == "Unknown"
        assert info["orm"] is None


# ═══════════════════════════════════════════════════════════════════════════
# 4. Backward Compatibility — ArchitectureDetector output schema
# ═══════════════════════════════════════════════════════════════════════════

class TestBackwardCompatibility:
    """Ensure ArchitectureDetector().detect() still returns the legacy dict."""

    def test_detect_returns_expected_keys(self, tmp_path: Path):
        from bck_nd_hlpr.core.detector import ArchitectureDetector
        detector = ArchitectureDetector()
        result = detector.detect(str(tmp_path))
        # Must have all four keys
        assert "framework" in result
        assert "architecture" in result
        assert "features" in result
        assert "summary" in result
        # Types
        assert isinstance(result["framework"], str)
        assert isinstance(result["architecture"], str)
        assert isinstance(result["features"], list)
        assert isinstance(result["summary"], str)

    def test_detect_laravel_via_detector(self, tmp_path: Path):
        (tmp_path / "artisan").write_text("")
        (tmp_path / "composer.json").write_text(
            json.dumps({"require": {"laravel/framework": "^10.0"}})
        )
        from bck_nd_hlpr.core.detector import ArchitectureDetector
        detector = ArchitectureDetector()
        result = detector.detect(str(tmp_path))
        assert result["framework"] == "Laravel"

    def test_detect_express_via_detector(self, tmp_path: Path):
        (tmp_path / "package.json").write_text(
            json.dumps({"dependencies": {"express": "^4.18.0"}})
        )
        from bck_nd_hlpr.core.detector import ArchitectureDetector
        detector = ArchitectureDetector()
        result = detector.detect(str(tmp_path))
        assert result["framework"] == "Express.js"

    def test_detect_unknown_via_detector(self, tmp_path: Path):
        from bck_nd_hlpr.core.detector import ArchitectureDetector
        detector = ArchitectureDetector()
        result = detector.detect(str(tmp_path))
        assert result["framework"] == "Unknown"

    def test_single_file_path(self, tmp_path: Path):
        """Passing a file path instead of dir should not crash."""
        f = tmp_path / "hello.py"
        f.write_text("print('hello')\n")
        from bck_nd_hlpr.core.detector import ArchitectureDetector
        detector = ArchitectureDetector()
        result = detector.detect(str(f))
        assert result["framework"] == "Unknown"
        assert result["architecture"] == "Single File"
