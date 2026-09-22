"""Requirements domain model contracts and round trips."""

from bck_nd_hlpr.core.requirements import (
    AcceptanceCriteria,
    BusinessRule,
    RequirementSpecification,
    UserStory,
)

def test_user_story_model():
    story = UserStory(
        id="HU01",
        title="Registrar cliente",
        role="Agente de campo",
        want="Registrar un nuevo cliente",
        benefit="Contar con información centralizada",
        status="IN_PROGRESS",
    )
    data = story.to_dict()
    assert data["id"] == "HU01"
    assert data["title"] == "Registrar cliente"
    assert data["role"] == "Agente de campo"
    assert data["want"] == "Registrar un nuevo cliente"
    assert data["benefit"] == "Contar con información centralizada"
    assert data["status"] == "IN_PROGRESS"

    restored = UserStory.from_dict(data)
    assert restored.id == "HU01"
    assert restored.title == "Registrar cliente"
    assert restored.role == "Agente de campo"
    assert restored.want == "Registrar un nuevo cliente"
    assert restored.benefit == "Contar con información centralizada"
    assert restored.status == "IN_PROGRESS"


def test_user_story_defaults():
    story = UserStory(
        id="HU02",
        title="Consultar cliente",
        role="Usuario",
        want="Ver perfil",
        benefit="Visualizar datos",
    )
    assert story.status == "TODO"

    story_from_empty = UserStory.from_dict({})
    assert story_from_empty.id == ""
    assert story_from_empty.status == "TODO"


def test_acceptance_criteria_model():
    ac = AcceptanceCriteria(
        id="AC01",
        given="un cliente no registrado",
        when="se envían datos válidos",
        then="se crea el registro en la base de datos",
    )
    data = ac.to_dict()
    assert data == {
        "id": "AC01",
        "given": "un cliente no registrado",
        "when": "se envían datos válidos",
        "then": "se crea el registro en la base de datos",
    }
    restored = AcceptanceCriteria.from_dict(data)
    assert restored.id == "AC01"
    assert restored.given == "un cliente no registrado"
    assert restored.when == "se envían datos válidos"
    assert restored.then == "se crea el registro en la base de datos"


def test_business_rule_model():
    br = BusinessRule(
        id="BR01",
        description="El documento de identidad debe ser único y obligatorio.",
    )
    data = br.to_dict()
    assert data == {
        "id": "BR01",
        "description": "El documento de identidad debe ser único y obligatorio.",
    }
    restored = BusinessRule.from_dict(data)
    assert restored.id == "BR01"
    assert restored.description == "El documento de identidad debe ser único y obligatorio."


def test_requirement_specification_roundtrip():
    spec = RequirementSpecification(
        story=UserStory(
            id="HU01",
            title="Registrar cliente",
            role="Agente de campo",
            want="Registrar un nuevo cliente",
            benefit="Contar con información centralizada",
            status="TODO",
        ),
        business_rules=[
            BusinessRule(id="BR01", description="Documento obligatorio"),
            BusinessRule(id="BR02", description="Email válido"),
        ],
        acceptance_criteria=[
            AcceptanceCriteria(
                id="AC01",
                given="formulario completo",
                when="se hace submit",
                then="retorna HTTP 201",
            )
        ],
        required_data=[{"name": "dni", "type": "string", "required": True}],
        validations=[{"field": "email", "rule": "regex"}],
        exceptions=[{"code": 409, "condition": "DNI ya existente"}],
        open_questions=["¿Se permite registro sin correo electrónico?"],
    )

    data = spec.to_dict()
    assert data["story"]["id"] == "HU01"
    assert len(data["business_rules"]) == 2
    assert len(data["acceptance_criteria"]) == 1
    assert data["required_data"][0]["name"] == "dni"
    assert data["validations"][0]["field"] == "email"
    assert data["exceptions"][0]["code"] == 409
    assert data["open_questions"] == ["¿Se permite registro sin correo electrónico?"]

    restored = RequirementSpecification.from_dict(data)
    assert restored.story.id == "HU01"
    assert restored.story.title == "Registrar cliente"
    assert len(restored.business_rules) == 2
    assert restored.business_rules[0].id == "BR01"
    assert restored.business_rules[1].id == "BR02"
    assert len(restored.acceptance_criteria) == 1
    assert restored.acceptance_criteria[0].id == "AC01"
    assert restored.required_data == [{"name": "dni", "type": "string", "required": True}]
    assert restored.validations == [{"field": "email", "rule": "regex"}]
    assert restored.exceptions == [{"code": 409, "condition": "DNI ya existente"}]
    assert restored.open_questions == ["¿Se permite registro sin correo electrónico?"]
