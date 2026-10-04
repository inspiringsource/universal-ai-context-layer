"""Bounded, fingerprint-checked retrieval of one indexed symbol's source."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Any

from ai_context_map.analyzers.js_ts_structure import (
    GRAMMAR_BY_SUFFIX,
    extract_structure,
)
from ai_context_map.analyzers.python_symbols import PythonSymbolAnalyzer
from ai_context_map.navigation.index import MAX_ANALYSIS_BYTES, safe_path
from ai_context_map.navigation.structure import (
    format_call_target,
    format_import,
    format_symbol,
    python_symbols,
    symbol_id,
)

MAX_LINE_CHARS = 300


class RetrievalError(ValueError):
    """The reference could not be retrieved safely; the message says why."""


def _current_symbols(path: Path, data: bytes) -> list[dict[str, Any]]:
    """Re-derive symbols from the file as it is now (no index trusted)."""
    if path.suffix == ".py":
        tree = ast.parse(data.decode("utf-8"))
        return python_symbols(tree, PythonSymbolAnalyzer().extract(path))
    if path.suffix.lower() in GRAMMAR_BY_SUFFIX:
        return extract_structure(data, path.suffix).symbols
    raise RetrievalError(
        f"{path.name}: symbol retrieval supports Python and JS/TS only."
    )


def _lookup(
    symbols: list[dict[str, Any]], name: str, where: str
) -> tuple[dict[str, Any], str]:
    """Exact id, then exact qualified name, then a unique `.name` suffix.

    Never chooses between several matches; the error lists them instead.
    """
    named = [s for s in symbols if s["name"] == name]
    exact = [s for s in symbols if symbol_id(s) == name]
    # `helper` is ambiguous when `helper#2` exists; only an explicit id selects.
    if exact and len(named) <= 1:
        return exact[0], ""
    note = ""
    if not named:
        named = [s for s in symbols if s["name"].endswith("." + name)]
        note = "matched by unqualified name"
    if len(named) == 1:
        return named[0], note
    if not named:
        raise RetrievalError(f"UNRESOLVED: no symbol {name!r} in {where}.")
    raise RetrievalError(
        f"AMBIGUOUS: {len(named)} symbols match {name!r} in {where}; use one id:\n"
        + "\n".join(f"  {where}::{symbol_id(s)}  {format_symbol(s)}" for s in named)
    )


def _record_for(index: dict[str, Any], root: Path, relative: str) -> dict[str, Any]:
    relative = Path(relative).as_posix().removeprefix("./")
    safe_path(root, relative)
    if relative == ".ai" or relative.startswith(".ai/"):
        raise RetrievalError(
            "Generated UACL state is not source; use `aicontext evidence show`."
        )
    record = next((r for r in index["records"] if r["path"] == relative), None)
    if record is None:
        raise RetrievalError(
            f"NOT INDEXED: {relative} (excluded, unsupported, or added after the last "
            "`aicontext pack`)."
        )
    return record


def _read_current(root: Path, record: dict[str, Any]) -> tuple[Path, bytes | None, str]:
    path = safe_path(root, record["path"])
    if path.is_symlink():
        raise RetrievalError(f"Refusing symlink: {record['path']}")
    if not path.is_file():
        return path, None, "MISSING"
    if path.stat().st_size > MAX_ANALYSIS_BYTES:
        raise RetrievalError(f"{record['path']} is over 1 MB and not analyzed.")
    data = path.read_bytes()
    if record.get("sha256") and hashlib.sha256(data).hexdigest() == record["sha256"]:
        return path, data, "current"
    return path, data, "CHANGED"


def list_symbols(
    root: Path, index: dict[str, Any], relative: str, max_chars: int = 6000
) -> str:
    record = _record_for(index, root, relative)
    path, data, status = _read_current(root, record)
    if data is None:
        raise RetrievalError(
            f"MISSING: {record['path']} no longer exists; run `aicontext pack`."
        )
    symbols = record["symbols"]
    header = f"FILE {record['path']} [{status}"
    if status == "CHANGED":
        symbols = _current_symbols(path, data)
        header += "; listed from the current file, index is stale; run `aicontext pack`"
    parse = record.get("parse", {})
    if parse.get("status") == "partial" and status == "current":
        header += (
            f"; PARTIAL PARSE near line(s) {', '.join(map(str, parse['error_lines']))}"
        )
    lines = [header + "]"]
    lines += [
        f"{format_symbol(s)}  [{record['path']}::{symbol_id(s)}]" for s in symbols
    ]
    if status == "current":
        lines += [format_import(entry) for entry in record.get("import_refs", [])]
    text = ""
    for number, line in enumerate(lines):
        if len(text) + len(line) + 1 > max_chars - 120:
            text += f"[{len(lines) - number} more lines omitted by --max-chars {max_chars}]\n"
            break
        text += line + "\n"
    return text


def _excerpt(
    lines: list[str], start: int, end: int, max_lines: int, max_chars: int
) -> tuple[str, int]:
    """Line-numbered text for [start, end]; returns (text, last line shown)."""
    width = len(str(end))
    text = ""
    last = start - 1
    for number in range(start, end + 1):
        if number - start >= max_lines:
            break
        line = lines[number - 1] if number <= len(lines) else ""
        if len(line) > MAX_LINE_CHARS:
            line = (
                line[:MAX_LINE_CHARS] + f" [... line truncated: {len(line)} characters]"
            )
        row = f"{number:>{width}} | {line}\n"
        if len(text) + len(row) > max_chars:
            break
        text += row
        last = number
    return text, last


def retrieve_symbol(
    root: Path,
    index: dict[str, Any],
    reference: str,
    max_lines: int = 80,
    max_chars: int = 6000,
    context: int = 0,
    full: bool = False,
) -> str:
    """Return a bounded, line-numbered definition for `PATH::NAME` or a unique `NAME`."""
    root = root.resolve()
    if "::" in reference:
        relative, name = reference.split("::", 1)
        record = _record_for(index, root, relative)
    else:
        name = reference
        candidates = [
            (r, s)
            for r in index["records"]
            for s in r["symbols"]
            if r.get("language") and (symbol_id(s) == name or s["name"] == name)
        ] or [
            (r, s)
            for r in index["records"]
            for s in r["symbols"]
            if r.get("language") and s["name"].endswith("." + name)
        ]
        if len(candidates) != 1:
            if not candidates:
                raise RetrievalError(
                    f"UNRESOLVED: no indexed symbol named {name!r}. Try "
                    f'`aicontext find "{name}"` or PATH::QUALIFIED.NAME.'
                )
            raise RetrievalError(
                f"AMBIGUOUS: {len(candidates)} indexed symbols are named {name!r}; use one:\n"
                + "\n".join(
                    f"  {r['path']}::{symbol_id(s)}  {format_symbol(s)}"
                    for r, s in candidates
                )
            )
        record = candidates[0][0]
        name = symbol_id(candidates[0][1])
    if not record.get("language"):
        raise RetrievalError(
            f"{record['path']} has no parsed symbols (not Python/JS/TS, or unparsed)."
        )
    path, data, status = _read_current(root, record)
    where = record["path"]
    if data is None:
        raise RetrievalError(
            f"MISSING: {where} no longer exists; run `aicontext pack`."
        )
    notes: list[str] = []
    if status == "current":
        symbol, note = _lookup(record["symbols"], name, where)
        symbols = record["symbols"]
    else:
        # The stored location is not trusted for a changed file.
        try:
            symbols = _current_symbols(path, data)
        except (SyntaxError, UnicodeError) as exc:
            raise RetrievalError(
                f"CHANGED: {where} differs from the index and cannot be re-parsed "
                f"({type(exc).__name__}); run `aicontext pack` and inspect it directly."
            ) from exc
        try:
            symbol, note = _lookup(symbols, name, where)
        except RetrievalError as exc:
            old = next((s for s in record["symbols"] if symbol_id(s) == name), None)
            was = (
                f" (indexed at lines {old['line']}-{old.get('end_line')})"
                if old
                else ""
            )
            raise RetrievalError(
                f"CHANGED: {where} differs from the index{was}. {exc}"
            ) from exc
        notes.append(
            "CHANGED since the index: location re-derived from the current file; "
            "run `aicontext pack` to refresh."
        )
    if note:
        notes.append(f"Resolved {name!r} to {symbol_id(symbol)} ({note}).")
    lines = data.decode("utf-8", "replace").splitlines()
    first = max(
        1, min(symbol.get("doc_line", symbol["line"]), symbol["line"]) - context
    )
    end = min(len(lines), (symbol.get("end_line") or symbol["line"]) + context)
    out = [
        f"{where}::{symbol_id(symbol)}  [{symbol.get('kind', 'symbol')}; fingerprint {status}]"
    ]
    out.append(format_symbol(symbol))
    out += notes
    if symbol.get("syntax_error"):
        out.append(
            "PARTIAL PARSE: this declaration contains syntax errors; its range may be wrong."
        )
    parent = symbol.get("parent")
    enclosing = (
        next((s for s in symbols if s["name"] == parent), None) if parent else None
    )
    body = ""
    if enclosing is not None and enclosing["line"] < first:
        body += f"Enclosing {enclosing.get('kind', 'scope')} {parent}:\n"
        body += _excerpt(lines, enclosing["line"], enclosing["line"], 1, 400)[0]
        body += "   ...\n"
    limit_lines = end - first + 1 if full else max_lines
    # Leave room for the header, enclosing line, and omission/expansion notes.
    used = sum(len(x) + 1 for x in out) + len(body)
    limit_chars = 10**9 if full else max(400, max_chars - used - 700)
    excerpt, last = _excerpt(lines, first, end, limit_lines, limit_chars)
    text = "\n".join(out) + "\n" + body + excerpt
    if last < end:
        nested = [
            s for s in symbols if s.get("parent") == symbol["name"] and s["line"] > last
        ]
        text += (
            f"[Lines {last + 1}-{end} omitted ({end - last} of {end - first + 1}) by "
            f"--max-lines {max_lines} / --max-chars {max_chars}. Expand: add "
            f"`--max-lines {end - first + 1}` or `--full`.]\n"
        )
        if nested:
            text += "Omitted members (retrieve individually):\n" + "".join(
                f"  {where}::{symbol_id(s)} @{s['line']}\n" for s in nested[:12]
            )
            if len(nested) > 12:
                text += f"  ... {len(nested) - 12} more: `aicontext symbol {where} --list`\n"
    else:
        text += f"[Complete: lines {first}-{end}.]\n"
    targets = symbol.get("call_targets") if status == "current" else None
    if targets:
        text += (
            "Calls matched by imported name (inferred; runtime target unverified): "
            + "; ".join(format_call_target(t) for t in targets)
            + "\n"
        )
    return text
