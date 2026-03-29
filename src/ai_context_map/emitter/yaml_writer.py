from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import yaml

from ai_context_map.models.context import ContextDocument
from ai_context_map.models.memory import (
    CentralFile,
    ClusterSeed,
    RepositoryMemoryDocument,
    RepositoryZone,
    TaskRoutePrior,
    TestMapping,
)


def write_context_yaml(document: ContextDocument, output_path: Path) -> None:
    write_yaml(document, output_path)


def write_memory_yaml(document: RepositoryMemoryDocument, output_path: Path) -> None:
    write_yaml(document, output_path)


def write_yaml(document: object, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml.safe_dump(_to_data(document), sort_keys=False), encoding="utf-8")


def read_memory_yaml(path: Path) -> RepositoryMemoryDocument:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return RepositoryMemoryDocument(
        memory_version=int(data.get("memory_version", 1)),
        repository_zones=[
            RepositoryZone(name=item["name"], paths=list(item.get("paths", [])))
            for item in data.get("repository_zones", [])
        ],
        cluster_seeds=[
            ClusterSeed(
                label=item["label"],
                files=list(item.get("files", [])),
                signals=list(item.get("signals", [])),
            )
            for item in data.get("cluster_seeds", [])
        ],
        test_mappings=[
            TestMapping(
                implementation=item["implementation"],
                tests=list(item.get("tests", [])),
            )
            for item in data.get("test_mappings", [])
        ],
        central_files=[
            CentralFile(
                path=item["path"],
                score=float(item["score"]),
                reasons=list(item.get("reasons", [])),
            )
            for item in data.get("central_files", [])
        ],
        task_route_priors=[
            TaskRoutePrior(
                category=item["category"],
                files=list(item.get("files", [])),
            )
            for item in data.get("task_route_priors", [])
        ],
    )


def write_history_stub(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("history_version: 1\nentries: []\n", encoding="utf-8")


def _to_data(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _to_data(item) for key, item in asdict(value).items()}
    if isinstance(value, list):
        return [_to_data(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_data(item) for key, item in value.items()}
    return value
