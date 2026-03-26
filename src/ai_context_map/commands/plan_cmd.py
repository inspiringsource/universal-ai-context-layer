from __future__ import annotations

from pathlib import Path

from ai_context_map.planner import TaskPlan, plan_task


def build_plan(root: Path, task: str) -> TaskPlan:
    return plan_task(root, task)
