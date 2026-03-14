from __future__ import annotations

from pathlib import Path

import yaml


def inspect_context(root: Path) -> dict:
    path = root / ".ai" / "context.yaml"
    if not path.exists():
        raise FileNotFoundError("No context file found. Run `aicontext generate` first.")
    return yaml.safe_load(path.read_text(encoding="utf-8"))

