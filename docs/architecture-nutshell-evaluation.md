# Architecture overview experiment: evaluation

**Question.** Does a compact, hand-written architectural overview
([architecture-nutshell.md](architecture-nutshell.md)) help a fresh agent
understand this project and investigate it more efficiently? This includes
telling current behaviour apart from intended or superseded behaviour.

**Result in one line.** All six live runs were correct, with or without the
overview. The overview introduced no architectural errors, but it did not make
the investigations cheaper: total input-side tokens were about 25% higher with
it. **Recommendation: stop developing this approach. Do not automate it.**

This was an internal feasibility screen on UACL's own repository. The same
person wrote the tasks, the overview and the grades. It is not independent
validation, and it says nothing about other models, agents or projects.

## 1. Starting point (frozen)

- Commit `0766e581b2f47064d2f416bc74a07c2d1c9f57c6` on `main`, clean working
  tree.
- Ignored local files: `.ai/START_HERE.md`, `.ai/navigation.json` and
  `src/*.egg-info/`.
- `.ai/context.yaml` is tracked. It was last changed in `3c5ae19`.
- Every run used a copy of one snapshot taken before any experiment file
  existed. The copy included `.git` with its remote-tracking branches and the
  `.ai/` files, but not `.venv` or caches.
- The repository's `.ai/` files were not modified.

## 2. Frozen protocol

All of the following was fixed before the overview was written and before any
run. The private answer key (expected answers with sources) was kept outside
every working copy and is not published. The required criteria below are the
same as in that key.

**Tasks.** The wording was identical in both conditions; the full prompts are
in the run records.

| Task | Kind | PASS requires every item below (otherwise FAIL) |
| --- | --- | --- |
| T1 | Responsibility boundary: make `pack`/`find` respect `.gitignore` | (R1) names `navigation/index.py::build_index` as where the index's files are selected; (R2) notes `generate` uses a separate traversal (`scanner/walker.py`) and/or that `IgnoreRules` is shared with it; (R3) recommends a consistent location. Automatic fail: claims pack uses `scan_repository`. |
| T2 | Cross-component flow: hand-edited constraints → `generate` → `export --write-agents-md`; plus a new `known_risks` field | (R1) generate copies an explicit list of fields and rewrites the file; (R2) export renders from the YAML into `.ai/exports/`, and writes root `AGENTS.md` only with the flag; (R3) does not replace an existing root `AGENTS.md` without `--force`; (R4) a new field must be added to the model and the copy list, or regeneration drops it, and to `render_agents_markdown`. Automatic fail: arbitrary keys preserved; constraints extracted from docs; root overwritten by default. |
| T3 | Outdated claim: an older description of `.ai/memory.yaml` and `aicontext plan` | (R1) not on `main`, with source evidence; (R2) cites the history (README at `1702373`/`5e4dcba` or the unmerged branches); (R3) names a current mechanism (`pack`/`find`/`symbol` or `inspect-routes`); (R4) does not claim a recorded decision to abandon it, and marks abandonment as not established. Automatic fail: `plan` exists; a decision record says it was abandoned; it was merged and then removed. |

T3 uses a real direction change. The README on `main` at `1702373` described a
repository memory and an `aicontext plan` planner. The code exists only on
unmerged branches (`origin/feature/context-memory-layer`,
`feature/planner-json-and-impact`, `feature/repo-memory-layer-v2`,
`origin/benchmark/combined-context-features`). `5e4dcba` called `plan`
"intended". `81aa6aa` renamed the project to UACL, and `250c526` repositioned
it as an experimental context compiler. Nothing records whether the planner
was abandoned.

**Conditions.**

- **A (normal exploration):** the repository's own instructions (there are no
  root `AGENTS.md` or `CLAUDE.md` files), its documentation, and the native
  tools.
- **B (with overview):** identical, plus the frozen overview (sha256
  `e66d9dd1…`) pasted into the prompt after this sentence:
  "Additional starting context: an architectural overview of this repository,
  `docs/architecture-nutshell.md` (not present in your working copy),
  follows."
- Because the overview was part of the prompt, B's usage includes reading it.

**Common instruction.**

- The investigation is read-only. Do not write files, run `aicontext` or commit.
- Support conclusions with file:line or commit/branch references.
- Distinguish facts from inference and uncertainty.
- Answer in about 600 words or fewer, under the headings Answer, Evidence and
  Uncertainty.

**Runs.** One fresh `claude -p` process per run (Claude Code 2.1.289), in its
own copy of the snapshot, with these flags:

```text
--model claude-opus-5-5 --effort medium --output-format stream-json --verbose
--no-session-persistence --strict-mcp-config --no-chrome --disable-slash-commands
--setting-sources project,local --tools Read,Grep,Glob,Bash
--permission-mode dontAsk --permission-prompts none --max-budget-usd 5
--allowedTools "Bash(git log|show|branch|ls-tree|ls-files|grep|diff|status|rev-parse|blame|merge-base|cat-file|rev-list|for-each-ref:*)"
               "Bash(ls|cat|head|tail|wc|grep|rg|find|sed -n|tree:*)"
```

(The allow list was passed as one `Bash(<cmd>:*)` entry per command.)

- **Isolation.** Each run started with no conversation history, memory, MCP
  servers or user settings. A smoke test before the runs confirmed two things:
  writes were denied, and reads outside the working copy were denied through
  both Read and Bash. Every working copy's `git status` was the same before
  and after its run.
- **Order.** The order was randomized with seed 20261004:
  T1-B, T1-A, T2-B, T2-A, T3-A, T3-B. The runs were sequential.
- **Limit (declared in advance).** 900 s wall clock or $5 as reported by the
  tool. A run that hit the limit or ended without an answer would count as a
  failure. None hit the limit.
- **Grading.** One person (the experimenter) graded against the frozen
  criteria. Grading was not blind, because B answers mention the overview.

## 3. Results

Usage is as reported by Claude Code's `result` event, all from
`claude-opus-5-5` with no other models used. "Input side" means uncached
input plus cache creation plus cache reads. Thinking tokens are part of the
output tokens.

| Run | Accepted | Turns | Tool calls | Input | Cache create | Cache read | Input side | Output | Wall s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| T1-A | pass (3/3) | 7 | 6 | 12 | 20,524 | 75,300 | 95,836 | 3,695 | 36.9 |
| T1-B | pass (3/3) | 9 | 8 | 16 | 23,478 | 134,602 | 158,096 | 3,840 | 38.7 |
| T2-A | pass (4/4) | 9 | 8 | 14 | 26,181 | 112,726 | 138,921 | 4,114 | 52.5 |
| T2-B | pass (4/4) | 14 | 13 | 16 | 28,692 | 146,700 | 175,408 | 4,368 | 41.1 |
| T3-A | pass (4/4) | 18 | 17 | 18 | 18,349 | 119,807 | 138,174 | 4,739 | 44.3 |
| T3-B | pass (4/4) | 19 | 18 | 18 | 16,931 | 113,928 | 130,877 | 4,769 | 44.5 |
| **A total** | 3/3 | 34 | 31 | | | | **372,931** | 12,548 | 133.7 |
| **B total** | 3/3 | 42 | 39 | | | | **464,381** (+24.5%) | 12,977 (+3.4%) | 124.3 |

- **Correctness.** Every run met every required criterion.
- **Missed rules.** No run missed a required rule.
- **Unsupported claims.** T2-B made one minor, non-architectural slip. It
  attributed the need for a field default to `slots=True`; the actual cause is
  dataclass field ordering, which it also stated.
- **Project direction.** No run was confused about it. Both T3 runs separated
  "never merged" from "abandoned", said that abandonment is not established,
  and labelled "pack succeeded plan" as an inference.

**Did the overview influence exploration?**

- **T1-B: yes, for orientation.** Its second tool call went straight to
  `navigation/index.py`. T1-A first read `scanner/walker.py` and found
  `build_index` by searching on its third call. T1-B also checked that HEAD
  matched the overview's revision and said the overview's flow claims match
  the code. Even so, it made more calls and read more context.
- **T2-B: yes.** It confirmed the overview's generate/export rules against the
  source. Its higher call count came mostly from recovering after a denied
  compound `cd … && cat` command, then rereading the same files with Read.
- **T3-B: weak.** Its exploration mirrored T3-A's history search. It made one
  wasted call on a guessed path, `src/aicontext/cli.py`. That may be because
  the overview names modules without the `src/ai_context_map/` prefix
  (inference). It also flagged the overview's `cli.py:126-190` range as
  "slightly off". The range starts at the `def` lines; the decorators sit one
  line earlier.
- **Answers.** B answers were not more correct. They were slightly more
  detailed: T1-B listed side effects on `symbol`, and T3-B quoted line numbers
  from inside the unmerged branches. Equivalent detail appears in A answers on
  other points: T2-A independently found the stale `aicontext_version` key.

Records: [`benchmarks/architecture-nutshell/`](../benchmarks/architecture-nutshell/)
holds one JSON file per run. Each contains:

- the exact prompt, the output and the settings;
- every tool call's input and result size;
- permission denials, usage, timing and the grade.

Local paths are replaced with `<repo>`. No answer key is included. The tool
also reports a cost estimate (about $0.25–0.35 per run). It is recorded only
as reported; it is not billing evidence and is not used in any comparison.

## 4. Preparation cost (reported separately)

- **Measured usage: `null`.** The overview was written inside an interactive
  Claude Code session (Opus 5.5) that does not expose its own token usage.
  Elapsed time was not measured reliably either.
- **Investigation required:**
  - README and the four existing docs;
  - about 25 source files across the CLI, commands, emitters, models,
    scanner, graph, navigation and workstate;
  - about a dozen `git` history commands to find and confirm the direction
    change (branch containment, README at three revisions);
  - a pass to verify every reference, which caught two errors before the
    runs: a line range, and a branch family that had been left out.
- **Not separable.** The same investigation produced the answer key, so the
  overview's marginal cost cannot be separated from protocol preparation.
- **Author bias.** The author knew the tasks while writing the overview. The
  overview was kept general (component level; it does not mention
  `.gitignore` or `known_risks`). Even so, its flows and the direction-change
  section cover facts the tasks depend on. This favours B, and B still did
  not do better.
- **Reuse arithmetic.** Reuse could only repay preparation if each B
  investigation were cheaper than A. Here B used more input-side tokens in two
  of three tasks and about 25% more in total. With these data, preparation
  plus any number of investigations is never cheaper than A alone.

**Maintenance is a recurring cost, not a one-time one.**

- The overview is pinned to `0766e58` and cites line ranges.
- Any change to the cited files (`cli.py`, `generate_cmd.py`, `export_cmd.py`,
  `index.py`, `retrieve.py`, `store.py`) can invalidate a claim. So can a new
  direction change.
- Each revision mismatch needs a `git diff 0766e58 -- <cited files>` and a
  re-check of the affected claims.
- Even when the revision matches, the overview's meaning is not guaranteed
  correct. It is only as accurate as the last manual verification.

## 5. Limitations

- **One repository, one model, one agent, one run per cell.** Six runs cannot
  separate the conditions from run-to-run variation. For example, T2-A took
  the longest wall time while T2-B used the most tokens.
- **Ceiling effect.** This repository is small, has strong documentation, and
  has a readable git history. Condition A passed everything, so the tasks
  could not show a correctness benefit.
- **Experimenter effects.** The same person wrote the tasks, the overview, the
  answer key and the grades, and grading was not blind.
- **Shared prompt cache.** Sequential runs shared the cache for the common
  system prompt. Cache creation and cache reads are reported separately, and
  the condition order was randomized, but cache state was not controlled
  further.
- **Permission denials.** The read-only allow list caused denials in three
  runs (T2-B, T3-A, T3-B). Agents recovered every time, but the recovery
  inflated those runs' call counts.
- **Prose only.** A compact notation versus prose was not tested.

## 6. Stopping rule and recommendation

- **Correctness first.** Correctness was preserved: the overview introduced no
  architectural error and did not encourage outdated assumptions.
- **Efficiency.** No useful improvement. Usage was higher with the overview in
  T1 and T2 and slightly lower in T3, and all three differences are within
  plausible single-run variation. On efficiency the result is inconclusive,
  leaning negative.
- **Understanding.** Not measurably improved, because both conditions passed
  every criterion.

The predeclared rule says to stop when the overview "provides no useful
improvement over ordinary exploration". **Recommendation: stop further
development of the architecture overview. Do not automate its generation, and
do not move on to compact notation.**

If the question is ever reopened, there is one justified next step. Replicate
once on an unfamiliar, larger repository, with tasks written and graded by
someone other than the overview's author, before doing anything else.
