from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ImportReference:
    module: str | None
    level: int = 0
    names: list[str] = field(default_factory=list)
    raw: str | None = None


@dataclass(slots=True)
class FileNode:
    path: str
    language: str
    role: str = "unknown"
    size_bytes: int = 0
    imports: list[ImportReference] = field(default_factory=list)


@dataclass(slots=True)
class DependencyEdge:
    source: str
    target: str

