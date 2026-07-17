import os
from pathlib import Path

GITHUB_ACTION_YAML = """name: Deploy Documentation to GitHub Pages

# Living Documentation: builds the HTML portal with `bck-nd docs`
# and deploys it to GitHub Pages ONLY on pushes to `main`.
# Feature branches are never deployed: developers preview locally
# with `bck-nd docs .` and compare against the published main version.
on:
  push:
    branches:
      - main

# Least-privilege OIDC permissions for the official Pages deployment flow.
# `contents: read` is enough because we deploy via artifact upload
# (actions/deploy-pages), NOT by pushing to a gh-pages branch.
permissions:
  contents: read
  pages: write
  id-token: write

# Only one Pages deployment at a time; cancel stale in-flight runs.
concurrency:
  group: "pages"
  cancel-in-progress: true

jobs:
  docs:
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deploy.outputs.page_url }}
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          # Install bck-nd-hlpr (from source if this repo IS the tool, else from PyPI)
          if [ -f pyproject.toml ] && grep -q 'name = "bck-nd-hlpr"' pyproject.toml; then
            pip install .
          else
            pip install bck-nd-hlpr
          fi

      - name: Verify installation
        run: |
          echo "=== Checking pip show ==="
          pip show bck-nd-hlpr
          echo ""
          echo "=== Checking module import ==="
          python -c "import bck_nd_hlpr; print('Module imported successfully')"
          echo ""
          echo "=== Checking CLI module ==="
          python -c "from bck_nd_hlpr.cli import app; print('CLI module OK')"

      - name: Generate static documentation
        run: |
          mkdir -p docs
          bck-nd docs . --output docs
        shell: bash

      - name: Create .nojekyll
        run: |
          touch docs/.nojekyll
          echo "Created .nojekyll"

      - name: Diagnostic - verify docs output
        run: |
          echo "=== Checking docs directory ==="
          ls -la docs/
          echo ""
          echo "=== Verifying index.html exists ==="
          if [ -f docs/index.html ]; then
            echo "docs/index.html found ($(wc -c < docs/index.html) bytes)"
          else
            echo "docs/index.html NOT FOUND - build failed!"
            exit 1
          fi
          echo ""
          echo "=== Verifying .nojekyll exists ==="
          if [ -f docs/.nojekyll ]; then
            echo "docs/.nojekyll found"
          else
            echo "docs/.nojekyll NOT FOUND"
            exit 1
          fi

      - name: Upload Pages artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: ./docs

      - name: Deploy to GitHub Pages
        id: deploy
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