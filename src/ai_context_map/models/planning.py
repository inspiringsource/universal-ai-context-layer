from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class PlannedFile:
    path: str
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TaskPlan:
    read_first: list[PlannedFile] = field(default_factory=list)
    edit_candidates: list[PlannedFile] = field(default_factory=list)
    impacted_files: list[PlannedFile] = field(default_factory=list)
    likely_tests: list[PlannedFile] = field(default_factory=list)
    working_cluster: list[PlannedFile] = field(default_factory=list)
