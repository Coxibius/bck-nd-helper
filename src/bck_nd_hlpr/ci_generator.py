import os
from pathlib import Path
import typer

GITHUB_ACTION_YAML = """name: 🚀 Auto-Documentation (bck-nd-hlpr)

on:
  push:
    branches:
      - main
  workflow_dispatch:

permissions:
  contents: write

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    steps:
      - name: 📥 Checkout Code
        uses: actions/checkout@v4

      - name: 🐍 Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: 📦 Install Backend Helper
        run: |
          python -m pip install --upgrade pip
          # Check if we are running inside the bck-nd-hlpr repo itself
          if [ -f pyproject.toml ] && grep -q "name = \\"bck-nd-hlpr\\"" pyproject.toml; then
            echo "Installing from local source..."
            pip install .
          else
            echo "Installing from PyPI..."
            pip install bck-nd-hlpr
          fi

      - name: 🛠️ Generate Documentation (UML, ER, Infra, Routes)
        run: |
          bck-nd docs . -o docs-output

      - name: 🚀 Deploy to GitHub Pages
        uses: peaceiris/actions-gh-pages@v3
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: ./docs-output
          commit_message: "docs: update living documentation 🤖"
"""

def generate_ci_workflow(root_path: str = "."):
    """
    Generates the GitHub Action workflow file for auto-documentation.
    """
    workflows_dir = Path(root_path) / ".github" / "workflows"
    workflow_file = workflows_dir / "bck-nd-docs.yml"

    # Create directories if they don't exist
    workflows_dir.mkdir(parents=True, exist_ok=True)

    # Write the YAML content
    with open(workflow_file, "w", encoding="utf-8") as f:
        f.write(GITHUB_ACTION_YAML)

    return workflow_file
