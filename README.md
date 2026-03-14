# ai-context-map

`ai-context-map` is a Python-first CLI that scans a repository and produces a compact, machine-readable context file for AI coding agents.

It is not a human README replacement. It is a deterministic repository memory and navigation map intended to reduce context reconstruction overhead for AI systems working in a codebase.

## Why it exists

AI coding agents waste time rediscovering repository structure, entry points, important modules, and likely risk areas. This tool builds that map once, in a structured format, without requiring model calls or external services.

## V1 capabilities

- Scan a repository with sensible ignore rules
- Detect Python and basic JS/TS source files
- Parse local imports and build a lightweight dependency graph
- Rank important files using filename, role, and graph signals
- Identify likely entry points, core modules, hotspots, and directory roles
- Emit `.ai/context.yaml`
- Initialize `.ai/history.yaml` and `.aicontext.toml`

## Install locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Usage

Initialize support files:

```bash
aicontext init
```

Generate a context map for the current repository:

```bash
aicontext generate
```

Inspect top results without opening the YAML manually:

```bash
aicontext inspect
```

Generate for another path:

```bash
aicontext generate /path/to/repo
```

## Output

The main output is written to `.ai/context.yaml`.

Example:

```yaml
aicontext_version: 1
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
      score: 10.5
      reasons:
        - high incoming dependency count
navigation_map:
  directories:
    - path: src
      role: source_root
hotspots:
  - path: src/app/service.py
    reason: high centrality
provenance:
  enabled: false
  history_file: .ai/history.yaml
```

## Configuration

`aicontext init` creates `.aicontext.toml`:

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

## Provenance roadmap

V1 creates a stub `.ai/history.yaml`:

```yaml
history_version: 1
entries: []
```

The code is structured so later versions can append repository change history with fields such as timestamp, actor type, model, prompt summary, files changed, notes, and review status.

## Limitations

- Python import resolution is stronger than JS/TS in V1
- Graph resolution is local-project focused and intentionally conservative
- Architectural roles are heuristic, not semantic
- No git churn scoring yet
- No LLM-based summary generation

## Development

```bash
pytest
ruff check .
```

