"""Bounded discovery and scope metadata for local Requirements collections."""

from collections import deque
from dataclasses import dataclass
from html import escape
import os
from pathlib import Path
import stat
from typing import Iterable, Optional, Tuple, Union

from bck_nd_hlpr.core.constants import GLOBAL_IGNORE_DIRS, SKIP_DIRS
from bck_nd_hlpr.core.sanitizer import sanitize_text
from bck_nd_hlpr.core.utils.gitignore_parser import GitIgnoreMatcher

from .parser import RequirementsLoadResult, RequirementsParser


DEFAULT_REQUIREMENTS_LOCATION_DEPTH = 6
MAX_REQUIREMENTS_LOCATION_DIRECTORIES = 4096
MAX_REQUIREMENTS_LOCATIONS = 32
MAX_REQUIREMENTS_SCOPE_CHARS = 2048


@dataclass(frozen=True)
class RequirementsLocationDiagnostic:
    """Neutral discovery diagnostic that never exposes a filesystem path."""

    code: str
    message: str


@dataclass(frozen=True)
class RequirementsLocation:
    """One independently loaded Requirements collection."""

    project_root: Path
    requirements_directory: Path
    relative_root: str
    source: str
    selected: bool
    result: RequirementsLoadResult
    story_count: int
    ids: Tuple[str, ...]
    status_counts: Tuple[Tuple[str, int], ...]
    rejected: bool
    diagnostic_code: Optional[str]


@dataclass(frozen=True)
class RequirementsLocationReport:
    """Selected scope plus independently discovered descendant collections."""

    selected_project_root: Optional[Path]
    selected_location: Optional[RequirementsLocation]
    nested_locations: Tuple[RequirementsLocation, ...]
    conflicting_ids: Tuple[str, ...]
    truncated: bool = False
    diagnostics: Tuple[RequirementsLocationDiagnostic, ...] = ()

    @property
    def locations(self) -> Tuple[RequirementsLocation, ...]:
        if self.selected_location is None:
            return self.nested_locations
        return (self.selected_location,) + self.nested_locations


def _is_link_or_reparse(path_stat: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(path_stat.st_mode) or bool(
        getattr(path_stat, "st_file_attributes", 0) & reparse_flag
    )


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        root_text = os.path.normcase(os.path.abspath(str(root)))
        candidate_text = os.path.normcase(os.path.abspath(str(candidate)))
        return os.path.commonpath([root_text, candidate_text]) == root_text
    except (OSError, ValueError):
        return False


def _safe_directory(path: Path, root: Optional[Path] = None) -> Optional[Path]:
    try:
        path_stat = path.lstat()
        if _is_link_or_reparse(path_stat) or not stat.S_ISDIR(path_stat.st_mode):
            return None
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if root is not None and not _is_within(resolved, root):
        return None
    return resolved


def _requirements_directory(project_root: Path) -> Optional[Path]:
    metadata = _safe_directory(project_root / ".bck-nd", project_root)
    if metadata is None:
        return None
    requirements = _safe_directory(metadata / "requirements", project_root)
    if requirements is None or not _is_within(requirements, metadata):
        return None
    return requirements


def _relative_label(path: Path, root: Path) -> str:
    if path == root:
        return "."
    relative = path.relative_to(root).as_posix()
    return relative or "."


def _source_label(relative_root: str) -> str:
    if relative_root == ".":
        return ".bck-nd/requirements"
    return f"{relative_root}/.bck-nd/requirements"


def _location(
    project_root: Path,
    selected_root: Path,
    result: RequirementsLoadResult,
    *,
    selected: bool,
) -> RequirementsLocation:
    relative_root = _relative_label(project_root, selected_root)
    ids = tuple(
        sorted(
            (str(spec.story.id).strip() for spec in result.specifications),
            key=lambda value: (value.casefold(), value),
        )
    )
    statuses = {}
    for spec in result.specifications:
        status = str(spec.story.status or "TODO").strip().upper()
        statuses[status] = statuses.get(status, 0) + 1
    diagnostic_code = result.error_code
    if diagnostic_code is None and result.diagnostics:
        diagnostic_code = result.diagnostics[0].code
    return RequirementsLocation(
        project_root=project_root,
        requirements_directory=project_root / ".bck-nd" / "requirements",
        relative_root=relative_root,
        source=_source_label(relative_root),
        selected=selected,
        result=result,
        story_count=len(result.specifications),
        ids=ids,
        status_counts=tuple(sorted(statuses.items())),
        rejected=result.rejected,
        diagnostic_code=diagnostic_code,
    )


def _conflicting_ids(
    locations: Iterable[RequirementsLocation],
) -> Tuple[str, ...]:
    occurrences = {}
    labels = {}
    for location in locations:
        for story_id in location.ids:
            normalized = story_id.strip().casefold()
            if not normalized:
                continue
            occurrences.setdefault(normalized, set()).add(location.relative_root)
            labels.setdefault(normalized, story_id.strip())
    conflicts = [
        labels[normalized]
        for normalized, roots in occurrences.items()
        if len(roots) > 1
    ]
    return tuple(sorted(conflicts, key=lambda value: (value.casefold(), value)))


def _ordered_diagnostics(
    diagnostics: Iterable[RequirementsLocationDiagnostic],
) -> Tuple[RequirementsLocationDiagnostic, ...]:
    return tuple(
        sorted(
            set(diagnostics),
            key=lambda item: (item.code, item.message),
        )
    )


def _record_ignore_policy_diagnostics(
    matcher: GitIgnoreMatcher,
    diagnostics: list,
) -> None:
    if matcher.diagnostics:
        diagnostics.append(
            RequirementsLocationDiagnostic(
                code="REQUIREMENTS_IGNORE_POLICY_UNAVAILABLE",
                message="A Requirements discovery subtree was excluded by ignore policy.",
            )
        )


def _ignore_policy_blocks(
    matcher: GitIgnoreMatcher,
    directory: Path,
    selected_root: Path,
) -> bool:
    try:
        relative_parts = directory.relative_to(selected_root).parts
    except ValueError:
        return True
    for diagnostic in matcher.diagnostics:
        scope = str(diagnostic.scope or ".").replace("\\", "/")
        if scope in {"", "."}:
            return True
        scope_parts = tuple(part for part in scope.split("/") if part and part != ".")
        if relative_parts[: len(scope_parts)] == scope_parts:
            return True
    return False


def discover_requirements_locations(
    project_path: Union[str, Path],
    current_result: Optional[RequirementsLoadResult] = None,
    *,
    max_depth: int = DEFAULT_REQUIREMENTS_LOCATION_DEPTH,
    max_directories: int = MAX_REQUIREMENTS_LOCATION_DIRECTORIES,
    max_locations: int = MAX_REQUIREMENTS_LOCATIONS,
) -> RequirementsLocationReport:
    """Discover descendant collections without merging or changing scope."""
    if (
        isinstance(max_depth, bool)
        or isinstance(max_directories, bool)
        or isinstance(max_locations, bool)
        or max_depth < 0
        or max_directories < 1
        or max_locations < 1
    ):
        raise ValueError("Requirements location limits must be positive integers.")

    requested_root = Path(os.path.abspath(str(project_path)))
    selected_root = _safe_directory(requested_root)
    if selected_root is None:
        diagnostic = RequirementsLocationDiagnostic(
            code="REQUIREMENTS_SCOPE_UNAVAILABLE",
            message="The selected Requirements scope could not be inspected safely.",
        )
        return RequirementsLocationReport(
            selected_project_root=None,
            selected_location=None,
            nested_locations=(),
            conflicting_ids=(),
            diagnostics=(diagnostic,),
        )

    ignored = {name.casefold() for name in GLOBAL_IGNORE_DIRS | SKIP_DIRS}
    diagnostics = []
    ignore_matcher = GitIgnoreMatcher(selected_root)
    _record_ignore_policy_diagnostics(ignore_matcher, diagnostics)
    discovered = []
    selected_location = None
    truncated = False
    inspected = 0
    pending = deque([(selected_root, 0)])

    while pending:
        if inspected >= max_directories:
            truncated = True
            break
        directory, depth = pending.popleft()
        inspected += 1

        requirements = _requirements_directory(directory)
        if requirements is not None:
            if len(discovered) + (1 if selected_location is not None else 0) >= max_locations:
                truncated = True
                break
            is_selected = directory == selected_root
            result = (
                current_result
                if is_selected and current_result is not None
                else RequirementsParser.load_collection(directory)
            )
            item = _location(
                directory,
                selected_root,
                result,
                selected=is_selected,
            )
            if is_selected:
                selected_location = item
            else:
                discovered.append(item)

        if _ignore_policy_blocks(ignore_matcher, directory, selected_root):
            _record_ignore_policy_diagnostics(ignore_matcher, diagnostics)
            continue

        try:
            entries = []
            with os.scandir(str(directory)) as iterator:
                for entry in iterator:
                    try:
                        entry_stat = entry.stat(follow_symlinks=False)
                    except OSError:
                        diagnostics.append(
                            RequirementsLocationDiagnostic(
                                code="REQUIREMENTS_LOCATION_UNAVAILABLE",
                                message="A descendant directory could not be inspected safely.",
                            )
                        )
                        continue
                    if _is_link_or_reparse(entry_stat) or not stat.S_ISDIR(
                        entry_stat.st_mode
                    ):
                        continue
                    entries.append(entry.name)
        except OSError:
            diagnostics.append(
                RequirementsLocationDiagnostic(
                    code="REQUIREMENTS_LOCATION_UNAVAILABLE",
                    message="A descendant directory could not be inspected safely.",
                )
            )
            continue

        for name in sorted(entries, key=lambda value: (value.casefold(), value)):
            normalized = name.casefold()
            if normalized == ".bck-nd" or normalized in ignored:
                continue
            if name.startswith("."):
                continue
            child_path = directory / name
            if ignore_matcher.matches(child_path, is_dir=True):
                _record_ignore_policy_diagnostics(ignore_matcher, diagnostics)
                continue
            _record_ignore_policy_diagnostics(ignore_matcher, diagnostics)
            if _ignore_policy_blocks(ignore_matcher, child_path, selected_root):
                continue
            if depth >= max_depth:
                truncated = True
                continue
            child = _safe_directory(child_path, selected_root)
            if child is None:
                continue
            pending.append((child, depth + 1))

    nested = tuple(
        sorted(
            discovered,
            key=lambda item: (item.relative_root.casefold(), item.relative_root),
        )
    )
    all_locations = ((selected_location,) if selected_location else ()) + nested
    return RequirementsLocationReport(
        selected_project_root=selected_root,
        selected_location=selected_location,
        nested_locations=nested,
        conflicting_ids=_conflicting_ids(all_locations),
        truncated=truncated,
        diagnostics=_ordered_diagnostics(diagnostics),
    )


def _safe_metadata_value(value: str) -> str:
    single_line = " ".join(str(value).splitlines()).strip()
    return escape(sanitize_text(single_line), quote=False)


def render_requirements_scope(
    report: RequirementsLocationReport,
    *,
    max_chars: int = MAX_REQUIREMENTS_SCOPE_CHARS,
) -> Optional[str]:
    """Render bounded relative-only metadata for omitted collections."""
    if not report.nested_locations and not report.truncated:
        return None
    if max_chars < len("<requirements_scope>\n</requirements_scope>"):
        return None

    selected = report.selected_location
    required = [
        "selected: .",
        "current_collection: "
        + (
            "missing"
            if selected is None
            else ("invalid" if selected.rejected else "available")
        ),
        f"nested_locations_omitted: {len(report.nested_locations)}",
    ]
    optional = []
    if report.nested_locations:
        optional.append("nested_roots:")
        optional.extend(
            f"  - {_safe_metadata_value(location.relative_root)}"
            for location in report.nested_locations
        )
    if report.conflicting_ids:
        optional.append("conflicting_ids:")
        optional.extend(
            f"  - {_safe_metadata_value(story_id)}"
            for story_id in report.conflicting_ids
        )
    if report.truncated:
        optional.append("discovery_truncated: true")

    opening = "<requirements_scope>"
    closing = "</requirements_scope>"
    lines = [opening, *required]
    metadata_truncated = False
    for line in optional:
        candidate = "\n".join([*lines, line, closing])
        if len(candidate) > max_chars:
            metadata_truncated = True
            break
        lines.append(line)
    if metadata_truncated:
        marker = "metadata_truncated: true"
        while len("\n".join([*lines, marker, closing])) > max_chars and len(lines) > 1 + len(required):
            lines.pop()
        if len("\n".join([*lines, marker, closing])) <= max_chars:
            lines.append(marker)
    rendered = "\n".join([*lines, closing])
    return rendered if len(rendered) <= max_chars else None


__all__ = [
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
