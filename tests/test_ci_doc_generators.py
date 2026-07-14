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
    assert "name: Generate Documentation" in content
    assert "push:" in content
    assert "main" in content
    assert "workflow_dispatch" not in content
    assert "bck-nd docs ." in content
    assert "documentation.yml" not in content

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
