from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ProjectSummary:
    name: str
    root: str
    detected_languages: list[str]
    summary: str | None = None


@dataclass(slots=True)
class EntryPoint:
    path: str
    confidence: float
    reasons: list[str]


@dataclass(slots=True)
class CoreModule:
    path: str
    score: float
    reasons: list[str]


@dataclass(slots=True)
class DirectoryRole:
    path: str
    role: str


@dataclass(slots=True)
class KeyFile:
    path: str
    role: str
    importance: str


@dataclass(slots=True)
class NavigationMap:
    directories: list[DirectoryRole] = field(default_factory=list)
    key_files: list[KeyFile] = field(default_factory=list)


@dataclass(slots=True)
class Hotspot:
    path: str
    reason: str


@dataclass(slots=True)
class Anchor:
    file: str
    symbol: str
    symbol_type: str
    line: int | None = None
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TaskRouteFile:
    path: str
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RankedTaskRoute:
    category: str
    files: list[TaskRouteFile] = field(default_factory=list)


@dataclass(slots=True)
class ProvenanceInfo:
    enabled: bool
    history_file: str


@dataclass(slots=True)
class ContextDocument:
    aicontext_version: int
    project: ProjectSummary
    architecture: dict[str, Any]
    navigation_map: NavigationMap
    hotspots: list[Hotspot]
    anchors: list[Anchor]
    task_routes: dict[str, list[TaskRouteFile]]
    constraints: list[str]
    known_issues: list[str]
    provenance: ProvenanceInfo
    metrics: dict[str, Any] = field(default_factory=dict)
