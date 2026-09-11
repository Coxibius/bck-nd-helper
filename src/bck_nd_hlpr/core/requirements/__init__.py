"""
Requirements Module — Domain models and parser for User Stories, Acceptance Criteria,
and Business Rules.
"""

from .models import (
    AcceptanceCriteria,
    BusinessRule,
    RequirementSpecification,
    UserStory,
)
from .parser import (
    MAX_REQUIREMENT_FILES,
    MAX_REQUIREMENT_JSON_DEPTH,
    MAX_REQUIREMENT_JSON_NODES,
    MAX_REQUIREMENT_SOURCE_BYTES,
    MAX_REQUIREMENTS_DIRECTORY_ENTRIES,
    MAX_REQUIREMENTS_TOTAL_BYTES,
    RequirementLoadDiagnostic,
    RequirementsLoadResult,
    RequirementsParser,
    VALID_STORY_STATUSES,
)
from .renderer import (
    MAX_REQUIREMENTS_CONTEXT_CHARS,
    MIN_REQUIREMENTS_CONTEXT_CHARS,
    REQUIREMENTS_TRUNCATION_MARKER,
    build_requirements_context,
    build_requirements_summary,
    render_requirements_context,
    render_requirements_summary,
)
from .locations import (
    DEFAULT_REQUIREMENTS_LOCATION_DEPTH,
    MAX_REQUIREMENTS_LOCATION_DIRECTORIES,
    MAX_REQUIREMENTS_LOCATIONS,
    MAX_REQUIREMENTS_SCOPE_CHARS,
    RequirementsLocation,
    RequirementsLocationDiagnostic,
    RequirementsLocationReport,
    discover_requirements_locations,
    render_requirements_scope,
)

__all__ = [
    "UserStory",
    "AcceptanceCriteria",
    "BusinessRule",
    "RequirementSpecification",
    "RequirementsParser",
    "RequirementLoadDiagnostic",
    "RequirementsLoadResult",
    "VALID_STORY_STATUSES",
    "MAX_REQUIREMENT_FILES",
    "MAX_REQUIREMENT_SOURCE_BYTES",
    "MAX_REQUIREMENTS_DIRECTORY_ENTRIES",
    "MAX_REQUIREMENTS_TOTAL_BYTES",
    "MAX_REQUIREMENT_JSON_DEPTH",
    "MAX_REQUIREMENT_JSON_NODES",
    "MAX_REQUIREMENTS_CONTEXT_CHARS",
    "MIN_REQUIREMENTS_CONTEXT_CHARS",
    "REQUIREMENTS_TRUNCATION_MARKER",
    "build_requirements_context",
    "build_requirements_summary",
    "render_requirements_context",
    "render_requirements_summary",
    "DEFAULT_REQUIREMENTS_LOCATION_DEPTH",
    "MAX_REQUIREMENTS_LOCATION_DIRECTORIES",
    "MAX_REQUIREMENTS_LOCATIONS",
    "MAX_REQUIREMENTS_SCOPE_CHARS",
    "RequirementsLocation",
    "RequirementsLocationDiagnostic",
    "RequirementsLocationReport",
    "discover_requirements_locations",
    "render_requirements_scope",
]
