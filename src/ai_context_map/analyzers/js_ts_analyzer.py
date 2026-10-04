from __future__ import annotations

from pathlib import Path

from ai_context_map.analyzers.js_ts_structure import extract_structure
from ai_context_map.models.graph import ImportReference


class JsTsAnalyzer:
    """Import, re-export, require, and literal dynamic-import specifiers via Tree-sitter."""

    language = "javascript"

    def analyze(self, path: Path) -> list[ImportReference]:
        structure = extract_structure(path.read_bytes(), path.suffix)
        return [
            ImportReference(
                module=entry["spec"], raw=entry["spec"], names=entry.get("names", [])
            )
            for entry in structure.imports
            if entry["kind"] != "dynamic-import-unresolvable"
        ]
