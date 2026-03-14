from __future__ import annotations

import ast
from pathlib import Path

from ai_context_map.models.graph import ImportReference


class PythonAnalyzer:
    language = "python"

    def analyze(self, path: Path) -> list[ImportReference]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        refs: list[ImportReference] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    refs.append(ImportReference(module=alias.name, raw=alias.name))
            elif isinstance(node, ast.ImportFrom):
                refs.append(
                    ImportReference(
                        module=node.module,
                        level=node.level,
                        names=[alias.name for alias in node.names if alias.name != "*"],
                        raw=node.module,
                    )
                )
        return refs

