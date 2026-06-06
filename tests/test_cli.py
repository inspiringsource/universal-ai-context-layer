import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from ai_context_map.cli import app

runner = CliRunner()


def test_cli_init_and_generate(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text(
        "from app.service import run\n\nif __name__ == '__main__':\n    run()\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "app").mkdir()
    (tmp_path / "src" / "app" / "service.py").write_text(
        "def run():\n    return 1\n", encoding="utf-8"
    )

    init_result = runner.invoke(app, ["init", str(tmp_path)])
    assert init_result.exit_code == 0
    assert (tmp_path / ".aicontext.toml").exists()
    assert (tmp_path / ".ai" / "history.yaml").exists()

    generate_result = runner.invoke(app, ["generate", str(tmp_path)])
    assert generate_result.exit_code == 0
    assert (tmp_path / ".ai" / "context.yaml").exists()
    assert "Project:" in generate_result.stdout
    context = yaml.safe_load(
        (tmp_path / ".ai" / "context.yaml").read_text(encoding="utf-8")
    )
    assert context["architecture"]["core_modules"][0]["pagerank_score"] > 0
    assert (
        context["architecture"]["top_pagerank_nodes"][0]["path"] == "src/app/service.py"
    )
    assert context["metrics"]["top_ranked_file_metadata"][0]["pagerank_score"] > 0
    assert context["tech_stack"] == ["python"]

    context["project_goals"] = ["Preserve context across AI tools."]
    context["current_tasks"] = ["Add portable exports."]
    context["decisions"] = [
        {"title": "Canonical YAML", "rationale": "Easy to edit and diff."}
    ]
    context["ai_instructions"] = ["Read the context map before changing code."]
    context["agent_roles"] = [
        {"name": "Coding Agent", "responsibility": "Implement scoped tasks."}
    ]
    (tmp_path / ".ai" / "context.yaml").write_text(
        yaml.safe_dump(context), encoding="utf-8"
    )

    update_result = runner.invoke(app, ["generate", str(tmp_path)])
    assert update_result.exit_code == 0
    updated = yaml.safe_load(
        (tmp_path / ".ai" / "context.yaml").read_text(encoding="utf-8")
    )
    assert updated["project_goals"] == ["Preserve context across AI tools."]

    inspect_result = runner.invoke(app, ["inspect", str(tmp_path)])
    assert inspect_result.exit_code == 0
    assert "Project goals:" in inspect_result.stdout
    assert "Preserve context across AI tools." in inspect_result.stdout
    assert "Add portable exports." in inspect_result.stdout

    inspect_routes_result = runner.invoke(app, ["inspect-routes", str(tmp_path)])
    assert inspect_routes_result.exit_code == 0
    assert "Task routes:" in inspect_routes_result.stdout
    assert "Top anchors:" in inspect_routes_result.stdout

    export_result = runner.invoke(app, ["export", str(tmp_path)])
    assert export_result.exit_code == 0
    markdown = (tmp_path / ".ai" / "exports" / "AI_CONTEXT.md").read_text(
        encoding="utf-8"
    )
    exported_json = json.loads(
        (tmp_path / ".ai" / "exports" / "project-context.json").read_text(
            encoding="utf-8"
        )
    )
    assert "## Agent Roles" in markdown
    assert "Coding Agent" in markdown
    assert exported_json["project_goals"] == ["Preserve context across AI tools."]
    assert (tmp_path / ".ai" / "exports" / "UACL_CONTEXT.md").exists()
    assert (tmp_path / ".ai" / "exports" / "uacl-context.json").exists()

    custom_export_result = runner.invoke(
        app,
        ["export", str(tmp_path), "--output-dir", str(tmp_path / "context-handoff")],
    )
    assert custom_export_result.exit_code == 0
    assert (tmp_path / "context-handoff" / "AI_CONTEXT.md").exists()
    assert (tmp_path / "context-handoff" / "UACL_CONTEXT.md").exists()
