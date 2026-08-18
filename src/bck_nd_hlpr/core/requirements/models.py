"""
Requirements Domain Models — Data structures representing User Stories,
Acceptance Criteria, Business Rules, and Requirement Specifications.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class UserStory:
    """Represents an agile User Story."""
    id: str
    title: str
    role: str
    want: str
    benefit: str
    status: str = "TODO"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "role": self.role,
            "want": self.want,
            "benefit": self.benefit,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserStory":
        return cls(
            id=data.get("id", ""),
            title=data.get("title", ""),
            role=data.get("role", ""),
            want=data.get("want", ""),
            benefit=data.get("benefit", ""),
            status=data.get("status", "TODO"),
        )


@dataclass
class AcceptanceCriteria:
    """Represents a Given-When-Then acceptance criterion scenario."""
    id: str
    given: str
    when: str
    then: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "given": self.given,
            "when": self.when,
            "then": self.then,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AcceptanceCriteria":
        return cls(
            id=data.get("id", ""),
            given=data.get("given", ""),
            when=data.get("when", ""),
            then=data.get("then", ""),
        )


@dataclass
class BusinessRule:
    """Represents a discrete domain or business rule."""
    id: str
    description: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BusinessRule":
        return cls(
            id=data.get("id", ""),
            description=data.get("description", ""),
        )


@dataclass
class RequirementSpecification:
    """
    Comprehensive specification bundling a User Story with its Acceptance Criteria,
    Business Rules, Data dictionary, Validations, Exceptions, and Open Questions.
    """
    story: UserStory
    business_rules: List[BusinessRule] = field(default_factory=list)
    acceptance_criteria: List[AcceptanceCriteria] = field(default_factory=list)
    required_data: List[Dict[str, Any]] = field(default_factory=list)
    validations: List[Dict[str, Any]] = field(default_factory=list)
    exceptions: List[Dict[str, Any]] = field(default_factory=list)
    open_questions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "story": self.story.to_dict() if self.story else {},
            "business_rules": [br.to_dict() for br in self.business_rules],
            "acceptance_criteria": [ac.to_dict() for ac in self.acceptance_criteria],
            "required_data": [dict(d) for d in self.required_data],
            "validations": [dict(v) for v in self.validations],
            "exceptions": [dict(e) for e in self.exceptions],
            "open_questions": list(self.open_questions),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RequirementSpecification":
        story_data = data.get("story")
        if isinstance(story_data, dict):
            story = UserStory.from_dict(story_data)
        elif isinstance(story_data, UserStory):
            story = story_data
        elif any(k in data for k in ("id", "title", "role", "want", "benefit")):
            story = UserStory.from_dict(data)
        else:
            story = UserStory(id="", title="", role="", want="", benefit="")

        business_rules = [
            br if isinstance(br, BusinessRule) else BusinessRule.from_dict(br)
            for br in data.get("business_rules", [])
            if isinstance(br, (dict, BusinessRule))
        ]
        acceptance_criteria = [
            ac if isinstance(ac, AcceptanceCriteria) else AcceptanceCriteria.from_dict(ac)
            for ac in data.get("acceptance_criteria", [])
            if isinstance(ac, (dict, AcceptanceCriteria))
        ]
        required_data = [
            dict(item) for item in data.get("required_data", []) if isinstance(item, dict)
        ]
        validations = [
            dict(item) for item in data.get("validations", []) if isinstance(item, dict)
        ]
        exceptions = [
            dict(item) for item in data.get("exceptions", []) if isinstance(item, dict)
        ]
        open_questions = [
            str(q) for q in data.get("open_questions", [])
        ]

        return cls(
            story=story,
            business_rules=business_rules,
            acceptance_criteria=acceptance_criteria,
            required_data=required_data,
            validations=validations,
            exceptions=exceptions,
            open_questions=open_questions,
        )
