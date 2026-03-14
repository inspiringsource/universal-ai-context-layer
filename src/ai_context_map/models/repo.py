from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class RepositoryFile:
    path: Path
    relative_path: str
    language: str | None
    extension: str
    is_source: bool
    size_bytes: int


@dataclass(slots=True)
class ScanResult:
    root: Path
    files: list[RepositoryFile] = field(default_factory=list)
    languages: set[str] = field(default_factory=set)

