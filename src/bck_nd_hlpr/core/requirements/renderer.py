"""Bounded, deterministic renderers for Requirements Intelligence context."""

from pathlib import Path
from typing import Callable, Iterable, Iterator, Optional, Sequence, Union

from bck_nd_hlpr.core.sanitizer import sanitize_text

from .models import RequirementSpecification
from .parser import RequirementsLoadResult, RequirementsParser


MAX_REQUIREMENTS_CONTEXT_CHARS = 12_000
MIN_REQUIREMENTS_CONTEXT_CHARS = 256
REQUIREMENTS_TRUNCATION_MARKER = "... [REQUIREMENTS CONTEXT TRUNCATED]"
REQUIREMENTS_COLLECTION_REJECTED = "Requirements collection unavailable safely"
NO_REQUIREMENTS_MESSAGE = (
    "No requirements found under .bck-nd/requirements/. Create JSON specifications "
    "under .bck-nd/requirements/ to define User Stories."
)
_PRIORITY_LINE_CHARS = 192
_LINE_TRUNCATION_SUFFIX = "… [TRUNCATED]"


class _RepositoryLine(str):
    """Marker type for a sanitized line whose values came from the repository."""


def _safe(value: object) -> str:
    """Sanitize repository data before it participates in the budget."""
    return (
        sanitize_text(str(value))
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _ordered(
    specifications: Sequence[RequirementSpecification],
) -> Sequence[RequirementSpecification]:
    # The parser already returns deterministic file order. Preserve it so small
    # repositories retain their pre-budget rendering behavior byte for byte.
    return tuple(specifications)


def _truncate_repository_line(line: str, max_chars: int) -> _RepositoryLine:
    """Truncate sanitized text without splitting one of our escaped entities."""
    if len(line) <= max_chars:
        return _RepositoryLine(line)
    if max_chars <= len(_LINE_TRUNCATION_SUFFIX):
        return _RepositoryLine(_LINE_TRUNCATION_SUFFIX[:max_chars])
    prefix_chars = max_chars - len(_LINE_TRUNCATION_SUFFIX)
    prefix = line[:prefix_chars]
    last_ampersand = prefix.rfind("&")
    last_semicolon = prefix.rfind(";")
    if last_ampersand > last_semicolon:
        prefix = prefix[:last_ampersand]
    return _RepositoryLine(prefix.rstrip() + _LINE_TRUNCATION_SUFFIX)


def _priority_line(line: str) -> _RepositoryLine:
    """Keep repository-controlled provenance useful within a bounded line."""
    return _truncate_repository_line(line, _PRIORITY_LINE_CHARS)


def _context_header_lines() -> Iterator[str]:
    yield "<!-- User Stories & Acceptance Criteria -->"


def _context_story_header(spec: RequirementSpecification) -> str:
    story = spec.story
    status = f" [{_safe(story.status)}]" if story.status else ""
    title = f" - {_safe(story.title)}" if story.title else ""
    return _RepositoryLine(f"{_safe(story.id)}{status}{title}")


def _context_story_details(
    spec: RequirementSpecification, *, truncate_lines: bool = False
) -> Iterator[str]:
    render = _priority_line if truncate_lines else _RepositoryLine
    story = spec.story
    if story.role:
        yield render(f"  As a: {_safe(story.role)}")
    if story.want:
        yield render(f"  I want: {_safe(story.want)}")
    if story.benefit:
        yield render(f"  So that: {_safe(story.benefit)}")
    if spec.business_rules:
        yield "  Business Rules:"
        for rule in spec.business_rules:
            yield render(f"    - {_safe(rule.id)}: {_safe(rule.description)}")
    if spec.acceptance_criteria:
        yield "  Acceptance Criteria:"
        for criterion in spec.acceptance_criteria:
            yield render(
                f"    - {_safe(criterion.id)}: Given {_safe(criterion.given)} "
                f"When {_safe(criterion.when)} Then {_safe(criterion.then)}"
            )
    if spec.required_data:
        yield "  Required Data:"
        for item in spec.required_data:
            yield render(f"    - {_safe(item)}")
    if spec.validations:
        yield "  Validations:"
        for validation in spec.validations:
            yield render(f"    - {_safe(validation)}")
    if spec.exceptions:
        yield "  Exceptions:"
        for exception in spec.exceptions:
            yield render(f"    - {_safe(exception)}")
    if spec.open_questions:
        yield "  Open Questions:"
        for question in spec.open_questions:
            yield render(f"    - {_safe(question)}")
    yield ""


def _context_full_lines(
    specifications: Sequence[RequirementSpecification],
) -> Iterator[str]:
    yield from _context_header_lines()
    for spec in specifications:
        yield _context_story_header(spec)
        yield from _context_story_details(spec)


def _context_priority_lines(
    specifications: Sequence[RequirementSpecification],
) -> Iterator[str]:
    yield from _context_header_lines()
    for spec in specifications:
        yield _priority_line(_context_story_header(spec))
    for spec in specifications:
        yield from _context_story_details(spec, truncate_lines=True)


def _summary_header_lines(
    specifications: Sequence[RequirementSpecification],
) -> Iterator[str]:
    known_statuses = ("TODO", "IN_PROGRESS", "TESTING", "DONE", "BLOCKED")
    counts = {status: 0 for status in known_statuses}
    other = 0
    for spec in specifications:
        status = str(spec.story.status or "TODO").upper()
        if status in counts:
            counts[status] += 1
        else:
            other += 1
    yield "# Requirements Summary\n"
    yield (
        f"**Total Stories**: {len(specifications)} (TODO: {counts.get('TODO', 0)}, "
        f"IN_PROGRESS: {counts.get('IN_PROGRESS', 0)}, "
        f"TESTING: {counts.get('TESTING', 0)}, DONE: {counts.get('DONE', 0)}, "
        f"BLOCKED: {counts.get('BLOCKED', 0)}, OTHER: {other})\n"
    )


def _summary_story_header(spec: RequirementSpecification) -> str:
    story = spec.story
    status = f"[{_safe(story.status)}]" if story.status else "[TODO]"
    return _RepositoryLine(
        f"### {_safe(story.id)} {status} - {_safe(story.title)}"
    )


def _summary_story_details(
    spec: RequirementSpecification, *, truncate_lines: bool = False
) -> Iterator[str]:
    render = _priority_line if truncate_lines else _RepositoryLine
    story = spec.story
    if story.role:
        yield render(f"- **As a**: {_safe(story.role)}")
    if story.want:
        yield render(f"- **I want**: {_safe(story.want)}")
    if story.benefit:
        yield render(f"- **So that**: {_safe(story.benefit)}")
    if spec.business_rules:
        yield f"- **Business Rules** ({len(spec.business_rules)}):"
        for rule in spec.business_rules:
            yield render(f"  - `{_safe(rule.id)}`: {_safe(rule.description)}")
    if spec.acceptance_criteria:
        yield f"- **Acceptance Criteria** ({len(spec.acceptance_criteria)}):"
        for criterion in spec.acceptance_criteria:
            yield render(
                f"  - `{_safe(criterion.id)}`: **Given** {_safe(criterion.given)} "
                f"**When** {_safe(criterion.when)} **Then** {_safe(criterion.then)}"
            )
    if spec.required_data:
        yield render(f"- **Required Data**: {_safe(spec.required_data)}")
    if spec.validations:
        yield render(f"- **Validations**: {_safe(spec.validations)}")
    if spec.exceptions:
        yield render(f"- **Exceptions**: {_safe(spec.exceptions)}")
    if spec.open_questions:
        yield f"- **Open Questions** ({len(spec.open_questions)}):"
        for question in spec.open_questions:
            yield render(f"  - {_safe(question)}")
    yield ""


def _summary_full_lines(
    specifications: Sequence[RequirementSpecification],
) -> Iterator[str]:
    yield from _summary_header_lines(specifications)
    for spec in specifications:
        yield _summary_story_header(spec)
        yield from _summary_story_details(spec)


def _summary_priority_lines(
    specifications: Sequence[RequirementSpecification],
) -> Iterator[str]:
    yield from _summary_header_lines(specifications)
    for spec in specifications:
        yield _priority_line(_summary_story_header(spec))
    for spec in specifications:
        yield from _summary_story_details(spec, truncate_lines=True)


def _fits(factory: Callable[[], Iterable[str]], max_chars: int) -> bool:
    length = 0
    first = True
    for line in factory():
        length += len(line) + (0 if first else 1)
        if length > max_chars:
            return False
        first = False
    return True


def _bounded(
    full_factory: Callable[[], Iterable[str]],
    priority_factory: Callable[[], Iterable[str]],
    max_chars: int,
) -> str:
    """Render without ever constructing text larger than the public budget."""
    if max_chars < len(REQUIREMENTS_TRUNCATION_MARKER):
        return REQUIREMENTS_TRUNCATION_MARKER[:max_chars]
    if _fits(full_factory, max_chars):
        return "\n".join(full_factory()).rstrip()

    lines = []
    used = 0
    marker_cost = len(REQUIREMENTS_TRUNCATION_MARKER) + 1
    for line in priority_factory():
        separator = 0 if not lines else 1
        if used + separator + len(line) + marker_cost > max_chars:
            available = max_chars - used - separator - marker_cost
            if isinstance(line, _RepositoryLine) and available > len(
                _LINE_TRUNCATION_SUFFIX
            ):
                lines.append(_truncate_repository_line(line, available))
            break
        lines.append(line)
        used += separator + len(line)
    if lines:
        return "\n".join(lines).rstrip() + "\n" + REQUIREMENTS_TRUNCATION_MARKER
    return REQUIREMENTS_TRUNCATION_MARKER


def _rejected_message(result: RequirementsLoadResult) -> str:
    code = result.error_code or "REQUIREMENTS_COLLECTION_UNAVAILABLE"
    return f"{REQUIREMENTS_COLLECTION_REJECTED} ({code})."


def _validated_budget(max_chars: Optional[int]) -> int:
    budget = MAX_REQUIREMENTS_CONTEXT_CHARS if max_chars is None else max_chars
    if isinstance(budget, bool) or not isinstance(budget, int):
        raise TypeError("max_chars must be an integer.")
    if budget < 0:
        raise ValueError("max_chars must be zero or greater.")
    return budget


def render_requirements_context(
    result: RequirementsLoadResult,
    *,
    max_chars: Optional[int] = None,
) -> Optional[str]:
    """Render one already-loaded collection for an AI context block."""
    budget = _validated_budget(max_chars)
    if budget == 0:
        return ""
    if result.rejected:
        return _rejected_message(result)[:budget]
    if not result.specifications:
        return None
    specifications = _ordered(result.specifications)
    return _bounded(
        lambda: _context_full_lines(specifications),
        lambda: _context_priority_lines(specifications),
        budget,
    )


def render_requirements_summary(
    result: RequirementsLoadResult,
    *,
    max_chars: Optional[int] = None,
) -> str:
    """Render one already-loaded collection as a bounded Markdown summary."""
    budget = _validated_budget(max_chars)
    if budget == 0:
        return ""
    if result.rejected:
        return _rejected_message(result)[:budget]
    if not result.specifications:
        return NO_REQUIREMENTS_MESSAGE[:budget]
    specifications = _ordered(result.specifications)
    return _bounded(
        lambda: _summary_full_lines(specifications),
        lambda: _summary_priority_lines(specifications),
        budget,
    )


def build_requirements_context(
    project_path: Union[str, Path] = ".",
    *,
    max_chars: Optional[int] = None,
) -> Optional[str]:
    """Load once and build bounded inner ``requirements_context`` content."""
    return render_requirements_context(
        RequirementsParser.load_collection(project_path),
        max_chars=max_chars,
    )


def build_requirements_summary(
    project_path: Union[str, Path] = ".",
    *,
    max_chars: Optional[int] = None,
) -> str:
    """Load once and build the bounded MCP Requirements summary."""
    return render_requirements_summary(
        RequirementsParser.load_collection(project_path),
        max_chars=max_chars,
    )
