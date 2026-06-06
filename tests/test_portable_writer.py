import json
from pathlib import Path

from ai_context_map.emitter.portable_writer import write_portable_exports


def test_write_portable_exports(tmp_path: Path) -> None:
    context = {
        "uacl_version": 2,
        "project": {"name": "demo", "summary": "Portable context demo."},
        "project_goals": ["Keep decisions available across models."],
        "tech_stack": ["Python"],
        "architecture": {"layers": [], "entry_points": []},
        "navigation_map": {"key_files": []},
        "current_tasks": ["Ship export support."],
        "decisions": [
            {"title": "Use YAML", "rationale": "Human-editable source of truth."}
        ],
        "constraints": ["Keep exports deterministic."],
        "known_issues": [],
        "ai_instructions": ["Read context before editing."],
        "agent_roles": [{"name": "Reviewer Agent", "responsibility": "Check changes."}],
        "task_routes": {},
    }

    paths = write_portable_exports(context, tmp_path)

    assert paths == [
        tmp_path / "AGENTS.md",
        tmp_path / "UACL_CONTEXT.md",
        tmp_path / "uacl-context.json",
        tmp_path / "AI_CONTEXT.md",
        tmp_path / "project-context.json",
    ]
    agents = paths[0].read_text(encoding="utf-8")
    markdown = paths[1].read_text(encoding="utf-8")
    data = json.loads(paths[2].read_text(encoding="utf-8"))
    assert "# AGENTS.md: demo" in agents
    assert "## Instructions" in agents
    assert "# UACL Context: demo" in markdown
    assert "**Reviewer Agent**: Check changes." in markdown
    assert data["decisions"][0]["title"] == "Use YAML"
    assert paths[1].read_text(encoding="utf-8") == paths[3].read_text(encoding="utf-8")
    assert paths[2].read_text(encoding="utf-8") == paths[4].read_text(encoding="utf-8")
