import os
from pathlib import Path
import typer

GITHUB_ACTION_YAML = """name: Generate Documentation

on:
  push:
    branches:
      - main
  workflow_dispatch:

permissions:
  contents: write

jobs:
  docs:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
          # Install bck-nd-hlpr
          if [ -f pyproject.toml ] && grep -q "name = \\"bck-nd-hlpr\\"" pyproject.toml; then
            pip install .
          else
            pip install bck-nd-hlpr
          fi

      - name: Run Backend Helper Scan (generate HTML with embedded Mermaid)
        run: |
          bck-nd docs . -o docs

      - name: Deploy to GitHub Pages
        uses: peaceiris/actions-gh-pages@v3
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: docs
"""

def generate_ci_workflow(root_path: str = "."):
    """
    Generates the GitHub Action workflow file for auto-documentation.
    """
    workflows_dir = Path(root_path) / ".github" / "workflows"
    workflow_file = workflows_dir / "documentation.yml"

    # Create directories if they don't exist
    workflows_dir.mkdir(parents=True, exist_ok=True)

    # Write the YAML content
    with open(workflow_file, "w", encoding="utf-8") as f:
        f.write(GITHUB_ACTION_YAML)

    return workflow_file
