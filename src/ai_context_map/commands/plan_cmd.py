from __future__ import annotations

from pathlib import Path

from ai_context_map.navigation.planner import load_task_plan


def plan_task_for_repository(root: Path, task: str):
    return load_task_plan(root, task)
