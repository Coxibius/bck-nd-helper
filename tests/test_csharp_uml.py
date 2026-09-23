"""C# UML fidelity regressions using the real Tree-sitter parser."""

import pytest

from bck_nd_hlpr.core.asg.builder import ASGBuilder
from bck_nd_hlpr.core.asg.renderers import ASGToMermaidRenderer
from bck_nd_hlpr.core.csharp_parser import parse_project_for_csharp_uml
from bck_nd_hlpr.core.uml_parser import generate_mermaid_class_diagram


CSHARP_SOURCE = """
namespace University.Structures;

public interface IBase<T>
{
}

public class Resultado
{
}

public interface IArbolGeneral<T> : IBase<T>
{
    int Cantidad { get; }
    T ObtenerValor();
    T Obtener(int indice);
    Resultado Crear();
    Resultado Buscar(string clave);
    void Reiniciar();
    int Contar();
    IReadOnlyList<Resultado> Listar(string filtro);
}

public sealed class ArbolGeneral<T>
{
}

public record Nodo(int Id);
"""


@pytest.fixture(scope="module")
def csharp_classes(tmp_path_factory):
    project = tmp_path_factory.mktemp("csharp-uml-fidelity")
    (project / "Structures.cs").write_text(CSHARP_SOURCE, encoding="utf-8")
    classes = parse_project_for_csharp_uml(str(project), max_depth=None)
    return {item.name: item for item in classes}, classes


def _class_body(diagram: str, class_name: str) -> list[str]:
    lines = diagram.splitlines()
    declaration = f"class {class_name} {{"
    start = next(index for index, line in enumerate(lines) if line.strip() == declaration)
    body = []
    for line in lines[start + 1:]:
        if line.strip() == "}":
            return body
        body.append(line.strip())
    raise AssertionError(f"Unclosed Mermaid declaration for {class_name}")


@pytest.mark.parametrize(
    "expected_signature",
    [
        "ObtenerValor()",
        "Obtener(int indice)",
        "Crear()",
        "Buscar(string clave)",
        "Reiniciar()",
        "Contar()",
        "Listar(string filtro)",
    ],
)
def test_csharp_method_name_comes_from_semantic_name_field(
    csharp_classes, expected_signature
):
    classes, _all_classes = csharp_classes

    assert expected_signature in classes["IArbolGeneral"].methods


def test_csharp_interface_class_and_record_keep_their_classification(csharp_classes):
    classes, _all_classes = csharp_classes

    interface = classes["IArbolGeneral"]
    assert interface.is_interface is True
    assert interface.attributes == ["int Cantidad"]
    assert interface.bases == ["IBase<T>"]
    assert interface.module == "University.Structures"
    assert classes["ArbolGeneral"].is_interface is False
    assert classes["Resultado"].is_interface is False
    assert classes["Nodo"].is_interface is False


def test_csharp_mermaid_contains_correct_method_declarations(csharp_classes):
    _classes, all_classes = csharp_classes

    diagram = generate_mermaid_class_diagram(all_classes)
    interface_body = _class_body(diagram, "IArbolGeneral")

    assert "+ObtenerValor()" in interface_body
    assert "+Obtener(int indice)" in interface_body
    assert "+Crear()" in interface_body
    assert "+Buscar(string clave)" in interface_body
    assert "+T()" not in interface_body
    assert "+T(int indice)" not in interface_body
    assert "+Resultado()" not in interface_body
    assert "+Resultado(string clave)" not in interface_body


def test_existing_asg_mermaid_consumer_marks_csharp_interface(csharp_classes):
    _classes, all_classes = csharp_classes

    graph = ASGBuilder.from_uml_classes(all_classes)
    diagram = ASGToMermaidRenderer.render_uml(graph)

    assert "<<interface>>" in _class_body(diagram, "IArbolGeneral")
    assert "<<interface>>" not in _class_body(diagram, "ArbolGeneral")
    assert "<<interface>>" not in _class_body(diagram, "Nodo")
