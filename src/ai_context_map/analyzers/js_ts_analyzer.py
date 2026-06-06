from __future__ import annotations

import re
from pathlib import Path

from ai_context_map.models.graph import ImportReference

IMPORT_RE = re.compile(
    r"""(?:import\s+(?:.+?\s+from\s+)?|export\s+.+?\s+from\s+|require\()\s*['"]([^'"]+)['"]""",
    re.MULTILINE,
)


class JsTsAnalyzer:
    language = "javascript"

    def analyze(self, path: Path) -> list[ImportReference]:
        content = path.read_text(encoding="utf-8")
        return [
            ImportReference(module=match, raw=match)
            for match in IMPORT_RE.findall(content)
        ]
