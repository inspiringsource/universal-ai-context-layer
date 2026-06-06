from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import yaml

from ai_context_map.models.context import ContextDocument


def write_context_yaml(document: ContextDocument, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        yaml.safe_dump(_to_data(document), sort_keys=False), encoding="utf-8"
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
