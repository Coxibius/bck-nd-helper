
# Advanced Configuration

## 🤖 MCP Integration (Claude Desktop / Cursor)

Backend Helper includes a server compatible with the **Model Context Protocol (MCP)**. This allows any compatible AI client (like **Claude Desktop** or **Cursor**) to interact directly with your codebase using our local reverse engineering and diagramming tools without needing to send all your code to the cloud or consume valuable context tokens by transferring full files.

The AI will call local tools on demand to analyze the architecture, generate diagrams, search for technical debt, or audit security.

### How to Run the MCP Server (Local Test)

Once you have installed the package locally (`pip install -e .`), you can run the MCP server using the global command:

```bash
bck-nd-mcp

Alternatively, you can run it as a Python module:
code Bash

python -m bck_nd_hlpr.cli.mcp_server

How to Configure Clients
1. Claude Desktop

Add the following configuration block to your claude_desktop_config.json file:

    Windows Path: %APPDATA%\Claude\claude_desktop_config.json

    Mac/Linux Path: ~/Library/Application Support/Claude/claude_desktop_config.json

Using the global executable (Recommended):
code JSON

{
  "mcpServers": {
    "backend-helper": {
      "command": "bck-nd-mcp",
      "env": {
        "OPENAI_API_KEY": "your-optional-api-key",
        "ANTHROPIC_API_KEY": "your-optional-api-key"
      }
    }
  }
}

Using the explicit Python module (Most robust for environment/PATH issues):
code JSON

{
  "mcpServers": {
    "backend-helper": {
      "command": "python",
      "args": [
        "-m",
        "bck_nd_hlpr.cli.mcp_server"
      ],
      "env": {
        "OPENAI_API_KEY": "your-optional-api-key",
        "ANTHROPIC_API_KEY": "your-optional-api-key"
      }
    }
  }
}


2. Cursor

    Go to Cursor Settings > Features > MCP.

    Click on + Add New MCP Server.

    Configure the following parameters:

        Name: backend-helper

        Type: command

        Command: bck-nd-mcp (or python -m bck_nd_hlpr.cli.mcp_server to lock it to your active python environment).

    Save and click on Refresh. Done! You now have 16 powerful architecture tools instantly available to your AI assistant.

```
