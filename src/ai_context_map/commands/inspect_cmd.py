from __future__ import annotations

from pathlib import Path

import yaml

from ai_context_map.config import load_config


def inspect_context(root: Path) -> dict:
    path = root / load_config(root).output_path
    if not path.exists():
        raise FileNotFoundError(
            "No context file found. Run `aicontext generate` first."
        )
    return yaml.safe_load(path.read_text(encoding="utf-8"))
