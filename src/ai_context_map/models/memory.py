from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class RepositoryZone:
    name: str
    paths: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ClusterSeed:
    label: str
    files: list[str] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TestMapping:
    __test__ = False

    implementation: str
    tests: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CentralFile:
    path: str
    score: float
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TaskRoutePrior:
    category: str
    files: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RepositoryMemoryDocument:
    memory_version: int
    repository_zones: list[RepositoryZone] = field(default_factory=list)
    cluster_seeds: list[ClusterSeed] = field(default_factory=list)
    test_mappings: list[TestMapping] = field(default_factory=list)
    central_files: list[CentralFile] = field(default_factory=list)
    task_route_priors: list[TaskRoutePrior] = field(default_factory=list)
