# Universal AI Context Layer (UACL)

**Context compiler for AI-assisted development.**

UACL helps generate, validate, and maintain `AGENTS.md` and AI-readable project context from repository sources.

UACL does not replace `AGENTS.md`. It can generate and support `AGENTS.md` while compiling related Markdown and JSON context outputs. Its value is in repeatable compilation, validation, and lightweight drift detection as a repository changes.

Existing source code, README files, documentation, and architecture decision records remain the source of truth. UACL compiles from those sources and preserves explicitly maintained context fields; it does not supersede disciplined project documentation.

UACL is experimental. Its current analysis and validation are intentionally lightweight.

> **Suggested GitHub About:** Context compiler for AI-assisted development. Generate, validate, and maintain AGENTS.md and AI-readable project context from repository sources.

## Why UACL

Project context is often distributed across source code, README files, documentation, architecture decisions, task notes, and existing agent instructions. Even when a project has an `AGENTS.md`, it can become stale as files move and decisions change.

UACL provides a lightweight maintenance workflow:

- **Generate:** analyze repository structure and refresh the canonical context.
- **Compile:** produce `AGENTS.md`, UACL Markdown, and JSON outputs.
- **Validate:** detect missing referenced files, empty important sections, missing outputs, and stale exports.
- **Preserve:** keep human-authored goals, decisions, constraints, tasks, and AI instructions when generated repository analysis is refreshed.

UACL supports repository instruction conventions by maintaining useful context artifacts that existing AI tools can consume.

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
aicontext export --output-dir ./compiled-context
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

## Related Tools / Positioning

UACL exists in a growing ecosystem of tools and conventions around AI context files and `AGENTS.md`. It does not claim to define or own this category.

UACL currently focuses on:

- repository context compilation
- `AGENTS.md` export
- drift and staleness checks
- preserving human-authored context fields

Other tools may provide deeper semantic or AST-based drift detection. UACL's current drift checks are intentionally lightweight.

## Optional Agent Workflows

Shared agent roles and orchestration are a possible use of compiled context, not UACL's core promise. See [`examples/agent-orchestration.yaml`](examples/agent-orchestration.yaml) for a lightweight future-direction example.

## Examples

- [`examples/AGENTS.md`](examples/AGENTS.md): compiled repository instructions
- [`examples/UACL_CONTEXT.md`](examples/UACL_CONTEXT.md): compiled Markdown context
- [`examples/uacl-context.json`](examples/uacl-context.json): machine-readable compiled context
- [`examples/AI_CONTEXT.md`](examples/AI_CONTEXT.md) and [`examples/project-context.json`](examples/project-context.json): compatibility aliases
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

- Drift detection is currently timestamp- and reference-based, not semantic.
- Documentation and ADR ingestion is lightweight.
- UACL does not automatically solve context loss between AI tools.
- UACL does not replace disciplined documentation or make generated outputs authoritative over their repository sources.
- UACL is not yet a full semantic indexer or MCP server.
- UACL does not yet import issues from external trackers, resolve conflicting instructions, or automatically update a hand-authored root `AGENTS.md`.

## License

Licensed under the [Apache License 2.0](LICENSE).
