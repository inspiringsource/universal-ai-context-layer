"""Structural facts for the navigation index and their compact map notation.

Three kinds of information are kept apart:

- syntax facts: declarations, ranges, signatures, import specifiers, and call
  expressions, parsed from one file (Tree-sitter for JS/TS, `ast` for Python);
- inferred relationships: an import specifier resolved to an indexed file, or
  a call whose callee name matches an import of an exported declaration;
- recorded conclusions: the checkpoint, written by an agent (not this module).
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path
from typing import Any

from ai_context_map.analyzers.js_ts_structure import (
    ResolverConfig,
    resolve_module,
)
from ai_context_map.analyzers.python_symbols import PythonSymbol

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


def terms(text: str) -> set[str]:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return {
        word
        for word in re.findall(r"[a-z0-9]+", text.lower())
        if len(word) > 1 and word not in STOP_WORDS
    }


MAX_REEXPORT_DEPTH = 3
MODIFIERS = {
    "async",
    "static",
    "get",
    "set",
    "abstract",
    "private",
    "public",
    "protected",
    "readonly",
    "override",
    "*",
}
MAX_CALL_TARGETS = 8
LEGEND = (
    "Legend: EXPORT/DEF = parsed declaration @lines; IMPORT a → b = import resolved "
    "to a file; CALLS = callee matched to an imported declaration (inferred; runtime "
    "target unverified); TEST-CANDIDATE = test importing the file (coverage unverified)."
)


def _with_qualified_name(signature: str, name: str, qualified: str) -> str:
    if name == qualified:
        return signature
    return re.sub(
        rf"(?<![\w$.]){re.escape(name)}(?=[(<\s:=]|$)",
        lambda _: qualified,
        signature,
        count=1,
    )


def python_symbols(
    tree: ast.AST, extracted: list[PythonSymbol]
) -> list[dict[str, Any]]:
    """Add ranges, kinds, and signatures to the existing Python symbol list."""
    spans: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.If, ast.Assign),
        ):
            spans.setdefault(node.lineno, node)
    symbols: list[dict[str, Any]] = []
    for item in extracted:
        symbol: dict[str, Any] = {"name": item.name, "line": item.line}
        node = spans.get(item.line or -1)
        if node is None:
            symbols.append(symbol)
            continue
        symbol["end_line"] = getattr(node, "end_lineno", None) or item.line
        symbol["kind"] = item.symbol_type
        bare = item.name.rsplit(".", 1)[-1]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
            returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
            signature = f"{prefix}{node.name}({ast.unparse(node.args)}){returns}"
        elif isinstance(node, ast.ClassDef):
            bases = ", ".join(ast.unparse(base) for base in node.bases)
            signature = f"class {node.name}" + (f"({bases})" if bases else "")
        else:
            signature = ast.unparse(node).split("\n", 1)[0]
            bare = ""
        if bare:
            signature = _with_qualified_name(signature, bare, item.name)
        symbol["signature"] = _short(signature)
        decorators = getattr(node, "decorator_list", [])
        if decorators:
            symbol["doc_line"] = min(decorator.lineno for decorator in decorators)
        vocabulary = [
            child.id
            if isinstance(child, ast.Name)
            else child.arg
            if isinstance(child, ast.arg)
            else child.attr
            for child in ast.walk(node)
            if isinstance(child, (ast.Name, ast.arg, ast.Attribute))
        ]
        symbol["terms"] = sorted(terms(" ".join([signature, *vocabulary])))
        symbols.append(symbol)
    return symbols


def _short(text: str, limit: int = 160) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def symbol_id(symbol: dict[str, Any]) -> str:
    return symbol.get("id") or symbol["name"]


# -- relationships ---------------------------------------------------------------


def link_records(
    by_path: dict[str, dict[str, Any]], config: ResolverConfig
) -> dict[str, int]:
    """Resolve JS/TS import specifiers and match call names to imported declarations.

    Returns counts of relationship statuses for reporting.
    """
    counts: Counter[str] = Counter()
    for path, record in by_path.items():
        for entry in record.get("import_refs", []):
            if entry["kind"] == "dynamic-import-unresolvable":
                entry["status"] = "non-literal"
                counts["non-literal"] += 1
                continue
            target, status, alternatives = resolve_module(
                path, entry["spec"], by_path, config
            )
            entry["status"] = status
            if target:
                entry["target"] = target
            if alternatives:
                entry["alternatives"] = alternatives
            counts[status] += 1
    for record in by_path.values():
        if not record.get("import_refs"):
            continue
        bindings = _import_bindings(record)
        for symbol in record["symbols"]:
            targets: list[dict[str, Any]] = []
            for call in symbol.get("calls", []):
                callee = call.removeprefix("new ").strip("<>")
                head, _, member = callee.partition(".")
                binding = bindings.get(head)
                if binding is None:
                    continue
                target_path, imported = binding
                first_member = member.split(".")[0]
                if imported == "*":
                    candidates = [first_member]
                elif imported == "default" and first_member:
                    # `utils.isFunction` with `export default { isFunction }`.
                    candidates = [f"default.{first_member}", "default"]
                else:
                    candidates = [imported]
                found: list[tuple[str, str]] = []
                matched = ""
                for wanted in candidates:
                    if wanted and not found:
                        found = _find_export(by_path, target_path, wanted, set())
                        matched = wanted
                if not found:
                    counts["call-unmatched"] += 1
                    continue
                status = "inferred" if len(found) == 1 else "ambiguous"
                if (
                    first_member
                    and imported != "*"
                    and matched != f"default.{first_member}"
                ):
                    # `Headers.from(...)` on an imported class: its declared member.
                    member_found = _member_of(by_path, found, first_member)
                    if member_found:
                        found = member_found
                    elif status == "inferred":
                        # The owner is known; the member is inherited, dynamic,
                        # or destructured, so no declaration can be named.
                        status = "owner-only"
                counts[f"call-{status}"] += 1
                targets.append(
                    {
                        "call": call,
                        "status": status,
                        "targets": [f"{p}::{s}" for p, s in found[:3]],
                    }
                )
                if len(targets) >= MAX_CALL_TARGETS:
                    break
            if targets:
                symbol["call_targets"] = targets
    return dict(counts)


def _member_of(
    by_path: dict[str, dict[str, Any]], found: list[tuple[str, str]], member: str
) -> list[tuple[str, str]]:
    """Declared members `Owner.member` of the matched declarations."""
    members: list[tuple[str, str]] = []
    for path, owner_id in found:
        owner = next(
            (s for s in by_path[path]["symbols"] if symbol_id(s) == owner_id), None
        )
        if owner is None:
            continue
        members += [
            (path, symbol_id(s))
            for s in by_path[path]["symbols"]
            if s["name"] == f"{owner['name']}.{member}"
        ]
    return members


def _import_bindings(record: dict[str, Any]) -> dict[str, tuple[str, str]]:
    """Local name -> (resolved file, imported name or '*' for namespaces)."""
    bindings: dict[str, tuple[str, str]] = {}
    for entry in record.get("import_refs", []):
        target = entry.get("target")
        if not target or entry["kind"] not in {"import", "import-require"}:
            continue
        for name in entry.get("names", []):
            original, _, alias = name.partition(" as ")
            bindings[alias or original] = (target, original)
    return bindings


def _find_export(
    by_path: dict[str, dict[str, Any]], path: str, name: str, seen: set[str]
) -> list[tuple[str, str]]:
    """Exported top-level declarations named `name`, following re-exports."""
    record = by_path.get(path)
    if record is None or path in seen or len(seen) > MAX_REEXPORT_DEPTH:
        return []
    seen = seen | {path}
    found: list[tuple[str, str]] = []
    for symbol in record["symbols"]:
        if name.startswith("default.") and (
            symbol["name"] == name or name in symbol.get("export_as", [])
        ):
            found.append((path, symbol_id(symbol)))
            continue
        if "parent" in symbol or not symbol.get("exported"):
            continue
        if (name == "default" and symbol.get("default")) or (
            name != "default"
            and (symbol["name"] == name or name in symbol.get("export_as", []))
        ):
            found.append((path, symbol_id(symbol)))
    if found:
        return found
    local = record.get("export_bindings", {}).get(name)
    for entry in record.get("import_refs", []) if local else []:
        # `import { X } from './x'; export { X }` re-exports an imported binding.
        if entry["kind"] != "import" or not entry.get("target"):
            continue
        for imported in entry.get("names", []):
            original, _, alias = imported.partition(" as ")
            if (alias or original) == local:
                found += _find_export(by_path, entry["target"], original, seen)
    if found:
        return found
    for entry in record.get("import_refs", []):
        if entry["kind"] != "reexport" or not entry.get("target"):
            continue
        for exported in entry.get("names", ["*"]):
            original, _, alias = exported.partition(" as ")
            if original == "*" and not alias:
                found += _find_export(by_path, entry["target"], name, seen)
            elif (alias or original) == name and not original.startswith("*"):
                found += _find_export(by_path, entry["target"], original, seen)
    return found


# -- notation ----------------------------------------------------------------------


def format_symbol(symbol: dict[str, Any]) -> str:
    tag = "EXPORT" if symbol.get("exported") else "DEF"
    kind = symbol.get("kind", "symbol")
    signature = symbol.get("signature") or symbol["name"]
    if signature.startswith(f"{kind} "):
        signature = signature[len(kind) + 1 :]
    # `async`, `static`, `private` ... read naturally before the kind word.
    modifiers = []
    while (word := signature.split(" ", 1)[0]) in MODIFIERS and " " in signature:
        modifiers.append(word)
        signature = signature.split(" ", 1)[1]
    if modifiers:
        kind = " ".join([*modifiers, kind])
    end = symbol.get("end_line") or symbol["line"]
    location = f"@{symbol['line']}" + (f"-{end}" if end != symbol["line"] else "")
    notes = []
    if symbol.get("id"):
        notes.append(f"id {symbol['id']}")
    if symbol.get("default"):
        notes.append("default export")
    if symbol.get("export_as"):
        notes.append("exported as " + ", ".join(symbol["export_as"]))
    if symbol.get("recovered"):
        notes.append("RECOVERED by line scan in unparsed region; range estimated")
    elif symbol.get("syntax_error"):
        notes.append("contains parse errors")
    suffix = f" ({'; '.join(notes)})" if notes else ""
    return f"{tag} {kind} {signature} {location}{suffix}"


def format_call_target(target: dict[str, Any]) -> str:
    text = f"{target['call']} → {' | '.join(target['targets'])}"
    if target["status"] == "ambiguous":
        text += " (AMBIGUOUS)"
    elif target["status"] == "owner-only":
        text += " (member not found as a declaration; points to its owner)"
    return text


def format_import(entry: dict[str, Any]) -> str:
    status = entry.get("status", "unresolved")
    spec = entry["spec"]
    kind = "" if entry["kind"] == "import" else f" ({entry['kind']})"
    if status in {"resolved", "alias"}:
        via = " via tsconfig/jsconfig paths" if status == "alias" else ""
        return f"IMPORT {spec} → {entry['target']}{kind}{via}"
    if status == "ambiguous":
        others = ", ".join(entry.get("alternatives", []))
        return f"IMPORT {spec} → AMBIGUOUS {entry['target']} (also {others}){kind}"
    if status == "package":
        return f"IMPORT {spec} (package; not resolved){kind}"
    return f"IMPORT {spec} → UNRESOLVED{kind}"


def relevance(symbol: dict[str, Any], wanted: set[str]) -> int:
    """Name matches weigh more than words used inside the declaration body."""
    if not wanted:
        return 0
    name_hits = len(wanted.intersection(terms(symbol["name"])))
    body_hits = len(wanted.intersection(symbol.get("terms", ())))
    return 3 * name_hits + body_hits


def _span(symbol: dict[str, Any]) -> int:
    return (symbol.get("end_line") or symbol["line"] or 0) - (symbol["line"] or 0)


def relevant_symbols(
    symbols: list[dict[str, Any]], wanted: set[str]
) -> list[dict[str, Any]]:
    """Symbols scoring at least half the best score; narrower definitions first."""
    scored = [(relevance(symbol, wanted), symbol) for symbol in symbols]
    best = max((score for score, _ in scored), default=0)
    if best == 0:
        return []
    return [
        symbol
        for score, symbol in sorted(
            scored, key=lambda item: (-item[0], _span(item[1]), item[1]["line"] or 0)
        )
        if score * 2 >= best
    ]


def _display(symbol: dict[str, Any], limit: int = 110) -> str:
    line = format_symbol(symbol)
    signature = symbol.get("signature") or ""
    if len(signature) > limit:
        line = line.replace(signature, signature[: limit - 1].rstrip() + "…", 1)
    return line


def structure_lines(
    record: dict[str, Any],
    by_path: dict[str, dict[str, Any]],
    wanted: set[str],
    max_symbols: int,
    listed: set[str] | frozenset[str] = frozenset(),
    max_imports: int = 2,
) -> list[str]:
    """Task-relevant structure lines for one current file (whole lines only).

    Shows declarations relevant to the query (by name, then by words used in
    their bodies), imports leading to related files, and flagged imports.
    Files with no relevant declaration get at most two top-level ones.
    """
    if record.get("role") == "documentation":
        return []
    lines: list[str] = []
    parse = record.get("parse")
    if parse and parse.get("status") == "partial":
        lines.append(
            "PARTIAL PARSE near line(s) "
            + ", ".join(map(str, parse["error_lines"]))
            + " (invalid, or syntax this grammar does not support); declarations "
            "there may be missing, recovered by line scan, or wrong."
        )
    is_test = record.get("role") == "test"
    candidates = relevant_symbols(record["symbols"], wanted)
    if is_test:
        # Test helpers often share request words; only name matches are shown.
        candidates = [s for s in candidates if wanted.intersection(terms(s["name"]))][
            :2
        ]
    shown = candidates[:max_symbols]
    if not shown and not is_test:
        shown = [
            symbol
            for symbol in record["symbols"]
            if "parent" not in symbol
            and symbol.get("kind") not in {"const", "let", "var"}
            and (symbol.get("exported") or record.get("language") == "python")
        ][:2]
    lines += [_display(symbol) for symbol in shown]
    called_files: set[str] = set()
    for symbol in shown:
        targets = symbol.get("call_targets", [])
        if not targets or relevance(symbol, wanted) == 0:
            continue
        called_files |= {t["targets"][0].split("::")[0] for t in targets}
        if not any(line.startswith("CALLS") for line in lines):
            lines.append(
                f"CALLS from {symbol['name']}: "
                + "; ".join(format_call_target(t) for t in targets[:3])
            )

    def import_score(target: str) -> int:
        return len(wanted.intersection(terms(target))) + 2 * (target in called_files)

    # Files already named by CALLS or listed in the shortlist need no IMPORT line.
    covered = called_files | set(listed)
    imports = record.get("import_refs")
    flagged = [
        e for e in imports or [] if e.get("status") in {"ambiguous", "unresolved"}
    ]
    if is_test:
        lines += [format_import(entry) for entry in flagged[:1]]
    elif imports is not None:
        local = [
            e
            for e in imports
            if e.get("status") in {"resolved", "alias"}
            and import_score(e["target"]) > 0
            and e["target"] not in covered
        ]
        local.sort(key=lambda e: -import_score(e["target"]))
        chosen = flagged[:1] + local[: max_imports - min(1, len(flagged))]
        lines += [format_import(entry) for entry in chosen]
    else:
        targets = sorted(
            (t for t in record["imports"] if import_score(t) > 0 and t not in covered),
            key=import_score,
            reverse=True,
        )[:max_imports]
        lines += [f"IMPORT → {target}" for target in targets]
    tests = [
        path
        for path in record.get("imported_by", [])
        if by_path[path]["role"] == "test" and path not in listed
    ]
    lines += [
        f"TEST-CANDIDATE {path} (imports this file; coverage unverified)"
        for path in tests[:1]
    ]
    return lines


def orientation(index: dict[str, Any]) -> str:
    """One bounded line describing the indexed repository."""
    records = index["records"]
    languages = Counter(record.get("language", "other") for record in records)
    top_dirs = Counter(
        Path(record["path"]).parts[0] if len(Path(record["path"]).parts) > 1 else "."
        for record in records
    )
    imported = sorted(
        (
            (len(record["imported_by"]), record["path"])
            for record in records
            if record["imported_by"] and record["role"] != "test"
        ),
        reverse=True,
    )[:3]
    partial = sum(
        1 for record in records if record.get("parse", {}).get("status") == "partial"
    )
    text = (
        "Repository: "
        + ", ".join(f"{count} {name}" for name, count in languages.most_common(4))
        + " files; top directories: "
        + ", ".join(f"{name} ({count})" for name, count in top_dirs.most_common(3))
    )
    if imported:
        text += "; most imported: " + ", ".join(
            f"{path} ({count})" for count, path in imported[:2]
        )
    if partial:
        text += f"; {partial} JS/TS file(s) only partially parsed"
    return _short(text, 300) + "."
