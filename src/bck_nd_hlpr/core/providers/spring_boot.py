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
    candidates: List[Path] = []
    src_main = root / "src" / "main" / "java"
    if src_main.is_dir():
        candidates.extend(find_files_by_glob(src_main, "**/*.java"))
    else:
        candidates.extend(find_files_by_glob(root, "**/*.java"))
    for java_file in candidates:
        try:
            text = java_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
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
        pom = root / "pom.xml"
        if pom.exists():
            try:
                content = pom.read_text(encoding="utf-8", errors="ignore")
                if "spring-boot" in content:
                    return True
            except Exception:
                pass

        # 2. Gradle — build.gradle / build.gradle.kts containing spring-boot
        for gradle_name in ("build.gradle", "build.gradle.kts"):
            gradle = root / gradle_name
            if gradle.exists():
                try:
                    content = gradle.read_text(encoding="utf-8", errors="ignore")
                    if "spring-boot" in content or "org.springframework.boot" in content:
                        return True
                except Exception:
                    pass

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
            path = root / name
            if path.exists():
                try:
                    build_content += path.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    pass

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
        src_main = root / "src" / "main" / "java"
        if src_main.is_dir():
            for p in src_main.rglob("*.java"):
                parent_lower = p.parent.name.lower()
                if parent_lower in ("model", "models", "entity", "entities", "domain"):
                    results.append(p)
        return sorted(results)

    def find_route_files(self, root_path: Path) -> List[Path]:
        root = Path(root_path)
        results: List[Path] = []
        src_main = root / "src" / "main" / "java"
        if src_main.is_dir():
            for p in src_main.rglob("*.java"):
                parent_lower = p.parent.name.lower()
                if parent_lower in ("controller", "controllers", "rest", "api", "resource", "resources"):
                    results.append(p)
        return sorted(results)
