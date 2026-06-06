from __future__ import annotations

from pathlib import Path

LANGUAGE_BY_EXTENSION = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
}


def classify_file(path: Path) -> tuple[str | None, bool]:
    language = LANGUAGE_BY_EXTENSION.get(path.suffix.lower())
    return language, language is not None
