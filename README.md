# AI Context Map

`ai-context-map` is a lightweight CLI that builds a **deterministic repository memory and planning layer** for AI coding agents.

Instead of forcing an AI to rediscover repository structure through repeated search and file exploration, the tool precomputes a **structured memory of the codebase** and applies **task-aware planning** to guide navigation.

**A lightweight, deterministic alternative to embedding-based or prompt-based repo understanding tools.**

---

## Core Idea

> Provide a **deterministic, inspectable, precomputed navigation + memory layer** so AI agents know **where to look and how to act before touching code**.

---

## System Overview

AI Context Map introduces **three core layers**:

1. **Structural Mapping** (`.ai/context.yaml`)
2. **Repository Memory** (`.ai/memory.yaml`)
3. **Task-Aware Planning** (CLI `plan`)

This transforms AI behavior from:

AI → search → random reads → guess structure

into:

Repository → memory → guided planning → focused execution

---

# Why this exists

AI coding agents struggle with:

- large repositories
- implicit architecture
- hidden dependencies
- multi-file coupling

Typical failure modes:

- opening irrelevant files
- missing central modules
- making local fixes that break global logic
- excessive token usage

AI Context Map solves this by **externalizing structure and memory before inference**.

---

# Core capabilities

### Structural Analysis
- Repository scanning with ignore rules
- Python + basic JS/TS support
- Dependency graph construction
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
- Plan task-oriented investigation using structural ranking, keyword priors, and repository memory
- Emit `.ai/context.yaml`
- Initialize `.ai/history.yaml` and `.aicontext.toml`

### Deterministic Ranking
- PageRank centrality
- filename heuristics
- entrypoint detection
- directory roles

### Repository Memory (NEW)
Generated in `.ai/memory.yaml`:

- repository zones (api, service, config, etc.)
- cluster seeds (graph + directory + role + test relationships)
- test mappings (implementation ↔ tests)
- central files (top-ranked nodes)
- task-route priors

### Planning Engine (NEW)

```
aicontext plan "<task>"
```

Produces:

- read_first
- edit_candidates
- impacted_files
- likely_tests
- working_cluster

### Working Clusters

Instead of isolated files, the system groups:

- implementation
- dependencies
- tests
- related modules

---

# Architectural Design

## Two-Stage Model

### 1. Repository Memory (cheap)
- precomputed
- static
- deterministic

### 2. Task Planning (focused)
- dynamic
- task-aware
- memory-constrained

This follows a key principle:

> Separate memory (cheap) from reasoning (expensive)

---

# Ranking Mechanism

1. Dependency Graph Construction  
2. PageRank Centrality  
3. Heuristic Signals  
4. Score Blending  

Outputs:

- core_modules
- hotspots
- key_files

---

# Memory Layer Design

Memory is structured into:

### Repository Zones
Logical grouping:
- api
- service
- config
- tests
- utils
- cli
- models

### Cluster Seeds
Generated using:
- graph neighbors
- test relationships
- directory similarity
- role similarity

### Test Mapping
Automatic detection:
implementation → tests

### Central Files
Top ranked nodes with explanations

### Task Route Priors
Precomputed entry points per task type

---

# Task-Aware Planning (Next Step / USP)

Future extension:

Task → Task Type → Strategy → Plan

Types:
- bugfix
- feature
- refactor
- test_fix
- config_change

Each modifies planning behavior.

---

# Install

```
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

---

# Usage

```
aicontext init
aicontext generate
aicontext inspect
aicontext inspect-routes
```

Plan where to read and edit for a natural-language task:

```
aicontext plan "fix login bug"
```

Emit the same plan as JSON:

```
aicontext plan "fix login bug" --json
```

Generate context for another path:

```
aicontext generate /path/to/repo
```

The planner combines the existing structural ranking with lightweight task keyword priors and repository memory from recent co-change history.
Impacted-file suggestions are derived from likely edit candidates using structural neighbors and repository memory.

Planner output sections:

- `Read first`: best starting points for investigation
- `Likely edit candidates`: files most likely to need changes
- `Likely impacted files`: nearby files likely affected by the change
- `Likely tests`: tests that look relevant to validate or update

---

# Output

```
.ai/context.yaml
.ai/memory.yaml
```

---

# Limitations

- Python-first
- JS/TS limited
- heuristic-based
- no semantic analysis

---

# Related Work

## Graph-Constrained Reasoning
Luo et al., ICML 2025  
https://github.com/RManLuo/graph-constrained-reasoning  

## DeepSeek Engram
Cheng et al., 2026  
https://arxiv.org/abs/2601.07372  

### Insight

DeepSeek:
- memory INSIDE model

AI Context Map:
- memory OUTSIDE model

---

# Mini Literature Review

| Work | Idea | Difference |
|-----|-----|-----|
| RepoMap | summaries | not structural |
| CodePlan | planning | no memory layer |
| RepoGraph | graph reasoning | heavier |
| RIG | full graph | complex infra |

---

# Positioning

AI Context Map =

lightweight + deterministic + inspectable + memory-first

---

# Summary

AI Context Map introduces a new abstraction:

> Repository Memory + Task-Aware Planning

---

## Authors

- Abraham Bobrovsky  
- Marco Benedetti  

---

## License

Copyright (c) 2026 Abraham Bobrovsky, Marco Benedetti  
All rights reserved.
