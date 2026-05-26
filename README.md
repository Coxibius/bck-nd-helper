# 🛠️ Backend Helper (`bck-nd-hlpr`)

> **Lightweight Architecture CLI** - Reverse-engineer any codebase into ASCII diagrams with AI-powered insights.

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Zero Heavy Dependencies](https://img.shields.io/badge/dependencies-lightweight-green.svg)](https://pypi.org/project/bck-nd-hlpr/)

**Backend Helper** is a lightweight CLI tool that automatically detects backend architectures and generates ASCII diagrams. Built for CI/CD pipelines, code reviews, and rapid onboarding.

---

## ⚡ Key Features

- 🔍 **Auto-Detection**: Identifies Flask, FastAPI, Django, Next.js, Express.js, NestJS, Gin, Actix-web, and more
- 🏭 **Architecture Recognition**: Detects MVC, Microservices, Layered Architecture patterns
-  **Smart Diagrams**: Different visualizations for Controllers, Models, Services, Routes
- 🤖 **BYO-Key AI Analysis**: Directly integrate with OpenAI, Anthropic, Gemini, or local Ollama using API keys. No middleware needed!
- 🌐 **Cloud AI Fallback**: Support for 9 AI personalities via n8n webhooks if no keys are provided.
- 🛡️ **Dependency-Free Core**: No PyTorch, No Transformers. Installs in <3 seconds
- 🪟 **OS-Safe Scanning**: Robust directory traversal ignoring `venv`, `node_modules`, and system restricted files
- 🎨 **Visual & Mermaid**: Output Unicode diagrams or copy-paste Mermaid code
- 🚀 **Auto-Documentation (CI/CD)**: One-command setup for GitHub Actions to host living docs on GitHub Pages (`init-ci`)
- ⚙️ **Flexible Config**: Customize detection via `pyproject.toml`
- 🌍 **Polyglot Ready**: C# (.NET Core), Python (Django/FastAPI), JavaScript/TypeScript (Next.js/Express.js/Drizzle ORM), Java (Spring Boot), PHP (Laravel), Go, Rust, Docker, Terraform, Prisma schemas (`schema.prisma`), and SQL migrations (`.sql`)

---

## 📦 Installation

```bash
# From source
cd bck-nd-hlpr
pip install .

# Development mode
pip install -e .

# Verify
bck-nd --help

# Optional: Set your preferred AI Provider key
# set OPENAI_API_KEY=sk-... (Windows)
# export OPENAI_API_KEY=sk-... (Mac/Linux)
```

---

## 📚 Command Manual

### 🖥️ `explore` - Interactive TUI Mode (Explorer) 🆕

Launch a full-screen Terminal User Interface (TUI) to interactively explore your project's architecture, powered by `textual`.

#### **Usage**
```bash
bck-nd explore
```

**What you get:**
- **Sidebar:** Directory tree to navigate your codebase.
- **Main View:** Click on a `.py` file to instantly generate its ASCII diagram and Mermaid Sequence routes.
- **Dynamic Analysis:** Click on a folder to see the high-level architecture of that specific directory.
- **Shortcuts:** Press `D` to toggle dark/light mode, `Q` to quit.

---

### 🌐 `docs` - Static HTML Portal Generation 🆕

Automatically generates a complete, static HTML documentation portal for your project. Perfect for CI/CD and GitHub Pages.

#### **Usage**
```bash
# Generate docs in the current directory (output folder: 'docs')
bck-nd docs . --output docs
```

**What you get in `docs/index.html`:**
- **Infrastructure Map:** Visual representation of `docker-compose.yml`.
- **API Routes:** Sequence diagrams of HTTP endpoints.
- **UML Class Diagram:** Auto-generated class hierarchy with associations and dependencies.
- **Entity-Relationship:** E-R diagrams for ORM models (Entity Framework, SQLAlchemy, Django).
- **Technical Debt:** Actionable table of TODOs and FIXMEs.
- Fully self-contained, using MermaidJS CDN for rendering. No heavy build tools required.

---

### 🚀 `init-ci` - GitHub Actions Automation 🆕

Set up "Living Documentation" in seconds. This command injects a ready-to-use GitHub Action into your repository.

#### **Usage**
```bash
bck-nd init-ci
```

**What it does:**
- Creates `.github/workflows/bck-nd-docs.yml`.
- Configures an automatic trigger on `push` to `main`.
- Installs `bck-nd-hlpr` in the CI runner.
- Generates the full HTML portal (UML, ER, Infra, Routes).
- Deploys the result automatically to **GitHub Pages**.

---

### 🕵️ `scan` - Automatic Architecture Detection

Automatically scans your project, detects the framework and architecture, and generates intelligent diagrams.

#### **Basic Usage**
```bash
# Scan current directory (default depth: 3)
bck-nd scan .

# Scan specific directory
bck-nd scan src

# Custom depth
bck-nd scan . --depth 5
```

#### **Modes**

##### 1. **Diagram Only (Default)**
```bash
bck-nd scan .
```
**Output:**
- Framework detection (Flask, FastAPI, Django, etc.)
- Architecture type (MVC, Microservices, etc.)
- Features (Docker, Auth, Database, etc.)
- ASCII diagram showing component relationships

##### 2. **Mermaid Export (New!)**
```bash
bck-nd scan . --format mermaid
```
**Output:**
- Generates `graph TD` code ready to copy-paste into Notion, GitHub, or Obsidian.
- **Also shows** the specific visual diagram in the terminal for instant preview.
- Perfect for documentation and presentations.

##### 3. **UML Class Diagram**
```bash
bck-nd scan . --uml
```
- Generates `classDiagram` code for Mermaid.js.
- Uses a unified multi-language parser combining AST (Python) and Tree-Sitter (C#, Java, JS/TS, PHP) to extract classes, methods, properties, and constructors automatically.
- Automatically infers relationships (`-->` Associations, `..>` Dependencies) and inheritance (`<|--`) across all files.

##### 3. **Diagram + Local Report**
```bash
bck-nd scan . --explain
```
**Output:**
- Everything from mode 1, PLUS
- Text-based component breakdown
- List of Controllers, Models, Services
- No AI required (100% offline)

##### 5. **Entity-Relationship Diagram (ER) 🆕**
```bash
bck-nd scan . --er
```
**Output:**
- Generates `erDiagram` for Mermaid.js.
- Scans modern schema configurations, migrations, and ORMs across languages:
  - **Modern Configs**: Prisma Schemas (`schema.prisma`), Drizzle ORM schemas (`.ts/.js`), and raw SQL migrations (`.sql`)
  - **Traditional ORMs**: Entity Framework (C#), Spring Boot / JPA (Java), Laravel / Eloquent (PHP), SQLAlchemy / Django models (Python), and Sequelize / Mongoose (JS/TS)
- Bulletproof Mermaid Syntax: Safely handles Generics (e.g. `List<T>`), table brackets, and special characters.
- Detects database columns, primary keys (`PK`), data annotations, and auto-generates bidirectional relationships (`||--o{`, `}o--||`) with intelligent schema deduplication and merging.

##### 6. **API Route Map 🆕**
```bash
bck-nd scan . --routes
```
**Output:**
- Generates `sequenceDiagram` for Mermaid.js.
- Scans `Flask` and `FastAPI` endpoints.
- Visualizes `Client -> API` interactions with methods and paths.

##### 7. **Infrastructure Diagram 🆕**
```bash
bck-nd scan . --infra
```
**Output:**
- Generates `graph LR` for Mermaid.js.
- Scans `docker-compose.yml` files.
- Shows services, images, and dependencies.
- Database services (postgres, redis, mysql, mongo) displayed as cylinders.

##### 8. **Technical Debt Scanner 🆕**
```bash
bck-nd scan . --todo
```
**Output:**
- Scans for TODO, FIXME, HACK, XXX, BUG comments
- Beautiful color-coded table using Rich
- Shows file, line number, type, and message
- Statistics by debt type
- Debt level assessment
- Perfect for code reviews and sprint planning

##### 9. **Security Audit 🆕**
```bash
bck-nd scan . --audit
```
**Output:**
- Scans for hardcoded secrets, keys, and dangerous config
- Reports "Critical" risks like AWS Keys or Private PEMs
- Reports "High/Warning" risks like DB passwords or hardcoded IPs
- Essential for pre-commit checks

##### 10. **Dependency Heatmap 🆕**
```bash
bck-nd scan . --impact
```
**Output:**
- Shows a "Heatmap" of your files based on how many other files import them.
- Helps identify "Core" modules that are risky to refactor.
- Sorts by Impact Score (High = Connected to everything).

##### 11. **Diagram + AI Analysis**

```bash
bck-nd scan . --ai
```
**Output:**
- Everything from mode 1, PLUS
- AI-powered architectural analysis
- Design pattern recommendations
- Code quality insights
- Detects API keys in your environment (OpenAI, Anthropic, Gemini, Ollama) or falls back to Webhook (n8n).

##### 11. **Force Specific AI Provider 🆕**

```bash
bck-nd scan . --ai --provider openai
```
**Output:**
- Supported providers: `openai`, `anthropic`, `gemini`, `ollama`, `webhook`.
- Safely reports an error if the corresponding API key is missing.

##### 12. **AI Only (No Diagram)**
```bash
bck-nd scan . --no-graph --ai
```
**Output:**
- Only AI analysis (no ASCII diagram)
- Faster for text-only reports

#### **AI Personalities**
```bash
# Professional analysis
bck-nd scan . --ai --style pro

# Security-focused review
bck-nd scan . --ai --style hacker

# Critical code review (like Gordon Ramsay)
bck-nd scan . --ai --style ramsay

# Simple explanations
bck-nd scan . --ai --style eli5

# Available styles (Mostly optimized for the Webhook / n8n Mode):
# pro, hacker, soviet, eli5, ramsay, jarvis, corporate, medieval, doom
```

---

### 📐 `flow` - Manual Diagram Generation

Create custom architecture diagrams from string descriptions.

#### **Usage**
```bash
bck-nd flow "Client -> API -> Database"

bck-nd flow "Client -> LoadBalancer -> [API_v1, API_v2] ; API_v1 -> Redis"

bck-nd flow "User -> Auth [Service] -> JWT [Token] -> API"
```

#### **Syntax**
- `A -> B` - Creates connection from A to B
- `[X, Y, Z]` - Multiple nodes in same position
- `;` - New row
- `[DB]`, `[SQL]`, `[DATA]` - Rendered as database cylinders
- `[Service]`, `[DIR]` - Rendered as soft boxes
- `[?]`, `[IF]` - Rendered as diamonds

---

## 🎯 Usage Examples

### Example 1: Quick Project Analysis
```bash
cd my-backend-project
bck-nd scan .
```
**What you get:**
```
🔍 Analizando arquitectura de '.'...
💻 Framework detectado: FastAPI
🏭 Arquitectura: REST API (Route-based)
✨ Características: Docker, SQLAlchemy ORM, Authentication

📝 FastAPI application using REST API (Route-based) with Docker, SQLAlchemy ORM, Authentication.

📊 DIAGRAMA DE ARQUITECTURA:
[ASCII diagram showing Routes -> Services -> Models -> Database]
```

### Example 2: Deep Analysis with AI
```bash
bck-nd scan . --ai --style pro --depth 5
```
**What you get:**
- Complete architecture detection
- Full project diagram
- AI analysis including:
  - Design pattern recommendations
  - Security considerations
  - Performance optimization suggestions
  - Code quality assessment

### Example 3: Text-Only Report
```bash
bck-nd scan src --explain --no-graph
```
**What you get:**
- Framework/architecture detection
- Component list without diagram
- Perfect for CI/CD logs

### Example 4: Compare Two Approaches
```bash
# Old monolith
bck-nd scan ./legacy --ai --style ramsay

# New microservices
bck-nd scan ./new-arch --ai --style pro
```

---

## 🔧 Architecture Detection

Backend Helper automatically detects:

### **Frameworks**
| Language | Frameworks |
|----------|-----------|
| Python | Flask, FastAPI, Django (Specialized ER/UML), Quart |
| JavaScript/TypeScript | Next.js (Filesystem Routes & React UML), Express.js (Specialized ER/UML), Fastify, Koa, NestJS (Route Detection) |
| Java | Spring Boot (Specialized ER/UML), Maven, Gradle |
| PHP | Laravel (Specialized ER/UML) |
| C# / .NET | .NET Core, Entity Framework (Specialized ER/UML) |
| Go | Gin, Fiber |
| Rust | Actix-web, Rocket |

### **Architecture Patterns**
- **Microservices Architecture** - Multiple services in docker-compose
- **MVC + Services (Layered)** - Controllers, Models, Services folders
- **MVC Pattern** - Controllers + Models
- **REST API (Route-based)** - Routes + Models
- **Containerized Application** - Docker detected
- **Monolithic Application** - Fallback


### **Features Detection**
- Docker / Docker Compose
- Databases (SQL, SQLite)
- ORM (SQLAlchemy, Django ORM)
- Authentication (JWT, OAuth)
- API Documentation (Swagger/OpenAPI)
- CI/CD (GitHub Actions, GitLab CI)
- Unit Tests
- **Security**: Auto-redaction of secrets in output (Sanitizer) 🆕

### **Configuration**
You can override architecture detection by adding this to `pyproject.toml`:

```toml
[tool.bck-nd]
controllers = ["handlers", "views"]
models = ["entities", "schemas"]
services = ["logic", "usecases"]
```

---

## 💾 Output Persistence (New!)

You can now save any report or diagram to a file using `-o` / `--output`.
The tool automatically **strips ANSI color codes** for clean text files.

```bash
# Save ASCII diagram
bck-nd scan . -o architecture.txt

# Save Technical Debt Report (Clean text)
bck-nd scan . --todo -o report.txt

# Save Mermaid diagram
bck-nd scan . --er --format mermaid -o db.mmd
```

---

## 🧪 AI Providers Setup (BYO-Key)

Backend Helper now supports direct integration with AI models using your own keys. By default, it checks environment variables in this order:
`OPENAI_API_KEY` -> `ANTHROPIC_API_KEY` -> `GOOGLE_API_KEY` -> `OLLAMA_HOST` -> Webhook Fallback.

### Option 1: OpenAI
```bash
export OPENAI_API_KEY="sk-..."
bck-nd scan . --ai
```

### Option 2: Anthropic (Claude)
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
bck-nd scan . --ai
```

### Option 3: Google Gemini
```bash
export GOOGLE_API_KEY="AIzaSy..."
bck-nd scan . --ai
```

### Option 4: Ollama (Local)
No API key required. Make sure Ollama is running on `http://localhost:11434`.
```bash
# Optionally customize the host
export OLLAMA_HOST="http://localhost:11434"
bck-nd scan . --ai --provider ollama
```

### Option 5: n8n Webhook Fallback

If no keys are found, it falls back to the legacy webhook approach.

#### 1. Install n8n
```bash
npm install -g n8n
```

##### 2. Start n8n
```bash
n8n start
```
Access: `http://localhost:5678`

##### 3. Create Workflow
1. Add **Webhook** trigger
   - Method: `POST`
   - Path: `explain`
2. Add **AI** node (OpenAI/Gemini)
   - System: `{{ $json.prompt }}`
   - Input: `{{ $json.text }}`
3. Add **Respond to Webhook**
   - JSON: `{ "text": "{{ $json.output }}" }`
4. Activate workflow

##### 4. Custom Webhook (Optional)
```bash
# Windows
set BCK_ND_WEBHOOK_URL=https://your-server.com/webhook/explain

# Linux/Mac
export BCK_ND_WEBHOOK_URL=https://your-server.com/webhook/explain
```

---

## 🤖 Integración MCP (Claude Desktop / Cursor)

Backend Helper incluye un servidor compatible con el **Model Context Protocol (MCP)**. Esto permite a cualquier cliente de IA compatible (como **Claude Desktop** o **Cursor**) interactuar directamente con tu base de código usando nuestras herramientas locales de ingeniería inversa y diagramado sin necesidad de enviar todo tu código a la nube o consumir valiosos tokens de contexto al transferir archivos completos.

La IA llamará a las herramientas locales bajo demanda para analizar la arquitectura, generar diagramas, buscar deudas técnicas o auditar la seguridad.

### Cómo Configurar

#### 1. Claude Desktop
Añade el siguiente bloque de configuración a tu archivo `claude_desktop_config.json`:

* **Ruta en Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
* **Ruta en Mac/Linux:** `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "backend-helper": {
      "command": "python",
      "args": [
        "c:/bck-nd-hlpr/mcp_server.py"
      ],
      "env": {
        "OPENAI_API_KEY": "tu-api-key-opcional",
        "ANTHROPIC_API_KEY": "tu-api-key-opcional"
      }
    }
  }
}
```

#### 2. Cursor
1. Ve a **Cursor Settings** > **Features** > **MCP**.
2. Haz clic en **+ Add New MCP Server**.
3. Configura los siguientes parámetros:
   - **Name**: `backend-helper`
   - **Type**: `stdio`
   - **Command**: `python c:/bck-nd-hlpr/mcp_server.py`
4. Guarda y haz clic en **Refresh**. ¡Listo! Tendrás 11 herramientas de arquitectura disponibles instantáneamente para tu IA.

---

##  Comparison: Different Commands

| Command | Architecture Detection | Diagram | Text Report | AI Analysis |
|---------|----------------------|---------|-------------|-------------|
| `bck-nd scan .` | ✅ | ✅ | ❌ | ❌ |
| `bck-nd scan . --explain` | ✅ | ✅ | ✅ | ❌ |
| `bck-nd scan . --ai` | ✅ | ✅ | ❌ | ✅ |
| `bck-nd scan . --explain --ai` | ✅ | ✅ | ✅ | ✅ |
| `bck-nd scan . --no-graph --ai` | ✅ | ❌ | ❌ | ✅ |
| `bck-nd flow "A -> B"` | ❌ | ✅ | ❌ | ❌ |
| `bck-nd explore` | ✅ | ✅ | ✅ | ❌ |
| `bck-nd init-ci` | ✅ | ✅ | ✅ | ❌ |

---

## 🎭 AI Personalities Guide

| Style | Description | Use Case |
|-------|-------------|----------|
| `pro` | Senior Software Architect - Technical, formal | Production documentation |
| `hacker` | Security Expert - Focuses on vulnerabilities | Security audits |
| `soviet` | Soviet Engineer - Efficiency-focused | Performance reviews |
| `eli5` | Kindergarten Teacher - Simple explanations | Onboarding juniors |
| `ramsay` | Gordon Ramsay - Brutally critical | Code reviews |
| `jarvis` | Tony Stark's AI - Elegant, helpful | Executive presentations |
| `corporate` | Manager - Buzzword-heavy | Stakeholder reports |
| `medieval` | Ancient Wizard - Metaphorical | Creative documentation |
| `doom` | Doom Slayer - Bugs are demons | Bug hunting |

---

## 🐛 Troubleshooting

### "No se encontraron archivos"
**Solution:**
```bash
# Increase depth
bck-nd scan . --depth 5

# Or scan specific directory
bck-nd scan src --depth 3
```

### "Error conexión: ..."
**Cause:** n8n not running  
**Solution:**
```bash
# Terminal 1
n8n start

# Terminal 2
bck-nd scan . --ai
```

### "Framework detectado: Unknown"
**Cause:** Framework not yet supported or non-standard structure  
**Solution:** Use `bck-nd flow` for manual diagrams

---

## 📊 Supported File Types

| Type | Detection Method | Output Shape |
|------|-----------------|--------------|
| Controllers | `*controller.py`, `*ctrl.py` | Box → API |
| Models | `*model.py`, `*entity.py`, `*schema.py` | Box → Database (Cylinder) |
| Services | `*service.py`, `*svc.py` | Box → Business Logic |
| Routes | `*route.py`, `*router.py` | Box → Endpoints |
| Middleware | `*middleware.py` | Box → Request Pipeline |
| Database Files | `.sql`, `.db`, `.sqlite` | Cylinder → Data Storage |
| Docker | `Dockerfile`, `docker-compose.yml` | Soft Box |
| Infrastructure | `.tf` (Terraform) | Box → Infrastructure |

---

## 🚀 What's Different from ASCII Architect?

| Feature | ASCII Architect | Backend Helper |
|---------|----------------|----------------|
| Auto-Detection | ❌ | ✅ Flask, FastAPI, Django, etc. |
| Architecture Patterns | ❌ | ✅ MVC, Microservices, etc. |
| Component Classification | ❌ | ✅ Controllers, Models, Services |
| Neural Engine (GPT-2) | ✅ | ❌ Removed for speed |
| Installation Size | ~500MB | <50MB |
| Installation Time | ~2 min | <3 sec |
| Cloud AI | ✅ | ✅ 9 personalities |

---

## 📝 Real-World Usage

### CI/CD Integration

#### **Option A: Automatic Setup (Recommended)**
```bash
# Run this once locally to inject the workflow
bck-nd init-ci
git add . && git commit -m "ci: add auto-documentation" && git push origin main
```

#### **Option B: Manual YAML**
```yaml
# .github/workflows/arch-analysis.yml
- name: Analyze Architecture
  run: |
    pip install bck-nd-hlpr
    bck-nd scan . --explain --no-graph > architecture.txt
```

### Code Review Automation
```bash
# Before PR approval
bck-nd scan . --ai --style pro > review.md
```

### Documentation Generation
``bash
# Generate architecture docs
bck-nd scan . --explain > docs/ARCHITECTURE.md
bck-nd scan . --ai --style pro > docs/AI_ANALYSIS.md
```

---

## 📚 Documentation

- [IA-context.md](IA-context.md) - Development rules & architecture
- [ROADMAP.txt](ROADMAP.txt) - Feature roadmap
- [MANIFEST.in](MANIFEST.in) - Package configuration

---

## 💡 Philosophy

> **"Less guessing, more coding."**

Backend Helper is designed for **speed**, **intelligence**, and **actionable insights**. No bloated dependencies, no waiting for model downloads. Just instant architectural understanding.

---

## 🤝 Contributing

Issues and PRs welcome! See [IA-context.md](IA-context.md) for development guidelines.

---

## 📄 License

MIT License - See LICENSE file for details

---

**Built with ❤️ for developers who value clarity and speed.**