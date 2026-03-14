from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DEFAULT_IGNORED_DIRS = {
    ".git",
    "node_modules",
    "dist",
    "build",
    ".next",
    "coverage",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".idea",
    ".vscode",
    "target",
    "vendor",
}

DEFAULT_IGNORED_FILES = {
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "poetry.lock",
}


@dataclass(slots=True)
class IgnoreRules:
    exclude_paths: list[str]

    def should_ignore_dir(self, relative_path: str) -> bool:
        parts = Path(relative_path).parts
        if any(part in DEFAULT_IGNORED_DIRS for part in parts):
            return True
        return any(relative_path == path or relative_path.startswith(f"{path}/") for path in self.exclude_paths)

    def should_ignore_file(self, relative_path: str) -> bool:
        path = Path(relative_path)
        if path.name in DEFAULT_IGNORED_FILES:
            return True
        return self.should_ignore_dir(relative_path)

