from __future__ import annotations

from pathlib import Path


ROLE_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("entrypoint", ("main", "cli", "server", "manage", "__main__")),
    ("api", ("api", "route", "router", "endpoint")),
    ("config", ("config", "settings")),
    ("data_model", ("model", "schema", "entity", "dto")),
    ("storage", ("db", "database", "repository", "storage", "store")),
    ("business_logic", ("service", "core", "domain", "logic")),
    ("utility", ("util", "utils", "helper", "helpers", "common")),
    ("test", ("test", "tests", "spec")),
    ("ui", ("view", "component", "page", "screen")),
]


def classify_role(relative_path: str) -> str:
    path = Path(relative_path)
    lowered = "/".join(part.lower() for part in path.parts)
    for role, patterns in ROLE_PATTERNS:
        if any(pattern in lowered for pattern in patterns):
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

