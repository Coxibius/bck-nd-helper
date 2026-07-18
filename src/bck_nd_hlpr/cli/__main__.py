"""Allow `python -m bck_nd_hlpr.cli` as a fallback to the `bck-nd` entry point."""
from bck_nd_hlpr.cli.cli import app

if __name__ == "__main__":
    app()
