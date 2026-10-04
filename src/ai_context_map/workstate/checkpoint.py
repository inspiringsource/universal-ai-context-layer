"""Explicitly recorded working checkpoint: small, versioned, identifiable records."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from ai_context_map.navigation.index import safe_path
from ai_context_map.workstate.evidence import evidence_exists, evidence_status
from ai_context_map.workstate.store import (
    CHECKPOINT_PATH,
    atomic_write_text,
    repository_change,
    utc_now,
    work_path,
    worktree_fingerprint,
)

SCHEMA_VERSION = 1
# kind -> (id prefix, default basis or None when it must be stated, statuses)
KINDS: dict[str, tuple[str, str | None, tuple[str, ...]]] = {
    "objective": ("obj", "user", ("active",)),
    "next": ("next", "agent", ("active",)),
    "progress": ("p", "agent", ("in_progress", "attempted", "done", "blocked")),
    "todo": ("t", "agent", ("open", "done", "blocked")),
    "decision": ("d", "agent", ("active", "retired")),
    "rejected": ("r", "agent", ("active",)),
    "constraint": ("c", None, ("active", "retired")),
    "verification": ("v", "observed", ("active",)),
    "assumption": ("a", "assumed", ("unverified", "confirmed", "refuted")),
    "question": ("q", "assumed", ("open", "resolved")),
}
BASES = {
    "user": "user instruction",
    "observed": "verified observation; must cite evidence or refs",
    "agent": "agent decision or judgement",
    "assumed": "unverified assumption",
}
# Short labels keep repeated per-record markers cheap in the entry file.
BASIS_LABELS = {
    "user": "user instruction",
    "observed": "observed",
    "agent": "agent",
    "assumed": "UNVERIFIED",
}
OUTCOMES = ("passed", "failed", "partial", "inconclusive")
SINGLETONS = ("objective", "next")
INPUT_FIELDS = {
    "id",
    "kind",
    "text",
    "basis",
    "status",
    "reason",
    "outcome",
    "evidence",
    "refs",
    "supersedes",
    "blocking",
}
STORED_FIELDS = INPUT_FIELDS | {"created_at", "updated_at", "revision", "superseded_by"}
CONTENT_FIELDS = INPUT_FIELDS - {"id", "supersedes"}
RECORD_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
REF = re.compile(r"(?P<path>[^:\s][^:]*?)(?::(?P<start>\d+)(?:-(?P<end>\d+))?)?")
MAX_TEXT = 2000
TEMPLATE = {
    "objective": "One sentence: what the work must achieve.",
    "next": "The single next concrete action.",
    "records": [
        {
            "id": "c-no-force",
            "kind": "constraint",
            "basis": "user",
            "text": "Never overwrite a root AGENTS.md without --force.",
        },
        {
            "kind": "decision",
            "text": "Store evidence under .ai/work/.",
            "reason": "Self-ignoring directory keeps it out of Git.",
        },
        {
            "kind": "rejected",
            "text": "Parsing output with regex filters per tool.",
            "reason": "Failed on pytest -q formatting; see evidence.",
            "evidence": ["ev-20260101-120000-abcd"],
        },
        {
            "kind": "verification",
            "outcome": "passed",
            "text": "pytest: 31 passed, 0 failed (read from output).",
            "evidence": ["ev-20260101-120000-abcd"],
        },
        {"kind": "progress", "status": "attempted", "text": "Tried X; not verified."},
        {"kind": "assumption", "text": "CI uses Python 3.11 (not checked)."},
        {
            "kind": "question",
            "text": "Should --force also apply to CLAUDE.md?",
            "blocking": True,
        },
        {"id": "p1", "status": "done", "evidence": ["ev-..."], "replace": True},
    ],
}


class CheckpointError(ValueError):
    """Invalid checkpoint input or state; nothing was written."""


def empty_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": None,
        "repository": None,
        "records": [],
    }


def load_checkpoint(root: Path) -> dict[str, Any] | None:
    """Load and validate; None when absent. Invalid files raise rather than reset."""
    path = work_path(root, CHECKPOINT_PATH)
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CheckpointError(
            f"{CHECKPOINT_PATH} is unreadable ({exc}); fix or move it."
        ) from exc
    validate_state(state)
    return state


def _fail(message: str) -> None:
    raise CheckpointError(message)


def _check_ref(root: Path | None, ref: Any) -> list[str]:
    if not isinstance(ref, str) or not (match := REF.fullmatch(ref)):
        _fail(f"Invalid ref {ref!r}; use path, path:LINE, or path:START-END.")
    if root is None:
        return []
    try:
        path = safe_path(root, match["path"])
    except ValueError as exc:
        raise CheckpointError(str(exc)) from exc
    return [] if path.exists() else [f"ref {ref!r} does not exist (recorded anyway)"]


def validate_record(record: dict[str, Any], stored: bool = True) -> None:
    allowed = STORED_FIELDS if stored else INPUT_FIELDS
    unknown = set(record) - allowed
    if unknown:
        _fail(f"Unknown field(s) {sorted(unknown)} in record {record.get('id', '?')}.")
    rid = record.get("id")
    if not isinstance(rid, str) or not RECORD_ID.fullmatch(rid):
        _fail(
            f"Invalid record id {rid!r}; use lowercase letters, digits, '.', '_' or '-'."
        )
    kind = record.get("kind")
    if kind not in KINDS:
        _fail(f"{rid}: kind must be one of {sorted(KINDS)}.")
    _, _, statuses = KINDS[kind]
    text = record.get("text")
    if not isinstance(text, str) or not text.strip():
        _fail(f"{rid}: text is required.")
    for field in ("text", "reason"):
        if isinstance(record.get(field), str) and len(record[field]) > MAX_TEXT:
            _fail(
                f"{rid}: {field} exceeds {MAX_TEXT} characters; store long output as evidence "
                "with `aicontext capture` and cite its ID."
            )
    if "reason" in record and not isinstance(record["reason"], str):
        _fail(f"{rid}: reason must be a string.")
    if record.get("basis") not in BASES:
        _fail(
            f"{rid}: basis must be one of {sorted(BASES)} ({kind} has no safe default)."
        )
    if record.get("status") not in statuses:
        _fail(f"{rid}: status for {kind} must be one of {list(statuses)}.")
    for field in ("evidence", "refs"):
        value = record.get(field, [])
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in value
        ):
            _fail(f"{rid}: {field} must be a list of strings.")
    cited = bool(record.get("evidence") or record.get("refs"))
    if record["basis"] == "observed" and not cited:
        _fail(f"{rid}: an observed record must cite evidence IDs or source refs.")
    if kind in {"assumption", "question"} and record["basis"] != "assumed":
        _fail(f"{rid}: {kind} records are unverified by definition (basis 'assumed').")
    if kind == "assumption" and record["status"] != "unverified" and not cited:
        _fail(f"{rid}: confirming or refuting an assumption requires evidence or refs.")
    if kind == "verification":
        if record["basis"] != "observed":
            _fail(f"{rid}: verification records must have basis 'observed'.")
        if record.get("outcome") not in OUTCOMES:
            _fail(f"{rid}: verification outcome must be one of {list(OUTCOMES)}.")
    elif "outcome" in record:
        _fail(f"{rid}: outcome applies only to verification records.")
    if kind in {"decision", "rejected"} and not str(record.get("reason", "")).strip():
        _fail(f"{rid}: {kind} records require a reason.")
    if record["status"] == "retired" and not str(record.get("reason", "")).strip():
        _fail(f"{rid}: retiring a {kind} requires a reason.")
    if "blocking" in record and not isinstance(record["blocking"], bool):
        _fail(f"{rid}: blocking must be true or false.")


def validate_state(state: Any) -> None:
    if not isinstance(state, dict) or state.get("schema_version") != SCHEMA_VERSION:
        _fail(
            f"Unsupported checkpoint schema; expected schema_version {SCHEMA_VERSION}."
        )
    if set(state) - {"schema_version", "updated_at", "repository", "records"}:
        _fail("Unknown top-level checkpoint fields.")
    records = state.get("records")
    if not isinstance(records, list):
        _fail("Checkpoint records must be a list.")
    by_id: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            _fail("Each checkpoint record must be an object.")
        validate_record(record)
        if record["id"] in by_id:
            _fail(f"Duplicate record id {record['id']}.")
        by_id[record["id"]] = record
    for record in records:
        for link in ("supersedes", "superseded_by"):
            if link in record and record[link] not in by_id:
                _fail(
                    f"{record['id']}: {link} points to unknown record {record[link]}."
                )
    for kind in SINGLETONS:
        current = [r["id"] for r in records if r["kind"] == kind and is_current(r)]
        if len(current) > 1:
            _fail(f"More than one current {kind}: {current}.")


def is_current(record: dict[str, Any]) -> bool:
    return "superseded_by" not in record


def _content(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: record[key]
        for key in CONTENT_FIELDS
        if key in record and record[key] != []
    }


def _normalize(item: dict[str, Any]) -> dict[str, Any]:
    record = {key: value for key, value in item.items() if key != "replace"}
    kind = record.get("kind")
    if kind in KINDS:
        _, basis, statuses = KINDS[kind]
        if basis is not None:
            record.setdefault("basis", basis)
        record.setdefault("status", statuses[0])
    return record


def _next_id(records: list[dict[str, Any]], kind: str) -> str:
    prefix = KINDS[kind][0]
    numbers = [
        int(match.group(1))
        for record in records
        if (match := re.fullmatch(re.escape(prefix) + r"(\d+)", record["id"]))
    ]
    return f"{prefix}{max(numbers, default=0) + 1}"


def apply_update(
    state: dict[str, Any] | None, payload: Any, root: Path | None = None
) -> tuple[dict[str, Any], list[str]]:
    """Apply a JSON update to a copy of state. Raises CheckpointError; never partial."""
    state = copy.deepcopy(state) if state else empty_state()
    if not isinstance(payload, dict):
        _fail("Checkpoint input must be a JSON object.")
    unknown = set(payload) - {"objective", "next", "records"}
    if unknown:
        _fail(
            f"Unknown top-level input field(s) {sorted(unknown)}; expected objective, next, records."
        )
    items: list[dict[str, Any]] = []
    for kind in SINGLETONS:
        if kind in payload:
            value = payload[kind]
            value = {"text": value} if isinstance(value, str) else value
            if not isinstance(value, dict):
                _fail(f"{kind} must be a string or record object.")
            if value.setdefault("kind", kind) != kind:
                _fail(f"{kind} field must hold a {kind} record.")
            items.append(value)
    records_in = payload.get("records", [])
    if not isinstance(records_in, list):
        _fail("records must be a list.")
    items.extend(records_in)

    now = utc_now()
    records: list[dict[str, Any]] = state["records"]
    by_id = {record["id"]: record for record in records}
    report: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            _fail("Each record must be a JSON object.")
        if set(item) - INPUT_FIELDS - {"replace"}:
            _fail(f"Unknown field(s) {sorted(set(item) - INPUT_FIELDS - {'replace'})}.")
        replace = item.get("replace", False)
        if not isinstance(replace, bool):
            _fail("replace must be true or false.")
        for ref in item.get("refs", []) if isinstance(item.get("refs"), list) else []:
            report += [f"warning: {w}" for w in _check_ref(root, ref)]
        if root is not None:
            for evidence_id in (
                item.get("evidence", [])
                if isinstance(item.get("evidence"), list)
                else []
            ):
                if isinstance(evidence_id, str) and not evidence_exists(
                    root, evidence_id
                ):
                    _fail(f"Evidence {evidence_id!r} does not exist; capture it first.")

        existing = by_id.get(item.get("id", ""))
        if existing is not None:
            if "supersedes" in item and item["supersedes"] != existing.get(
                "supersedes"
            ):
                _fail(f"{existing['id']}: supersedes can only be set on a new record.")
            if replace:
                if item.get("kind", existing["kind"]) != existing["kind"]:
                    _fail(
                        f"{existing['id']}: kind cannot change; supersede it with a new record."
                    )
                # No defaults here: omitted fields keep their recorded values.
                candidate = {
                    **existing,
                    **{k: v for k, v in item.items() if k != "replace"},
                }
                # Changing status may drop a field that no longer applies.
                candidate = {k: v for k, v in candidate.items() if v is not None}
            else:
                candidate = {**_normalize({"kind": existing["kind"], **item})}
                for key in (
                    "created_at",
                    "updated_at",
                    "revision",
                    "superseded_by",
                    "supersedes",
                ):
                    if key in existing:
                        candidate[key] = existing[key]
            validate_record(candidate)
            if _content(candidate) == _content(existing):
                report.append(f"unchanged {existing['id']}")
                continue
            if not replace:
                _fail(
                    f"Record {existing['id']} already exists with different content. "
                    'Add "replace": true to change it, or use a new id with "supersedes".'
                )
            candidate["revision"] = existing.get("revision", 1) + 1
            candidate["updated_at"] = now
            records[records.index(existing)] = candidate
            by_id[candidate["id"]] = candidate
            report.append(
                f"replaced {candidate['id']} (revision {candidate['revision']})"
            )
            continue

        if replace:
            _fail(f"Cannot replace unknown record {item.get('id')!r}.")
        record = _normalize(item)
        kind = record.get("kind")
        if kind not in KINDS:
            _fail(f"New records need kind, one of {sorted(KINDS)}.")
        if "id" not in record:
            duplicate = next(
                (
                    r
                    for r in records
                    if is_current(r)
                    and r["kind"] == kind
                    and r["text"] == record.get("text")
                ),
                None,
            )
            if duplicate is not None:
                probe = {**record, "id": duplicate["id"]}
                if _content(probe) == _content(duplicate):
                    report.append(
                        f"unchanged {duplicate['id']} (same {kind} already recorded)"
                    )
                    continue
                _fail(
                    f"A current {kind} with the same text exists as {duplicate['id']}; "
                    'update it by id with "replace": true.'
                )
            record["id"] = _next_id(records, kind)
        if kind in SINGLETONS and "supersedes" not in record:
            current = next(
                (r for r in records if r["kind"] == kind and is_current(r)), None
            )
            if current is not None:
                record["supersedes"] = current["id"]
        record.update(created_at=now, updated_at=now, revision=1)
        validate_record(record)
        target_id = record.get("supersedes")
        if target_id is not None:
            target = by_id.get(target_id)
            if target is None:
                _fail(f"{record['id']}: supersedes unknown record {target_id!r}.")
            if not is_current(target):
                _fail(
                    f"{target_id} is already superseded by {target['superseded_by']}."
                )
            if target["kind"] == "constraint" and record["kind"] != "constraint":
                _fail(
                    f"Constraint {target_id} can only be superseded by another constraint."
                )
            target["superseded_by"] = record["id"]
            target["updated_at"] = now
        records.append(record)
        by_id[record["id"]] = record
        report.append(
            f"added {record['id']} ({kind})"
            + (f", supersedes {target_id}" if target_id else "")
        )
    validate_state(state)
    if any(not line.startswith(("unchanged", "warning")) for line in report):
        state["updated_at"] = now
        if root is not None:
            state["repository"] = worktree_fingerprint(root)
    return state, report


def save_checkpoint(root: Path, state: dict[str, Any]) -> Path:
    validate_state(state)
    path = work_path(root, CHECKPOINT_PATH, create=True)
    atomic_write_text(path, json.dumps(state, indent=2, ensure_ascii=False) + "\n")
    return path


def update_checkpoint(root: Path, payload: Any) -> list[str]:
    root = root.resolve()
    state, report = apply_update(load_checkpoint(root), payload, root)
    if any(not line.startswith(("unchanged", "warning")) for line in report):
        save_checkpoint(root, state)
    else:
        report.append("no changes; checkpoint not rewritten")
    return report


def _evidence_note(root: Path, record: dict[str, Any]) -> str:
    parts = [
        f"{eid} {evidence_status(root, eid)}" for eid in record.get("evidence", [])
    ]
    parts += record.get("refs", [])
    return f" [evidence: {', '.join(parts)}]" if parts else ""


def format_record(root: Path, record: dict[str, Any], limit: int | None = None) -> str:
    kind = record["kind"]
    # Questions are labelled by their status; their basis adds nothing.
    label = [record["id"]] + (
        [] if kind == "question" else [BASIS_LABELS[record["basis"]]]
    )
    if kind == "verification":
        label.insert(1, record["outcome"].upper())
    elif record["status"] not in {"active", "unverified"}:
        status = record["status"]
        if status == "done" and not (record.get("evidence") or record.get("refs")):
            status = "done, unverified"
        label.insert(1, status)
    if record.get("blocking"):
        label.append("BLOCKING")
    if record.get("supersedes"):
        label.append(f"supersedes {record['supersedes']}")
    text = record["text"]
    if record.get("reason"):
        text += f" — because: {record['reason']}"
    if limit is not None and len(text) > limit:
        text = (
            text[:limit].rstrip()
            + f" [... truncated; full: aicontext checkpoint show --id {record['id']}]"
        )
    return f"- [{'; '.join(label)}] {text}{_evidence_note(root, record)}"


def is_blocker(record: dict[str, Any]) -> bool:
    return record["status"] == "blocked" or (
        record["kind"] == "question"
        and record["status"] == "open"
        and bool(record.get("blocking"))
    )


def briefing_sections(
    root: Path, state: dict[str, Any] | None
) -> tuple[list[str], list[str], dict[str, int]]:
    """Return (essential lines, optional lines in priority order, counts).

    Essential lines must never be truncated or dropped; optional lines are
    whole records that may be omitted behind `aicontext checkpoint show`.
    """
    if state is None:
        return (
            [
                "## Working checkpoint",
                "",
                "No checkpoint recorded. Continuation state (objective, decisions, constraints) "
                "is unknown; ask the user or record one with `aicontext checkpoint update`.",
                "",
            ],
            [],
            {"current": 0, "superseded": 0},
        )
    # Position breaks timestamp ties (second precision): later records are newer.
    order = {r["id"]: n for n, r in enumerate(state["records"])}
    current = [r for r in state["records"] if is_current(r)]
    by_kind: dict[str, list[dict[str, Any]]] = {kind: [] for kind in KINDS}
    for record in current:
        by_kind[record["kind"]].append(record)
    for kind_records in by_kind.values():
        kind_records.sort(key=lambda r: (r["updated_at"], order[r["id"]]), reverse=True)
    missing = [kind for kind in SINGLETONS if not by_kind[kind]]
    essential = [
        "## Working checkpoint",
        "",
        "Recorded explicitly by an agent, not inferred. Labels: user instruction; "
        "observed (cites evidence); agent (decision/judgement); UNVERIFIED (assumption). "
        "Verify before relying on it.",
        f"Updated: {state['updated_at']}; repository since update: "
        f"{repository_change(root, state.get('repository'))}.",
    ]
    if missing:
        essential.append(f"CHECKPOINT INCOMPLETE: no {' or '.join(missing)} recorded.")
    essential.append("")
    for kind, title in (("objective", "Objective"), ("next", "Next action")):
        for record in by_kind[kind]:
            essential.append(f"{title}: {format_record(root, record)[2:]}")
    constraints = [r for r in by_kind["constraint"] if r["status"] == "active"]
    essential += ["", "Constraints (all active constraints; never omitted):"]
    essential += [format_record(root, r) for r in constraints] or ["- none recorded"]
    blockers = [
        r
        for kind in ("progress", "todo", "question")
        for r in by_kind[kind]
        if is_blocker(r)
    ]
    essential += ["", "Unresolved blockers:"]
    essential += [format_record(root, r) for r in blockers] or ["- none recorded"]
    essential.append("")

    def pick(kind: str, statuses: set[str] | None = None) -> list[dict[str, Any]]:
        return [
            r
            for r in by_kind[kind]
            if (statuses is None or r["status"] in statuses) and not is_blocker(r)
        ]

    optional: list[str] = []
    groups = [
        (
            "Unfinished work",
            pick("progress", {"in_progress", "attempted"}) + pick("todo", {"open"}),
        ),
        ("Recent verification", pick("verification")),
        ("Decisions", pick("decision", {"active"})[:5]),
        ("Rejected approaches", pick("rejected")),
        (
            "Open assumptions and questions",
            pick("assumption", {"unverified"}) + pick("question", {"open"}),
        ),
        ("Completed", pick("progress", {"done"}) + pick("todo", {"done"})),
    ]
    for title, records in groups:
        if records:
            optional.append(f"### {title}")
            optional += [format_record(root, r, limit=300) for r in records]
    counts = {
        "current": len(current),
        "superseded": len(state["records"]) - len(current),
        "decisions_beyond_short_list": max(0, len(pick("decision", {"active"})) - 5),
    }
    return essential, optional, counts


def render_checkpoint(
    root: Path,
    state: dict[str, Any] | None,
    show_all: bool = False,
    record_id: str | None = None,
) -> str:
    if state is None:
        return "No checkpoint recorded. Start with `aicontext checkpoint template`.\n"
    if record_id:
        record = next((r for r in state["records"] if r["id"] == record_id), None)
        if record is None:
            raise CheckpointError(f"No record {record_id!r}.")
        return json.dumps(record, indent=2, ensure_ascii=False) + "\n"
    essential, optional, counts = briefing_sections(root, state)
    lines = [*essential, *optional]
    if show_all:
        superseded = [r for r in state["records"] if not is_current(r)]
        if superseded:
            lines += ["### Superseded (history)"]
            lines += [
                format_record(root, r) + f" -> superseded by {r['superseded_by']}"
                for r in superseded
            ]
        retired = [
            r
            for r in state["records"]
            if is_current(r)
            and r["status"] in {"retired", "refuted", "resolved", "confirmed"}
        ]
        if retired:
            lines += ["### Retired, resolved, confirmed or refuted"]
            lines += [format_record(root, r) for r in retired]
    else:
        lines.append(
            f"{counts['superseded']} superseded record(s) hidden; use --all. "
            "Raw JSON for one record: --id ID."
        )
    return "\n".join(lines) + "\n"


CITATION_ORDER = ("next", "objective", "progress", "todo", "constraint", "decision")


def cited_paths(state: dict[str, Any] | None) -> list[tuple[str, str]]:
    """(path, record id) for files cited by current, unfinished checkpoint records.

    These are the agent's recorded pointers; `pack` lists them as such, separately
    from lexical matches. Done, retired, or superseded records are not cited.
    """
    if state is None:
        return []
    cited: list[tuple[str, str]] = []
    for kind in CITATION_ORDER:
        for record in state["records"]:
            if (
                record["kind"] != kind
                or not is_current(record)
                or record["status"] in {"done", "retired"}
            ):
                continue
            for ref in record.get("refs", []):
                match = REF.fullmatch(ref)
                path = match["path"] if match else None
                if path and path not in {p for p, _ in cited}:
                    cited.append((path, record["id"]))
    return cited
