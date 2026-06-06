# Universal AI Context Layer

Universal AI Context Layer (UACL) is a portable, model-independent context layer for AI-assisted development.

The project began as an AI context map focused on repository navigation. UACL expands that idea into a vendor-neutral continuity layer that combines repository intelligence with durable project knowledge: goals, architecture, decisions, constraints, tasks, known issues, AI instructions, and agent roles.

UACL helps developers carry the same project context through Claude, ChatGPT, Cursor, Codex, Gemini, and future AI tools without repeatedly rebuilding context from isolated conversations.

## Why UACL

AI-assisted development often fragments project knowledge across tools and chat sessions. Switching tools can mean repeating architecture decisions, losing constraints, and creating inconsistent implementation plans.

UACL provides a shared source of truth that is:

- **Portable:** export project context as Markdown or JSON.
- **Model-independent:** use the same context across vendors and models.
- **Structured:** preserve goals, architecture, decisions, constraints, tasks, issues, instructions, and agent roles.
- **Repository-aware:** identify important files, entry points, code anchors, hotspots, and task-focused routes.
- **Workflow-oriented:** maintain continuity between research, architecture, implementation, and review.
- **Versionable:** keep the canonical context file alongside the codebase.

UACL does not claim to solve AI memory. It provides a practical, explicit context handoff layer that developers and agents can inspect, edit, version, and transfer.

## Cross-Model Continuity

```text
Claude -> ChatGPT -> Cursor -> Codex -> Gemini
           same project context
           same decisions
           same constraints
           continuous developer workflow
```

The canonical `.ai/context.yaml` combines generated repository intelligence with human-authored project context. Running `aicontext generate` refreshes repository analysis while preserving durable continuity fields already recorded in the file.

## Portable Exports

`aicontext export` writes preferred UACL exports:

- `.ai/exports/UACL_CONTEXT.md`
- `.ai/exports/uacl-context.json`

It also writes compatibility aliases for existing integrations:

- `.ai/exports/AI_CONTEXT.md`
- `.ai/exports/project-context.json`

The preferred and compatibility files contain equivalent context.

## Demo Workflow

1. A developer starts a project with Claude and defines initial goals and architecture.
2. UACL scans the repository and stores generated context plus project decisions, tasks, and constraints in `.ai/context.yaml`.
3. The developer exports `UACL_CONTEXT.md` or `uacl-context.json`.
4. The developer switches to ChatGPT, which reads the portable context and continues without a complete project re-explanation.
5. The developer switches to Cursor or Codex for implementation using the same decisions, constraints, tasks, and important-file guidance.
6. Reviewer and architecture agents read and update the shared context for the next workflow stage.

## Agent Orchestration

Specialized agents can coordinate through the same UACL context instead of isolated conversations:

| Agent | Shared-context responsibility |
| --- | --- |
| Coordinator Agent | Prioritizes tasks and keeps agent work aligned |
| Research Agent | Records findings, alternatives, and unresolved questions |
| Coding Agent | Implements scoped tasks using architecture and constraints |
| Architecture Agent | Maintains system boundaries and architecture decisions |
| Reviewer Agent | Checks changes against goals, decisions, constraints, and known issues |

See [`examples/agent-orchestration.yaml`](examples/agent-orchestration.yaml).

## Installation

Requires Python 3.11 or newer.

### Recommended: uv

Install the project and development tools from the committed lockfile:

```bash
uv sync --extra dev
```

[`uv`](https://docs.astral.sh/uv/) provides fast dependency resolution and installation. The committed `uv.lock` file keeps development environments reproducible. uv is recommended, but it is not required.

Run the CLI through the managed environment:

```bash
uv run aicontext --help
```

### Alternative: venv and pip

Contributors who do not use uv can continue to use a standard virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Both workflows install `aicontext`, the CLI for Universal AI Context Layer. The command and `ai_context_map` Python package retain their existing names for backward compatibility.

## CLI Workflow

Initialize UACL configuration and provenance files:

```bash
uv run aicontext init
# or, from an activated pip/venv environment:
aicontext init
```

Generate or update the canonical context:

```bash
uv run aicontext generate
# or:
aicontext generate
```

Edit `.ai/context.yaml` to record project-specific knowledge:

```yaml
project_goals:
  - Preserve context when developers switch AI tools.
current_tasks:
  - Validate context handoffs across multiple models.
decisions:
  - title: Keep YAML as the canonical context
    rationale: It is readable, editable, and version-control friendly.
constraints:
  - Do not send repository content to a remote service automatically.
ai_instructions:
  - Read this context before changing code.
agent_roles:
  - name: Reviewer Agent
    responsibility: Validate changes against decisions and constraints.
```

Inspect goals, tasks, decisions, important files, and hotspots:

```bash
uv run aicontext inspect
# or:
aicontext inspect
```

Inspect task-focused routes and code anchors:

```bash
uv run aicontext inspect-routes
# or:
aicontext inspect-routes
```

Export portable UACL context:

```bash
uv run aicontext export
# or:
aicontext export
```

Choose a custom export directory:

```bash
uv run aicontext export --output-dir ./context-handoff
```

Every command accepts an optional repository path:

```bash
uv run aicontext generate ../another-project
```

## Development

With uv:

```bash
uv sync --extra dev
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

With an activated pip/venv environment, run the same tools directly:

```bash
pytest -q
ruff check .
ruff format --check .
```

## CI

GitHub Actions runs the test suite, Ruff linting, and formatting checks on every push and pull request.

## Context Schema

UACL context includes:

- project summary and goals
- detected or declared tech stack
- inferred architecture and important files
- current tasks and task-focused routes
- decisions and rationale
- constraints and known issues
- AI instructions and agent roles
- code anchors, hotspots, and generation metrics

Generated repository intelligence is refreshed by `aicontext generate`. Human-authored continuity fields are preserved from the existing canonical file.

## Examples

- [`examples/UACL_CONTEXT.md`](examples/UACL_CONTEXT.md): preferred portable Markdown handoff
- [`examples/uacl-context.json`](examples/uacl-context.json): preferred machine-readable handoff
- [`examples/AI_CONTEXT.md`](examples/AI_CONTEXT.md): compatibility Markdown filename
- [`examples/project-context.json`](examples/project-context.json): compatibility JSON filename
- [`examples/agent-orchestration.yaml`](examples/agent-orchestration.yaml): shared agent roles

## Compatibility

The repository and Python distribution use the name `universal-ai-context-layer`. Existing technical identifiers remain where changing them would unnecessarily break users:

- CLI command: `aicontext`
- Python import package: `ai_context_map`
- configuration file: `.aicontext.toml`
- canonical context file: `.ai/context.yaml`
- compatibility exports: `AI_CONTEXT.md` and `project-context.json`

## Current Scope

UACL is an experimental prototype. It currently analyzes Python, JavaScript, and TypeScript repository structure, preserves explicit project context, and exports portable Markdown and JSON handoffs. It does not connect directly to AI provider APIs or automatically merge concurrent agent updates.

## License

Licensed under the [Apache License 2.0](LICENSE).
