from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
import subprocess

from ai_context_map.memory.models import FileMemory, MemoryLink, MemoryProvenance, RepositoryMemory
from ai_context_map.scanner.ignore import IgnoreRules


def extract_git_cochange_memory(root: Path, commit_limit: int = 100) -> RepositoryMemory:
    commits = _read_recent_commits(root, commit_limit=commit_limit)
    files = build_file_memory(commits)
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return RepositoryMemory(
        provenance=MemoryProvenance(source="git", commit_limit=commit_limit, generated_at=generated_at),
        files=files,
    )


def build_file_memory(commits: list[list[str]]) -> list[FileMemory]:
    totals: Counter[str] = Counter()
    related_by_file: dict[str, Counter[str]] = defaultdict(Counter)

    for files in commits:
        unique_files = sorted(set(files))
        for path in unique_files:
            totals[path] += 1
        if len(unique_files) < 2:
            continue
        for left, right in combinations(unique_files, 2):
            related_by_file[left][right] += 1
            related_by_file[right][left] += 1

    file_memories: list[FileMemory] = []
    for path in sorted(totals):
        related = [
            MemoryLink(
                path=related_path,
                count=count,
                weight=round(count / max(totals[path], totals[related_path]), 4),
            )
            for related_path, count in sorted(
                related_by_file.get(path, {}).items(),
                key=lambda item: (-item[1], item[0]),
            )
        ]
        file_memories.append(FileMemory(path=path, related=related))
    return file_memories


def _read_recent_commits(root: Path, commit_limit: int) -> list[list[str]]:
    cmd = [
        "git",
        "-C",
        str(root),
        "log",
        f"--max-count={commit_limit}",
        "--name-only",
        "--format=commit:%H",
        "--diff-filter=ACMR",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    commits: list[list[str]] = []
    current: list[str] = []
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("commit:"):
            if current:
                commits.append(current)
                current = []
            continue
        if _should_include_path(stripped):
            current.append(stripped)
    if current:
        commits.append(current)
    return commits


def _should_include_path(relative_path: str) -> bool:
    ignore_rules = IgnoreRules(exclude_paths=[])
    if relative_path.startswith(".ai/"):
        return False
    if ignore_rules.should_ignore_file(relative_path):
        return False
    path = Path(relative_path)
    name = path.name.lower()
    if name.endswith((".min.js", ".min.css", ".map", ".pyc")):
        return False
    return True
