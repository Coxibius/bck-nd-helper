import os
from pathlib import Path
import typer

GITHUB_ACTION_YAML = """name: Generate Documentation

# Living Documentation: builds the HTML portal with `bck-nd docs`
# and deploys it to GitHub Pages ONLY on pushes to `main`.
# Feature branches are never deployed: developers preview locally
# with `bck-nd docs .` and compare against the published main version.
on:
  push:
    branches:
      - main

# Least-privilege permissions for the official Pages deployment flow.
# `contents: read` is enough because we deploy via OIDC artifact upload
# (actions/deploy-pages), NOT by pushing to a gh-pages branch.
permissions:
  contents: read
  pages: write
  id-token: write

# Never cancel an in-flight production deployment, but queue new ones.
concurrency:
  group: "pages"
  cancel-in-progress: false

jobs:
  build:
    name: Build Documentation
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      # Cache pip downloads. Keyed on dependency manifests with a
      # restore-keys fallback so the cache still hits on partial changes
      # and never fails on projects without requirements/pyproject files.
      - name: Cache pip dependencies
        uses: actions/cache@v4
        with:
          path: ~/.cache/pip
          key: ${{ runner.os }}-pip-${{ hashFiles('**/requirements*.txt', '**/pyproject.toml') }}
          restore-keys: |
            ${{ runner.os }}-pip-

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
          # Install bck-nd-hlpr (from source if this repo IS the tool, else from PyPI)
          if [ -f pyproject.toml ] && grep -q 'name = "bck-nd-hlpr"' pyproject.toml; then
            pip install .
          else
            pip install bck-nd-hlpr
          fi

      - name: Generate documentation portal
        run: |
          bck-nd docs . --output _site

      - name: Setup GitHub Pages
        uses: actions/configure-pages@v5

      - name: Upload Pages artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: _site

  deploy:
    name: Deploy to GitHub Pages
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
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