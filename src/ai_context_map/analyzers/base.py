from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ai_context_map.models.graph import ImportReference


class Analyzer(Protocol):
    language: str

    def analyze(self, path: Path) -> list[ImportReference]:
        ...

