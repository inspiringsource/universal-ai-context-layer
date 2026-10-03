import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ai_context_map.cli import app
from ai_context_map.config import Config
from ai_context_map.navigation.index import BRIEF_PATH, INDEX_PATH, build_index
from ai_context_map.scanner.walker import scan_repository
from ai_context_map.workstate.checkpoint import (
    CheckpointError,
    apply_update,
    briefing_sections,
    load_checkpoint,
    update_checkpoint,
)
from ai_context_map.workstate.evidence import run_capture, show_evidence
from ai_context_map.workstate.store import (
    CHECKPOINT_PATH,
    EVIDENCE_DIR,
    repository_change,
    worktree_fingerprint,
)

PY = sys.executable


def write(root: Path, relative: str, content: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def capture(root: Path, *argv: str, label: str = "") -> tuple[int, str, str]:
    code, receipt = run_capture(root, list(argv), label)
    evidence_id = receipt.split("evidence: ")[1].split()[0]
    return code, receipt, evidence_id


def evidence_file(root: Path, evidence_id: str, stream: str = "stdout") -> Path:
    return root / EVIDENCE_DIR / evidence_id / f"{stream}.log"


# --- checkpoint -----------------------------------------------------------


def test_checkpoint_records_are_identifiable_and_not_duplicated(tmp_path: Path) -> None:
    payload = {
        "objective": "Ship bounded capture",
        "next": "Write tests",
        "records": [
            {
                "id": "c-git",
                "kind": "constraint",
                "basis": "user",
                "text": "Do not commit.",
            },
            {"kind": "assumption", "text": "CI uses 3.11"},
        ],
    }
    first = update_checkpoint(tmp_path, payload)
    assert "added obj1 (objective)" in first and "added c-git (constraint)" in first
    before = (tmp_path / CHECKPOINT_PATH).read_bytes()
    again = update_checkpoint(tmp_path, payload)
    assert all(line.startswith(("unchanged", "no changes")) for line in again)
    assert (tmp_path / CHECKPOINT_PATH).read_bytes() == before
    assert len(load_checkpoint(tmp_path)["records"]) == 4


def test_objective_and_decision_supersession_preserves_history(tmp_path: Path) -> None:
    update_checkpoint(
        tmp_path,
        {
            "objective": "Old goal",
            "records": [{"kind": "decision", "text": "Use A", "reason": "simple"}],
        },
    )
    report = update_checkpoint(
        tmp_path,
        {
            "objective": "New goal",
            "records": [
                {
                    "kind": "rejected",
                    "text": "Use A",
                    "reason": "Failed under load",
                    "supersedes": "d1",
                }
            ],
        },
    )
    assert "added obj2 (objective), supersedes obj1" in report
    records = {r["id"]: r for r in load_checkpoint(tmp_path)["records"]}
    assert records["obj1"]["superseded_by"] == "obj2"
    assert records["d1"]["superseded_by"] == "r1"
    assert records["obj1"]["text"] == "Old goal"  # history kept, not rewritten
    essential, optional, counts = briefing_sections(tmp_path, load_checkpoint(tmp_path))
    text = "\n".join(essential + optional)
    assert "New goal" in text and "Old goal" not in text
    assert counts["superseded"] == 2
    with pytest.raises(CheckpointError, match="already superseded"):
        update_checkpoint(
            tmp_path,
            {
                "records": [
                    {"kind": "decision", "text": "B", "reason": "x", "supersedes": "d1"}
                ]
            },
        )


def test_constraints_survive_unrelated_updates_and_need_explicit_change(
    tmp_path: Path,
) -> None:
    constraint = {
        "id": "c1",
        "kind": "constraint",
        "basis": "user",
        "text": "Never push.",
    }
    update_checkpoint(tmp_path, {"records": [constraint]})
    update_checkpoint(tmp_path, {"objective": "x", "next": "y"})
    update_checkpoint(tmp_path, {"next": "z"})
    state = load_checkpoint(tmp_path)
    assert next(r for r in state["records"] if r["id"] == "c1")["text"] == "Never push."
    with pytest.raises(CheckpointError, match="already exists with different content"):
        update_checkpoint(
            tmp_path, {"records": [{**constraint, "text": "Push freely."}]}
        )
    with pytest.raises(
        CheckpointError, match="only be superseded by another constraint"
    ):
        update_checkpoint(
            tmp_path,
            {
                "records": [
                    {
                        "kind": "decision",
                        "text": "Push",
                        "reason": "r",
                        "supersedes": "c1",
                    }
                ]
            },
        )
    with pytest.raises(CheckpointError, match="requires a reason"):
        update_checkpoint(
            tmp_path, {"records": [{"id": "c1", "status": "retired", "replace": True}]}
        )
    report = update_checkpoint(
        tmp_path,
        {
            "records": [
                {
                    "id": "c1",
                    "status": "retired",
                    "reason": "User lifted it",
                    "replace": True,
                }
            ]
        },
    )
    assert report == ["replaced c1 (revision 2)"]
    essential, _, _ = briefing_sections(tmp_path, load_checkpoint(tmp_path))
    assert "Never push." not in "\n".join(essential)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "must be a JSON object"),
        ({"goal": "x"}, "Unknown top-level"),
        (
            {"records": [{"kind": "constraint", "text": "no basis"}]},
            "basis must be one of",
        ),
        ({"records": [{"kind": "decision", "text": "no reason"}]}, "require a reason"),
        (
            {
                "records": [
                    {"kind": "verification", "outcome": "passed", "text": "tests ran"}
                ]
            },
            "must cite evidence",
        ),
        (
            {"records": [{"kind": "verification", "text": "x", "refs": ["a.py"]}]},
            "outcome must be one of",
        ),
        (
            {
                "records": [
                    {
                        "kind": "assumption",
                        "basis": "observed",
                        "text": "x",
                        "refs": ["a.py"],
                    }
                ]
            },
            "unverified by definition",
        ),
        (
            {"records": [{"kind": "progress", "status": "fixed", "text": "x"}]},
            "status for progress",
        ),
        ({"records": [{"kind": "todo", "text": "x", "color": "red"}]}, "Unknown field"),
        ({"records": [{"kind": "todo", "text": "x" * 2001}]}, "exceeds 2000"),
        (
            {
                "records": [
                    {
                        "kind": "todo",
                        "text": "x",
                        "evidence": ["ev-20260101-000000-abcd"],
                    }
                ]
            },
            "does not exist",
        ),
        (
            {"records": [{"kind": "todo", "text": "x", "refs": ["../outside.py"]}]},
            "escapes",
        ),
        (
            {"records": [{"id": "nope", "text": "x", "replace": True}]},
            "Cannot replace unknown",
        ),
    ],
)
def test_invalid_input_is_rejected_without_writing(
    tmp_path: Path, payload: object, message: str
) -> None:
    update_checkpoint(tmp_path, {"objective": "keep me"})
    before = (tmp_path / CHECKPOINT_PATH).read_bytes()
    with pytest.raises(CheckpointError, match=message):
        update_checkpoint(tmp_path, payload)
    assert (tmp_path / CHECKPOINT_PATH).read_bytes() == before


def test_one_bad_record_rejects_the_whole_batch(tmp_path: Path) -> None:
    with pytest.raises(CheckpointError):
        update_checkpoint(
            tmp_path,
            {
                "objective": "valid",
                "records": [{"kind": "decision", "text": "no reason"}],
            },
        )
    assert not (tmp_path / CHECKPOINT_PATH).exists()


def test_attempted_or_unverified_work_is_not_presented_as_done(tmp_path: Path) -> None:
    update_checkpoint(
        tmp_path,
        {
            "records": [
                {"kind": "progress", "status": "attempted", "text": "Patched parser"},
                {"kind": "progress", "status": "done", "text": "Renamed module"},
            ]
        },
    )
    _, optional, _ = briefing_sections(tmp_path, load_checkpoint(tmp_path))
    text = "\n".join(optional)
    assert "[p1; attempted; agent] Patched parser" in text
    assert "done, unverified" in text


def test_atomic_write_failure_keeps_previous_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    update_checkpoint(tmp_path, {"objective": "original"})
    before = (tmp_path / CHECKPOINT_PATH).read_bytes()

    def broken_replace(self: Path, target: Path) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", broken_replace)
    with pytest.raises(OSError, match="disk full"):
        update_checkpoint(tmp_path, {"objective": "replacement"})
    monkeypatch.undo()
    assert (tmp_path / CHECKPOINT_PATH).read_bytes() == before
    leftovers = [p.name for p in (tmp_path / ".ai/work").iterdir()]
    assert sorted(leftovers) == [".gitignore", "checkpoint.json"]


def test_corrupt_checkpoint_is_reported_not_reset(tmp_path: Path) -> None:
    path = write(tmp_path, CHECKPOINT_PATH, '{"schema_version": 99, "records": []}')
    result = CliRunner().invoke(
        app,
        ["checkpoint", "update", "-", "--root", str(tmp_path)],
        input='{"objective": "x"}',
    )
    assert result.exit_code == 1
    assert "Unsupported checkpoint schema" in result.output
    assert path.read_text() == '{"schema_version": 99, "records": []}'
    bad_json = CliRunner().invoke(
        app, ["checkpoint", "update", "-", "--root", str(tmp_path)], input="{oops"
    )
    assert bad_json.exit_code == 1 and "Cannot read JSON" in bad_json.output


def test_checkpoint_cli_update_from_file_and_show(tmp_path: Path) -> None:
    source = write(
        tmp_path,
        "update.json",
        json.dumps({"objective": "Goal", "next": "Step", "records": []}),
    )
    runner = CliRunner()
    result = runner.invoke(
        app, ["checkpoint", "update", str(source), "--root", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    shown = runner.invoke(app, ["checkpoint", "show", "--root", str(tmp_path)])
    assert "Objective: [obj1; user instruction] Goal" in shown.output
    one = runner.invoke(
        app, ["checkpoint", "show", "--id", "next1", "--root", str(tmp_path)]
    )
    assert json.loads(one.output)["text"] == "Step"
    template = runner.invoke(app, ["checkpoint", "template"])
    # The documented template must itself be valid apart from placeholder evidence.
    payload = json.loads(template.output)
    for record in payload["records"]:
        record.pop("evidence", None)
        if record.get("kind") in {"verification"}:
            record["refs"] = ["README.md"]
    payload["records"] = [r for r in payload["records"] if not r.get("replace")]
    apply_update(None, payload)


# --- START_HERE budget -----------------------------------------------------


def pack(root: Path, *args: str) -> tuple[int, str]:
    result = CliRunner().invoke(app, ["pack", str(root), *args])
    return result.exit_code, result.output


def test_entry_file_includes_essentials_and_points_to_more(tmp_path: Path) -> None:
    write(tmp_path, "src/billing.py", "def refund_invoice():\n    return 1\n")
    write(tmp_path, "AGENTS.md", "# Rules\n")
    update_checkpoint(
        tmp_path,
        {
            "objective": "Fix refund_invoice rounding",
            "next": "Run the billing tests",
            "records": [
                {
                    "kind": "constraint",
                    "basis": "user",
                    "text": "Keep cents as integers.",
                },
                {"kind": "progress", "status": "blocked", "text": "Need fixture data"},
                *[
                    {"kind": "decision", "text": f"Decision {n}", "reason": "because"}
                    for n in range(7)
                ],
            ],
        },
    )
    code, output = pack(tmp_path)
    assert code == 0, output
    brief = (tmp_path / BRIEF_PATH).read_text()
    assert "Objective: [obj1; user instruction] Fix refund_invoice rounding" in brief
    assert "Next action:" in brief and "Keep cents as integers." in brief
    assert "Unresolved blockers:" in brief and "Need fixture data" in brief
    assert "src/billing.py" in brief  # task defaulted from the objective
    assert "Decision 6" in brief and "Decision 1" not in brief  # short list
    assert "aicontext checkpoint show" in brief and "aicontext evidence show" in brief
    assert "CHECKPOINT INCOMPLETE" not in brief
    # The full index and checkpoint JSON stay out of the entry file.
    assert '"records"' not in brief and "sha256" not in brief
    assert (tmp_path / INDEX_PATH).exists()


def test_budget_omits_optional_detail_explicitly(tmp_path: Path) -> None:
    write(tmp_path, "src/a.py", "def a(): pass\n")
    update_checkpoint(
        tmp_path,
        {
            "objective": "Goal",
            "next": "Step",
            "records": [
                {"kind": "todo", "text": f"Optional todo number {n} " + "x" * 120}
                for n in range(20)
            ],
        },
    )
    code, output = pack(tmp_path, "--max-chars", "3000")
    assert code == 0, output
    brief = (tmp_path / BRIEF_PATH).read_text()
    assert len(brief) <= 3000
    omitted = int(
        brief.split("Checkpoint: 22 current records; ")[1].split(" optional")[0]
    )
    assert omitted > 0
    assert brief.count("Optional todo number") == 20 - omitted


def test_essential_overflow_fails_explicitly_and_writes_nothing(tmp_path: Path) -> None:
    long_rule = "Never drop customer data. " * 60  # ~1,560 characters
    update_checkpoint(
        tmp_path,
        {
            "objective": "Goal",
            "next": "Step",
            "records": [
                {"kind": "constraint", "basis": "user", "text": long_rule.strip()}
            ],
        },
    )
    code, output = pack(tmp_path, "--max-chars", "1500")
    assert code == 1
    assert "cannot safely contain" in output and "never truncated" in output
    assert not (tmp_path / BRIEF_PATH).exists()
    code, output = pack(tmp_path, "--max-chars", "4000")
    assert code == 0
    assert long_rule.strip() in (tmp_path / BRIEF_PATH).read_text()


def test_incomplete_or_missing_checkpoint_is_labelled(tmp_path: Path) -> None:
    write(tmp_path, "src/a.py", "def a(): pass\n")
    pack(tmp_path)
    assert "No checkpoint recorded" in (tmp_path / BRIEF_PATH).read_text()
    update_checkpoint(tmp_path, {"objective": "Goal only"})
    pack(tmp_path)
    assert (
        "CHECKPOINT INCOMPLETE: no next recorded" in (tmp_path / BRIEF_PATH).read_text()
    )


# --- capture and evidence ----------------------------------------------------


def test_capture_preserves_complete_output_and_exit_status(tmp_path: Path) -> None:
    script = (
        "import sys\n"
        "sys.stdout.buffer.write(b'caf\\xc3\\xa9\\n\\xff raw bytes\\nno newline')\n"
        "sys.stderr.write('warning: something\\n')\n"
        "sys.exit(3)\n"
    )
    code, receipt, evidence_id = capture(tmp_path, PY, "-c", script, label="bytes")
    assert code == 3
    assert "exit status: 3" in receipt
    assert evidence_file(tmp_path, evidence_id).read_bytes() == (
        b"caf\xc3\xa9\n\xff raw bytes\nno newline"
    )
    assert (
        evidence_file(tmp_path, evidence_id, "stderr").read_text()
        == "warning: something\n"
    )
    meta = json.loads((tmp_path / EVIDENCE_DIR / evidence_id / "meta.json").read_text())
    assert meta["streams"]["stdout"]["lines"] == 3
    assert meta["started_at"] and meta["finished_at"]
    assert len(meta["streams"]["stdout"]["sha256"]) == 64
    assert "passed" not in receipt.lower()


def test_capture_cli_returns_command_status_and_uses_no_shell(tmp_path: Path) -> None:
    runner = CliRunner()
    ok = runner.invoke(
        app,
        ["capture", "--root", str(tmp_path), "--", PY, "-c", "print('ok')"],
    )
    assert ok.exit_code == 0, ok.output
    marker = tmp_path / "pwned"
    result = runner.invoke(
        app,
        [
            "capture",
            "--root",
            str(tmp_path),
            "--label",
            "args",
            "--",
            PY,
            "-c",
            "import sys; print(sys.argv[1:]); sys.exit(4)",
            "$HOME",
            f"; touch {marker}",
        ],
    )
    assert result.exit_code == 4
    assert not marker.exists()
    evidence_id = result.output.split("evidence: ")[1].split()[0]
    assert "'$HOME'" in evidence_file(tmp_path, evidence_id).read_text()


def test_capture_missing_command_and_unwritable_evidence(tmp_path: Path) -> None:
    runner = CliRunner()
    missing = runner.invoke(
        app, ["capture", "--root", str(tmp_path), "--", "definitely-not-a-command-uacl"]
    )
    assert missing.exit_code == 127
    assert "LAUNCH FAILED" in missing.output
    outside = tmp_path.parent / (tmp_path.name + "-elsewhere")
    outside.mkdir()
    repo = tmp_path / "repo"
    (repo / ".ai").mkdir(parents=True)
    (repo / ".ai/work").symlink_to(outside, target_is_directory=True)
    marker = repo / "ran"
    failed = runner.invoke(
        app,
        ["capture", "--root", str(repo), "--", PY, "-c", f"open({str(marker)!r}, 'w')"],
    )
    assert failed.exit_code == 125
    assert "command NOT run" in failed.output
    assert not marker.exists() and not list(outside.iterdir())


def test_large_output_has_bounded_receipt_and_retrieval(tmp_path: Path) -> None:
    script = (
        "import sys\n"
        "for i in range(200000): print(f'row {i:06d} ' + 'x' * 20)\n"
        "print('Z' * 100000)\n"
    )
    code, receipt, evidence_id = capture(tmp_path, PY, "-c", script)
    assert code == 0
    stored = evidence_file(tmp_path, evidence_id)
    assert stored.stat().st_size > 5_000_000
    assert len(receipt) < 2500
    assert "lines 1-" in receipt and "omitted" in receipt
    assert "line truncated in preview: 100000 bytes" in receipt
    view = show_evidence(tmp_path, evidence_id, "stdout", "100-100000", max_chars=1000)
    assert len(view) < 1800
    assert "   100| row 000099" in view
    assert "stopped at line" in view and "--lines" in view
    grep = show_evidence(tmp_path, evidence_id, grep=r"row 1999(98|99)")
    assert "199999| row 199998" in grep and "[2 matching lines; 2 shown]" in grep


def test_full_retrieval_is_exact_and_bounded_default_is_explained(
    tmp_path: Path,
) -> None:
    script = "for i in range(100): print('line', i)"
    _, _, evidence_id = capture(tmp_path, PY, "-c", script)
    runner = CliRunner()
    default = runner.invoke(
        app, ["evidence", "show", evidence_id, "--root", str(tmp_path)]
    )
    assert (
        "    61| line 60" in default.output and "    60| line 59" not in default.output
    )
    assert "[lines 1-60 omitted" in default.output
    full = runner.invoke(
        app, ["evidence", "show", evidence_id, "--full", "--root", str(tmp_path)]
    )
    assert full.stdout_bytes == evidence_file(tmp_path, evidence_id).read_bytes()


def test_changed_and_missing_evidence_are_identified(tmp_path: Path) -> None:
    _, _, evidence_id = capture(tmp_path, PY, "-c", "print('original')")
    update_checkpoint(
        tmp_path,
        {
            "records": [
                {
                    "kind": "verification",
                    "outcome": "inconclusive",
                    "text": "printed original",
                    "evidence": [evidence_id],
                }
            ]
        },
    )
    evidence_file(tmp_path, evidence_id).write_text("tampered\n")
    view = show_evidence(tmp_path, evidence_id)
    assert "integrity CHANGED" in view and "NOT the original capture" in view
    _, optional, _ = briefing_sections(tmp_path, load_checkpoint(tmp_path))
    assert f"{evidence_id} CHANGED" in "\n".join(optional)
    evidence_file(tmp_path, evidence_id).unlink()
    assert "cannot be recovered" in show_evidence(tmp_path, evidence_id, "stdout")
    shutil.rmtree(tmp_path / EVIDENCE_DIR / evidence_id)
    _, optional, _ = briefing_sections(tmp_path, load_checkpoint(tmp_path))
    assert f"{evidence_id} MISSING" in "\n".join(optional)
    result = CliRunner().invoke(
        app, ["evidence", "show", evidence_id, "--root", str(tmp_path)]
    )
    assert result.exit_code == 1 and "MISSING" in result.output
    bad = CliRunner().invoke(
        app, ["evidence", "show", "../../etc", "--root", str(tmp_path)]
    )
    assert bad.exit_code == 1 and "Invalid evidence ID" in bad.output


# --- repository hygiene ------------------------------------------------------


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_generated_state_is_ignored_by_git_and_indexing(tmp_path: Path) -> None:
    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(tmp_path), *args], capture_output=True, text=True
        )

    git("init", "-q")
    source = write(tmp_path, "src/app.py", "def main(): pass\n")
    git("add", "-A")
    git("-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", "init")
    _, _, evidence_id = capture(
        tmp_path, PY, "-c", "print('def leaked_symbol(): pass')"
    )
    update_checkpoint(tmp_path, {"objective": "Goal"})
    assert git("status", "--porcelain").stdout == ""
    assert (
        git("check-ignore", "-q", f"{EVIDENCE_DIR}/{evidence_id}/stdout.log").returncode
        == 0
    )
    paths = {record["path"] for record in build_index(tmp_path)["records"]}
    assert not any(path.startswith(".ai/") for path in paths)
    scanned = {f.relative_path for f in scan_repository(tmp_path, Config()).files}
    assert not any(path.startswith(".ai/work") for path in scanned)
    recorded = worktree_fingerprint(tmp_path)
    assert repository_change(tmp_path, recorded) == "unchanged"
    source.write_text("def main(): return 1\n")
    assert repository_change(tmp_path, recorded) == "CHANGED"
    assert "repository since capture: CHANGED" in show_evidence(tmp_path, evidence_id)


def test_budget_is_never_exceeded_across_sizes(tmp_path: Path) -> None:
    for n in range(6):
        write(tmp_path, f"src/mod_{n}.py", f"def handler_{n}(): pass\n")
    update_checkpoint(
        tmp_path,
        {
            "objective": "Improve handler errors",
            "next": "Check handler_3",
            "records": [
                {"kind": "constraint", "basis": "user", "text": "Keep the API stable."},
                *[{"kind": "todo", "text": f"Todo {n} " + "y" * 90} for n in range(12)],
            ],
        },
    )
    sections = briefing_sections(tmp_path, load_checkpoint(tmp_path))
    index = build_index(tmp_path)
    from ai_context_map.navigation.index import render_brief

    for query in ("handler", "no lexical match zzz"):
        for budget in range(1200, 5000, 37):
            try:
                brief = render_brief(
                    tmp_path, index, query, budget, checkpoint=sections
                )
            except ValueError as exc:
                assert "cannot safely contain" in str(exc)
                continue
            assert len(brief) <= budget
            assert "Keep the API stable." in brief


def test_replace_keeps_unspecified_fields(tmp_path: Path) -> None:
    update_checkpoint(
        tmp_path, {"records": [{"kind": "todo", "status": "blocked", "text": "a"}]}
    )
    update_checkpoint(
        tmp_path,
        {"records": [{"id": "t1", "kind": "todo", "text": "b", "replace": True}]},
    )
    record = load_checkpoint(tmp_path)["records"][0]
    assert (record["text"], record["status"], record["revision"]) == ("b", "blocked", 2)
    with pytest.raises(CheckpointError, match="list of strings"):
        update_checkpoint(
            tmp_path, {"records": [{"kind": "todo", "text": "c", "evidence": [1]}]}
        )
