# UACL architecture in a nutshell (experiment)

Source revision: `0766e58` (main). Hand-written. If HEAD differs, re-check
claims about changed files; a matching revision does not guarantee
correctness. *[inference]* marks claims not stated directly in source or docs.

**Purpose.** Experimental Python CLI, `aicontext`, that compiles AI-readable
context from a repository without calling a model. No proven benefit
(README, "Experimental Status").

## Components

- **CLI**: `cli.py`, thin Typer dispatch.
- **Context compiler**: `commands/{generate,check,export}_cmd.py`,
  `emitter/`, `models/context.py`.
- **Repository analysis** (shared): `scanner/`, `analyzers/` (Python `ast`,
  JS/TS Tree-sitter), `graph/` (import graph, ranking), `navigation/{routes,anchors}.py`.
- **Navigation map**: `navigation/{index,structure,retrieve}.py` behind
  `pack`, `find`, `symbol`.
- **Work state**: `workstate/` behind `checkpoint`, `capture`, `evidence`.

## Flows

```text
generate: scanner/walker → GraphBuilder → rank_files → anchors, task_routes
          + listed hand-maintained fields from existing YAML → .ai/context.yaml
export:   .ai/context.yaml → portable_writer → .ai/exports/{AGENTS.md, …}
          (+ root AGENTS.md only with --write-agents-md)
pack:     build_index (own os.walk) → GraphBuilder + link_records
          → .ai/navigation.json ; + checkpoint → .ai/START_HERE.md
find, symbol: read the stored navigation.json; they do not rebuild it
```

Sources: `generate_cmd.py:32-157`, `export_cmd.py:14-49`,
`index.py:68-247,606-624`, `cli.py:126-190`.

## Data and state

- Authoritative: source code and docs; outputs are compiled (README intro).
- `.ai/context.yaml`: generated analysis plus hand-maintained fields. The
  committed copy was last changed in `3c5ae19` and uses the old key
  `aicontext_version` (`git log -- .ai/context.yaml`), so it is stale.
- `.ai/navigation.json`, `.ai/START_HERE.md`: rebuilt by `pack`, gitignored.
- `.ai/work/`: checkpoint and evidence, self-ignoring (`store.py:16-21`).

## Rules

- `generate` keeps only an explicit list of hand fields
  (`generate_cmd.py:119-136`).
- An existing root `AGENTS.md` is replaced only with `--force`
  (`export_cmd.py:30-49`).
- Entry-file constraints are never truncated; `pack` fails instead
  (`index.py:467`).
- `.ai/` is never indexed or served as source (`index.py:71`, `retrieve.py:72`).
- `IMPORT`/`CALLS` are inferred, not execution flow (`docs/structural-map.md`).
- Budgets are characters, not tokens.

## Status

- Implemented and tested: commands above (`tests/`).
- Experimental and unvalidated with live agents: navigation map, checkpoints
  (`docs/navigation-evaluation.md`, `docs/continuation-evaluation.md`).
- Future only: tracker integration, risk-aware context, agent orchestration,
  session-history import (README).
- Placeholders *[inference]*: `enable_git_metadata` is read only by
  `config.py`; provenance is `enabled=False` (`generate_cmd.py:128`).

## Direction changes

1. **AI Context Map**: navigation and planning. The README at `1702373`
   described `.ai/memory.yaml` and `aicontext plan`. That code exists only
   on unmerged `origin/feature/*` and `origin/benchmark/*` branches. No decision record says whether
   it was abandoned.
2. **UACL** (`81aa6aa`): "cross-model continuity", then repositioned as an
   "experimental context compiler" (`250c526`).
3. `eb84ee5` and `0766e58` added the navigation map and work state.
   Tree-sitter replaced regex JS/TS extraction (`docs/structural-map.md`).
   The "payment processing" message on `0766e58` describes test fixtures
   (`tests/fixtures/jsts`).

**More:** README, `docs/structural-map.md`, `docs/continuation-workflow.md`.
There is no ADR directory.
