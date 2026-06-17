# Advanced Configuration

## 🤖 MCP Integration (Claude Desktop / Cursor)

Backend Helper includes a server compatible with the **Model Context Protocol (MCP)**. This allows any compatible AI client (like **Claude Desktop** or **Cursor**) to interact directly with your codebase using our local reverse engineering and diagramming tools without needing to send all your code to the cloud or consume valuable context tokens by transferring full files.

The AI will call local tools on demand to analyze the architecture, generate diagrams, search for technical debt, or audit security.

**Run MCP server (local test)**

python -m bck_nd_hlpr.mcp_server

then configure Claude/Cursor to call it as documented in this file.

### How to Configure

#### 1. Claude Desktop

Add the following configuration block to your `claude_desktop_config.json` file:

* **Windows Path:** `%APPDATA%\Claude\claude_desktop_config.json`
* **Mac/Linux Path:** `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "backend-helper": {
      "command": "python",
      "args": [
        "python",
        "-m",
        "bck_nd_hlpr.mcp_server"
      ],
      "env": {
        "OPENAI_API_KEY": "your-optional-api-key",
        "ANTHROPIC_API_KEY": "your-optional-api-key"
      }
    }
  }
}
```

#### 2. Cursor

1. Go to **Cursor Settings** > **Features** > **MCP**.
2. Click on **+ Add New MCP Server**.
3. Configure the following parameters:
   - **Name**: `backend-helper`
   - **Type**: `stdio`
   - **Command**: `python -m bck_nd_hlpr.mcp_server`
4. Save and click on **Refresh**. Done! You will instantly have 11 architecture tools available for your AI.
