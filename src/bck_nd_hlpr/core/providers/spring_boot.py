"""
Spring Boot architecture provider.
"""
from pathlib import Path
from typing import Dict, Any, List, Optional

from bck_nd_hlpr.core.providers.base import BaseArchitectureProvider, find_files_by_glob


_SPRING_BOOT_APP_ANNOTATIONS = (
    "@SpringBootApplication",
    "@SpringBootConfiguration",
)


def find_application_class(root_path: Path) -> Optional[Path]:
    """Locate the Spring Boot application entry-point class.

    Scans Java sources (preferring ``src/main/java/**``) for a file containing
    the ``@SpringBootApplication`` (or ``@SpringBootConfiguration``) annotation
    commonly placed on the application's bootstrap class.  Returns the path of
    the first match, or *None* if no such file exists.
    """
    root = Path(root_path)
    provider = SpringBootProvider()
    candidates: List[Path] = []
    src_main = root / "src" / "main" / "java"
    snapshot = provider._snapshot(root)
    candidates.extend(find_files_by_glob(root, "**/*.java", file_index=snapshot))
    preferred = [path for path in candidates if src_main in path.parents]
    if preferred:
        candidates = preferred
    for java_file in candidates:
        text = provider._read(root, java_file)
        if text is None:
            continue
        for marker in _SPRING_BOOT_APP_ANNOTATIONS:
            if marker in text:
                return java_file
    return None


class SpringBootProvider(BaseArchitectureProvider):
    """Detects Spring Boot (Java/Kotlin) projects."""

    @property
    def name(self) -> str:
        return "Spring Boot"

    @property
    def language(self) -> str:
        return "java"

    # -- Detection ------------------------------------------------------------

    def detect(self, root_path: Path) -> bool:
        root = Path(root_path)

        # 1. Maven — pom.xml containing spring-boot
        pom = self._file(root, "pom.xml")
        if pom is not None:
            content = self._read(root, pom)
            if content is not None and "spring-boot" in content:
                return True

        # 2. Gradle — build.gradle / build.gradle.kts containing spring-boot
        for gradle_name in ("build.gradle", "build.gradle.kts"):
            gradle = self._file(root, gradle_name)
            if gradle is not None:
                content = self._read(root, gradle)
                if content is not None and (
                    "spring-boot" in content or "org.springframework.boot" in content
                ):
                    return True

        return False

    # -- Metadata -------------------------------------------------------------

    def get_framework_info(self, root_path: Path) -> Dict[str, Any]:
        root = Path(root_path)
        features: List[str] = []
        orm = self._detect_orm(root)

        if orm:
            features.append(orm)

        return {
            "framework": "Spring Boot",
            "language": "java",
            "architecture_type": "MVC + Services (Layered)",
            "orm": orm,
            "features": features,
        }

    # -- Helpers --------------------------------------------------------------

    def _detect_orm(self, root: Path) -> str | None:
        """Inspect build files for JPA / Hibernate references."""
        build_content = ""
        for name in ("pom.xml", "build.gradle", "build.gradle.kts"):
            path = self._file(root, name)
            if path is not None:
                content = self._read(root, path)
                if content is not None:
                    build_content += content

        if "spring-boot-starter-data-jpa" in build_content or "spring-data-jpa" in build_content:
            return "Spring Data JPA / Hibernate"
        if "hibernate" in build_content.lower():
            return "Hibernate"
        if "mybatis" in build_content.lower():
            return "MyBatis"
        return None

    def find_model_files(self, root_path: Path) -> List[Path]:
        root = Path(root_path)
        results: List[Path] = []
        # Conventional: src/main/java/**/model/ or **/entity/
        for path in self._files(root, suffixes=(".java",)):
            relative = path.relative_to(root).as_posix().casefold()
            parent_lower = path.parent.name.lower()
            if relative.startswith("src/main/java/") and parent_lower in (
                "model", "models", "entity", "entities", "domain"
            ):
                results.append(path)
        return sorted(results)

    def find_route_files(self, root_path: Path) -> List[Path]:
        root = Path(root_path)
        results: List[Path] = []
        for path in self._files(root, suffixes=(".java",)):
            relative = path.relative_to(root).as_posix().casefold()
            parent_lower = path.parent.name.lower()
            if relative.startswith("src/main/java/") and parent_lower in (
                "controller", "controllers", "rest", "api", "resource", "resources"
            ):
                results.append(path)
        return sorted(results)
