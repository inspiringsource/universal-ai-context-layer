"""Local navigation evaluation for the structural map on external JS/TS repositories.

Compares, per task in benchmarks/structural_tasks.json, with a fixed 6,000
character entry budget and six shortlist slots:

- previous: UACL at commit eb84ee5 (regex JS/TS hints), run from `git archive`;
- structural: the current Tree-sitter map plus `aicontext symbol` retrieval;
- search: a scripted stand-in for ordinary targeted search (ripgrep-style
  matching of the request's words, then reading files).

It measures discovery and characters of text exposed under stated reading
rules. It does not run a model, so it cannot show that an agent would follow
the map, finish a task, or use fewer tokens. Characters are not tokens.

Usage:
  uv run python benchmarks/evaluate_structure.py --repos-dir DIR [--clone] [--out FILE]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import statistics
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

from ai_context_map.navigation.index import (
    build_index,
    render_brief,
    select_records,
    serialize_index,
    terms,
)
from ai_context_map.navigation.retrieve import retrieve_symbol
from ai_context_map.navigation.structure import _find_export, symbol_id
from ai_context_map.scanner.ignore import DEFAULT_IGNORED_DIRS

ROOT = Path(__file__).resolve().parents[1]
PREVIOUS_COMMIT = "eb84ee5"
BUDGET = 6000
SLOTS = 6
WINDOW = 80  # lines an agent might read from a shown line instead of the whole file
SEARCH_LINES_PER_FILE = 5
SEARCH_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".md", ".json"}

PREVIOUS_RUNNER = r"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from ai_context_map.navigation.index import build_index, render_brief, select_records
root = Path(sys.argv[2]); tasks = json.loads(sys.argv[3])
start = time.perf_counter(); index = build_index(root); elapsed = time.perf_counter() - start
out = {"index_seconds": elapsed, "index_characters": len(json.dumps(index, indent=2) + "\n"), "tasks": {}}
for task in tasks:
    out["tasks"][task["id"]] = {
        "selected": [r["path"] for r in select_records(index, task["task"], 6)],
        "brief": render_brief(root, index, task["task"], 6000),
    }
print(json.dumps(out))
"""


def clone(repos_dir: Path, name: str, meta: dict) -> Path:
    target = repos_dir / name
    if not target.exists():
        subprocess.run(["git", "clone", "-q", meta["url"], str(target)], check=True)
    subprocess.run(
        ["git", "-C", str(target), "checkout", "-q", meta["commit"]], check=True
    )
    return target


def head(path: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()


def previous_source(workdir: Path) -> Path:
    archive = subprocess.run(
        ["git", "-C", str(ROOT), "archive", PREVIOUS_COMMIT, "src"],
        capture_output=True,
        check=True,
    ).stdout
    subprocess.run(["tar", "-x", "-C", str(workdir)], input=archive, check=True)
    return workdir / "src"


def run_previous(source: Path, repo: Path, tasks: list[dict]) -> dict:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            PREVIOUS_RUNNER,
            str(source),
            str(repo),
            json.dumps(tasks),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


# -- ordinary targeted search stand-in ---------------------------------------------


def search_files(repo: Path) -> list[Path]:
    files = []
    for directory, dirs, names in os.walk(repo):
        dirs[:] = sorted(
            d for d in dirs if d not in DEFAULT_IGNORED_DIRS and d != ".ai"
        )
        for name in sorted(names):
            path = Path(directory) / name
            if path.suffix in SEARCH_EXTENSIONS and not path.is_symlink():
                files.append(path)
    return files


def targeted_search(repo: Path, files: list[Path], query: str) -> tuple[list[str], str]:
    """Case-insensitive search for each request word (same tokenizer as UACL).

    Files are ranked by distinct words matched (rarer words weigh more), then
    by match count; the output shows up to five matching lines per top file,
    like `rg -n -m 5 -i 'word1|word2'` restricted to the six best files.
    """
    words = sorted(terms(query))
    pattern = re.compile("|".join(re.escape(word) for word in words), re.IGNORECASE)
    hits: dict[str, tuple[set[str], list[tuple[int, str]]]] = {}
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        found: set[str] = set()
        lines: list[tuple[int, str]] = []
        for number, line in enumerate(text.splitlines(), 1):
            matches = {m.group(0).lower() for m in pattern.finditer(line)}
            if matches:
                found |= matches
                lines.append((number, line.strip()[:160]))
        if found:
            hits[path.relative_to(repo).as_posix()] = (found, lines)
    frequency = Counter(word for found, _ in hits.values() for word in found)
    ranked = sorted(
        hits,
        key=lambda p: (
            -sum(math.log(1 + len(hits) / frequency[w]) for w in hits[p][0]),
            -len(hits[p][1]),
            p,
        ),
    )[:SLOTS]
    output = "".join(
        f"{path}:{number}:{line}\n"
        for path in ranked
        for number, line in hits[path][1][:SEARCH_LINES_PER_FILE]
    )
    return ranked, output


# -- measurement helpers ---------------------------------------------------------


def located(output: str, mode: str, index: dict | None = None) -> set[tuple[str, int]]:
    """(file, line) pairs an output points at, under each format's notation.

    `path::symbol` references (CALLS lines) count at that symbol's parsed line.
    """
    pairs: set[tuple[str, int]] = set()
    if index is not None:
        for path, name in re.findall(r"([\w./@-]+\.[jt]sx?)::([\w$.#]+)", output):
            record = next((r for r in index["records"] if r["path"] == path), None)
            symbol = record and next(
                (s for s in record["symbols"] if symbol_id(s) == name), None
            )
            if symbol:
                pairs.add((path, symbol["line"]))
    if mode == "search":
        for match in re.finditer(r"^([^\s:]+):(\d+):", output, re.MULTILINE):
            pairs.add((match.group(1), int(match.group(2))))
        return pairs
    current = None
    for line in output.splitlines():
        pointer = re.match(r"- `([^`]+)`", line)
        if pointer:
            current = pointer.group(1)
            for name_line in re.findall(r"[\w$.#]+:(\d+)", line.split("]:", 1)[-1]):
                pairs.add((current, int(name_line)))
        elif current and line.startswith("  "):
            for start in re.findall(r" @(\d+)(?:-\d+)?", line):
                pairs.add((current, int(start)))
    return pairs


def file_characters(repo: Path, relative: str) -> int:
    return len((repo / relative).read_text(encoding="utf-8"))


def window_characters(repo: Path, relative: str, line: int) -> int:
    lines = (repo / relative).read_text(encoding="utf-8").splitlines(keepends=True)
    return len("".join(lines[line - 1 : line - 1 + WINDOW]))


def find_symbol(index: dict, relative: str, name: str) -> dict | None:
    record = next((r for r in index["records"] if r["path"] == relative), None)
    if record is None:
        return None
    return next((s for s in record["symbols"] if s["name"] == name), None)


def evaluate_task(task, repo, index, previous, files) -> dict:
    query = task["task"]
    expected = task["expected"]
    files_wanted = {item["file"] for item in expected}
    structural_paths = [r["path"] for r in select_records(index, query, SLOTS)]
    brief = render_brief(repo, index, query, BUDGET)
    previous_paths = previous["selected"]
    previous_brief = previous["brief"]
    search_paths, search_output = targeted_search(repo, files, query)
    results = {}
    for condition, paths, output, mode in (
        ("previous", previous_paths, previous_brief, "brief"),
        ("structural", structural_paths, brief, "brief"),
        ("search", search_paths, search_output, "search"),
    ):
        points = located(output, mode, index if condition == "structural" else None)
        rows = []
        follow_full = follow_window = 0
        for item in expected:
            file_found = item["file"] in paths
            file_named = file_found or item["file"] in output
            symbol_found = (item["file"], item["line"]) in points
            retrieval = 0
            if condition == "structural" and symbol_found:
                symbol = find_symbol(index, item["file"], item["symbol"])
                retrieval = len(
                    retrieve_symbol(repo, index, f"{item['file']}::{symbol_id(symbol)}")
                )
                follow_full += retrieval
                follow_window += retrieval
            elif file_named:
                follow_full += file_characters(repo, item["file"])
                follow_window += (
                    window_characters(repo, item["file"], item["line"])
                    if symbol_found
                    else file_characters(repo, item["file"])
                )
            rows.append(
                {
                    "file": item["file"],
                    "symbol": item["symbol"],
                    "file_found": file_found,
                    "file_named": file_named,
                    "file_position": paths.index(item["file"]) + 1
                    if file_found
                    else None,
                    "symbol_located": symbol_found,
                }
            )
        results[condition] = {
            "selected": paths,
            "expected": rows,
            "files_found": sum(r["file_found"] for r in rows),
            "files_named": sum(r["file_named"] for r in rows),
            "symbols_located": sum(r["symbol_located"] for r in rows),
            "other_files_listed": len([p for p in paths if p not in files_wanted]),
            "initial_characters": len(output),
            "followup_characters_full_files": follow_full,
            "followup_characters_windowed": follow_window,
        }
    return {
        "id": task["id"],
        "repo": task["repo"],
        "task": query,
        "wording_differs": task["wording_differs"],
        "cross_module": task["cross_module"],
        "expected_items": len(expected),
        **results,
    }


def relationship_audit(index: dict, sample_size: int = 20, seed: int = 7) -> dict:
    """Automated consistency checks plus a fixed random sample for manual review."""
    by_path = {r["path"]: r for r in index["records"]}
    checked = mismatched = 0
    mismatches = []
    for record in index["records"]:
        for entry in record.get("import_refs", []):
            if entry.get("status") not in {"resolved", "alias", "ambiguous"}:
                continue
            for name in entry.get("names", []):
                original = name.split(" as ")[0]
                if original.startswith("*") or entry["kind"] == "reexport":
                    continue
                checked += 1
                if not _find_export(by_path, entry["target"], original, set()):
                    mismatched += 1
                    if len(mismatches) < 10:
                        mismatches.append(
                            f"{record['path']}:{entry['line']} imports {original!r} from "
                            f"{entry['target']}, which has no matching parsed export"
                        )
    calls = [
        (record["path"], symbol, target)
        for record in index["records"]
        for symbol in record["symbols"]
        for target in symbol.get("call_targets", [])
    ]
    random.Random(seed).shuffle(calls)
    statuses = Counter(
        e.get("status") for r in index["records"] for e in r.get("import_refs", [])
    )
    return {
        "import_statuses": dict(statuses),
        "relationships": index["relationships"],
        "named_imports_checked": checked,
        "named_imports_without_matching_export": mismatched,
        "mismatch_examples": mismatches,
        "call_target_sample_for_manual_review": [
            f"{path}::{symbol_id(symbol)} calls {target['call']} -> "
            f"{target['targets']} [{target['status']}]"
            for path, symbol, target in calls[:sample_size]
        ],
    }


def timings(repo: Path, runs: int = 3) -> dict:
    """In-process build time (initial) and rebuild after one file changes (refresh)."""
    initial = []
    for _ in range(runs):
        start = time.perf_counter()
        index = build_index(repo)
        initial.append(time.perf_counter() - start)
    source = next(
        repo / r["path"]
        for r in index["records"]
        if r.get("language") in {"typescript", "javascript"}
    )
    original = source.read_bytes()
    refresh = []
    try:
        for run in range(runs):
            source.write_bytes(original + f"\n// touched {run}\n".encode())
            start = time.perf_counter()
            build_index(repo)
            refresh.append(time.perf_counter() - start)
    finally:
        source.write_bytes(original)
    return {
        "initial_seconds_median": round(statistics.median(initial), 3),
        "refresh_seconds_median": round(statistics.median(refresh), 3),
        "runs": runs,
        "note": "Refresh is a full rebuild; there is no incremental cache.",
    }


def summarize(rows: list[dict]) -> dict:
    summary = {}
    for condition in ("previous", "structural", "search"):
        subset = {
            "all": rows,
            "wording_differs": [r for r in rows if r["wording_differs"]],
            "cross_module": [r for r in rows if r["cross_module"]],
        }
        summary[condition] = {
            name: {
                "tasks": len(items),
                "expected_items": sum(r["expected_items"] for r in items),
                "files_found": sum(r[condition]["files_found"] for r in items),
                "files_named": sum(r[condition]["files_named"] for r in items),
                "symbols_located": sum(r[condition]["symbols_located"] for r in items),
                "tasks_with_all_files": sum(
                    r[condition]["files_found"] == r["expected_items"] for r in items
                ),
            }
            for name, items in subset.items()
        }
        summary[condition]["characters"] = {
            "initial_total": sum(r[condition]["initial_characters"] for r in rows),
            "followup_full_files_total": sum(
                r[condition]["followup_characters_full_files"] for r in rows
            ),
            "followup_windowed_total": sum(
                r[condition]["followup_characters_windowed"] for r in rows
            ),
        }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repos-dir", type=Path, required=True)
    parser.add_argument(
        "--clone", action="store_true", help="Clone missing repositories."
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    spec = json.loads((ROOT / "benchmarks/structural_tasks.json").read_text())
    report: dict = {
        "scope": (
            "Local proxy on two public repositories with tasks written by the implementing "
            "agent. Measures discovery and characters under stated reading rules; no model "
            "was run. Characters are not tokens."
        ),
        "budget_characters": BUDGET,
        "slots": SLOTS,
        "previous_commit": PREVIOUS_COMMIT,
        "repositories": {},
        "tasks": [],
    }
    with tempfile.TemporaryDirectory() as workdir:
        source = previous_source(Path(workdir))
        for name, meta in spec["repositories"].items():
            repo = (
                clone(args.repos_dir, name, meta)
                if args.clone
                else args.repos_dir / name
            )
            if head(repo) != meta["commit"]:
                raise SystemExit(f"{repo} is not at {meta['commit']}; use --clone")
            tasks = [t for t in spec["tasks"] if t["repo"] == name]
            previous = run_previous(source, repo, tasks)
            start = time.perf_counter()
            index = build_index(repo)
            elapsed = time.perf_counter() - start
            files = search_files(repo)
            report["repositories"][name] = {
                "commit": meta["commit"],
                "indexed_files": len(index["records"]),
                "parsed_symbols": sum(len(r["symbols"]) for r in index["records"]),
                "partially_parsed_files": sum(
                    r.get("parse", {}).get("status") == "partial"
                    for r in index["records"]
                ),
                "index_bytes": len(serialize_index(index).encode()),
                "previous_index_characters": previous["index_characters"],
                "previous_index_seconds": round(previous["index_seconds"], 3),
                "first_build_seconds": round(elapsed, 3),
                "timing": timings(repo),
                "audit": relationship_audit(index),
            }
            for task in tasks:
                report["tasks"].append(
                    evaluate_task(
                        task, repo, index, previous["tasks"][task["id"]], files
                    )
                )
    report["summary"] = summarize(report["tasks"])
    text = json.dumps(report, indent=2)
    if args.out:
        args.out.write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
