"""
Requirements Parser — Loads and parses User Story and Requirement specifications
from the .bck-nd/requirements/ directory.
"""

import json
import logging
from pathlib import Path
from typing import List, Optional, Union

from .models import RequirementSpecification

logger = logging.getLogger(__name__)


class RequirementsParser:
    """Parses requirement JSON files from the project workspace."""

    @staticmethod
    def parse_file(file_path: Union[str, Path]) -> Optional[RequirementSpecification]:
        """
        Parses a single JSON requirement specification file.

        Args:
            file_path: Path to the requirement JSON file.

        Returns:
            RequirementSpecification instance if valid, or None if parsing fails.
        """
        path = Path(file_path)
        try:
            if not path.is_file():
                return None
            content = path.read_text(encoding="utf-8")
            data = json.loads(content)
            if not isinstance(data, dict):
                logger.warning("Requirement file '%s' does not contain a JSON object.", path)
                return None
            return RequirementSpecification.from_dict(data)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError, ValueError) as exc:
            logger.warning("Failed to parse requirement file '%s': %s", path, exc)
            return None

    @classmethod
    def load_from_directory(
        cls, project_path: Union[str, Path]
    ) -> List[RequirementSpecification]:
        """
        Reads and parses all .json requirement files located under
        '<project_path>/.bck-nd/requirements/'.

        Args:
            project_path: Root path of the project.

        Returns:
            List of successfully parsed RequirementSpecification objects.
            Returns an empty list if directory is missing or unreadable.
        """
        try:
            base_path = Path(project_path)
            # Support both passing the project root or the direct requirements folder
            if base_path.name == "requirements" and base_path.is_dir():
                req_dir = base_path
            else:
                req_dir = base_path / ".bck-nd" / "requirements"

            if not req_dir.exists() or not req_dir.is_dir():
                return []

            specs: List[RequirementSpecification] = []
            for file_path in sorted(req_dir.glob("*.json")):
                spec = cls.parse_file(file_path)
                if spec is not None:
                    specs.append(spec)

            return specs
        except Exception as exc:
            logger.warning("Error loading requirements from '%s': %s", project_path, exc)
            return []
