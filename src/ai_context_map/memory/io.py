from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import yaml

from ai_context_map.memory.models import FileMemory, MemoryLink, MemoryProvenance, RepositoryMemory


def write_memory_yaml(memory: RepositoryMemory, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml.safe_dump(asdict(memory), sort_keys=False), encoding="utf-8")


def read_memory_yaml(path: Path) -> RepositoryMemory:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    provenance_data = data.get("provenance")
    provenance = MemoryProvenance(**provenance_data) if provenance_data else None

    files = [
        FileMemory(
            path=item["path"],
            related=[MemoryLink(**related_item) for related_item in item.get("related", [])],
        )
        for item in data.get("files", [])
    ]
    return RepositoryMemory(
        memory_version=int(data.get("memory_version", 1)),
        provenance=provenance,
        files=files,
    )
