from __future__ import annotations

from pathlib import Path

from ai_context_map.config import DEFAULT_CONFIG_TEXT, config_path
from ai_context_map.emitter.yaml_writer import write_history_stub


def run_init(root: Path) -> list[str]:
    created: list[str] = []
    ai_dir = root / ".ai"
    if not ai_dir.exists():
        ai_dir.mkdir(parents=True, exist_ok=True)
        created.append(".ai/")
    cfg_path = config_path(root)
    if not cfg_path.exists():
        cfg_path.write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8")
        created.append(".aicontext.toml")
    history_path = ai_dir / "history.yaml"
    if not history_path.exists():
        write_history_stub(history_path)
        created.append(".ai/history.yaml")
    return created
