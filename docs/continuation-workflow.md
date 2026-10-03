# Continue work with a checkpoint and captured evidence

This is an experimental CLI workflow for file-capable coding agents (Claude
Code, Codex, Gemini CLI, and others). It uses ordinary JSON, Markdown, and log
files under `.ai/`. It calls no model, installs no hooks, and does not read or
modify any agent's native session files.

## The sequence

1. **Work normally.** Use `aicontext find "symbol or task"` for bounded code
   pointers. Optionally wrap noisy commands:

   ```bash
   aicontext capture --label "tests" -- uv run pytest -v
   ```

   The complete stdout and stderr go to `.ai/work/evidence/<id>/`. Only a small
   receipt is printed: command, exit status, evidence ID, sizes, fingerprints,
   and the last few lines of each stream. The command runs without a shell, so
   pipes, globs, and `$VARS` are passed literally; wrap with `sh -c '...'` only
   if you really want a shell. The wrapper exits with the command's status
   (127 not found, 126 not executable, 125 if evidence could not be preserved).

2. **Record the checkpoint while the agent still knows the work** — at a
   meaningful milestone or before a handoff, not after every command:

   ```bash
   aicontext checkpoint template            # example payload, every record kind
   aicontext checkpoint update - <<'EOF'
   {"objective": "Make export refuse to overwrite root AGENTS.md without --force",
    "next": "Add the CLI test for --write-agents-md without --force",
    "records": [
      {"id": "c-no-commit", "kind": "constraint", "basis": "user", "text": "Do not commit or push."},
      {"kind": "decision", "text": "Check existence before writing", "reason": "Avoid partial writes", "refs": ["src/ai_context_map/commands/export_cmd.py"]},
      {"kind": "verification", "outcome": "failed", "text": "test_export_force failed: FileExistsError not raised", "evidence": ["ev-20261003-174722-6ad7"]}
    ]}
   EOF
   ```

3. **Generate the entry file:** `aicontext pack` (optionally `--task`,
   `--max-chars`). Without `--task`, code pointers are chosen from the recorded
   objective and next action.

4. **Start a fresh conversation.**

5. **Ask:** "Read `.ai/START_HERE.md`, follow applicable repository
   instructions and its references, then continue the recorded next action."

6. **Retrieve only what is needed and keep the checkpoint current:**

   ```bash
   aicontext checkpoint show                # current records; --all for history
   aicontext checkpoint show --id d2        # one record as JSON
   aicontext evidence list
   aicontext evidence show ev-... --grep "FAILED|Error"
   aicontext evidence show ev-... --stream stdout --lines 120-180
   aicontext evidence show ev-... --stream stdout --full   # raw, unbounded
   ```

## Record model

Each record has a stable `id` (supplied, or assigned such as `c3`, `d2`), a
`kind`, a `basis`, a `status`, and optional `reason`, `evidence` (evidence IDs),
and `refs` (`path`, `path:LINE`, `path:START-END`).

| kind | meaning | rules |
| --- | --- | --- |
| `objective`, `next` | current goal and next action | one current each; setting a new one supersedes the old |
| `progress`, `todo` | work state | `attempted` is distinct from `done`; `done` without evidence renders as "done, unverified" |
| `decision`, `rejected` | choices and failed approaches | `reason` required |
| `constraint` | must survive restarts | `basis` must be stated; never truncated or dropped from the entry file; only replaced explicitly, superseded by another constraint, or retired with a reason |
| `verification` | an observed result | basis `observed`, an `outcome` (passed/failed/partial/inconclusive), and evidence or refs required |
| `assumption`, `question` | unverified by definition | basis `assumed`; confirming/refuting an assumption requires evidence |

`basis` distinguishes a **user instruction**, an **observed** fact (must cite
evidence or refs), an **agent** decision or judgement, and an **assumed**
(UNVERIFIED) belief. The tool cannot check that a cited log actually supports a
claim; it only ensures the claim points at something checkable and that the
evidence still matches its fingerprint.

Updates are validated as a whole and written atomically (temporary file,
fsync, rename). One bad record rejects the entire batch. Re-sending identical
content is a no-op, a same-text record without an ID is not duplicated, and
changing an existing ID requires `"replace": true`. Superseded records stay in
the file as history. A corrupt or unknown-schema checkpoint is reported, never
silently reset. Concurrent writers are not coordinated; use one agent at a time.

## Entry-file budget

`aicontext pack --max-chars N` (default 6,000 **characters**, not tokens) puts
these in `.ai/START_HERE.md`, never truncated:

- instruction-file pointers, objective, next action, every active constraint,
  and unresolved blockers (blocked work, blocking open questions).

Then, while space remains: unfinished work, recent verification, up to five
recent decisions, rejected approaches, open assumptions/questions, completed
work, and code/test pointers (the first three pointers are reserved space).
Optional records are omitted whole and counted in the footer; text longer than
300 characters is cut with an explicit marker naming `checkpoint show --id`.
If the essential part cannot fit, `pack` fails with the needed size and writes
nothing. A missing objective or next action is labelled `CHECKPOINT INCOMPLETE`.
A missing checkpoint is stated rather than implied.

## Staleness and integrity

- Each evidence stream has a sha256; retrieval reports `current`, `CHANGED`
  (file edited after capture), or `MISSING`.
- In Git repositories, checkpoint updates and captures record HEAD plus a
  fingerprint of modified and untracked files (excluding `.ai/`). Retrieval and
  the entry file then say whether the repository changed since. This is a
  coarse signal; it does not say whether the change matters.
- `.ai/work/` contains a `.gitignore` with `*`, so checkpoint and evidence stay
  out of Git without editing your own `.gitignore`. They are excluded from
  `pack`, `find`, and `generate`. Nothing is uploaded. Evidence may contain
  secrets printed by commands; it is stored in plain text locally.
- `.ai/START_HERE.md` is regenerated output; in this repository it is
  gitignored. Elsewhere, add it to `.gitignore` if the checkpoint content
  should not be committed.

## Boundaries

- Creating a checkpoint does **not** remove history from the active
  conversation. The reduction happens only when you start a fresh session with
  the small entry file, or when a bounded receipt replaces verbose output
  before it enters context.
- Writing a checkpoint costs output tokens (the demo payload is about 1,400
  characters) and retrieving evidence costs input tokens. Count both.
- Native compaction, `--resume`/`--continue`, and history lookup are competing
  workflows. They may preserve more nuance at a higher or lower cost; only a
  live comparison can say.
- A receipt is often *larger* than a manual `| tail -n 20` for small outputs.
  The benefit of capture over `tail` is that the rest stays recoverable with
  stable line numbers and integrity checks, not that the receipt is smaller.
- Shared file formats do not establish that different agents continue each
  other's work reliably. That has not been tested.

## Instruction to paste into any file-capable coding agent

> Maintain a working checkpoint with the `aicontext` CLI. Record it with
> `aicontext checkpoint update -` (JSON on stdin; run `aicontext checkpoint
> template` once for the format) at meaningful milestones — after a decision,
> a rejected approach, a verification result, or a new user constraint — and
> always before a handoff or when context is getting long. Do not update after
> every command. Label each record's basis honestly: `user` only for my explicit
> instructions, `observed` only when citing evidence IDs or file refs, `agent`
> for your own decisions, and assumptions/questions as unverified. Record
> attempted fixes as `attempted`, not `done`; never record "tests pass" from an
> exit status alone — read the output. For verbose commands use `aicontext
> capture --label NAME -- CMD ...` and cite its evidence ID. Update records by
> ID instead of adding duplicates; supersede outdated ones. Before handing off,
> run `aicontext pack` and confirm `.ai/START_HERE.md` states the objective,
> next action, and all constraints.
