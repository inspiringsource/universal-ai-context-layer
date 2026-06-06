# Universal AI Context Layer

Universal AI Context Layer (UACL) is a context compiler and maintenance tool for AI-assisted development.

Repository instruction files such as `AGENTS.md` are becoming common conventions for giving coding agents durable project guidance. UACL does not replace `AGENTS.md`. It helps generate, validate, and keep `AGENTS.md` and related context outputs fresh as a project changes.

UACL analyzes repository structure, tracks existing project context, and compiles AI-consumable outputs including `AGENTS.md`, Markdown, and JSON.

> **Short description:** Context compiler for AI-assisted development: generate, validate, and refresh AGENTS.md, Markdown, and JSON context from your repository.

## Why UACL

The problem is not only moving context between AI tools. Context is often fragmented across source code, README files, documentation, architecture decisions, task notes, and existing agent instructions. Even when a project has an `AGENTS.md`, it can become stale as files move and decisions change.

UACL provides a lightweight maintenance workflow:

- **Generate:** analyze repository structure and refresh the canonical context.
- **Compile:** produce `AGENTS.md`, UACL Markdown, and JSON outputs.
- **Validate:** detect missing referenced files, empty important sections, missing outputs, and stale exports.
- **Preserve:** keep human-authored goals, decisions, constraints, tasks, and AI instructions when generated repository analysis is refreshed.

UACL does not solve AI memory and does not compete with repository instruction standards. It maintains useful context artifacts that existing AI tools can consume.

## Context Compiler Model

```text
source code
README and docs
ADRs
existing AGENTS.md
.ai/context.yaml
future issue/task integrations
        |
        v
      UACL
 generate + validate + refresh
        |
        v
AGENTS.md + UACL_CONTEXT.md + JSON
```

The current prototype analyzes Python, JavaScript, and TypeScript repository structure; tracks README, docs, ADRs, existing `AGENTS.md`, and the canonical YAML as context sources; and preserves manually recorded project knowledge. Issue and task-system integrations are future work.

## Outputs

`aicontext export` always compiles outputs under `.ai/exports/`:

- `.ai/exports/AGENTS.md`
- `.ai/exports/UACL_CONTEXT.md`
- `.ai/exports/uacl-context.json`
- compatibility aliases: `AI_CONTEXT.md` and `project-context.json`

To explicitly write a root-level `AGENTS.md`:

```bash
aicontext export --write-agents-md
```

UACL will not overwrite an existing root `AGENTS.md` unless `--force` is also passed:

```bash
aicontext export --write-agents-md --force
```

## Workflow

1. Run `aicontext generate` to analyze the repository and refresh `.ai/context.yaml`.
2. Edit the canonical YAML to record goals, decisions, constraints, tasks, and instructions.
3. Run `aicontext check` to find simple drift and completeness problems.
4. Run `aicontext export` to compile fresh AI-consumable outputs.
5. Optionally write a root `AGENTS.md` explicitly for tools that discover it there.

## Installation

Requires Python 3.11 or newer.

### Recommended: uv

```bash
uv sync --extra dev
uv run aicontext --help
```

`uv.lock` keeps development environments reproducible. uv is recommended, but it is not required.

### Alternative: venv and pip

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Both workflows install `aicontext`. The CLI name, `ai_context_map` Python package, `.aicontext.toml`, and `.ai/context.yaml` remain for compatibility.

## CLI Workflow

```bash
aicontext generate
aicontext inspect
aicontext check
aicontext export
aicontext export --write-agents-md
```

With uv, prefix commands with `uv run`:

```bash
uv run aicontext generate
uv run aicontext inspect
uv run aicontext check
uv run aicontext export
uv run aicontext export --write-agents-md
```

Additional commands:

```bash
aicontext init
aicontext inspect-routes
aicontext export --output-dir ./context-handoff
```

## Canonical Context

`.ai/context.yaml` combines generated repository analysis with human-maintained context:

```yaml
project_goals:
  - Keep generated AI instructions aligned with the repository.
current_tasks:
  - Validate AGENTS.md generation.
decisions:
  - title: Treat AGENTS.md as a compiled output
    rationale: Existing standards should be supported rather than replaced.
constraints:
  - Never overwrite a root AGENTS.md without an explicit force flag.
ai_instructions:
  - Run tests and formatting checks before completing changes.
```

The schema also records:

- `context_sources`
- `generated_outputs`
- `last_generated_at`
- `drift_warnings`
- `validation_warnings`
- `agent_roles`
- `ai_instructions`

## Drift Checks

`aicontext check` performs intentionally lightweight checks:

- important referenced files that no longer exist
- source or documentation newer than the canonical context
- missing `.ai/exports/AGENTS.md`
- missing or stale generated outputs
- empty goals, constraints, tasks, or decisions

Warnings are recorded in the canonical context. This is a practical first pass, not semantic validation of every instruction.

## Optional Agent Workflows

Shared agent roles and orchestration are a possible use of compiled context, not UACL's core promise. See [`examples/agent-orchestration.yaml`](examples/agent-orchestration.yaml) for a lightweight future-direction example.

## Examples

- [`examples/AGENTS.md`](examples/AGENTS.md): compiled repository instructions
- [`examples/UACL_CONTEXT.md`](examples/UACL_CONTEXT.md): compiled Markdown context
- [`examples/uacl-context.json`](examples/uacl-context.json): machine-readable compiled context
- [`examples/agent-orchestration.yaml`](examples/agent-orchestration.yaml): optional future agent workflow

## Development

```bash
uv sync --extra dev
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

GitHub Actions runs the test suite, Ruff linting, and formatting checks on every push and pull request.

## Current Limitations

UACL currently uses lightweight repository analysis and explicit YAML fields. It does not yet semantically merge arbitrary documentation, import issues from external trackers, resolve conflicting instructions, or automatically update a hand-authored root `AGENTS.md`.

## License

Licensed under the [Apache License 2.0](LICENSE).
