# AI Context Map

`ai-context-map` is a lightweight CLI that builds a deterministic repository memory and planning layer for AI coding agents.

Instead of forcing an AI to rediscover repository structure through repeated search and file exploration, the tool precomputes a structured memory of the codebase and applies task-aware planning to guide navigation.

A lightweight, deterministic alternative to embedding-based or prompt-based repo understanding tools.

The goal is simple:

Help an AI agent quickly determine where to look first before making a change.

The system extends beyond static mapping by introducing:

- a repository memory layer (.ai/memory.yaml)
- memory-first planning
- task-focused working clusters

This allows AI agents to operate on a coherent working area, not just isolated files.

---

## Positioning

AI Context Map is a lightweight, deterministic alternative to embedding-based or prompt-based repository understanding tools.

It combines:
- structural analysis
- repository memory
- task-aware planning

to guide AI agents toward the most relevant working areas before performing modifications.

The system is fully deterministic, inspectable, and model-agnostic.

---

# Why this exists

AI coding agents often struggle with large repositories because they must first infer architecture from raw files.

Typical behavior:

- searching randomly across the repo
- opening many irrelevant files
- missing central modules
- making narrow edits that break downstream code

ai-context-map precomputes a repository navigation + memory layer so an AI can start from the most relevant locations immediately.

Instead of:

AI → search → read random files → infer structure

The workflow becomes:

Repository → memory + structure → guided planning → code change

The result is faster inspection, less token usage, and more reliable edits.

---

# Core capabilities

- Scan a repository with sensible ignore rules
- Detect Python and basic JS/TS source files
- Parse local imports and build a lightweight dependency graph
- Rank important files using deterministic structural signals (PageRank + heuristics)

- Build a repository memory layer (.ai/memory.yaml) including:
  - repository zones (api, service, config, etc.)
  - cluster seeds (related file groups)
  - test mappings
  - central files
  - task-route priors

- Perform memory-first task planning
- Generate task-focused working clusters for coherent multi-file changes
- Explain file selection with traceable reasoning

- Emit:
  - .ai/context.yaml
  - .ai/memory.yaml

- Initialize:
  - .ai/history.yaml
  - .aicontext.toml

The tool intentionally avoids LLM calls and external services so the output remains deterministic and reproducible.

---

# Ranking Mechanism

AI Context Map ranks files using a deterministic hybrid scoring model built from structural signals extracted from the repository.

1. Dependency Graph Construction  
2. PageRank centrality  
3. Heuristic structural signals  
4. Score blending  

This balances architectural centrality and role-based heuristics.

---

# Task Planning

aicontext plan "<task description>"

Example:

aicontext plan "update api route behavior"

Output:
- read_first
- edit_candidates
- impacted_files
- likely_tests
- working_cluster

JSON:
aicontext plan "<task>" --json

---

# Architectural Direction

Two-stage design:

1. Repository memory (cheap, precomputed)
2. Task-specific planning (focused, dynamic)

Separates memory (cheap) from reasoning (expensive).

---

# Install locally

python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

---

# Usage

aicontext init
aicontext generate
aicontext inspect
aicontext inspect-routes

---

# Output

.ai/context.yaml  
.ai/memory.yaml  

---

# Limitations

- Python-first symbol extraction
- minimal JS/TS analysis
- heuristic-based detection

---

# Development

pytest
ruff check .

---

# Related Work

Graph-constrained Reasoning (ICML 2025)  
https://github.com/RManLuo/graph-constrained-reasoning

## DeepSeek Engram (Conditional Memory)

**Conditional Memory via Scalable Lookup: A New Axis of Sparsity for Large Language Models**  
Cheng et al., DeepSeek-AI

Paper: https://arxiv.org/abs/2601.07372

This work introduces a separation between neural computation and static memory using efficient lookup mechanisms (Engram).

### Relationship to AI Context Map

DeepSeek integrates memory **inside the model**, enabling constant-time lookup for stored patterns.

AI Context Map applies a similar principle **outside the model**:

- repository structure is precomputed as memory  
- task planning operates on this memory layer  
- expensive reasoning is applied only to relevant regions  

Both approaches share the same core idea:

> separate memory from reasoning to reduce unnecessary computation

### Key Difference

| DeepSeek Engram | AI Context Map |
|----------------|---------------|
| Memory inside LLM | Memory outside LLM |
| Token-level / pattern memory | Repository-level structural memory |
| Improves model efficiency | Improves navigation and task execution |

---

# Summary

AI Context Map provides a deterministic navigation + memory layer for AI coding agents.

---

## Authors

- Abraham Bobrovsky
- Marco Benedetti

---

## License

Copyright (c) 2026 Abraham Bobrovsky, Marco Benedetti

All rights reserved.
