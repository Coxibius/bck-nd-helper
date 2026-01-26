# 🛠️ Backend Helper (`bck-nd-hlpr`)

> **Lightweight Architecture CLI** - Reverse-engineer any codebase into ASCII diagrams with AI-powered insights.

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Zero Heavy Dependencies](https://img.shields.io/badge/dependencies-lightweight-green.svg)](https://pypi.org/project/bck-nd-hlpr/)

**Backend Helper** is a lightweight CLI tool that automatically detects backend architectures and generates ASCII diagrams. Built for CI/CD pipelines, code reviews, and rapid onboarding.

---

## ⚡ Key Features

- � **Auto-Detection**: Identifies Flask, FastAPI, Django, Express.js, NestJS, Gin, Actix-web, and more
- 🏭 **Architecture Recognition**: Detects MVC, Microservices, Layered Architecture patterns
- � **Smart Diagrams**: Different visualizations for Controllers, Models, Services, Routes
- 🧠 **Cloud AI Analysis**: 9 AI personalities via n8n webhooks (Professional, Hacker, Gordon Ramsay, etc.)
- 🛡️ **Dependency-Free Core**: No PyTorch, No Transformers. Installs in <3 seconds
- 🪟 **OS-Safe Scanning**: Robust directory traversal ignoring `venv`, `node_modules`, and system restricted files
- 🎨 **Visual & Mermaid**: Output Unicode diagrams or copy-paste Mermaid code
- ⚙️ **Flexible Config**: Customize detection via `pyproject.toml`
- 🌍 **Polyglot Ready**: Python, JavaScript/TypeScript, Go, Rust, Docker, Terraform

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
```

---

## 📚 Command Manual

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
- Generates `graph TD` code ready to copy-paste into Notion, GitHub, or Obsidian.
- **Also shows** the specific visual diagram in the terminal for instant preview.
- Perfect for documentation and presentations.

##### 3. **UML Class Diagram**
```bash
bck-nd scan . --uml
```
**Output:**
- Generates `classDiagram` code for Mermaid.js.
- Uses AST parsing to find classes, methods, and inheritance.

##### 3. **Diagram + Local Report**
```bash
bck-nd scan . --explain
```
**Output:**
- Everything from mode 1, PLUS
- Text-based component breakdown
- List of Controllers, Models, Services
- No AI required (100% offline)

##### 4. **Entity-Relationship Diagram (ER) 🆕**
```bash
bck-nd scan . --er
```
**Output:**
- Generates `erDiagram` for Mermaid.js.
- Scans `SQLAlchemy` and `Django` models.
- Shows tables, columns, types, and FK relationships.

##### 5. **API Route Map 🆕**
```bash
bck-nd scan . --routes
```
**Output:**
- Generates `sequenceDiagram` for Mermaid.js.
- Scans `Flask` and `FastAPI` endpoints.
- Visualizes `Client -> API` interactions with methods and paths.

##### 6. **Infrastructure Diagram 🆕**
```bash
bck-nd scan . --infra
```
**Output:**
- Generates `graph LR` for Mermaid.js.
- Scans `docker-compose.yml` files.
- Shows services, images, and dependencies.
- Database services (postgres, redis, mysql, mongo) displayed as cylinders.

##### 7. **Technical Debt Scanner 🆕**
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

##### 8. **Security Audit 🆕**
```bash
bck-nd scan . --audit
```
**Output:**
- Scans for hardcoded secrets, keys, and dangerous config
- Reports "Critical" risks like AWS Keys or Private PEMs
- Reports "High/Warning" risks like DB passwords or hardcoded IPs
- Essential for pre-commit checks

##### 9. **Dependency Heatmap 🆕**
```bash
bck-nd scan . --impact
```
**Output:**
- Shows a "Heatmap" of your files based on how many other files import them.
- Helps identify "Core" modules that are risky to refactor.
- Sorts by Impact Score (High = Connected to everything).

##### 10. **Diagram + AI Analysis**

```bash
bck-nd scan . --ai
```
**Output:**
- Everything from mode 1, PLUS
- AI-powered architectural analysis
- Design pattern recommendations
- Code quality insights
- Requires n8n webhook running

##### 9. **AI Only (No Diagram)**
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

#Available styles:
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
| Python | Flask, FastAPI, Django, Quart |
| JavaScript/TypeScript | Express.js, Fastify, Koa, NestJS (Route Detection Support!) |
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

## 🧪 n8n Webhook Setup


### 1. Install n8n
```bash
npm install -g n8n
```

### 2. Start n8n
```bash
n8n start
```
Access: `http://localhost:5678`

### 3. Create Workflow
1. Add **Webhook** trigger
   - Method: `POST`
   - Path: `explain`
2. Add **AI** node (OpenAI/Gemini)
   - System: `{{ $json.prompt }}`
   - Input: `{{ $json.text }}`
3. Add **Respond to Webhook**
   - JSON: `{ "text": "{{ $json.output }}" }`
4. Activate workflow

### 4. Custom Webhook (Optional)
```bash
# Windows
set BCK_ND_WEBHOOK_URL=https://your-server.com/webhook/explain

# Linux/Mac
export BCK_ND_WEBHOOK_URL=https://your-server.com/webhook/explain
```

---

## � Comparison: Different Commands

| Command | Architecture Detection | Diagram | Text Report | AI Analysis |
|---------|----------------------|---------|-------------|-------------|
| `bck-nd scan .` | ✅ | ✅ | ❌ | ❌ |
| `bck-nd scan . --explain` | ✅ | ✅ | ✅ | ❌ |
| `bck-nd scan . --ai` | ✅ | ✅ | ❌ | ✅ |
| `bck-nd scan . --explain --ai` | ✅ | ✅ | ✅ | ✅ |
| `bck-nd scan . --no-graph --ai` | ✅ | ❌ | ❌ | ✅ |
| `bck-nd flow "A -> B"` | ❌ | ✅ | ❌ | ❌ |

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