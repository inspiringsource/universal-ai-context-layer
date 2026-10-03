"""Local storage helpers for checkpoint and evidence files under `.ai/work/`."""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ai_context_map.navigation.index import safe_path

WORK_DIR = ".ai/work"
CHECKPOINT_PATH = f"{WORK_DIR}/checkpoint.json"
EVIDENCE_DIR = f"{WORK_DIR}/evidence"
# A self-ignoring directory keeps local state out of Git in any repository
# without editing the user's own .gitignore.
GITIGNORE_TEXT = "# Local UACL checkpoint and evidence; not for version control.\n*\n"
CHUNK = 1 << 16


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def work_path(root: Path, relative: str, create: bool = False) -> Path:
    """Resolve a path under `.ai/work`, refusing symlinks and repository escapes."""
    root = root.resolve()
    path = safe_path(root, relative)
    for parent in [root / ".ai", root / WORK_DIR]:
        if parent.is_symlink():
            raise ValueError(f"Refusing to use symlinked directory: {parent}")
    if create:
        work = root / WORK_DIR
        work.mkdir(parents=True, exist_ok=True)
        ignore = work / ".gitignore"
        if not ignore.exists():
            atomic_write_text(ignore, GITIGNORE_TEXT)
    return path


def atomic_write_text(path: Path, text: str) -> None:
    """Write via a fsynced temporary file and rename; the old file survives failures."""
    if path.is_symlink():
        raise ValueError(f"Refusing to write through symlink: {path}")
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def file_digest(path: Path) -> tuple[str, int, int]:
    """Stream a file once: sha256, byte count, and line count."""
    digest = hashlib.sha256()
    size = lines = 0
    last = b"\n"
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
            size += len(chunk)
            lines += chunk.count(b"\n")
            last = chunk[-1:]
    if last != b"\n":
        lines += 1
    return digest.hexdigest(), size, lines


def iter_lines(path: Path, max_line_bytes: int) -> Iterator[tuple[int, bytes, int]]:
    """Yield (line number, bounded prefix, full length) without loading long lines."""
    with path.open("rb") as handle:
        number = 0
        while True:
            prefix = handle.readline(max_line_bytes)
            if not prefix:
                return
            number += 1
            length = len(prefix)
            ended = prefix.endswith(b"\n")
            while not ended and (rest := handle.readline(CHUNK)):
                length += len(rest)
                ended = rest.endswith(b"\n")
            yield number, prefix.rstrip(b"\r\n"), length - ended


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=True,
        timeout=20,
    ).stdout


def worktree_fingerprint(root: Path) -> dict[str, Any] | None:
    """Fingerprint HEAD plus modified/untracked file contents, excluding `.ai/`.

    Returns None outside Git. Used only to flag possibly stale records.
    """
    try:
        _git(root, "rev-parse", "--is-inside-work-tree")
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        head: str | None = _git(root, "rev-parse", "HEAD").decode().strip()
    except subprocess.SubprocessError:
        head = None
    try:
        listed = _git(
            root, "ls-files", "-z", "--modified", "--others", "--exclude-standard"
        )
    except (OSError, subprocess.SubprocessError):
        return None
    digest = hashlib.sha256()
    for relative in sorted(set(listed.decode("utf-8", "surrogateescape").split("\0"))):
        if not relative or relative == ".ai" or relative.startswith(".ai/"):
            continue
        path = root / relative
        digest.update(relative.encode("utf-8", "surrogateescape") + b"\0")
        if path.is_file() and not path.is_symlink():
            digest.update(file_digest(path)[0].encode())
        else:
            digest.update(b"<absent>")
    return {"head": head, "worktree_sha256": digest.hexdigest()}


def repository_change(root: Path, recorded: dict[str, Any] | None) -> str:
    """Compare a recorded fingerprint with now: 'unchanged', 'CHANGED', or 'unknown'."""
    if not recorded:
        return "unknown"
    current = worktree_fingerprint(root)
    if current is None:
        return "unknown"
    return "unchanged" if current == recorded else "CHANGED"


def find_root(start: Path) -> Path:
    """Nearest ancestor holding `.ai` or `.git`; otherwise the start directory."""
    start = start.resolve()
    for candidate in [start, *start.parents]:
        if (candidate / ".ai").is_dir() or (candidate / ".git").exists():
            return candidate
    return start
