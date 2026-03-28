from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class MemoryLink:
    path: str
    count: int
    weight: float


@dataclass(slots=True)
class FileMemory:
    path: str
    related: list[MemoryLink] = field(default_factory=list)


@dataclass(slots=True)
class MemoryProvenance:
    source: str
    commit_limit: int
    generated_at: str | None = None


@dataclass(slots=True)
class RepositoryMemory:
    memory_version: int = 1
    provenance: MemoryProvenance | None = None
    files: list[FileMemory] = field(default_factory=list)
