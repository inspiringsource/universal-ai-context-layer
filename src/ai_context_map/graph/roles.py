from __future__ import annotations

from pathlib import Path
import re


TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


ROLE_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("entrypoint", ("main", "cli", "server", "manage", "__main__")),
    ("config", ("config", "settings")),
    ("data_model", ("model", "schema", "entity", "dto")),
    ("storage", ("db", "database", "repository", "storage", "store")),
    ("business_logic", ("service", "core", "domain", "logic")),
    ("utility", ("util", "utils", "helper", "helpers", "common")),
    ("test", ("test", "tests", "spec")),
    ("ui", ("view", "component", "page", "screen")),
]


def classify_role(relative_path: str) -> str:
    if _is_api_path(relative_path):
        return "api"
    tokens = _path_tokens(relative_path)
    for role, patterns in ROLE_PATTERNS:
        if any(pattern in tokens for pattern in patterns):
            return role
    return "unknown"


def classify_directory_role(relative_path: str) -> str:
    lowered = relative_path.lower().strip("/")
    if lowered in {"src", "app", "lib"}:
        return "source_root"
    if lowered in {"tests", "test"}:
        return "tests"
    if "api" in lowered:
        return "api"
    if "config" in lowered:
        return "config"
    return "directory"


def _path_tokens(relative_path: str) -> set[str]:
    path = Path(relative_path).with_suffix("")
    tokens: set[str] = set()
    for part in path.parts:
        tokens.update(TOKEN_PATTERN.findall(part.lower()))
    return tokens


def _is_api_path(relative_path: str) -> bool:
    path = Path(relative_path).with_suffix("")
    lowered_parts = [part.lower() for part in path.parts]
    if "api" in lowered_parts:
        return True
    tokens = _path_tokens(relative_path)
    return any(token in tokens for token in {"route", "routes", "router", "routing", "endpoint"})
