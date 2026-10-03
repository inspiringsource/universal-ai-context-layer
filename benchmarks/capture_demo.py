"""Output-size demonstration for capture/evidence and the checkpoint entry file.

Runs real commands from this repository through `aicontext capture`, then one
bounded retrieval each, and counts the characters an agent would read. This is
an output-size measurement in characters/bytes. It is not a token count and
not a subscription-usage or billing measurement.

Evidence is written to a temporary directory so the repository stays clean.
Usage: uv run python benchmarks/capture_demo.py [--keep]
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from ai_context_map.navigation.index import build_index, render_brief
from ai_context_map.workstate.checkpoint import (
    apply_update,
    briefing_sections,
    save_checkpoint,
)

REPO = Path(__file__).resolve().parents[1]
BIN = Path(sys.executable).parent
CLI = [sys.executable, "-m", "ai_context_map.cli"]

SCENARIOS = [
    {
        "name": "verbose test run",
        "command": [sys.executable, "-m", "pytest", "-v", "-p", "no:cacheprovider"],
        # Confirm no failures beyond the summary visible in the receipt.
        "retrieve": ["--grep", "FAILED|ERROR"],
    },
    {
        "name": "strict lint with many findings",
        "command": [str(BIN / "ruff"), "check", "--select", "ALL", "--no-cache", "src"],
        "retrieve": ["--grep", "workstate/store.py", "--max-chars", "2500"],
    },
    {
        "name": "recent history with patches",
        "command": ["git", "log", "-p", "-n", "15", "--no-color"],
        "retrieve": ["--stream", "stdout", "--lines", "1-40"],
    },
    {
        "name": "navigation evaluation JSON",
        "command": [sys.executable, "benchmarks/evaluate_navigation.py"],
        "retrieve": ["--grep", '"(task_hits|baseline_hits|indexed_files)"'],
    },
]


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=REPO, capture_output=True, text=True, check=False)


def measure_capture(evidence_root: Path) -> list[dict]:
    rows = []
    for scenario in SCENARIOS:
        result = run(
            [
                *CLI,
                "capture",
                "--root",
                str(evidence_root),
                "--label",
                scenario["name"],
                "--",
                *scenario["command"],
            ]
        )
        if "evidence: " not in result.stdout:
            rows.append({"name": scenario["name"], "error": result.stderr.strip()})
            continue
        evidence_id = result.stdout.split("evidence: ")[1].split()[0]
        meta = json.loads(
            (
                evidence_root / ".ai/work/evidence" / evidence_id / "meta.json"
            ).read_text()
        )
        raw = sum(stream["bytes"] for stream in meta["streams"].values())
        retrieved = run(
            [
                *CLI,
                "evidence",
                "show",
                evidence_id,
                "--root",
                str(evidence_root),
                *scenario["retrieve"],
            ]
        )
        combined = b"".join(
            (
                evidence_root / ".ai/work/evidence" / evidence_id / f"{name}.log"
            ).read_bytes()
            for name in ("stdout", "stderr")
        ).decode("utf-8", "replace")
        tail20 = "\n".join(combined.splitlines()[-20:]) + "\n"
        exposed = len(result.stdout) + len(retrieved.stdout)
        rows.append(
            {
                "name": scenario["name"],
                "command": " ".join(
                    Path(scenario["command"][0]).name.split() + scenario["command"][1:]
                ),
                "exit_status": result.returncode,
                "evidence_id": evidence_id,
                "raw_output_bytes": raw,
                "raw_output_lines": sum(
                    stream["lines"] for stream in meta["streams"].values()
                ),
                "receipt_chars": len(result.stdout),
                "retrieval": " ".join(scenario["retrieve"]),
                "retrieval_chars": len(retrieved.stdout),
                "total_exposed_chars": exposed,
                "exposed_fraction_of_raw": round(exposed / raw, 3) if raw else None,
                "manual_tail_20_chars_for_comparison": len(tail20),
            }
        )
    return rows


def measure_checkpoint(evidence_root: Path, rows: list[dict]) -> dict:
    """Cost of writing a realistic checkpoint vs. the entry file it produces."""
    evidence = {row["name"]: row["evidence_id"] for row in rows if "evidence_id" in row}
    payload = {
        "objective": "Add explicit checkpoint, capture, and bounded evidence retrieval to aicontext.",
        "next": "Run a live three-condition continuation comparison and record usage.",
        "records": [
            {
                "kind": "constraint",
                "basis": "user",
                "text": "Do not commit, push, or publish.",
            },
            {
                "kind": "constraint",
                "basis": "user",
                "text": "No global hooks, shell changes, or native session-file edits; capture is explicit.",
            },
            {
                "kind": "constraint",
                "basis": "user",
                "text": "Report sizes in characters/bytes, never as measured tokens or billing savings.",
            },
            {
                "kind": "decision",
                "text": "Store state under self-ignoring .ai/work/",
                "reason": "Keeps evidence out of Git without editing the user's .gitignore.",
            },
            {
                "kind": "decision",
                "text": "Keep stdout and stderr in separate files",
                "reason": "Faithful preservation; interleaving order is not reconstructed.",
            },
            {
                "kind": "rejected",
                "text": "Per-tool output filters",
                "reason": "Speculative; a transparent tail preview is honest and general.",
            },
            {
                "kind": "verification",
                "outcome": "inconclusive",
                "text": "Captured verbose test run; read the receipt summary rather than trusting exit 0.",
                "evidence": [evidence.get("verbose test run")],
            },
            {
                "kind": "assumption",
                "text": "Agents will follow START_HERE retrieval commands when told to.",
            },
            {
                "kind": "question",
                "text": "Does a fresh session with the checkpoint finish with fewer total tokens?",
            },
        ],
    }
    payload["records"] = [
        record
        for record in payload["records"]
        if record.get("evidence", [True])[0] is not None
    ]
    state, report = apply_update(None, payload, evidence_root)
    save_checkpoint(evidence_root, state)
    index = build_index(REPO)
    query = payload["objective"] + " " + payload["next"]
    without = render_brief(REPO, index, query, 6000)
    with_checkpoint = render_brief(
        REPO, index, query, 6000, checkpoint=briefing_sections(evidence_root, state)
    )
    full_state = json.dumps(state, indent=2)
    return {
        "update_payload_chars_written_by_agent": len(json.dumps(payload)),
        "update_report_chars": len("\n".join(report)),
        "entry_file_chars_without_checkpoint": len(without),
        "entry_file_chars_with_checkpoint": len(with_checkpoint),
        "checkpoint_json_chars_kept_out_of_entry_file": len(full_state),
        "full_navigation_index_chars_kept_out_of_entry_file": len(
            json.dumps(index, indent=2)
        ),
    }


def main() -> None:
    evidence_root = Path(tempfile.mkdtemp(prefix="uacl-capture-demo-"))
    try:
        rows = measure_capture(evidence_root)
        checkpoint = measure_checkpoint(evidence_root, rows)
        report = {
            "scope": (
                "Output-size measurement in characters/bytes on this repository. Not tokens, "
                "not subscription usage, not task quality. Totals count the receipt plus one "
                "bounded retrieval; real agents may retrieve more or less."
            ),
            "capture": rows,
            "checkpoint": checkpoint,
        }
        print(json.dumps(report, indent=2))
    finally:
        if "--keep" in sys.argv:
            print(f"Evidence kept at {evidence_root}", file=sys.stderr)
        else:
            shutil.rmtree(evidence_root)


if __name__ == "__main__":
    main()
