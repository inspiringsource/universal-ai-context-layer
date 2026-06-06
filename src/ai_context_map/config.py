from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_TEXT = """include_paths = []
exclude_paths = []
languages = ["python", "javascript", "typescript"]
enable_git_metadata = false
output_path = ".ai/context.yaml"

[filename_weights]
main = 4.0
app = 3.0
server = 3.0
cli = 3.0
api = 2.5
routes = 2.5
config = 1.5
service = 2.0
index = 2.0
"""


@dataclass(slots=True)
class Config:
    include_paths: list[str] = field(default_factory=list)
    exclude_paths: list[str] = field(default_factory=list)
    languages: list[str] = field(
        default_factory=lambda: ["python", "javascript", "typescript"]
    )
    filename_weights: dict[str, float] = field(
        default_factory=lambda: {
            "main": 4.0,
            "app": 3.0,
            "server": 3.0,
            "cli": 3.0,
            "api": 2.5,
            "routes": 2.5,
            "config": 1.5,
            "service": 2.0,
            "index": 2.0,
        }
    )
    enable_git_metadata: bool = False
    output_path: str = ".ai/context.yaml"


def config_path(root: Path) -> Path:
    return root / ".aicontext.toml"


def load_config(root: Path) -> Config:
    path = config_path(root)
    if not path.exists():
        return Config()
    data = tomllib.loads(path.read_text())
    return Config(
        include_paths=list(data.get("include_paths", [])),
        exclude_paths=list(data.get("exclude_paths", [])),
        languages=list(data.get("languages", ["python", "javascript", "typescript"])),
        filename_weights=dict(data.get("filename_weights", {}))
        or Config().filename_weights,
        enable_git_metadata=bool(data.get("enable_git_metadata", False)),
        output_path=str(data.get("output_path", ".ai/context.yaml")),
    )
