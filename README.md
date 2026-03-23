# AI Context Map

`ai-context-map` is a lightweight CLI that scans a repository and produces a **structured navigation context for AI coding agents**.

Instead of forcing an AI to rediscover repository structure through repeated search and file exploration, the tool builds a **deterministic structural map** of the project ahead of time.

**A lightweight, deterministic alternative to embedding-based or prompt-based repo understanding tools.**

The goal is simple:

> Help an AI agent quickly determine **where to look first before making a change**.

The generated context highlights entry points, core modules, dependency hotspots, important symbols, and task-oriented navigation routes.


## Positioning

AI Context Map is a lightweight, deterministic alternative to embedding-based or prompt-based repository understanding tools.

Instead of relying on vector search or LLM summarization, it builds an inspectable structural map of the repository using static analysis.

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
- Rank important files using a deterministic scoring system that combines:
  - repository dependency graph centrality (PageRank)
  - filename role heuristics (e.g., `main`, `api`, `routes`, `service`)
  - entrypoint detection signals
  - lightweight structural signals from the dependency graph
- Explain file importance with traceable reasons
- Extract Python symbol anchors from high-value files
- Identify entry points, core modules, and dependency hotspots
- Suggest task-specific navigation routes
- Emit `.ai/context.yaml`
- Initialize `.ai/history.yaml` and `.aicontext.toml`

The tool intentionally avoids LLM calls and external services so the output remains **deterministic and reproducible**.

---

# Ranking Mechanism

AI Context Map ranks files using a **deterministic hybrid scoring model** built from structural signals extracted from the repository.

The ranking pipeline operates in several stages:

1. **Dependency Graph Construction**  
   Local imports and module relationships are parsed to construct a directed file‑level dependency graph.

2. **Graph Centrality (PageRank)**  
   A lightweight deterministic PageRank algorithm is computed over the dependency graph.  
   Files that many important modules depend on receive higher centrality scores.

3. **Heuristic Structural Signals**  
   Additional signals are extracted from repository structure, including:

   - filename role patterns (`main`, `api`, `routes`, `service`, `cli`, etc.)
   - entrypoint detection
   - directory role hints (e.g., `core`, `api`, `service`)

4. **Score Normalization and Blending**  
   PageRank and heuristic scores are normalized and blended into a final deterministic importance score.

This produces rankings that balance:

- **architectural centrality** (via PageRank)
- **role‑based heuristics** (via filename and structure signals)

The resulting ranking is used to identify:

- `core_modules`
- `hotspots`
- `key_files`

These signals guide AI agents toward the most structurally relevant parts of the repository before performing modifications.

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

---

# Mini Literature Review

This section summarizes research and tools related to **repository structure analysis and graph‑guided navigation for AI coding agents**. The goal is to position **AI Context Map** within the emerging ecosystem of tools that help AI systems understand large codebases.

## Motivation

AI coding agents frequently struggle with large repositories because they must dynamically infer:

- architectural structure
- dependencies between modules
- entry points
- the potential impact of code changes

Without structural guidance, agents often explore repositories inefficiently, reading many irrelevant files and missing important dependencies.

Recent research and tooling attempts to address this problem by introducing **repository graphs, structural summaries, or navigation layers** that help AI systems reason about codebases.

---

## Selected Related Work

| Work | Core Idea | Method | Overlap with AI Context Map | Key Difference |
|-----|-----|-----|-----|-----|
| **Aider RepoMap** | Provide repository summaries for LLMs | Static extraction of symbols and files | Similar goal of providing structural overview | Focused on prompt summarization rather than navigation graphs |
| **CodePlan (2023)** | Plan repository‑level code edits | Dependency analysis and change‑impact reasoning | Recognizes structural dependencies | Focuses on edit planning rather than navigation |
| **RepoUnderstander (2024)** | Enable LLMs to understand entire repositories | Hierarchical repository representation | Shares goal of repository‑level understanding | Emphasizes exploration strategies |
| **CodexGraph (2024)** | Graph database interface between code and LLMs | Graph database representation of repositories | Uses graph structure for navigation | Requires heavier infrastructure |
| **RepoGraph (ICLR 2025)** | Graph representation of repositories | Static dependency graphs used during reasoning | Strong conceptual overlap | Focuses more on graph reasoning than lightweight mapping |
| **GraphCodeAgent (2025)** | Improve AI coding with graph reasoning | Dual graph representation of code relationships | Similar graph‑guided approach | Focused on code generation performance |
| **Code Graph Model (CGM, 2025)** | Integrate code graphs into LLM reasoning | Graph‑based retrieval and reasoning | Uses structural code knowledge | Integrates graphs directly into model reasoning |
| **Repository Intelligence Graph (RIG, 2026)** | Deterministic structural map exposed to AI agents | Static repository analysis producing a graph | Very similar conceptual direction | Emphasizes full architectural knowledge graphs |

---

## Observations

Several patterns appear across recent work:

### 1. Repository Graphs Are Becoming Standard

Many modern systems represent codebases as **graphs of dependencies, modules, and functions**. This suggests graph‑based representations are increasingly seen as a natural abstraction for reasoning about large repositories.

### 2. AI Agents Benefit From Structural Priors

Instead of exploring repositories blindly, systems increasingly provide:

- dependency graphs
- symbol maps
- architecture summaries
- change‑impact predictions

These act as **structural priors** that guide the agent's reasoning process.

### 3. Existing Systems Are Often Heavyweight

Many current approaches rely on complex infrastructures such as:

- graph databases
- multi‑stage reasoning pipelines
- model‑specific integrations

This leaves room for **lightweight, model‑agnostic tools** that provide structural context without requiring large infrastructure.

---

## Positioning of AI Context Map

AI Context Map aims to occupy a lightweight position within this ecosystem.

The system focuses on generating a **deterministic structural navigation layer** for AI coding agents using simple static analysis.

Key characteristics:

- lightweight repository scanning
- deterministic structural signals
- model‑agnostic design
- machine‑readable navigation routes
- minimal infrastructure requirements

Rather than embedding graphs directly into model reasoning, AI Context Map produces a **navigation context that external AI agents can use to guide exploration and modification tasks**.

---

## Potential Research Directions

Future development could explore several directions:

- task‑oriented repository navigation
- automated change‑impact analysis
- incremental repository mapping
- integration with AI coding agents

Possible evaluation metrics include:

- reduction in repository files read by an agent
- reduction in token consumption
- faster bug localization
- improved accuracy of multi‑file modifications

---

## Project Scope

AI Context Map was originally built to support personal AI‑assisted development workflows, with an emphasis on making repository analysis more predictable and easier to inspect.

The project is intended as a lightweight, deterministic, and inspectable solution for repository analysis rather than a comprehensive research platform or tightly coupled agent stack.

Similar ideas appear across recent research and tooling, which reinforces the value of structural repository representations as a practical interface for AI systems.

This repository is public to document the approach, invite experimentation, and encourage others to improve or optimize the graph extraction, ranking, graph signals, and navigation strategies.

---

## Summary

Providing repository structure to AI coding agents is an increasingly active research direction.

AI Context Map explores a **lightweight, deterministic approach to structural navigation**, aiming to provide practical benefits without requiring complex infrastructure.

Even if similar ideas appear in recent work, a simple and model‑agnostic implementation may still offer useful insights and practical value for AI‑assisted software development.

---

## Academic Contact

**Prof. Dr. Michael Graber**  
Lecturer in Machine Learning and Data Science  

**Contact**  
- Phone: +41 56 202 84 08 (Direct)  
- Email: michael.graber@fhnw.ch

---

## License

This project is licensed under the MIT License.
