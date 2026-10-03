# Live continuation comparison (prepared, not yet run)

No live model runs have been performed for the checkpoint workflow. The local
demonstration (`benchmarks/capture_demo.py`) measures only output sizes. This
protocol is for deciding whether the workflow is worth keeping.

## Question

When the same partially finished task is continued, does a fresh session with
the checkpoint and evidence workflow finish correctly with less total usage, or
with fewer missed constraints and repeated failed attempts, than:

1. **Native continuation:** the tool's own resume/continue, including its
   automatic or manual compaction (`claude --resume` / `/compact`,
   `codex resume`, Gemini CLI's saved-chat resume).
2. **Manual handoff:** a fresh session given a short handoff note written by
   the first session when asked "write a handoff note for a new session".
3. **Checkpoint workflow:** a fresh session told to read `.ai/START_HERE.md`,
   after the first session recorded a checkpoint and ran `aicontext pack`.

## Task (this repository)

> Add `--context N` to `aicontext evidence show --grep`, printing N lines
> before and after each match, with original line numbers, bounded by
> `--max-chars`. Add tests.

### Session 1 script (identical for every condition)

Give these prompts in order to a fresh session at the same starting commit,
then stop after the last one regardless of progress:

1. The task above.
2. After the agent first proposes or starts an implementation: "Constraint:
   overlapping context windows must not print a line twice, and output without
   `--context` must stay byte-identical."
3. If the agent loads whole files into memory: "That breaks on multi-GB logs;
   keep it streaming." (If it does not, say: "Make sure it stays streaming for
   multi-GB logs.")
4. "Run the tests with `aicontext capture --label tests -- uv run pytest -q`."
5. "We're stopping here. Prepare for a handoff." — then, per condition:
   - native: nothing further; resume this session later.
   - manual: "Write a handoff note for a new session." Save it verbatim.
   - checkpoint: "Record the checkpoint and run `aicontext pack`." (with the
     paste-able instruction from `docs/continuation-workflow.md` given at the
     start of session 1 in this condition only).

Snapshot the working tree after session 1 (`git stash create` hash or a
tarball, excluding nothing under `.ai/work/`) so every repetition of a
condition continues from the same files that its own session 1 produced.
Because session 1 differs per condition, run it at least three times per
condition and report variation in where it stopped.

### Session 2 prompt

- native: "Continue the task."
- manual: the saved handoff note, then "Continue the task."
- checkpoint: "Read `.ai/START_HERE.md`, follow applicable repository
  instructions and its references, then continue the task."

### Acceptance criteria (scored by a person or a hidden test file)

1. `--grep X --context 2` prints matched lines and up to 2 neighbours with
   original line numbers.
2. Overlapping windows print each line once; separators between gaps.
3. Output without `--context` is byte-identical to the current output
   (hidden test compares against a saved fixture).
4. `--max-chars` still bounds output and reports where it stopped.
5. Streaming: memory does not scale with file size (a hidden test feeds a
   2 GB sparse/generated log under a memory limit, or reviews the code).
6. Existing tests, `ruff check`, and `ruff format --check` pass.

## Controls

Same model, reasoning setting, permissions, tool access, starting commit, and
machine for all conditions. Record whether prompt caching was warm: a resumed
session may read a long history from cache cheaply, which matters for billing
but not for context-window limits. Randomize condition order. At least three
repetitions per condition per agent; treat Claude Code, Codex, and Gemini as
separate experiments.

## What to record per run

Copy `benchmarks/continuation-run.template.json` and fill in every field.
Count session 1's checkpoint/handoff writing in the condition's total. Read
usage from the tool's own reporting (`/cost`, `/status`, session usage summary,
or API usage logs); write `null` when it is not exposed rather than estimating.

## Decision rule

Continue the project only if, across repetitions, the checkpoint condition
meets the acceptance criteria at least as often as the best alternative **and**
either uses measurably less total usage (beyond run-to-run variation) or
reduces missed constraints / repeated rejected approaches. A smaller entry file
alone is not success. If agents ignore the entry file's retrieval commands,
reread everything, or record unsupported "observed" claims, stop or redesign.
