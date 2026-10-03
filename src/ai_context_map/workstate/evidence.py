"""Explicit command capture: full output on disk, a bounded receipt in context."""

from __future__ import annotations

import json
import re
import secrets
import shlex
import subprocess
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ai_context_map.workstate.store import (
    EVIDENCE_DIR,
    atomic_write_text,
    file_digest,
    iter_lines,
    repository_change,
    utc_now,
    work_path,
    worktree_fingerprint,
)

STREAMS = ("stdout", "stderr")
EVIDENCE_ID = re.compile(r"ev-\d{8}-\d{6}-[0-9a-f]{4}")
PREVIEW_LINE_BYTES = 240
SHOW_LINE_BYTES = 2000
# Wrapper failures use the conventional codes of `env`/`timeout`.
EXIT_CAPTURE_FAILED = 125
EXIT_NOT_EXECUTABLE = 126
EXIT_NOT_FOUND = 127


def command_text(argv: list[str], limit: int = 300) -> str:
    text = shlex.join(argv)
    if len(text) <= limit:
        return text
    return (
        text[:limit]
        + f" [... {len(text) - limit} more characters; full argv in meta.json]"
    )


class CaptureError(RuntimeError):
    """Evidence could not be preserved."""


def evidence_dir(root: Path, evidence_id: str, create: bool = False) -> Path:
    if not EVIDENCE_ID.fullmatch(evidence_id):
        raise ValueError(f"Invalid evidence ID: {evidence_id!r}")
    path = work_path(root, f"{EVIDENCE_DIR}/{evidence_id}", create=create)
    if path.is_symlink():
        raise ValueError(f"Refusing symlinked evidence directory: {evidence_id}")
    return path


def evidence_exists(root: Path, evidence_id: str) -> bool:
    try:
        return (evidence_dir(root, evidence_id) / "meta.json").is_file()
    except ValueError:
        return False


def load_meta(root: Path, evidence_id: str) -> dict[str, Any]:
    path = evidence_dir(root, evidence_id) / "meta.json"
    if not path.is_file():
        raise ValueError(f"Evidence {evidence_id} is MISSING ({path} not found).")
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"Evidence {evidence_id} metadata is unreadable: {exc}"
        ) from exc
    if meta.get("schema_version") != 1 or meta.get("id") != evidence_id:
        raise ValueError(f"Evidence {evidence_id} metadata is invalid or mismatched.")
    return meta


def stream_integrity(root: Path, meta: dict[str, Any], stream: str) -> str:
    """'current', 'CHANGED' (fingerprint mismatch), or 'MISSING'."""
    recorded = meta.get("streams", {}).get(stream)
    path = evidence_dir(root, meta["id"]) / f"{stream}.log"
    if not recorded or not path.is_file() or path.is_symlink():
        return "MISSING"
    return "current" if file_digest(path)[0] == recorded["sha256"] else "CHANGED"


def evidence_status(root: Path, evidence_id: str) -> str:
    """One-word status for references from checkpoint records."""
    try:
        meta = load_meta(root, evidence_id)
    except ValueError:
        return "MISSING"
    if meta.get("status") != "completed":
        return meta.get("status", "invalid").upper()
    states = {stream_integrity(root, meta, stream) for stream in STREAMS}
    for bad in ("MISSING", "CHANGED"):
        if bad in states:
            return bad
    return "current"


def _write_meta(directory: Path, meta: dict[str, Any]) -> None:
    atomic_write_text(directory / "meta.json", json.dumps(meta, indent=2) + "\n")


def _tail(path: Path, count: int) -> tuple[list[tuple[int, str]], int]:
    lines: deque[tuple[int, str]] = deque(maxlen=count)
    total = 0
    for number, prefix, length in iter_lines(path, PREVIEW_LINE_BYTES):
        total = number
        text = prefix.decode("utf-8", "replace")
        if length > len(prefix):
            text += f" [... line truncated in preview: {length} bytes total]"
        lines.append((number, text))
    return list(lines), total


def run_capture(
    root: Path,
    argv: list[str],
    label: str = "",
    preview_lines: int = 12,
    preview_chars: int = 1500,
) -> tuple[int, str]:
    """Run argv without a shell, store complete output, and return (exit code, receipt)."""
    if not argv:
        raise CaptureError(
            "No command supplied. Usage: aicontext capture -- CMD [ARGS...]"
        )
    root = root.resolve()
    started = datetime.now(UTC)
    evidence_id = f"ev-{started:%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
    try:
        directory = evidence_dir(root, evidence_id, create=True)
        directory.parent.mkdir(parents=True, exist_ok=True)
        directory.mkdir()
    except (OSError, ValueError) as exc:
        raise CaptureError(
            f"Cannot create evidence directory; command NOT run: {exc}"
        ) from exc
    meta: dict[str, Any] = {
        "schema_version": 1,
        "id": evidence_id,
        "label": label,
        "argv": argv,
        "cwd": str(Path.cwd()),
        "started_at": started.isoformat(timespec="seconds"),
        "status": "running",
        "repository": worktree_fingerprint(root),
    }
    try:
        _write_meta(directory, meta)
    except OSError as exc:
        raise CaptureError(
            f"Cannot write evidence metadata; command NOT run: {exc}"
        ) from exc

    exit_code: int
    clock = time.monotonic()
    try:
        with (
            (directory / "stdout.log").open("wb") as out,
            (directory / "stderr.log").open("wb") as err,
        ):
            try:
                process = subprocess.Popen(argv, stdout=out, stderr=err)
            except FileNotFoundError as exc:
                meta.update(status="launch_failed", error=f"command not found: {exc}")
                exit_code = EXIT_NOT_FOUND
            except PermissionError as exc:
                meta.update(status="launch_failed", error=f"not executable: {exc}")
                exit_code = EXIT_NOT_EXECUTABLE
            except OSError as exc:
                meta.update(status="launch_failed", error=str(exc))
                exit_code = EXIT_NOT_EXECUTABLE
            else:
                try:
                    returncode = process.wait()
                    meta["status"] = "completed"
                except KeyboardInterrupt:
                    returncode = process.wait()
                    meta["status"] = "interrupted"
                meta["returncode"] = returncode
                # Mirror shell conventions for signals (e.g. SIGKILL -> 137).
                exit_code = 128 - returncode if returncode < 0 else returncode
    except OSError as exc:
        raise CaptureError(
            f"Cannot open evidence files; command NOT run: {exc}"
        ) from exc

    meta["finished_at"] = utc_now()
    meta["duration_seconds"] = round(time.monotonic() - clock, 3)
    meta["exit_code"] = exit_code
    try:
        meta["streams"] = {}
        for stream in STREAMS:
            sha, size, lines = file_digest(directory / f"{stream}.log")
            meta["streams"][stream] = {
                "file": f"{stream}.log",
                "bytes": size,
                "lines": lines,
                "sha256": sha,
            }
        _write_meta(directory, meta)
    except OSError as exc:
        raise CaptureError(
            f"Command finished with exit status {exit_code}, but evidence "
            f"{evidence_id} could NOT be finalized: {exc}. Do not rely on it."
        ) from exc
    return exit_code, render_receipt(root, meta, preview_lines, preview_chars)


def render_receipt(
    root: Path, meta: dict[str, Any], preview_lines: int, preview_chars: int
) -> str:
    directory = evidence_dir(root, meta["id"])
    relative = directory.relative_to(root.resolve()).as_posix()
    lines = [
        f"capture: {meta['label'] or '(no label)'}",
        f"command: {command_text(meta['argv'])}",
        f"exit status: {meta['exit_code']}"
        + {
            "launch_failed": f" (LAUNCH FAILED: {meta.get('error')})",
            "interrupted": " (interrupted)",
        }.get(meta["status"], ""),
        f"evidence: {meta['id']} ({relative}/)",
    ]
    for stream in STREAMS:
        info = meta["streams"][stream]
        lines.append(
            f"{stream}: {info['bytes']} bytes, {info['lines']} lines, sha256 {info['sha256'][:12]}"
            if info["bytes"]
            else f"{stream}: empty"
        )
    budget = preview_chars
    omitted_any = False
    # stderr usually carries the error; give it a smaller, separate share.
    for stream, share in (
        ("stderr", max(1, preview_lines // 2)),
        ("stdout", preview_lines),
    ):
        info = meta["streams"][stream]
        if not info["bytes"]:
            continue
        tail, total = _tail(directory / f"{stream}.log", share)
        shown: list[str] = []
        for number, text in reversed(tail):
            row = f"{number:>6}| {text}"
            if len(row) + 1 > budget:
                break
            budget -= len(row) + 1
            shown.insert(0, row)
        first = total - len(shown) + 1
        header = f"--- {stream} preview: last {len(shown)} of {total} lines"
        if first > 1:
            header += f" (lines 1-{first - 1} omitted)"
            omitted_any = True
        lines += [header + " ---", *shown]
    if not any(meta["streams"][stream]["bytes"] for stream in STREAMS):
        lines.append("--- no output on stdout or stderr ---")
    retrieval = f"aicontext evidence show {meta['id']}"
    lines.append(
        ("Omitted output is preserved. " if omitted_any else "Full output preserved. ")
        + f"Retrieve: `{retrieval} --stream stdout --lines A-B`, `--grep REGEX`, or `--full`."
    )
    lines.append(
        "Exit status reports how the process ended; read the output before claiming results."
    )
    return "\n".join(lines) + "\n"


def parse_range(text: str) -> tuple[int, int | None]:
    match = re.fullmatch(r"(\d+)(?:-(\d*))?", text.strip())
    if not match or int(match.group(1)) < 1:
        raise ValueError("--lines must look like 10-40, 10-, or 25 (1-based).")
    start = int(match.group(1))
    end = (
        start
        if match.group(2) is None
        else (int(match.group(2)) if match.group(2) else None)
    )
    if end is not None and end < start:
        raise ValueError("--lines end must not precede start.")
    return start, end


def show_evidence(
    root: Path,
    evidence_id: str,
    stream: str | None = None,
    lines: str | None = None,
    grep: str | None = None,
    max_chars: int = 4000,
    tail_lines: int = 40,
) -> str:
    """Bounded, line-numbered view of evidence with integrity and staleness notes."""
    root = root.resolve()
    meta = load_meta(root, evidence_id)
    directory = evidence_dir(root, evidence_id)
    out = [
        f"evidence: {evidence_id} — {meta.get('label') or '(no label)'}",
        f"command: {command_text(meta['argv'])}",
        f"captured: {meta['started_at']}; status: {meta['status']}; exit status: {meta.get('exit_code')}",
        f"repository since capture: {repository_change(root, meta.get('repository'))}",
    ]
    if meta["status"] != "completed":
        out.append(
            f"WARNING: capture status is {meta['status']!r}; output may be partial."
            + (f" Error: {meta['error']}" if meta.get("error") else "")
        )
    if "streams" not in meta:
        out.append("No stream metadata recorded; evidence is incomplete.")
        return "\n".join(out) + "\n"
    selected = (
        [stream] if stream else [s for s in STREAMS if meta["streams"][s]["bytes"]]
    )
    if not selected:
        out.append("Both streams are empty.")
    pattern = re.compile(grep) if grep else None
    start, end = parse_range(lines) if lines else (1, None)
    budget = max_chars
    for name in selected:
        info = meta["streams"][name]
        integrity = stream_integrity(root, meta, name)
        out.append(
            f"--- {name}: {info['bytes']} bytes, {info['lines']} lines; integrity {integrity} ---"
        )
        if integrity == "MISSING":
            out.append(f"{name}.log is missing; this output cannot be recovered.")
            continue
        if integrity == "CHANGED":
            out.append(
                f"WARNING: {name}.log no longer matches its recorded sha256; it is NOT the original capture."
            )
        path = directory / f"{name}.log"
        if pattern is None and lines is None:
            # Default view: the tail, where summaries and errors usually are.
            first, last = max(1, info["lines"] - tail_lines + 1), None
        else:
            first, last = start, end
        shown = matched = in_range = 0
        stopped_at: int | None = None
        for number, prefix, length in iter_lines(path, SHOW_LINE_BYTES):
            if number < first:
                continue
            if last is not None and number > last:
                break
            in_range += 1
            text = prefix.decode("utf-8", "replace")
            if pattern and not pattern.search(text):
                continue
            matched += 1
            if stopped_at is not None:
                continue
            if length > len(prefix):
                text += f" [... line truncated: {length} bytes; use --full]"
            row = f"{number:>6}| {text}"
            if len(row) + 1 > budget:
                stopped_at = number
                if not pattern:
                    break
                continue
            budget -= len(row) + 1
            out.append(row)
            shown += 1
        if pattern:
            out.append(
                f"[{matched} matching lines; {shown} shown"
                + (
                    f"; output stopped at line {stopped_at} by --max-chars {max_chars}"
                    if stopped_at
                    else ""
                )
                + "]"
            )
        elif stopped_at:
            out.append(
                f"[stopped at line {stopped_at} by --max-chars {max_chars}; "
                f"continue with --stream {name} --lines {stopped_at}-{last or ''}]"
            )
        elif not in_range:
            out.append(f"[no lines in range; {name} has {info['lines']} lines]")
        elif first > 1 and lines is None:
            out.append(
                f"[lines 1-{first - 1} omitted; use --stream {name} --lines 1-{first - 1}]"
            )
    out.append(
        f"Complete output: `aicontext evidence show {evidence_id} --stream NAME --full` (raw, unbounded)."
    )
    return "\n".join(out) + "\n"


def full_stream_path(root: Path, evidence_id: str, stream: str) -> tuple[Path, str]:
    meta = load_meta(root, evidence_id)
    integrity = stream_integrity(root, meta, stream)
    if integrity == "MISSING":
        raise ValueError(f"Evidence {evidence_id} {stream}.log is MISSING.")
    return evidence_dir(root, evidence_id) / f"{stream}.log", integrity


def list_evidence(root: Path, limit: int = 20) -> str:
    base = work_path(root, EVIDENCE_DIR)
    ids = sorted(
        (p.name for p in base.iterdir() if EVIDENCE_ID.fullmatch(p.name))
        if base.is_dir()
        else [],
        reverse=True,
    )
    if not ids:
        return (
            "No evidence captured. Use `aicontext capture --label NAME -- CMD ...`.\n"
        )
    rows = []
    for evidence_id in ids[:limit]:
        try:
            meta = load_meta(root, evidence_id)
            size = sum(info["bytes"] for info in meta.get("streams", {}).values())
            rows.append(
                f"{evidence_id}  exit {meta.get('exit_code')}  {size} bytes  "
                f"[{evidence_status(root, evidence_id)}]  {meta.get('label') or shlex.join(meta['argv'])[:60]}"
            )
        except ValueError as exc:
            rows.append(f"{evidence_id}  [INVALID] {exc}")
    if len(ids) > limit:
        rows.append(f"... {len(ids) - limit} older records omitted (use --limit).")
    return "\n".join(rows) + "\n"
