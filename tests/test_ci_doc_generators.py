import os
from pathlib import Path
from bck_nd_hlpr.ci_generator import generate_ci_workflow
from bck_nd_hlpr.doc_generator import DocGenerator

def test_generate_ci_workflow(tmp_path):
    # Call generate_ci_workflow with tmp_path
    workflow_file = generate_ci_workflow(str(tmp_path))
    
    # Assert correct path and file existence
    expected_path = tmp_path / ".github" / "workflows" / "bck-nd-docs.yml"
    assert workflow_file == expected_path
    assert expected_path.exists()
    
    # Verify content
    content = expected_path.read_text(encoding="utf-8")
    assert "name: Deploy Documentation to GitHub Pages" in content
    assert "push:" in content
    assert "main" in content
    assert "workflow_dispatch" in content
    assert "bck-nd docs ." in content
    assert "documentation.yml" not in content

    gitignore = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "!.bck-nd/" in gitignore
    assert ".bck-nd/cache/" in gitignore
    assert "!.bck-nd/requirements/" in gitignore
    assert "!.bck-nd/requirements/**" in gitignore

def test_doc_generator_basic(tmp_path):
    # Set up a dummy project structure under tmp_path
    project_dir = tmp_path / "my_project"
    project_dir.mkdir()
    
    # Create a dummy python file to trigger scanner structure
    dummy_py = project_dir / "app.py"
    dummy_py.write_text("class MyService:\n    def run(self):\n        pass\n", encoding="utf-8")
    
    # Create docker-compose.yml
    docker_yml = project_dir / "docker-compose.yml"
    docker_yml.write_text("version: '3'\nservices:\n  web:\n    image: nginx\n", encoding="utf-8")
    
    # Generate documentation
    output_dir = tmp_path / "docs_out"
    generator = DocGenerator()
    out_file = generator.generate(str(project_dir), str(output_dir))
    
    # Assert file was generated
    assert out_file is not None
    assert Path(out_file).exists()
    assert Path(out_file).name == "index.html"
    
    # Verify HTML content has placeholders replaced
    html_content = Path(out_file).read_text(encoding="utf-8")
    assert "<title>Project Documentation</title>" in html_content
    assert "MyService" in html_content
    assert "nginx" in html_content
    assert 'id="copy-ai-context-btn"' in html_content
    assert 'id="ai-context-content"' in html_content
    assert "Copy Complete AI Context to Clipboard" in html_content
    assert "&lt;project_tree&gt;" in html_content or "<project_tree>" in html_content
    assert "navigator.clipboard.writeText" in html_content
    assert 'data-renderer="offline-svg"' in html_content
    assert "https://cdn.jsdelivr.net" not in html_content
    assert "fonts.googleapis.com" not in html_content


def test_doc_generator_includes_requirements_in_offline_dashboard(tmp_path):
    project_dir = tmp_path / "requirements_project"
    project_dir.mkdir()
    (project_dir / "app.py").write_text("class Checkout: pass\n", encoding="utf-8")
    requirements_dir = project_dir / ".bck-nd" / "requirements"
    requirements_dir.mkdir(parents=True)
    (requirements_dir / "US-009.json").write_text(
        """{
  "story": {
    "id": "US-009",
    "title": "Offline checkout <script>alert(1)</script>",
    "role": "buyer",
    "want": "complete checkout",
    "benefit": "purchase offline",
    "status": "TESTING"
  },
  "acceptance_criteria": [
    {"id": "AC01", "given": "offline", "when": "opened", "then": "content renders"}
  ]
}
""",
        encoding="utf-8",
    )

    out_file = DocGenerator().generate(
        str(project_dir),
        str(tmp_path / "offline_docs"),
    )
    content = Path(out_file).read_text(encoding="utf-8")

    assert 'id="requirements"' in content
    assert 'href="#requirements"' in content
    assert "US-009" in content
    assert "TESTING" in content
    assert "Offline checkout &lt;script&gt;alert(1)&lt;/script&gt;" in content
    assert "https://" not in content
