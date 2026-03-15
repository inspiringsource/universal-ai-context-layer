# AI Context Map

`ai-context-map` is a lightweight CLI that scans a repository and produces a **structured navigation context for AI coding agents**.

Instead of forcing an AI to rediscover repository structure through repeated search and file exploration, the tool builds a **deterministic structural map** of the project ahead of time.

The goal is simple:

> Help an AI agent quickly determine **where to look first before making a change**.

The generated context highlights entry points, core modules, dependency hotspots, important symbols, and task-oriented navigation routes.

---

# Why this exists

AI coding agents often struggle with large repositories because they must first infer architecture from raw files.

Typical behavior:

- searching randomly across the repo
- opening many irrelevant files
- missing central modules
- making narrow edits that break downstream code

`ai-context-map` precomputes a **repository navigation layer** so an AI can start from the most relevant locations immediately.

Instead of:

```
AI → search → read random files → infer structure
```

The workflow becomes:

```
Repository → structural context map → AI navigation → code change
```

The result is faster inspection, less token usage, and more reliable edits.

---

# Core capabilities

- Scan a repository with sensible ignore rules
- Detect Python and basic JS/TS source files
- Parse local imports and build a lightweight dependency graph
- Rank important files using deterministic signals
- Explain file importance with traceable reasons
- Extract Python symbol anchors from high-value files
- Identify entry points, core modules, and dependency hotspots
- Suggest task-specific navigation routes
- Emit `.ai/context.yaml`
- Initialize `.ai/history.yaml` and `.aicontext.toml`

The tool intentionally avoids LLM calls and external services so the output remains **deterministic and reproducible**.

---

# Install locally

```
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

---

# Usage

Initialize support files:

```
aicontext init
```

Generate a repository context map:

```
aicontext generate
```

Inspect top-ranked files and anchors:

```
aicontext inspect
```

Inspect navigation routes and reasoning signals:

```
aicontext inspect-routes
```

Generate context for another path:

```
aicontext generate /path/to/repo
```

---

# Output

The primary output file is:

```
.ai/context.yaml
```

Example structure:

```yaml
aicontext_version: 2
project:
  name: example-repo
  root: .
  detected_languages:
    - python

architecture:
  entry_points:
    - path: src/main.py
      confidence: 0.95
      reasons:
        - filename pattern matched "main"

  core_modules:
    - path: src/app/service.py
      score: 12.0
      reasons:
        - high incoming dependency count
        - central in dependency graph

navigation_map:
  directories:
    - path: src
      role: source_root

  key_files:
    - path: src/api/routes.py
      role: api
      importance: critical

hotspots:
  - path: src/app/service.py
    reason: high centrality

anchors:
  - file: src/api/routes.py
    symbol: list_items
    symbol_type: route_handler
    line: 8
    reasons:
      - contains route handlers

task_routes:
  api_change:
    - path: src/api/routes.py
      reasons:
        - contains route handlers
        - API module

  model_or_logic_change:
    - path: src/app/service.py
      reasons:
        - located in core/service module

provenance:
  enabled: false
  history_file: .ai/history.yaml
```

---

# Anchors and task routes

**Anchors** are concise symbol pointers extracted from important Python files.

They surface high-value constructs such as:

- entrypoint functions
- route handlers
- core classes
- service logic

This avoids dumping every symbol in the repository while still giving the AI **high-signal navigation points**.

**Task routes** are deterministic file lists keyed by change type.

Examples:

- `bugfix`
- `api_change`
- `model_or_logic_change`
- `config_change`
- `test_update`

These routes help an AI agent begin investigation in the **most likely relevant parts of the repository**.

---

# Configuration

Running `aicontext init` creates `.aicontext.toml`:

```toml
include_paths = []
exclude_paths = []
languages = ["python", "javascript", "typescript"]
enable_git_metadata = false
output_path = ".ai/context.yaml"

[filename_weights]
main = 4.0
app = 3.0
server = 3.0
cli = 3.0
api = 2.5
routes = 2.5
config = 1.5
service = 2.0
index = 2.0
```

These weights influence how file importance is ranked during analysis.

---

# Provenance roadmap

V1 initializes `.ai/history.yaml`:

```yaml
history_version: 1
entries: []
```

Future versions may record structured change history including:

- timestamps
- actor type (human or AI)
- model used
- files changed
- summary of modification

This can eventually support **AI change auditing and repository evolution tracking**.

---

# Limitations

- Symbol anchors are currently Python-first
- JS/TS symbol extraction is minimal
- FastAPI route detection is heuristic
- Dependency graph is intentionally lightweight
- Task routes are deterministic heuristics
- No semantic program analysis yet

The project prioritizes **fast structural navigation signals** rather than deep static analysis.

---

# Development

Run tests:

```
pytest
```

Lint the codebase:

```
ruff check .
```

---

# Related Work

This project is conceptually related to research exploring **graph-constrained reasoning with large language models**.

Reference:

**Graph-constrained Reasoning: Faithful Reasoning on Knowledge Graphs with Large Language Models**  
Luo et al., ICML 2025

Repository:

https://github.com/RManLuo/graph-constrained-reasoning

That work demonstrates how constraining LLM reasoning using **knowledge graph structure** can reduce hallucinations and produce faithful reasoning paths.

## Relationship to AI Context Map

Graph-constrained Reasoning operates on **knowledge graphs of factual entities**.

AI Context Map applies a similar conceptual idea to **software repositories**.

Instead of reasoning over facts, we analyze the **structural graph of a codebase**, including relationships such as:

- module imports
- function calls
- dependency relationships
- architectural hotspots

The goal is to help AI agents **navigate repositories and reason about code changes more reliably**.

## Key Difference

| Graph‑constrained Reasoning | AI Context Map |
|-----------------------------|---------------|
| Works on knowledge graphs | Works on software repositories |
| Constrains LLM reasoning paths | Guides AI navigation across codebases |
| Focused on question answering | Focused on AI‑assisted code modification |

We include this reference to acknowledge the broader research direction of **graph‑guided reasoning with LLMs**, which influenced parts of the conceptual design of this project.