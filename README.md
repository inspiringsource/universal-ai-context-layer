# Universal AI Context Layer (UACL)

**Experimental context compiler for AI-assisted development.**

UACL is a prototype that generates, validates, and maintains `AGENTS.md` and AI-readable project context from repository sources.

UACL does not replace `AGENTS.md`. It can generate and support `AGENTS.md` while compiling related Markdown and JSON context outputs. Its intended role is to explore repeatable compilation, validation, and lightweight drift detection as a repository changes.

Existing source code, README files, documentation, and architecture decision records remain the source of truth. UACL compiles from those sources and preserves explicitly maintained context fields; it does not supersede disciplined project documentation.

## Start with a small task-specific map

The new experimental `pack` workflow creates a compact entry file and a local
searchable index without calling a model:

```bash
uv run aicontext pack --task "prevent export overwriting root AGENTS without force"
```

It writes two generated files:

- `.ai/START_HERE.md`: a bounded starting map, normally six references rather than a full repository dump, with a few task-relevant declarations, imports, and call links under each code reference.
- `.ai/navigation.json`: the complete index for on-demand lookup: file fingerprints, declarations with qualified names, line ranges and signatures, Markdown headings, import specifiers and their resolution, and syntactic call links. Source bodies are not stored.

In a fresh Claude Code, Codex, Gemini, or other file-capable agent session, ask:

> Read `.ai/START_HERE.md`, follow applicable repository instructions, and inspect the relevant sources before continuing my task. Use `aicontext symbol PATH::NAME` to read a listed definition instead of a whole file.

The format is ordinary Markdown and JSON; automatic loading and agent behaviour
have not been verified across those tools. You must explicitly direct the agent
to the entry file. This does not modify their conversation storage or billing.

For another question, retrieve a small set of pointers instead of loading the full index:

```bash
uv run aicontext find "resolve relative imports"
uv run aicontext find "reconcile_invoice" --limit 4 --max-chars 2000
```

To read one definition rather than a whole file, retrieve it by path and
qualified name (bounded, line-numbered, fingerprint-checked):

```bash
uv run aicontext symbol src/payments.ts::RefundService.process
uv run aicontext symbol src/payments.ts --list          # declarations and imports of one file
uv run aicontext symbol lib/core/Axios.js::Axios --max-lines 40   # or --full
```

A map entry from a real repository (axios) looks like this:

```text
- `lib/core/buildFullPath.js` [current; business_logic]: matches path, relative, url
  EXPORT function buildFullPath(baseURL, requestedURL, allowAbsoluteUrls, config) @68-76 (default export)
  CALLS from buildFullPath: isAbsoluteURL → lib/helpers/isAbsoluteURL.js::isAbsoluteURL; combineURLs → lib/helpers/combineURLs.js::combineURLs
```

`EXPORT`/`DEF` lines and import specifiers are parsed syntax facts (Tree-sitter
for JavaScript, JSX, TypeScript, and TSX; Python's `ast` for Python). `IMPORT a
→ b`, `CALLS`, and `TEST-CANDIDATE` are inferred relationships: a resolved path,
or a callee matched to the declaration an import binds. They are not verified
execution flow. The checkpoint section holds conclusions an agent recorded,
kept separate from both. Unresolved and ambiguous imports, and files the
parser read only partially, are marked. See
[the structural map guide](docs/structural-map.md) for notation, limits, and
evaluation.

`pack` also accepts a repository path and `--max-chars`. The default budget is
6,000 **characters**, not tokens. Entire references are omitted when the budget
is exhausted; the output reports omissions and never cuts an instruction pointer
in half. If the required navigation text cannot fit, the command fails before
writing outputs.

Search matches paths, Python identifiers and lookup keys, Python symbols,
JavaScript/TypeScript declared names (parsed with Tree-sitter), and Markdown
headings. Declarations within a file are ranked by their names and the words
used in their bodies. It prioritizes
direct matches and includes related tests through resolved imports. Import-linked
tests are candidates, not proof of coverage. This is lexical retrieval, not
semantic understanding. A query with no matching terms reports no match rather
than offering unrelated files as a confident answer.

Selected references are checked against content fingerprints. Changed files are
marked `STALE`, and old line numbers are suppressed. This does not detect newly
added files or refresh unselected references; rerun `pack` after repository changes.

The map points to existing `.ai/context.yaml` fields for recorded goals, decisions,
constraints, and tasks without rewriting that file. **It does not yet import or
summarize Claude/Codex/Gemini session history.** Root `AGENTS.md`, `CLAUDE.md`, and
`GEMINI.md` are preserved and referenced. Ancestor and directory-scoped instructions
must still be discovered by the agent.

The index respects UACL's configured include/exclude paths and built-in ignored
directories, prunes them before traversal, and skips symlinks and its own `.ai`
outputs. It does not parse `.gitignore`. Files above 1 MB, invalid Python, and
non-UTF-8 files are left unanalyzed with warnings. JS/TS files with syntax the
grammar rejects are kept, marked `parse partial`, and declarations in the
unparsed region are recovered by a labelled line scan. Only configured Python,
JavaScript (`.js`, `.jsx`), and TypeScript (`.ts`, `.tsx`) sources, Markdown,
and selected manifest filenames are indexed. Literal dynamic imports and root
`tsconfig.json`/`jsconfig.json` `paths` are resolved; `extends`, package export
maps, and non-literal imports are not.

Evaluate the navigation experiment locally:

```bash
uv run python benchmarks/evaluate_navigation.py
```

This compares six-reference task shortlists with UACL's task-independent file
ranking on six transparent tasks in this repository. It measures file discovery,
not completed AI tasks, time, billed usage, or savings. See
[the live evaluation protocol](docs/navigation-evaluation.md) before making
performance claims.

The structural map was evaluated locally on 17 tasks in two public JS/TS
repositories (hono, axios) against the previous regex version and a scripted
targeted search, with a fixed 6,000-character entry budget. It located 14 of
24 expected symbols (previous: 4; search: 0) and named 15 of 24 expected files
(previous: 12; search: 8), but placed the same 12 files in the shortlist as
before, and the entry roughly doubled (about 1,800 → 3,300 characters per
task). Total characters exposed under the stated reading rules were about
equal to the previous workflow's. The tasks were written by the implementer and
informed two design changes, so this is a development benchmark, not held-out
validation. No agent runs were made. Details and reproduction:
[docs/structural-map.md](docs/structural-map.md#evaluation).

## Continue in a fresh session with a checkpoint (experimental)

An agent can explicitly record a small working checkpoint, keep verbose command
output on disk, and hand over through `.ai/START_HERE.md`. No model is called,
no hooks are installed, and no native Claude/Codex/Gemini session files are read.

```bash
# Run a noisy command; full stdout/stderr are kept, a bounded receipt is printed.
uv run aicontext capture --label "tests" -- uv run pytest -v

# Record objective, next action, constraints, decisions, verification (JSON on stdin).
uv run aicontext checkpoint template
uv run aicontext checkpoint update - < checkpoint-update.json
uv run aicontext checkpoint show

# Entry file: objective, next action, every active constraint, blockers, then
# optional detail and code pointers within a character budget.
uv run aicontext pack

# In the fresh session, retrieve only what is needed.
uv run aicontext evidence show ev-... --grep "FAILED|Error"
uv run aicontext evidence show ev-... --stream stdout --lines 120-180
```

Records are identifiable and labelled by basis (user instruction, observed
with evidence, agent decision, unverified assumption). Constraints are never
truncated: if they cannot fit the budget, `pack` fails instead of writing a
misleading briefing. State lives in `.ai/work/`, which ignores itself in Git.

This reduces context only when a fresh session starts from the small entry
file, or when a receipt replaces verbose output before it enters context. It
does not shrink an active conversation, and writing the checkpoint has a cost.
`uv run python benchmarks/capture_demo.py` reproduces an output-size
measurement (characters, not tokens or billing; results in
`benchmarks/capture-results.json`). Live continuation quality and total usage
are **untested**. See [the workflow guide](docs/continuation-workflow.md),
including an instruction to paste into any agent, and
[the prepared live comparison](docs/continuation-evaluation.md).

## Experimental Status

UACL is an experimental project.

It explores whether generated and maintained AI-readable context files can improve AI-assisted development workflows across tools such as Claude, Codex, Cursor, Gemini, and others.

At this stage, there is no strong evidence that this approach consistently improves results across different models or coding agents. The project is kept open and documented as an exploration of the problem space: context drift, stale AI instructions, repository-aware context compilation, and cross-tool AI workflows.

The current value of UACL is primarily:

- documenting the experiment clearly
- providing a small working prototype
- making assumptions and limitations explicit
- creating a base for future validation or refinement

## Validation Needed

The main open question is whether generated context actually helps AI coding agents in practice.

Future validation should compare:

- agent runs with and without UACL-generated context
- task completion quality
- number of irrelevant files read
- incorrect assumptions
- token usage
- test selection
- whether stale or generated context hurts more than it helps

Until such testing exists, UACL should be treated as an experiment rather than a recommended production workflow.

> **Suggested GitHub About:** Experimental context compiler for AI-assisted development. Generates and validates AGENTS.md and AI-readable project context from repository sources.

## Why UACL

Project context is often distributed across source code, README files, documentation, architecture decisions, task notes, and existing agent instructions. Even when a project has an `AGENTS.md`, it can become stale as files move and decisions change.

UACL provides a lightweight maintenance workflow:

- **Generate:** analyze repository structure and refresh the canonical context.
- **Compile:** produce `AGENTS.md`, UACL Markdown, and JSON outputs.
- **Validate:** detect missing referenced files, empty important sections, missing outputs, and stale exports.
- **Preserve:** keep human-authored goals, decisions, constraints, tasks, and AI instructions when generated repository analysis is refreshed.

UACL attempts to support repository instruction conventions by maintaining context artifacts that existing AI tools can consume.

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

Dependencies include `tree-sitter` with the `tree-sitter-javascript` and
`tree-sitter-typescript` grammars (MIT; prebuilt wheels for common platforms).
See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for versions, upstream
URLs, and required notices.

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

Warnings are recorded in the canonical context. This provides a lightweight first pass, not semantic validation of every instruction.

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

## Possible Future Direction

A stronger future direction may be risk-aware context rather than broad context generation.

Instead of trying to tell an AI agent everything about a repository, UACL may evolve toward surfacing task-specific warnings that are difficult to infer from code alone, such as:

- files or areas involved in repeated regressions
- hidden coupling between files that often change together
- fragile modules with repeated hotfixes or reverts
- AI-generated code that needs extra review
- tests that may provide false confidence

This direction still needs validation before implementation.

## Current Limitations

- There is no proven productivity improvement from using UACL yet.
- Generated context may become stale.
- Generated context may harm results when it is wrong, incomplete, or noisy.
- Current drift checks are lightweight, timestamp- and reference-based rather than semantic.
- UACL is not recommended as a production workflow without validation.
- Documentation and ADR ingestion is lightweight.
- UACL does not automatically solve context loss between AI tools.
- UACL does not replace disciplined documentation or make generated outputs authoritative over their repository sources.
- UACL is not yet a full semantic indexer or MCP server. Its JS/TS map has no type or scope analysis; call links are name matches through imports.
- UACL does not yet import issues from external trackers, resolve conflicting instructions, or automatically update a hand-authored root `AGENTS.md`.

## License

Licensed under the [Apache License 2.0](LICENSE). Third-party components and
their notices are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
