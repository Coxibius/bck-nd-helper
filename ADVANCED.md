
# Advanced Configuration

## 🤖 MCP Integration (Claude Desktop / Cursor)

Backend Helper includes a server compatible with the **Model Context Protocol (MCP)**. This allows any compatible AI client (like **Claude Desktop** or **Cursor**) to interact directly with your codebase using our local reverse engineering and diagramming tools without needing to send all your code to the cloud or consume valuable context tokens by transferring full files.

The AI will call local tools on demand to analyze the architecture, generate diagrams, search for technical debt, or audit security.

### How to Run the MCP Server (Local Test)

Once you have installed the package locally (`pip install -e .`), you can run the MCP server using the global command:

```bash
bck-nd-mcp
```

Alternatively, you can run it as a Python module:

```bash
python -m bck_nd_hlpr.cli.mcp_server
```

### How to Configure Clients

#### 1. Claude Desktop

Add the following configuration block to your `claude_desktop_config.json` file:

- **Windows Path:** `%APPDATA%\Claude\claude_desktop_config.json`
- **Mac/Linux Path:** `~/Library/Application Support/Claude/claude_desktop_config.json`

**Using the global executable (Recommended):**

```json
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
```

**Using the explicit Python module** (Most robust for environment/PATH issues):

```json
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
```

#### 2. Cursor

1. Go to **Cursor Settings > Features > MCP**.
2. Click on **+ Add New MCP Server**.
3. Configure the following parameters:
   - **Name:** `backend-helper`
   - **Type:** `command`
   - **Command:** `bck-nd-mcp` (or `python -m bck_nd_hlpr.cli.mcp_server` to lock it to your active python environment).
4. Save and click on **Refresh**. Done! You now have 16 powerful architecture tools instantly available to your AI assistant.

---

## 📋 Requirements Specification Format (`.bck-nd/requirements/`)

The **Requirements Intelligence Layer** lets you define User Stories and acceptance criteria as structured files that `bck-nd` can parse, list, validate, and inject into LLM context dumps.

### Directory Structure

All requirement files live under the `.bck-nd/requirements/` directory at the root of your project:

```
my-project/
├── .bck-nd/
│   └── requirements/
│       ├── US-001.json          # JSON format
│       ├── US-001.md            # Markdown format (alternative)
│       ├── US-002.json
│       ├── HU-003.md
│       └── STORY-PAYMENTS.json
├── src/
└── ...
```

> **Note:** If both `US-001.json` and `US-001.md` exist, only the first encountered (sorted by stem then suffix) is loaded — duplicates by Story ID are deduplicated automatically.

### Supported File Formats

#### JSON Format (`.json`)

The JSON format maps directly to the `RequirementSpecification` data model. This is the most precise and machine-friendly format.

```json
{
  "story": {
    "id": "US-001",
    "title": "User Registration",
    "role": "new visitor",
    "want": "to create an account with email and password",
    "benefit": "I can access personalized features",
    "status": "IN_PROGRESS"
  },
  "business_rules": [
    { "id": "BR01", "description": "Email must be unique across all accounts" },
    { "id": "BR02", "description": "Password must be at least 8 characters with one uppercase and one number" }
  ],
  "acceptance_criteria": [
    {
      "id": "AC01",
      "given": "a visitor is on the registration page",
      "when": "they submit a valid email and password",
      "then": "an account is created and a confirmation email is sent"
    },
    {
      "id": "AC02",
      "given": "a visitor submits an already registered email",
      "when": "the form is submitted",
      "then": "an error message 'Email already in use' is shown"
    }
  ],
  "required_data": [
    { "field": "email", "type": "string (valid email format)" },
    { "field": "password", "type": "string (min 8 chars)" },
    { "field": "display_name", "type": "string (optional)" }
  ],
  "validations": [
    { "field": "email", "rule": "RFC 5322 format, unique in users table" },
    { "field": "password", "rule": "min 8 chars, 1 uppercase, 1 digit" }
  ],
  "exceptions": [
    { "code": "ERR_DUPLICATE_EMAIL", "description": "Email already registered" },
    { "code": "ERR_WEAK_PASSWORD", "description": "Password does not meet complexity requirements" }
  ],
  "open_questions": [
    "Should we support OAuth (Google/GitHub) in the first release?",
    "What is the maximum length for display_name?"
  ]
}
```

##### JSON Field Reference

| Field | Type | Description |
|---|---|---|
| `story.id` | `string` | Unique identifier (e.g. `US-001`, `HU01`, `REQ-42`) |
| `story.title` | `string` | Short descriptive title |
| `story.role` | `string` | The user role (*"As a …"*) |
| `story.want` | `string` | The desired capability (*"I want …"*) |
| `story.benefit` | `string` | The business value (*"So that …"*) |
| `story.status` | `string` | Workflow status: `TODO`, `IN_PROGRESS`, `TESTING`, `DONE` |
| `business_rules[]` | `array` | Each entry has `id` and `description` |
| `acceptance_criteria[]` | `array` | Each entry has `id`, `given`, `when`, `then` |
| `required_data[]` | `array` | Each entry has `field` and `type` |
| `validations[]` | `array` | Each entry has `field` and `rule` |
| `exceptions[]` | `array` | Each entry has `code` and `description` |
| `open_questions[]` | `array` | Free-text strings for unresolved questions |

> **Flat JSON alternative:** The parser also supports a flat structure where `id`, `title`, `role`, `want`, and `benefit` sit at the root level instead of nested under `story`.

---

#### Markdown Format (`.md`)

The Markdown format is human-friendly and supports all the same sections. The Story ID defaults to the filename stem (e.g. `US-001.md` → `US-001`).

```markdown
# US-001 [IN_PROGRESS] - User Registration

- **Role**: new visitor
- **Want**: to create an account with email and password
- **Benefit**: I can access personalized features

## Business Rules
- BR01: Email must be unique across all accounts
- BR02: Password must be at least 8 characters with one uppercase and one number

## Acceptance Criteria
- AC01: Given a visitor is on the registration page When they submit a valid email and password Then an account is created and a confirmation email is sent
- AC02: Given a visitor submits an already registered email When the form is submitted Then an error message 'Email already in use' is shown

## Required Data
- email: string (valid email format)
- password: string (min 8 chars)
- display_name: string (optional)

## Validations
- email: RFC 5322 format, unique in users table
- password: min 8 chars, 1 uppercase, 1 digit

## Exceptions
- ERR_DUPLICATE_EMAIL: Email already registered
- ERR_WEAK_PASSWORD: Password does not meet complexity requirements

## Open Questions
- Should we support OAuth (Google/GitHub) in the first release?
- What is the maximum length for display_name?
```

##### Markdown Header Format

The `# ` header supports multiple patterns:

| Pattern | Example |
|---|---|
| `# ID - Title` | `# US-001 - User Registration` |
| `# ID: Title` | `# HU01: Registro de Usuario` |
| `# ID [STATUS] - Title` | `# US-001 [IN_PROGRESS] - User Registration` |

Recognized ID prefixes: `HU`, `US`, `REQ`, `STORY` (case-insensitive).

##### Markdown Section Headers

The parser recognizes these `## ` section headers (English and Spanish):

| Section | Recognized Keywords |
|---|---|
| **Business Rules** | `business rule`, `reglas de negocio`, `regla` |
| **Acceptance Criteria** | `acceptance`, `aceptación`, `criterio` |
| **Required Data** | `data`, `dato` |
| **Validations** | `validation`, `validación` |
| **Exceptions** | `exception`, `excepción` |
| **Open Questions** | `question`, `pregunta` |

---

### How CLI Commands Consume Requirements

#### `bck-nd req list [path]`

Scans `.bck-nd/requirements/` and displays a summary table of all discovered stories:

```
┌──────────────────────────────────────────────────────────────┐
│         Project Requirements & User Stories (3 found)        │
├──────────┬─────────────┬───────────────────┬────────┬────────┤
│ Story ID │   Status    │ Title             │ Crit.  │ Rules  │
├──────────┼─────────────┼───────────────────┼────────┼────────┤
│  US-001  │ IN_PROGRESS │ User Registration │   2    │   2    │
│  US-002  │    TODO     │ Password Reset    │   3    │   1    │
│  HU-003  │    DONE     │ User Profile      │   1    │   0    │
└──────────┴─────────────┴───────────────────┴────────┴────────┘
```

#### `bck-nd req discover [story_id] [path]`

Generates a **Stakeholder Interview & Discovery Guide** for a specific story. When called without a `story_id`, it lists all available stories you can discover.

```bash
# List available stories for discovery
bck-nd req discover .

# Generate discovery guide for a specific story
bck-nd req discover US-001
```

#### `bck-nd prompt .`

When generating the LLM context dump, `bck-nd prompt .` automatically detects and injects all requirements from `.bck-nd/requirements/` into the output. The context dump includes:

- Story metadata (ID, status, role/want/benefit)
- Business rules
- Acceptance criteria (Given/When/Then)
- Required data dictionary
- Validations and exceptions

This ensures any AI assistant receiving the context dump has full visibility into the project's functional requirements alongside the architecture, UML, and ER diagrams.

#### MCP Tool: `get_requirements_summary`

When using the MCP server, AI clients can call the `get_requirements_summary` tool to retrieve a formatted summary of all requirement specifications without consuming the full context dump.
