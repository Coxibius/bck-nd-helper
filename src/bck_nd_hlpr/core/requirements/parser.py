"""
Requirements Parser — Loads and parses User Story and Requirement specifications
from the .bck-nd/requirements/ directory (supporting both JSON and Markdown).
"""

import json
import logging
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

from bck_nd_hlpr.core.sanitizer import sanitize_text
from bck_nd_hlpr.core.utils.file_lock import (
    FileLockError,
    exclusive_file_lock,
    fsync_directory,
)

from .models import AcceptanceCriteria, BusinessRule, RequirementSpecification, UserStory

logger = logging.getLogger(__name__)

VALID_STORY_STATUSES = frozenset(
    {"TODO", "IN_PROGRESS", "TESTING", "DONE", "BLOCKED"}
)
_VALID_STORY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
MAX_REQUIREMENT_SOURCE_BYTES = 1024 * 1024
MAX_REQUIREMENT_FILES = 512
MAX_REQUIREMENTS_DIRECTORY_ENTRIES = 4096
MAX_REQUIREMENTS_TOTAL_BYTES = 8 * 1024 * 1024
MAX_REQUIREMENT_JSON_DEPTH = 64
MAX_REQUIREMENT_JSON_NODES = 10_000
REQUIREMENTS_STATUS_LOCK_TIMEOUT = 5.0


def _requirements_status_lock_path(requirements_directory: Path) -> Path:
    """Return the persistent cooperative status-writer lock."""
    return requirements_directory / ".bck-nd-status.lock"


class RequirementSourceError(Exception):
    """Controlled signal for unsafe, oversized, or unstable requirement I/O."""


class RequirementJsonError(ValueError):
    """Controlled signal for invalid or overly complex requirement JSON."""

    def __init__(self, message: str, code: str = "REQUIREMENT_JSON_INVALID") -> None:
        super().__init__(message)
        self.code = code


class RequirementCollectionError(RequirementSourceError):
    """Controlled signal for a requirements collection rejected as a whole."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class RequirementLoadDiagnostic:
    """One neutral, safely exposed reason a requirement source was rejected."""

    code: str
    source: str
    message: str


@dataclass(frozen=True)
class RequirementsLoadResult:
    """Safe result that distinguishes an empty collection from rejection."""

    specifications: Tuple[RequirementSpecification, ...] = ()
    rejected: bool = False
    error_code: Optional[str] = None
    diagnostics: Tuple[RequirementLoadDiagnostic, ...] = ()


class RequirementsParser:
    """Parses requirement JSON and Markdown specification files from the project workspace."""

    VALID_STATUSES = VALID_STORY_STATUSES

    @staticmethod
    def _scan_json_depth(content: str) -> None:
        """Reject excessive JSON nesting without constructing Python objects."""
        depth = 0
        in_string = False
        escaped = False
        for character in content:
            if in_string:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    in_string = False
                continue
            if character == '"':
                in_string = True
            elif character in "[{":
                depth += 1
                if depth > MAX_REQUIREMENT_JSON_DEPTH:
                    raise RequirementJsonError(
                        "Requirement JSON exceeds the nesting limit."
                    )
            elif character in "]}":
                depth = max(0, depth - 1)

    @staticmethod
    def _count_json_nodes(value: Any) -> int:
        """Count JSON values and object keys iteratively with a strict ceiling."""
        count = 0
        pending = [value]
        while pending:
            current = pending.pop()
            count += 1
            if count > MAX_REQUIREMENT_JSON_NODES:
                raise RequirementJsonError(
                    "Requirement JSON exceeds the node limit."
                )
            if isinstance(current, dict):
                count += len(current)
                if count > MAX_REQUIREMENT_JSON_NODES:
                    raise RequirementJsonError(
                        "Requirement JSON exceeds the node limit."
                    )
                pending.extend(current.values())
            elif isinstance(current, list):
                pending.extend(current)
        return count

    @classmethod
    def _load_bounded_json(cls, raw_content: bytes) -> Any:
        """Decode JSON through the shared depth, node, and strict-value frontier."""
        try:
            try:
                content = raw_content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise RequirementJsonError(
                    "Requirement source is not valid UTF-8.",
                    "REQUIREMENT_SOURCE_INVALID_UTF8",
                ) from exc
            cls._scan_json_depth(content)

            def reject_constant(_value: str) -> None:
                raise RequirementJsonError(
                    "Requirement JSON contains a non-finite number."
                )

            def reject_duplicate_keys(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
                result: Dict[str, Any] = {}
                for key, item in pairs:
                    if key in result:
                        raise RequirementJsonError(
                            "Requirement JSON contains a duplicate object key.",
                            "REQUIREMENT_JSON_DUPLICATE_KEY",
                        )
                    result[key] = item
                return result

            value = json.loads(
                content,
                parse_constant=reject_constant,
                object_pairs_hook=reject_duplicate_keys,
            )
            cls._count_json_nodes(value)
            return value
        except RequirementJsonError:
            raise
        except (
            json.JSONDecodeError,
            RecursionError,
            MemoryError,
        ) as exc:
            raise RequirementJsonError(
                "Requirement JSON is invalid or unsafe."
            ) from exc

    @staticmethod
    def _validate_requirement_json_schema(data: Any) -> Dict[str, Any]:
        """Validate known container shapes before constructing domain models."""
        if not isinstance(data, dict):
            raise RequirementJsonError(
                "Requirement JSON must contain an object.",
                "REQUIREMENT_SCHEMA_INVALID",
            )
        if "story" in data and not isinstance(data["story"], dict):
            raise RequirementJsonError(
                "Requirement JSON contains an invalid story object.",
                "REQUIREMENT_SCHEMA_INVALID",
            )

        object_list_fields = (
            "business_rules",
            "acceptance_criteria",
            "required_data",
            "validations",
            "exceptions",
        )
        for field_name in object_list_fields:
            if field_name not in data:
                continue
            values = data[field_name]
            if not isinstance(values, list) or any(
                not isinstance(item, dict) for item in values
            ):
                raise RequirementJsonError(
                    "Requirement JSON contains an invalid structured list.",
                    "REQUIREMENT_SCHEMA_INVALID",
                )

        if "open_questions" in data:
            questions = data["open_questions"]
            if not isinstance(questions, list) or any(
                not isinstance(question, str) for question in questions
            ):
                raise RequirementJsonError(
                    "Requirement JSON contains invalid open questions.",
                    "REQUIREMENT_SCHEMA_INVALID",
                )
        return data

    @staticmethod
    def _is_link_or_reparse(path_stat: os.stat_result) -> bool:
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        return stat.S_ISLNK(path_stat.st_mode) or bool(
            getattr(path_stat, "st_file_attributes", 0) & reparse_flag
        )

    @staticmethod
    def _file_state(path_stat: os.stat_result) -> Tuple[int, int, int, int, int, int]:
        return (
            path_stat.st_dev,
            path_stat.st_ino,
            stat.S_IFMT(path_stat.st_mode),
            path_stat.st_size,
            path_stat.st_mtime_ns,
            path_stat.st_ctime_ns,
        )

    @staticmethod
    def _descriptor_state(path_stat: os.stat_result) -> Tuple[int, int, int, int, int]:
        return (
            path_stat.st_dev,
            path_stat.st_ino,
            stat.S_IFMT(path_stat.st_mode),
            path_stat.st_size,
            path_stat.st_mtime_ns,
        )

    @staticmethod
    def _is_within(candidate: Path, directory: Path) -> bool:
        try:
            candidate_text = os.path.normcase(os.path.abspath(str(candidate)))
            directory_text = os.path.normcase(os.path.abspath(str(directory)))
            return os.path.commonpath([directory_text, candidate_text]) == directory_text
        except (OSError, ValueError):
            return False

    @classmethod
    def _requirements_context(
        cls, project_path: Union[str, Path]
    ) -> Tuple[Path, Path, List[Path]]:
        base = Path(project_path)
        if base.name.casefold() == "requirements":
            requirements_dir = base
            if base.parent.name.casefold() == ".bck-nd":
                project_root = base.parent.parent
                components = [project_root, base.parent, base]
            else:
                project_root = base.parent
                components = [project_root, base]
        else:
            project_root = base
            requirements_dir = base / ".bck-nd" / "requirements"
            components = [project_root, requirements_dir.parent, requirements_dir]
        unique: List[Path] = []
        seen = set()
        for component in components:
            key = os.path.normcase(os.path.abspath(str(component)))
            if key not in seen:
                unique.append(component)
                seen.add(key)
        return requirements_dir, project_root, unique

    @classmethod
    def _verified_requirements_directory(
        cls, project_path: Union[str, Path]
    ) -> Optional[Tuple[Path, Path, List[Tuple[Path, os.stat_result]]]]:
        requirements_dir, project_root, components = cls._requirements_context(project_path)
        stats: List[Tuple[Path, os.stat_result]] = []
        try:
            for component in components:
                component_stat = component.lstat()
                if cls._is_link_or_reparse(component_stat) or not stat.S_ISDIR(
                    component_stat.st_mode
                ):
                    raise RequirementSourceError(
                        "Requirement directories must be regular local directories."
                    )
                stats.append((component, component_stat))
            resolved_root = project_root.resolve(strict=True)
            resolved_requirements = requirements_dir.resolve(strict=True)
        except FileNotFoundError:
            return None
        except (OSError, RuntimeError) as exc:
            raise RequirementSourceError(
                "Unable to inspect requirement directories safely."
            ) from exc
        if not cls._is_within(resolved_requirements, resolved_root):
            raise RequirementSourceError(
                "Requirement directory leaves the selected project root."
            )
        return requirements_dir, project_root, stats

    @classmethod
    def _read_verified_source(
        cls,
        file_path: Union[str, Path],
        *,
        requirements_directory: Optional[Union[str, Path]] = None,
        project_root: Optional[Union[str, Path]] = None,
    ) -> Tuple[bytes, os.stat_result]:
        path = Path(file_path)
        if requirements_directory is None or project_root is None:
            requirements_dir, inferred_root, components = cls._requirements_context(
                path.parent
            )
            if requirements_dir != path.parent:
                requirements_dir = path.parent
                inferred_root = path.parent.parent.parent if path.parent.parent.name == ".bck-nd" else path.parent.parent
                components = [inferred_root, path.parent.parent, path.parent] if path.parent.parent.name == ".bck-nd" else [inferred_root, path.parent]
        else:
            requirements_dir = Path(requirements_directory)
            inferred_root = Path(project_root)
            _, _, components = cls._requirements_context(requirements_dir)

        directory_stats: List[Tuple[Path, os.stat_result]] = []
        try:
            for component in components:
                component_stat = component.lstat()
                if cls._is_link_or_reparse(component_stat) or not stat.S_ISDIR(
                    component_stat.st_mode
                ):
                    raise RequirementSourceError(
                        "Requirement source uses a forbidden link or reparse point."
                    )
                directory_stats.append((component, component_stat))
            initial_stat = path.lstat()
        except RequirementSourceError:
            raise
        except (OSError, RuntimeError) as exc:
            raise RequirementSourceError(
                "Unable to inspect requirement source safely."
            ) from exc
        if cls._is_link_or_reparse(initial_stat) or not stat.S_ISREG(initial_stat.st_mode):
            raise RequirementSourceError(
                "Requirement source must be a regular local file."
            )
        if initial_stat.st_size > MAX_REQUIREMENT_SOURCE_BYTES:
            raise RequirementSourceError("Requirement source exceeds the 1 MiB limit.")
        try:
            resolved_root = inferred_root.resolve(strict=True)
            resolved_dir = requirements_dir.resolve(strict=True)
            resolved_path = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise RequirementSourceError(
                "Unable to resolve requirement source safely."
            ) from exc
        if not cls._is_within(resolved_dir, resolved_root) or not cls._is_within(
            resolved_path, resolved_dir
        ):
            raise RequirementSourceError(
                "Requirement source leaves the selected project root."
            )

        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(str(path), flags)
        except OSError as exc:
            raise RequirementSourceError(
                "Requirement source changed during secure reading."
            ) from exc
        try:
            opened_stat = os.fstat(descriptor)
            if (
                cls._is_link_or_reparse(opened_stat)
                or cls._descriptor_state(opened_stat) != cls._descriptor_state(initial_stat)
            ):
                raise RequirementSourceError(
                    "Requirement source changed during secure reading."
                )
            chunks: List[bytes] = []
            total = 0
            while True:
                remaining = MAX_REQUIREMENT_SOURCE_BYTES - total
                chunk = os.read(descriptor, min(64 * 1024, remaining + 1))
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_REQUIREMENT_SOURCE_BYTES:
                    raise RequirementSourceError(
                        "Requirement source exceeds the 1 MiB limit."
                    )
                chunks.append(chunk)
            content = b"".join(chunks)
            final_descriptor_stat = os.fstat(descriptor)
        except RequirementSourceError:
            raise
        except OSError as exc:
            raise RequirementSourceError(
                "Unable to read requirement source safely."
            ) from exc
        finally:
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            final_path_stat = path.lstat()
            for component, expected_stat in directory_stats:
                current_stat = component.lstat()
                if (
                    cls._is_link_or_reparse(current_stat)
                    or cls._file_state(current_stat) != cls._file_state(expected_stat)
                ):
                    raise RequirementSourceError(
                        "Requirement directory changed during secure reading."
                    )
        except RequirementSourceError:
            raise
        except OSError as exc:
            raise RequirementSourceError(
                "Requirement source changed during secure reading."
            ) from exc
        if (
            cls._is_link_or_reparse(final_path_stat)
            or cls._file_state(final_descriptor_stat) != cls._file_state(opened_stat)
            or cls._file_state(final_path_stat) != cls._file_state(initial_stat)
        ):
            raise RequirementSourceError(
                "Requirement source changed during secure reading."
            )
        return content, final_path_stat

    @classmethod
    def _safe_requirement_files(
        cls, project_path: Union[str, Path]
    ) -> Tuple[
        List[Path],
        Optional[Path],
        Optional[Path],
        Tuple[RequirementLoadDiagnostic, ...],
    ]:
        verified = cls._verified_requirements_directory(project_path)
        if verified is None:
            return [], None, None, ()
        requirements_dir, project_root, _ = verified
        files: List[Path] = []
        diagnostics: List[RequirementLoadDiagnostic] = []
        observed_bytes = 0
        entry_count = 0
        try:
            with os.scandir(str(requirements_dir)) as entries:
                for entry in entries:
                    entry_count += 1
                    if entry_count > MAX_REQUIREMENTS_DIRECTORY_ENTRIES:
                        raise RequirementCollectionError(
                            "REQUIREMENTS_DIRECTORY_ENTRY_LIMIT"
                        )
                    path = requirements_dir / entry.name
                    if path.suffix.lower() not in {".json", ".md", ".markdown"}:
                        continue
                    try:
                        path_stat = entry.stat(follow_symlinks=False)
                    except OSError:
                        diagnostics.append(cls._source_diagnostic(path))
                        continue
                    if cls._is_link_or_reparse(path_stat) or not stat.S_ISREG(
                        path_stat.st_mode
                    ):
                        diagnostics.append(cls._source_diagnostic(path))
                        continue
                    files.append(path)
                    observed_bytes += max(0, path_stat.st_size)
                    if (
                        len(files) > MAX_REQUIREMENT_FILES
                        or observed_bytes > MAX_REQUIREMENTS_TOTAL_BYTES
                    ):
                        raise RequirementCollectionError(
                            "REQUIREMENTS_COLLECTION_LIMIT"
                        )
        except RequirementCollectionError:
            raise
        except OSError as exc:
            raise RequirementCollectionError(
                "REQUIREMENTS_COLLECTION_UNAVAILABLE"
            ) from exc
        files.sort(key=lambda path: (path.stem.casefold(), path.suffix.casefold(), path.name))
        return (
            files,
            requirements_dir,
            project_root,
            cls._ordered_diagnostics(diagnostics),
        )

    @staticmethod
    def _exposed_source(path: Path) -> str:
        """Return one neutral project-relative source label without path disclosure."""
        safe_name = sanitize_text(path.name).replace("\\", "/")
        if not safe_name or "/" in safe_name or safe_name in {".", ".."}:
            safe_name = "<unavailable>"
        return f".bck-nd/requirements/{safe_name}"

    @classmethod
    def _source_diagnostic(
        cls,
        path: Path,
        *,
        code: str = "REQUIREMENT_SOURCE_UNSAFE",
        message: str = "A requirement source could not be read safely.",
    ) -> RequirementLoadDiagnostic:
        return RequirementLoadDiagnostic(
            code=code,
            source=cls._exposed_source(path),
            message=message,
        )

    @staticmethod
    def _ordered_diagnostics(
        diagnostics: Iterable[RequirementLoadDiagnostic],
    ) -> Tuple[RequirementLoadDiagnostic, ...]:
        ordered = sorted(
            set(diagnostics),
            key=lambda item: (
                item.source.casefold(),
                item.source,
                item.code,
                item.message,
            ),
        )
        return tuple(ordered[:MAX_REQUIREMENT_FILES])

    @staticmethod
    def _collection_diagnostic(code: str) -> RequirementLoadDiagnostic:
        messages = {
            "REQUIREMENTS_COLLECTION_LIMIT": (
                "The requirements collection exceeds a safe resource limit."
            ),
            "REQUIREMENTS_DIRECTORY_ENTRY_LIMIT": (
                "The requirements directory exceeds the safe entry limit."
            ),
            "REQUIREMENTS_COLLECTION_UNAVAILABLE": (
                "The requirements collection could not be read safely."
            ),
        }
        return RequirementLoadDiagnostic(
            code=code,
            source=".bck-nd/requirements/",
            message=messages.get(
                code,
                "The requirements collection was rejected safely.",
            ),
        )

    @classmethod
    def _parse_verified_content(
        cls, path: Path, raw_content: bytes
    ) -> Optional[RequirementSpecification]:
        """Parse already verified bytes without reopening the source."""
        suffix = path.suffix.lower()
        if suffix == ".json":
            data = cls._validate_requirement_json_schema(
                cls._load_bounded_json(raw_content)
            )
            return RequirementSpecification.from_dict(data)
        if suffix in {".md", ".markdown"}:
            return cls.parse_markdown(
                raw_content.decode("utf-8"), default_id=path.stem
            )
        # Preserve the historical direct parse_file() fallback for callers that
        # explicitly pass an extension outside collection discovery.
        try:
            data = cls._validate_requirement_json_schema(
                cls._load_bounded_json(raw_content)
            )
            return RequirementSpecification.from_dict(data)
        except RequirementJsonError:
            content = raw_content.decode("utf-8")
            if content.lstrip().startswith(("{", "[")):
                raise
            return cls.parse_markdown(content, default_id=path.stem)

    @classmethod
    def parse_markdown(
        cls, content: str, default_id: str = ""
    ) -> Optional[RequirementSpecification]:
        """
        Parses a Markdown user story specification string into a RequirementSpecification.

        Supports standard headers and sections:
          # HU01 - Title (or # HU01: Title, or # HU01 [IN_PROGRESS] - Title)
          - **Role**: ...
          - **Want**: ...
          - **Benefit**: ...
          ## Business Rules
          - BR01: ...
          ## Acceptance Criteria
          - AC01: Given ... When ... Then ...
          ## Required Data
          - field: type
          ## Validations
          - field: rule
          ## Exceptions
          - code: description
          ## Open Questions
          - question
        """
        if not content or not content.strip():
            return None

        lines = content.strip().splitlines()
        if not lines:
            return None

        story_id = default_id
        title = ""
        status = "TODO"
        role = ""
        want = ""
        benefit = ""

        business_rules: List[BusinessRule] = []
        acceptance_criteria: List[AcceptanceCriteria] = []
        required_data: List[dict] = []
        validations: List[dict] = []
        exceptions: List[dict] = []
        open_questions: List[str] = []

        current_section: Optional[str] = None
        section_lines: Dict[str, List[str]] = {}

        # 1. Parse Title Header & Section lines
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            # Check level 1 header: # HU01 [STATUS] - Title
            if stripped.startswith("# ") and not stripped.startswith("## "):
                header_text = stripped[2:].strip()
                header_match = re.match(
                    r'^(?:(?P<id>[A-Za-z0-9_\-]+)\s*)?(?:\[(?P<status>[A-Za-z_]+)\]\s*)?[-:]?\s*(?P<title>.+)$',
                    header_text
                )
                if header_match:
                    h_id = header_match.group("id")
                    h_status = header_match.group("status")
                    h_title = header_match.group("title")

                    if h_id and re.match(r'^(?:HU|US|REQ|STORY)\d*$', h_id, re.IGNORECASE):
                        story_id = h_id
                    elif not title:
                        if h_id:
                            title = f"{h_id} {h_title}".strip() if h_title else h_id
                        else:
                            title = h_title.strip() if h_title else header_text
                    if h_title and not title:
                        title = h_title.strip()
                    if h_status:
                        status = h_status.upper()
                else:
                    title = header_text
                current_section = "header"
                continue

            # Check level 2 header: ## Section Name
            if stripped.startswith("## "):
                sec_title = stripped[3:].strip().lower()
                if "business rule" in sec_title or "reglas de negocio" in sec_title or "regla" in sec_title:
                    current_section = "business_rules"
                elif "acceptance" in sec_title or "aceptaci" in sec_title or "criterio" in sec_title:
                    current_section = "acceptance_criteria"
                elif "data" in sec_title or "dato" in sec_title:
                    current_section = "required_data"
                elif "validation" in sec_title or "validaci" in sec_title:
                    current_section = "validations"
                elif "exception" in sec_title or "excepci" in sec_title:
                    current_section = "exceptions"
                elif "question" in sec_title or "pregunta" in sec_title:
                    current_section = "open_questions"
                else:
                    current_section = sec_title
                section_lines.setdefault(current_section, [])
                continue

            if current_section:
                section_lines.setdefault(current_section, []).append(stripped)
            else:
                section_lines.setdefault("header", []).append(stripped)

        # 2. Parse User Story Key-Values from header section
        header_content = section_lines.get("header", [])
        for hline in header_content:
            clean = hline.lstrip("-* \t")

            # Role / As a / Como
            role_m = re.match(r'^\*{0,2}(?:Role|As a|Como)\*{0,2}\s*:\s*(.+)$', clean, re.IGNORECASE)
            if role_m:
                role = role_m.group(1).strip()
                continue

            # Want / I want / Quiero
            want_m = re.match(r'^\*{0,2}(?:Want|I want|Quiero|Deseo)\*{0,2}\s*:\s*(.+)$', clean, re.IGNORECASE)
            if want_m:
                want = want_m.group(1).strip()
                continue

            # Benefit / So that / Para / Para que
            benefit_m = re.match(r'^\*{0,2}(?:Benefit|So that|Para|Para que)\*{0,2}\s*:\s*(.+)$', clean, re.IGNORECASE)
            if benefit_m:
                benefit = benefit_m.group(1).strip()
                continue

            # Status / Estado
            status_m = re.match(r'^\*{0,2}(?:Status|Estado)\*{0,2}\s*:\s*(.+)$', clean, re.IGNORECASE)
            if status_m:
                status = status_m.group(1).strip().upper()
                continue

            # Story ID if specified as **ID**: HU01
            id_m = re.match(r'^\*{0,2}(?:ID|Story ID|Identificador)\*{0,2}\s*:\s*(.+)$', clean, re.IGNORECASE)
            if id_m:
                story_id = id_m.group(1).strip()
                continue

            # Title if specified as **Title**: ...
            title_m = re.match(r'^\*{0,2}(?:Title|Título|Titulo)\*{0,2}\s*:\s*(.+)$', clean, re.IGNORECASE)
            if title_m:
                title = title_m.group(1).strip()
                continue

        # 3. Parse Business Rules
        br_lines = section_lines.get("business_rules", [])
        for idx, bline in enumerate(br_lines, 1):
            clean = bline.lstrip("-* \t")
            if not clean:
                continue
            br_m = re.match(r'^(?:`|\*\*)?([A-Za-z0-9_\-]+)(?:`|\*\*)?\s*[-:]\s*(.+)$', clean)
            if br_m:
                br_id = br_m.group(1).strip()
                br_desc = br_m.group(2).strip()
                business_rules.append(BusinessRule(id=br_id, description=br_desc))
            else:
                business_rules.append(BusinessRule(id=f"BR{idx:02d}", description=clean))

        # 4. Parse Acceptance Criteria (Given-When-Then)
        ac_lines = section_lines.get("acceptance_criteria", [])
        for idx, aline in enumerate(ac_lines, 1):
            clean = aline.lstrip("-* \t")
            if not clean:
                continue

            # Extract ID if present (e.g. AC01: Given ... When ... Then ...)
            ac_id = f"AC{idx:02d}"
            gwt_text = clean
            ac_id_m = re.match(r'^(?:`|\*\*)?([A-Za-z0-9_\-]+)(?:`|\*\*)?\s*[-:]\s*(.+)$', clean)
            if ac_id_m:
                cand_id = ac_id_m.group(1).strip()
                if re.match(r'^(?:AC|CRIT|CA)\d*$', cand_id, re.IGNORECASE):
                    ac_id = cand_id
                    gwt_text = ac_id_m.group(2).strip()

            # Parse Given-When-Then parts (support English and Spanish keywords)
            gwt_m = re.search(
                r'(?:\*{0,2}(?:Given|Dado)\*{0,2})\s+(?P<given>.+?)\s+(?:\*{0,2}(?:When|Cuando)\*{0,2})\s+(?P<when>.+?)\s+(?:\*{0,2}(?:Then|Entonces)\*{0,2})\s+(?P<then>.+)$',
                gwt_text,
                re.IGNORECASE
            )
            if gwt_m:
                given_val = gwt_m.group("given").strip()
                when_val = gwt_m.group("when").strip()
                then_val = gwt_m.group("then").strip()
                acceptance_criteria.append(
                    AcceptanceCriteria(id=ac_id, given=given_val, when=when_val, then=then_val)
                )
            else:
                acceptance_criteria.append(
                    AcceptanceCriteria(id=ac_id, given=gwt_text, when="", then="")
                )

        # 5. Parse Required Data
        for dline in section_lines.get("required_data", []):
            clean = dline.lstrip("-* \t")
            if not clean:
                continue
            dm = re.match(r'^`?([A-Za-z0-9_$]+)`?\s*[-:]\s*(.+)$', clean)
            if dm:
                required_data.append({"field": dm.group(1).strip(), "type": dm.group(2).strip()})
            else:
                required_data.append({"field": clean, "type": "string"})

        # 6. Parse Validations
        for vline in section_lines.get("validations", []):
            clean = vline.lstrip("-* \t")
            if not clean:
                continue
            vm = re.match(r'^`?([A-Za-z0-9_$]+)`?\s*[-:]\s*(.+)$', clean)
            if vm:
                validations.append({"field": vm.group(1).strip(), "rule": vm.group(2).strip()})
            else:
                validations.append({"field": clean, "rule": "custom"})

        # 7. Parse Exceptions
        for eline in section_lines.get("exceptions", []):
            clean = eline.lstrip("-* \t")
            if not clean:
                continue
            em = re.match(r'^`?([A-Za-z0-9_$]+)`?\s*[-:]\s*(.+)$', clean)
            if em:
                exceptions.append({"code": em.group(1).strip(), "description": em.group(2).strip()})
            else:
                exceptions.append({"code": "EXCEPTION", "description": clean})

        # 8. Parse Open Questions
        for qline in section_lines.get("open_questions", []):
            clean = qline.lstrip("-* \t")
            if clean:
                open_questions.append(clean)

        story = UserStory(
            id=story_id or "STORY",
            title=title or "Untitled Story",
            role=role,
            want=want,
            benefit=benefit,
            status=status,
        )

        return RequirementSpecification(
            story=story,
            business_rules=business_rules,
            acceptance_criteria=acceptance_criteria,
            required_data=required_data,
            validations=validations,
            exceptions=exceptions,
            open_questions=open_questions,
        )

    @classmethod
    def parse_file(
        cls,
        file_path: Union[str, Path],
        *,
        requirements_directory: Optional[Union[str, Path]] = None,
        project_root: Optional[Union[str, Path]] = None,
    ) -> Optional[RequirementSpecification]:
        """
        Parses a single JSON or Markdown requirement specification file.

        Args:
            file_path: Path to the requirement JSON or MD file.

        Returns:
            RequirementSpecification instance if valid, or None if parsing fails.
        """
        path = Path(file_path)
        try:
            raw_content, _ = cls._read_verified_source(
                path,
                requirements_directory=requirements_directory,
                project_root=project_root,
            )
            return cls._parse_verified_content(path, raw_content)
        except (
            RequirementSourceError,
            RequirementJsonError,
            OSError,
            UnicodeDecodeError,
            ValueError,
            TypeError,
            AttributeError,
            RecursionError,
            MemoryError,
        ):
            logger.warning("Failed to parse a requirement file safely.")
            return None

    @classmethod
    def _requirements_directory(cls, project_path: Union[str, Path]) -> Path:
        return cls._requirements_context(project_path)[0]

    @classmethod
    def find_story_file(
        cls,
        project_path: Union[str, Path],
        story_id: str,
    ) -> Optional[Path]:
        """Find a story by filename or parsed ID using case-insensitive matching."""
        normalized_id = str(story_id).strip().casefold()
        if not normalized_id or not _VALID_STORY_ID.fullmatch(str(story_id).strip()):
            return None

        try:
            files, requirements_dir, project_root, _diagnostics = cls._safe_requirement_files(
                project_path
            )
        except RequirementSourceError:
            return None
        if requirements_dir is None or project_root is None:
            return None

        for path in files:
            if path.stem.casefold() == normalized_id:
                return path

        for path in files:
            spec = cls.parse_file(
                path,
                requirements_directory=requirements_dir,
                project_root=project_root,
            )
            if (
                spec is not None
                and spec.story is not None
                and str(spec.story.id).strip().casefold() == normalized_id
            ):
                return path
        return None

    @classmethod
    def get_story_status(
        cls,
        project_path: Union[str, Path],
        story_id: str,
    ) -> Optional[str]:
        """Return the persisted status for a story, or ``None`` when absent."""
        story_file = cls.find_story_file(project_path, story_id)
        if story_file is None:
            return None
        try:
            requirements_dir, project_root, _ = cls._requirements_context(project_path)
            raw_content, _ = cls._read_verified_source(
                story_file,
                requirements_directory=requirements_dir,
                project_root=project_root,
            )
            if story_file.suffix.lower() == ".json":
                data = cls._validate_requirement_json_schema(
                    cls._load_bounded_json(raw_content)
                )
                story = data.get("story")
                if isinstance(story, dict):
                    return str(story.get("status") or "TODO").strip().upper()
                return str(data.get("status") or "TODO").strip().upper()
            markdown_content = raw_content.decode("utf-8")
        except (
            RequirementSourceError,
            RequirementJsonError,
            UnicodeDecodeError,
            TypeError,
            AttributeError,
            RecursionError,
            MemoryError,
        ):
            return None
        spec = cls.parse_markdown(
            markdown_content, default_id=story_file.stem
        )
        if spec is None or spec.story is None:
            return None
        return str(spec.story.status or "TODO").strip().upper()

    @classmethod
    def _atomic_replace_requirement(
        cls,
        target: Path,
        replacement: bytes,
        original: bytes,
        original_stat: os.stat_result,
        *,
        requirements_directory: Path,
        project_root: Path,
    ) -> bool:
        temp_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_file.write(replacement)
                temp_file.flush()
                os.fsync(temp_file.fileno())
                temp_path = Path(temp_file.name)
            os.chmod(temp_path, stat.S_IMODE(original_stat.st_mode))
            current, current_stat = cls._read_verified_source(
                target,
                requirements_directory=requirements_directory,
                project_root=project_root,
            )
            if (
                current != original
                or cls._file_state(current_stat) != cls._file_state(original_stat)
            ):
                raise RequirementSourceError(
                    "Requirement source changed concurrently; update was aborted."
                )
            os.replace(temp_path, target)
            temp_path = None
            fsync_directory(target.parent)
            return True
        except (OSError, RequirementSourceError):
            return False
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    @classmethod
    def _update_story_status_locked(
        cls,
        project_path: Union[str, Path],
        story_id: str,
        new_status: str,
    ) -> bool:
        """Update one JSON or Markdown story status without rewriting other content."""
        normalized_status = str(new_status).strip().upper()
        normalized_id = str(story_id).strip().upper()
        if (
            normalized_status not in cls.VALID_STATUSES
            or not _VALID_STORY_ID.fullmatch(normalized_id)
        ):
            return False

        story_file = cls.find_story_file(project_path, normalized_id)
        if story_file is None:
            return False

        try:
            requirements_dir, project_root, _ = cls._requirements_context(project_path)
            raw_bytes, original_stat = cls._read_verified_source(
                story_file,
                requirements_directory=requirements_dir,
                project_root=project_root,
            )
            if story_file.suffix.lower() == ".json":
                data = cls._validate_requirement_json_schema(
                    cls._load_bounded_json(raw_bytes)
                )
                story = data.get("story")
                if isinstance(story, dict):
                    story["status"] = normalized_status
                else:
                    data["status"] = normalized_status
                replacement = (
                    json.dumps(data, ensure_ascii=False, indent=2) + "\n"
                ).encode("utf-8")
                return cls._atomic_replace_requirement(
                    story_file,
                    replacement,
                    raw_bytes,
                    original_stat,
                    requirements_directory=requirements_dir,
                    project_root=project_root,
                )

            raw_content = raw_bytes.decode("utf-8")
            content = raw_content
            bom = ""
            if content.startswith("\ufeff"):
                bom, content = "\ufeff", content[1:]

            header_pattern = re.compile(
                r"^(?P<prefix>[ \t]*#[ \t]+)(?P<body>[^\r\n]*)(?P<ending>\r?\n|$)",
                re.MULTILINE,
            )
            headers = list(header_pattern.finditer(content))
            target_header = None
            for header in headers:
                body = header.group("body")
                id_match = re.match(r"(?P<id>[A-Za-z0-9][A-Za-z0-9_-]*)", body)
                if id_match and id_match.group("id").casefold() == normalized_id.casefold():
                    target_header = header
                    break

            if target_header is not None:
                body = target_header.group("body")
                id_match = re.match(r"(?P<id>[A-Za-z0-9][A-Za-z0-9_-]*)(?P<rest>.*)", body)
                if id_match is None:
                    return False
                rest = re.sub(
                    r"^[ \t]*\[[A-Za-z_]+\]",
                    "",
                    id_match.group("rest"),
                    count=1,
                    flags=re.IGNORECASE,
                )
                replacement = (
                    f"{target_header.group('prefix')}{id_match.group('id')} "
                    f"[{normalized_status}]{rest}{target_header.group('ending')}"
                )
                content = (
                    content[:target_header.start()]
                    + replacement
                    + content[target_header.end():]
                )
            elif headers:
                header = headers[0]
                title = re.sub(
                    r"^\s*\[[A-Za-z_]+\]\s*[-:]?\s*",
                    "",
                    header.group("body"),
                    count=1,
                    flags=re.IGNORECASE,
                ).strip()
                title_suffix = f" - {title}" if title else ""
                replacement = (
                    f"{header.group('prefix')}{normalized_id} [{normalized_status}]"
                    f"{title_suffix}{header.group('ending')}"
                )
                content = content[:header.start()] + replacement + content[header.end():]
            else:
                newline = "\r\n" if "\r\n" in content else "\n"
                content = (
                    f"# {normalized_id} [{normalized_status}]{newline}{newline}{content}"
                )

            return cls._atomic_replace_requirement(
                story_file,
                (bom + content).encode("utf-8"),
                raw_bytes,
                original_stat,
                requirements_directory=requirements_dir,
                project_root=project_root,
            )
        except (
            RequirementSourceError,
            RequirementJsonError,
            OSError,
            UnicodeDecodeError,
            ValueError,
            TypeError,
            AttributeError,
            RecursionError,
            MemoryError,
        ):
            logger.warning("Failed to update a requirement status safely.")
            return False

    @classmethod
    def update_story_status(
        cls,
        project_path: Union[str, Path],
        story_id: str,
        new_status: str,
    ) -> bool:
        """Update status while serializing cooperative Backend Helper writers."""
        normalized_status = str(new_status).strip().upper()
        normalized_id = str(story_id).strip().upper()
        if (
            normalized_status not in cls.VALID_STATUSES
            or not _VALID_STORY_ID.fullmatch(normalized_id)
        ):
            return False

        try:
            verified = cls._verified_requirements_directory(project_path)
            if verified is None:
                return False
            requirements_dir, _project_root, _stats = verified
            with exclusive_file_lock(
                _requirements_status_lock_path(requirements_dir),
                timeout=REQUIREMENTS_STATUS_LOCK_TIMEOUT,
            ):
                return cls._update_story_status_locked(
                    project_path,
                    normalized_id,
                    normalized_status,
                )
        except (FileLockError, RequirementSourceError, OSError):
            return False

    @classmethod
    def load_from_directory(
        cls, project_path: Union[str, Path]
    ) -> List[RequirementSpecification]:
        """
        Reads and parses all .json and .md requirement files located under
        '<project_path>/.bck-nd/requirements/'.

        Args:
            project_path: Root path of the project.

        Returns:
            List of successfully parsed RequirementSpecification objects.
            Returns an empty list if directory is missing or unreadable.
        """
        return list(cls.load_collection(project_path).specifications)

    @classmethod
    def load_collection(
        cls, project_path: Union[str, Path]
    ) -> RequirementsLoadResult:
        """Load one bounded collection and distinguish absence from rejection."""
        try:
            files, req_dir, project_root, scan_diagnostics = cls._safe_requirement_files(
                project_path
            )
            if req_dir is None or project_root is None:
                return RequirementsLoadResult()

            specs: List[RequirementSpecification] = []
            diagnostics = list(scan_diagnostics)
            seen_ids = set()
            actual_bytes = 0
            for file_path in files:
                try:
                    raw_content, _ = cls._read_verified_source(
                        file_path,
                        requirements_directory=req_dir,
                        project_root=project_root,
                    )
                except RequirementSourceError:
                    diagnostics.append(cls._source_diagnostic(file_path))
                    continue
                actual_bytes += len(raw_content)
                if actual_bytes > MAX_REQUIREMENTS_TOTAL_BYTES:
                    raise RequirementCollectionError(
                        "REQUIREMENTS_COLLECTION_LIMIT"
                    )
                try:
                    spec = cls._parse_verified_content(file_path, raw_content)
                except RequirementJsonError as exc:
                    diagnostics.append(
                        cls._source_diagnostic(
                            file_path,
                            code=exc.code,
                            message=(
                                "A requirement source contains invalid or unsafe JSON."
                                if exc.code != "REQUIREMENT_SCHEMA_INVALID"
                                else "A requirement source has an incompatible schema."
                            ),
                        )
                    )
                    continue
                except UnicodeDecodeError:
                    diagnostics.append(
                        cls._source_diagnostic(
                            file_path,
                            code="REQUIREMENT_SOURCE_INVALID_UTF8",
                            message="A requirement source is not valid UTF-8.",
                        )
                    )
                    continue
                except (
                    ValueError,
                    TypeError,
                    AttributeError,
                    RecursionError,
                    MemoryError,
                ):
                    diagnostics.append(
                        cls._source_diagnostic(
                            file_path,
                            code="REQUIREMENT_SCHEMA_INVALID",
                            message="A requirement source has an incompatible schema.",
                        )
                    )
                    continue
                if spec is not None and spec.story:
                    spec_id = str(spec.story.id or file_path.stem)
                    normalized_id = spec_id.casefold()
                    if normalized_id not in seen_ids:
                        specs.append(spec)
                        seen_ids.add(normalized_id)
                else:
                    diagnostics.append(
                        cls._source_diagnostic(
                            file_path,
                            code="REQUIREMENT_SCHEMA_INVALID",
                            message="A requirement source has an incompatible schema.",
                        )
                    )

            ordered_diagnostics = cls._ordered_diagnostics(diagnostics)
            if ordered_diagnostics:
                return RequirementsLoadResult(
                    rejected=True,
                    error_code=ordered_diagnostics[0].code,
                    diagnostics=ordered_diagnostics,
                )
            return RequirementsLoadResult(tuple(specs))
        except RequirementCollectionError as exc:
            logger.warning("Requirements collection was rejected safely.")
            diagnostic = cls._collection_diagnostic(exc.code)
            return RequirementsLoadResult(
                rejected=True,
                error_code=exc.code,
                diagnostics=(diagnostic,),
            )
        except (
            RequirementSourceError,
            OSError,
            RuntimeError,
            TypeError,
            AttributeError,
            RecursionError,
            MemoryError,
        ):
            logger.warning("Requirements collection was unavailable safely.")
            code = "REQUIREMENTS_COLLECTION_UNAVAILABLE"
            diagnostic = cls._collection_diagnostic(code)
            return RequirementsLoadResult(
                rejected=True,
                error_code=code,
                diagnostics=(diagnostic,),
            )
