#!/usr/bin/env python
import os
import sys

if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# Add the 'src' directory to sys.path to resolve bck_nd_hlpr package imports correctly
src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "src"))
sys.path.insert(0, src_path)

if __name__ == "__main__":
    try:
        from bck_nd_hlpr.mcp_server import main
        main()
    except ImportError as e:
        print(f"Error starting MCP Server: {e}", file=sys.stderr)
        print("Please ensure that you have installed the required dependencies by running:\n", file=sys.stderr)
        print("    pip install -e .\n", file=sys.stderr)
        sys.exit(1)
