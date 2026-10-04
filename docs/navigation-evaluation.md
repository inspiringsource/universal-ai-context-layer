# Evaluate navigation before claiming AI performance gains

The `pack` / `find` experiment aims to reduce unnecessary exploration while
preserving correct decisions. A small entry file alone does not prove any saving.

## Reproducible local proxy

Run `uv run python benchmarks/evaluate_navigation.py` at the repository root.
The six tasks and expected implementation files are recorded in
`benchmarks/navigation_tasks.json`. Both methods receive six shortlist slots.
The baseline is the same repository's existing task-independent file ranking.
The report lists every selected path and the expected file's position, plus
entry size in characters. It makes failures visible.

These tasks were chosen while building the feature, on its own repository. They
are not held-out or independent validation. Expected-file recall does not test
whether an agent makes the correct change, follows instructions, or reads fewer
total tokens. Do not convert the results into a percentage of usage saved.

The structural map has a separate local evaluation on two public JS/TS
repositories, including a comparison with the previous regex extraction and a
scripted targeted-search baseline: see
[structural-map.md](structural-map.md#evaluation). It has the same limits: no
agent was run.

## Live comparison

Use at least ten previously unseen tasks across two additional repositories.
Include a localized bug, a feature crossing module boundaries, a misleading
filename, a decision recorded only in notes, a stale index, and a task with no
lexical match. Keep a separate record of expected behaviour and relevant evidence
before generating a map.

For each task compare:

1. A fresh session with normal repository instructions and native search.
2. A fresh session with a short manually written handoff; for continuation tasks,
   also compare the tool's native compaction/history lookup.
3. A fresh session with identical instructions plus UACL's entry file and `find`.

Run the same starting checkout, request, model, reasoning setting, permissions,
and available tools in each condition. Repeat runs because model outputs vary.
Evaluate Claude Code, Codex, and Gemini separately; don't attribute a difference
between models to UACL. Account for cache state explicitly when comparing old and
fresh conversations.

Record:

- Acceptance result and regressions using task-specific tests or manual criteria.
- Missed constraints, repeated rejected approaches, and clarification needed.
- Source files opened, irrelevant files opened, and pointer retrieval calls.
- Time to the first relevant source and total time to completion.
- Total input/output/cache usage, including any checkpoint creation and retrieval,
  reading of `.ai/START_HERE.md`, and every `aicontext find`/`symbol` call.
- Whether the agent used `symbol` and `CALLS` leads or opened whole files anyway.
- Actual subscription usage change only when exposed and reasonably attributable.

Do not silently exclude unsuccessful tasks. Save failures with their entry file,
query, selected pointers, and missing evidence so the retrieval can be improved.

## Decision rule

Continue if the live comparison shows a repeatable reduction in total usage or
completion time while preserving correctness and constraints. If measured savings
are smaller than run-to-run variability, treat the result as inconclusive. If
agents reread everything, or miss important evidence, improve retrieval or stop
the experiment rather than adding more formats or integrations.

Session history ingestion is a separate future experiment. It must preserve
decisions and uncertainty, retain traceable evidence, and include checkpoint
maintenance costs in the comparison. There is still no session-history capture
or automatic agent integration. Explicit checkpoints and command capture are
covered in [continuation-workflow.md](continuation-workflow.md) and
[continuation-evaluation.md](continuation-evaluation.md).
