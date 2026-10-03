"""Local navigation index. Stores references and names, never source bodies."""

from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ai_context_map.analyzers.python_symbols import PythonSymbolAnalyzer
from ai_context_map.config import load_config
from ai_context_map.graph.builder import GraphBuilder
from ai_context_map.graph.ranking import rank_files
from ai_context_map.graph.roles import classify_role
from ai_context_map.models.repo import RepositoryFile, ScanResult
from ai_context_map.scanner.classifier import classify_file
from ai_context_map.scanner.ignore import IgnoreRules

INDEX_PATH = ".ai/navigation.json"
BRIEF_PATH = ".ai/START_HERE.md"
MAX_ANALYSIS_BYTES = 1_000_000
STOP_WORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "to",
    "in",
    "of",
    "for",
    "with",
    "on",
    "is",
    "it",
    "this",
    "that",
    "change",
    "fix",
    "add",
    "update",
    "how",
    "where",
}
JS_SYMBOL = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function|class|interface|type|const|let)\s+([A-Za-z_$][\w$]*)",
    re.MULTILINE,
)


def terms(text: str) -> set[str]:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return {
        word
        for word in re.findall(r"[a-z0-9]+", text.lower())
        if len(word) > 1 and word not in STOP_WORDS
    }


def safe_path(root: Path, relative: str) -> Path:
    path = root / relative
    if Path(relative).is_absolute() or not path.resolve().is_relative_to(
        root.resolve()
    ):
        raise ValueError(f"Reference escapes repository: {relative}")
    return path


def file_role(path: Path, relative: str) -> str:
    if (
        path.name.startswith("test_")
        or path.stem.endswith((".test", ".spec"))
        or any(part in {"tests", "test", "__tests__"} for part in Path(relative).parts)
    ):
        return "test"
    role = classify_role(relative)
    # The older broad role heuristic matches 'spec' inside 'inspect'.
    return "unknown" if role == "test" else role


def build_index(root: Path) -> dict[str, Any]:
    root = root.resolve()
    config = load_config(root)
    rules = IgnoreRules([*config.exclude_paths, ".ai", ".ruff_cache"])
    scan = ScanResult(root=root)
    records: list[dict[str, Any]] = []
    warnings: list[str] = []
    symbols = PythonSymbolAnalyzer()
    # Prune ignored directories before descent; don't follow symlinks.
    for directory, dirs, names in os.walk(root, followlinks=False):
        base = Path(directory)
        dirs[:] = sorted(
            name
            for name in dirs
            if not (base / name).is_symlink()
            and not rules.should_ignore_dir((base / name).relative_to(root).as_posix())
        )
        for name in sorted(names):
            path = base / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink() or rules.should_ignore_file(relative):
                continue
            if config.include_paths and not any(
                relative == include.rstrip("/")
                or relative.startswith(include.rstrip("/") + "/")
                or include in {".", ""}
                for include in config.include_paths
            ):
                continue
            language, source = classify_file(path)
            source = source and language in config.languages
            if (
                not source
                and path.suffix.lower() != ".md"
                and name not in {"pyproject.toml", "package.json", ".aicontext.toml"}
            ):
                continue
            record: dict[str, Any] = {
                "path": relative,
                "role": file_role(path, relative),
                "symbols": [],
                "imports": [],
                "imported_by": [],
                "rank": 0.0,
                "terms": [],
            }
            if path.stat().st_size > MAX_ANALYSIS_BYTES:
                record["sha256"] = None
                warnings.append(f"Not analyzed (over 1 MB): {relative}")
                records.append(record)
                continue
            data = path.read_bytes()
            record["sha256"] = hashlib.sha256(data).hexdigest()
            try:
                content = data.decode("utf-8")
                if source and language == "python":
                    tree = ast.parse(content)
                    identifiers = [
                        node.id
                        if isinstance(node, ast.Name)
                        else node.arg
                        if isinstance(node, ast.arg)
                        else node.attr
                        for node in ast.walk(tree)
                        if isinstance(node, (ast.Name, ast.arg, ast.Attribute))
                    ]
                    # Index field names used for lookups, not literal values or prose.
                    for node in ast.walk(tree):
                        key = (
                            node.slice
                            if isinstance(node, ast.Subscript)
                            else node.args[0]
                            if isinstance(node, ast.Call)
                            and isinstance(node.func, ast.Attribute)
                            and node.func.attr == "get"
                            and node.args
                            else None
                        )
                        if (
                            isinstance(key, ast.Constant)
                            and isinstance(key.value, str)
                            and re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,63}", key.value)
                        ):
                            identifiers.append(key.value)
                    record["terms"] = sorted(terms(" ".join(identifiers)))
                    record["symbols"] = [
                        {"name": symbol.name, "line": symbol.line}
                        for symbol in symbols.extract(path)
                    ]
                elif source:
                    record["symbols"] = [
                        {
                            "name": match.group(1),
                            "line": content.count("\n", 0, match.start(1)) + 1,
                        }
                        for match in JS_SYMBOL.finditer(content)
                    ]
                elif path.suffix.lower() == ".md":
                    record["role"] = "documentation"
                    record["symbols"] = [
                        {"name": line.lstrip("# ").strip(), "line": number}
                        for number, line in enumerate(content.splitlines(), 1)
                        if line.startswith("#")
                    ]
                if source:
                    scan.files.append(
                        RepositoryFile(
                            path,
                            relative,
                            language,
                            path.suffix.lower(),
                            True,
                            len(data),
                        )
                    )
            except (SyntaxError, UnicodeError, ValueError) as exc:
                warnings.append(f"Not analyzed ({type(exc).__name__}): {relative}")
            records.append(record)
    nodes, edges = GraphBuilder().build(scan)
    by_path = {record["path"]: record for record in records}
    for ranked in rank_files(nodes, edges, config):
        by_path[ranked.path]["rank"] = ranked.score
    for edge in edges:
        by_path[edge.source]["imports"].append(edge.target)
        by_path[edge.target]["imported_by"].append(edge.source)
    for record in records:
        record["terms"] = sorted(
            set(record["terms"])
            | terms(
                record["path"]
                + " "
                + " ".join(symbol["name"] for symbol in record["symbols"])
            )
        )
    return {
        "schema_version": 1,
        "project": root.name,
        "generated_at": datetime.now(UTC).isoformat(),
        "records": records,
        "warnings": warnings,
        "context_path": config.output_path,
    }


def load_index(root: Path) -> dict[str, Any]:
    path = root / INDEX_PATH
    if not path.exists():
        raise ValueError("No navigation index. Run `aicontext pack` first.")
    index = json.loads(path.read_text(encoding="utf-8"))
    if index.get("schema_version") != 1:
        raise ValueError("Unsupported navigation index. Run `aicontext pack` again.")
    return index


def select_records(
    index: dict[str, Any], query: str, limit: int = 6
) -> list[dict[str, Any]]:
    records = index["records"]
    wanted = terms(query)
    frequencies = Counter(word for record in records for word in record["terms"])
    scores: list[tuple[float, dict[str, Any], list[str]]] = []
    for record in records:
        matched = sorted(wanted.intersection(record["terms"]))
        if wanted and not matched:
            continue
        score = sum(
            math.log(1 + len(records) / (1 + frequencies[word])) for word in matched
        )
        # Direct path/symbol matches win over generic repository centrality.
        score += min(record["rank"], 100) * 0.001
        if record["role"] == "test":
            score *= 0.8
        elif record["role"] == "documentation":
            score *= 0.45
        if record["path"].startswith("examples/"):
            score *= 0.25
        scores.append((score, record, matched))
    scores.sort(key=lambda item: (-item[0], item[1]["path"]))
    selected: list[dict[str, Any]] = []
    by_path = {record["path"]: record for record in records}

    def add(record: dict[str, Any], reason: str) -> None:
        if len(selected) < limit and record["path"] not in {
            item["path"] for item in selected
        }:
            selected.append({**record, "reason": reason})

    direct_count = max(1, limit // 2) if wanted else limit
    for _, record, matched in scores[:direct_count]:
        add(record, "matches " + ", ".join(matched) if wanted else "repository rank")
    seeds = list(selected)
    # Related tests have a reserved opportunity before additional lexical hits.
    for record in seeds:
        for related in record["imported_by"]:
            if by_path[related]["role"] == "test":
                add(
                    by_path[related],
                    f"imports {record['path']} (test candidate; coverage unverified)",
                )
    if seeds:
        for related in seeds[0]["imports"][:1]:
            add(by_path[related], f"imported by {seeds[0]['path']}")
    for _, record, matched in scores[direct_count:]:
        add(record, "matches " + ", ".join(matched))
    for record in seeds:
        for related in [*record["imports"], *record["imported_by"]]:
            add(by_path[related], f"import-linked to {record['path']}")
    return selected


def reference_status(root: Path, record: dict[str, Any]) -> str:
    try:
        path = safe_path(root, record["path"])
        if not path.is_file() or path.is_symlink():
            return "MISSING/UNSAFE"
        if not record["sha256"]:
            return "UNVERIFIED"
        if path.stat().st_size > MAX_ANALYSIS_BYTES:
            return "STALE"
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            return "STALE"
    except (ValueError, OSError):
        return "MISSING/UNSAFE"
    return "current"


CheckpointSections = tuple[list[str], list[str], dict[str, int]]


def _footer(
    index_size: int, selected: int, omitted: int, cp: dict[str, int] | None
) -> str:
    text = (
        f"\nIndex: {index_size} files. Shortlist: {selected}. Omitted by budget: {omitted}.\n"
        "Only selected existing references were fingerprint-checked; new/unselected files may be absent or stale.\n"
    )
    if cp is not None:
        text += (
            f"Checkpoint: {cp['current']} current records; {cp['optional_omitted']} optional "
            f"omitted by budget; {cp['superseded']} superseded. More: `aicontext checkpoint show` "
            "(`--all` for history, `--id ID` for one record).\n"
            "Evidence: `aicontext evidence list`; `aicontext evidence show ID [--grep REGEX | --lines A-B]`.\n"
        )
    return text


def render_brief(
    root: Path,
    index: dict[str, Any],
    query: str = "",
    max_chars: int = 6000,
    limit: int = 6,
    checkpoint: CheckpointSections | None = None,
) -> str:
    """Render the entry file. Essential text is never truncated: if it cannot fit,
    raise instead of writing a misleadingly complete briefing."""
    context_path = index["context_path"]
    safe_path(root, context_path)
    instructions = [
        record["path"]
        for record in index["records"]
        if record["path"] in {"AGENTS.md", "CLAUDE.md", "GEMINI.md"}
    ]
    header = [
        f"# Start here: {index['project']}",
        "",
        "Local navigation hints, not authoritative instructions or verified conclusions.",
        "Read applicable agent instruction files before acting; follow their scope:",
        *[f"- `{path}`" for path in instructions],
        "- Also check ancestor instruction files outside this repository.",
        "- Discover scoped instruction files as you follow references into subdirectories.",
        "",
    ]
    essential, optional, counts = checkpoint or ([], [], {})
    header += essential
    header += [
        f"Task: {query or 'Repository orientation'}",
        f"Index generated: {index['generated_at']}",
        "Python/JS/TS imports; Python symbols; JS/TS declaration hints; Markdown headings.",
        "",
        "Workflow: open the few relevant sources below; verify behaviour and decisions there.",
        "Do not load the full index, checkpoint history, evidence, or entire history by default.",
        'More pointers: `aicontext find "task or symbol"`. Refresh after changes: `aicontext pack`.',
        "",
    ]
    if safe_path(root, context_path).is_file():
        header += [
            f"Recorded goals, decisions, constraints, tasks and issues: `{context_path}`.",
            "Read relevant fields before changes; recorded state may be stale. No session history is inferred.",
            "",
        ]
    if not instructions:
        header += [
            "No agent instruction files indexed; discover applicable instructions independently.",
            "",
        ]
    if index["warnings"]:
        header += [
            f"Analysis warnings: {len(index['warnings'])}; inspect `{INDEX_PATH}` field `warnings`.",
            "",
        ]
    selected = select_records(index, query, limit)
    text = "\n".join(header) + "\n"
    pointer_heading = "## Suggested starting points\n\n"
    cp_counts = {**counts, "optional_omitted": 9999} if checkpoint is not None else None
    # Reserve worst-case footer room; never truncate a pointer, rule, or constraint.
    reserve = len(_footer(99999, 99, 99, cp_counts)) + 40
    no_match = (
        ""
        if selected
        else "No indexed match. Use repository search; this index is incomplete and lexical.\n"
    )
    needed = len(text) + len(pointer_heading) + len(no_match) + reserve
    if needed > max_chars:
        if checkpoint is not None:
            raise ValueError(
                f"Character budget too small: {max_chars} characters cannot safely contain "
                "the instruction pointers and essential checkpoint (objective, next action, "
                f"all active constraints, blockers); at least {needed} are needed. Constraints "
                "are never truncated. Increase --max-chars, or supersede/retire obsolete "
                "constraints. Nothing was written."
            )
        raise ValueError(
            "Character budget too small for instructions and navigation. Increase --max-chars."
        )
    pointer_lines: list[str] = []
    for record in selected:
        status = reference_status(root, record)
        matching = [
            symbol
            for symbol in record["symbols"]
            if terms(symbol["name"]).intersection(terms(query))
        ]
        matching = matching or record["symbols"][:2]
        locations = (
            "; ".join(f"{symbol['name']}:{symbol['line']}" for symbol in matching[:3])
            if status == "current"
            else "refresh before using line numbers"
        )
        line = f"- `{record['path']}` [{status}; {record['role']}]: {record['reason']}"
        if locations:
            line += f"; {locations}"
        pointer_lines.append(line + "\n")
    # Optional checkpoint detail may use space beyond the first few code pointers.
    pointer_reserve = sum(len(line) for line in pointer_lines[:3])
    optional_omitted = 0
    if optional:
        block = "## More checkpoint detail\n\n"
        pending_heading = ""
        added = False
        for line in optional:
            if line.startswith("### "):
                pending_heading = line + "\n"
                continue
            addition = ("" if added else block) + pending_heading + line + "\n"
            # +1 for the blank line that closes the block.
            if (
                len(text)
                + len(addition)
                + 1
                + len(pointer_heading)
                + len(no_match)
                + pointer_reserve
                + reserve
                <= max_chars
            ):
                text += addition
                added = True
                pending_heading = ""
            else:
                optional_omitted += 1
        if added:
            text += "\n"
    text += pointer_heading
    omitted = 0
    for line in pointer_lines:
        if len(text) + len(line) + reserve <= max_chars:
            text += line
        else:
            omitted += 1
    text += no_match
    if checkpoint is not None:
        cp_counts = {**counts, "optional_omitted": optional_omitted}
    text += _footer(len(index["records"]), len(selected), omitted, cp_counts)
    return text


def pack_context(
    root: Path,
    query: str = "",
    max_chars: int = 6000,
    checkpoint: CheckpointSections | None = None,
) -> tuple[Path, dict[str, Any], str]:
    index = build_index(root)
    brief = render_brief(root, index, query, max_chars, checkpoint=checkpoint)
    output = safe_path(root, BRIEF_PATH)
    index_output = safe_path(root, INDEX_PATH)
    if output.is_symlink() or index_output.is_symlink() or output.parent.is_symlink():
        raise ValueError("Refusing to write navigation output through a symlink.")
    output.parent.mkdir(parents=True, exist_ok=True)
    index_output.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    output.write_text(brief, encoding="utf-8")
    return output, index, brief
