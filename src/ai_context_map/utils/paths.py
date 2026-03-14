from __future__ import annotations

from pathlib import Path


def ensure_repo_root(path: Path) -> Path:
    return path.resolve()

