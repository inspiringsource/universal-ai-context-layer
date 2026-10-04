"""Compare the previous regex JS/TS extraction with Tree-sitter extraction.

1. Fixtures (tests/fixtures/jsts) against hand-labelled facts
   (benchmarks/extraction_expected.json).
2. Optionally, real repositories without labels: regex declaration hits that
   fall inside comments or strings (definite false positives), exported
   top-level declarations the regex misses, and import specifier differences.

Usage:
  uv run python benchmarks/compare_extraction.py [--repos-dir DIR] [--out FILE]
DIR holds clones named in benchmarks/structural_tasks.json (see evaluate_structure.py).
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from pathlib import Path

from ai_context_map.analyzers.js_ts_structure import _parser, extract_structure
from ai_context_map.scanner.ignore import DEFAULT_IGNORED_DIRS

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "jsts"

# Frozen copies of the regular expressions used before Tree-sitter
# (src/ai_context_map/navigation/index.py and analyzers/js_ts_analyzer.py at eb84ee5).
LEGACY_SYMBOL = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function|class|interface|type|const|let)\s+([A-Za-z_$][\w$]*)",
    re.MULTILINE,
)
LEGACY_IMPORT = re.compile(
    r"""(?:import\s+(?:.+?\s+from\s+)?|export\s+.+?\s+from\s+|require\()\s*['"]([^'"]+)['"]""",
    re.MULTILINE,
)
SUFFIXES = {".js", ".jsx", ".ts", ".tsx"}


def legacy(content: str) -> tuple[list[tuple[str, int]], list[str]]:
    symbols = [
        (match.group(1), content.count("\n", 0, match.start(1)) + 1)
        for match in LEGACY_SYMBOL.finditer(content)
    ]
    return symbols, LEGACY_IMPORT.findall(content)


def fixtures() -> dict:
    expected = json.loads((ROOT / "benchmarks/extraction_expected.json").read_text())
    totals: Counter[str] = Counter()
    details = []
    for relative, facts in expected["files"].items():
        data = (FIXTURE / relative).read_bytes()
        want = {(name, line) for name, _, line in facts["declarations"]}
        want_bare = {(name.rsplit(".", 1)[-1], line) for name, line in want}
        want_imports = Counter(spec for spec, _ in facts["imports"])
        old_symbols, old_imports = legacy(data.decode())
        structure = extract_structure(data, Path(relative).suffix)
        new = {(s["name"], s["line"]) for s in structure.symbols}
        new_bare = {(name.rsplit(".", 1)[-1], line) for name, line in new}
        new_imports = Counter(i["spec"] for i in structure.imports)
        old = set(old_symbols)
        totals["expected_declarations"] += len(want)
        totals["regex_found_bare_name_and_line"] += len(want_bare & old)
        totals["regex_found_qualified"] += len(want & old)
        totals["regex_false_positives"] += len(old - want_bare)
        totals["tree_sitter_found_bare_name_and_line"] += len(want_bare & new_bare)
        totals["tree_sitter_found_qualified"] += len(want & new)
        totals["tree_sitter_false_positives"] += len(new_bare - want_bare)
        totals["expected_imports"] += sum(want_imports.values())
        totals["regex_imports_found"] += sum(
            (want_imports & Counter(old_imports)).values()
        )
        totals["regex_import_false_positives"] += sum(
            (Counter(old_imports) - want_imports).values()
        )
        totals["tree_sitter_imports_found"] += sum(
            (want_imports & new_imports).values()
        )
        totals["tree_sitter_import_false_positives"] += sum(
            (new_imports - want_imports).values()
        )
        details.append(
            {
                "file": relative,
                "regex_missed": sorted(f"{n}@{line}" for n, line in want_bare - old),
                "regex_false_positives": sorted(
                    f"{n}@{line}" for n, line in old - want_bare
                ),
                "tree_sitter_missed_qualified": sorted(
                    f"{n}@{line}" for n, line in want - new
                ),
                "tree_sitter_false_positives": sorted(
                    f"{n}@{line}" for n, line in new_bare - want_bare
                ),
                "regex_imports_missed": sorted(
                    (want_imports - Counter(old_imports)).elements()
                ),
                "tree_sitter_imports_missed": sorted(
                    (want_imports - new_imports).elements()
                ),
            }
        )
    totals["tree_sitter_symbols_with_end_line"] = totals["tree_sitter_found_qualified"]
    return {"totals": dict(totals), "files": details}


def _source_files(root: Path):
    for directory, dirs, names in os.walk(root):
        dirs[:] = sorted(
            d for d in dirs if d not in DEFAULT_IGNORED_DIRS and d != ".ai"
        )
        for name in sorted(names):
            path = Path(directory) / name
            if path.suffix in SUFFIXES and not path.is_symlink():
                yield path


def repository(root: Path) -> dict:
    """Unlabelled comparison; only definite errors are counted as errors."""
    counts: Counter[str] = Counter()
    examples: dict[str, list[str]] = {
        "regex_in_comment_or_string": [],
        "regex_missed_export": [],
        "import_differences": [],
    }
    missed_kinds: Counter[str] = Counter()
    for path in _source_files(root):
        data = path.read_bytes()
        if len(data) > 1_000_000:
            continue
        content = data.decode("utf-8", "replace")
        relative = path.relative_to(root).as_posix()
        old_symbols, old_imports = legacy(content)
        structure = extract_structure(data, path.suffix)
        tree = _parser(structure.grammar).parse(data)
        lines = content.splitlines()
        counts["files"] += 1
        counts["partial_files"] += structure.parse_status == "partial"
        counts["regex_declarations"] += len(old_symbols)
        counts["tree_sitter_declarations"] += len(structure.symbols)
        counts["tree_sitter_nested_declarations"] += sum(
            "parent" in s for s in structure.symbols
        )
        counts["tree_sitter_recovered_declarations"] += sum(
            bool(s.get("recovered")) for s in structure.symbols
        )
        for name, line in old_symbols:
            column = lines[line - 1].find(name)
            node = tree.root_node.descendant_for_point_range(
                (line - 1, column), (line - 1, column)
            )
            inside = node
            while inside is not None and inside.type not in {
                "comment",
                "string",
                "template_string",
            }:
                inside = inside.parent
            if inside is not None:
                counts["regex_in_comment_or_string"] += 1
                if len(examples["regex_in_comment_or_string"]) < 8:
                    examples["regex_in_comment_or_string"].append(
                        f"{relative}:{line} {name} ({inside.type})"
                    )
        old_set = set(old_symbols)
        for symbol in structure.symbols:
            if (
                "parent" in symbol
                or not symbol.get("exported")
                or symbol.get("recovered")
            ):
                continue
            if not any(
                name == symbol["name"] and abs(line - symbol["line"]) <= 1
                for name, line in old_set
            ):
                counts["exported_top_level_missed_by_regex"] += 1
                missed_kinds[symbol["kind"]] += 1
                if len(examples["regex_missed_export"]) < 8:
                    examples["regex_missed_export"].append(
                        f"{relative}:{symbol['line']} {symbol['kind']} {symbol['name']}"
                    )
        counts["exported_top_level_tree_sitter"] += sum(
            1
            for s in structure.symbols
            if "parent" not in s and s.get("exported") and not s.get("recovered")
        )
        old_specs = Counter(old_imports)
        new_specs = Counter(i["spec"] for i in structure.imports)
        only_old = old_specs - new_specs
        only_new = new_specs - old_specs
        counts["regex_import_specs"] += sum(old_specs.values())
        counts["tree_sitter_import_specs"] += sum(new_specs.values())
        counts["import_specs_only_regex"] += sum(only_old.values())
        counts["import_specs_only_tree_sitter"] += sum(only_new.values())
        if (only_old or only_new) and len(examples["import_differences"]) < 8:
            examples["import_differences"].append(
                f"{relative}: regex-only {sorted(only_old)[:3]}, tree-sitter-only {sorted(only_new)[:3]}"
            )
    return {
        "counts": dict(counts),
        "missed_export_kinds": dict(missed_kinds),
        "examples": examples,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repos-dir", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = {"fixtures": fixtures()}
    if args.repos_dir:
        tasks = json.loads((ROOT / "benchmarks/structural_tasks.json").read_text())
        report["repositories"] = {
            name: {"commit": meta["commit"], **repository(args.repos_dir / name)}
            for name, meta in tasks["repositories"].items()
        }
    text = json.dumps(report, indent=2)
    if args.out:
        args.out.write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
