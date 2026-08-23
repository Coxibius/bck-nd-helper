"""
Requirements Parser — Loads and parses User Story and Requirement specifications
from the .bck-nd/requirements/ directory (supporting both JSON and Markdown).
"""

import json
import logging
import re
from pathlib import Path
from typing import List, Optional, Union, Dict, Any

from .models import AcceptanceCriteria, BusinessRule, RequirementSpecification, UserStory

logger = logging.getLogger(__name__)

VALID_STORY_STATUSES = frozenset(
    {"TODO", "IN_PROGRESS", "TESTING", "DONE", "BLOCKED"}
)
_VALID_STORY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class RequirementsParser:
    """Parses requirement JSON and Markdown specification files from the project workspace."""

    VALID_STATUSES = VALID_STORY_STATUSES

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
    def parse_file(cls, file_path: Union[str, Path]) -> Optional[RequirementSpecification]:
        """
        Parses a single JSON or Markdown requirement specification file.

        Args:
            file_path: Path to the requirement JSON or MD file.

        Returns:
            RequirementSpecification instance if valid, or None if parsing fails.
        """
        path = Path(file_path)
        try:
            if not path.is_file():
                return None
            content = path.read_text(encoding="utf-8")
            if path.suffix.lower() == ".json":
                data = json.loads(content)
                if not isinstance(data, dict):
                    logger.warning("Requirement file '%s' does not contain a JSON object.", path)
                    return None
                return RequirementSpecification.from_dict(data)
            elif path.suffix.lower() in (".md", ".markdown"):
                return cls.parse_markdown(content, default_id=path.stem)
            else:
                try:
                    data = json.loads(content)
                    if isinstance(data, dict):
                        return RequirementSpecification.from_dict(data)
                except Exception:
                    pass
                return cls.parse_markdown(content, default_id=path.stem)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError, ValueError) as exc:
            logger.warning("Failed to parse requirement file '%s': %s", path, exc)
            return None

    @classmethod
    def _requirements_directory(cls, project_path: Union[str, Path]) -> Path:
        base_path = Path(project_path)
        if base_path.name == "requirements" and base_path.is_dir():
            return base_path
        return base_path / ".bck-nd" / "requirements"

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

        requirements_dir = cls._requirements_directory(project_path)
        if not requirements_dir.is_dir():
            return None

        files = sorted(
            (
                path
                for path in requirements_dir.iterdir()
                if path.is_file()
                and path.suffix.lower() in {".json", ".md", ".markdown"}
            ),
            key=lambda path: (path.stem.casefold(), path.suffix.casefold()),
        )

        for path in files:
            if path.stem.casefold() == normalized_id:
                return path

        for path in files:
            spec = cls.parse_file(path)
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
        if story_file.suffix.lower() == ".json":
            try:
                data = json.loads(story_file.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    return None
                story = data.get("story")
                if isinstance(story, dict):
                    return str(story.get("status") or "TODO").strip().upper()
                return str(data.get("status") or "TODO").strip().upper()
            except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                return None
        spec = cls.parse_file(story_file)
        if spec is None or spec.story is None:
            return None
        return str(spec.story.status or "TODO").strip().upper()

    @classmethod
    def update_story_status(
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
            if story_file.suffix.lower() == ".json":
                data = json.loads(story_file.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    return False
                story = data.get("story")
                if isinstance(story, dict):
                    story["status"] = normalized_status
                else:
                    data["status"] = normalized_status
                story_file.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                return True

            raw_content = story_file.read_bytes().decode("utf-8")
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

            story_file.write_bytes((bom + content).encode("utf-8"))
            return True
        except (json.JSONDecodeError, OSError, UnicodeDecodeError, ValueError) as exc:
            logger.warning(
                "Failed to update requirement status in '%s': %s",
                story_file,
                exc,
            )
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
        try:
            req_dir = cls._requirements_directory(project_path)

            if not req_dir.exists() or not req_dir.is_dir():
                return []

            specs: List[RequirementSpecification] = []
            seen_ids: set = set()
            files = sorted(
                list(req_dir.glob("*.json")) + list(req_dir.glob("*.md")) + list(req_dir.glob("*.markdown")),
                key=lambda p: (p.stem, p.suffix)
            )
            for file_path in files:
                spec = cls.parse_file(file_path)
                if spec is not None and spec.story:
                    spec_id = spec.story.id or file_path.stem
                    if spec_id not in seen_ids:
                        specs.append(spec)
                        seen_ids.add(spec_id)

            return specs
        except Exception as exc:
            logger.warning("Error loading requirements from '%s': %s", project_path, exc)
            return []
