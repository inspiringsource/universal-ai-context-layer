import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from ai_context_map.cli import app


runner = CliRunner()


def test_cli_init_and_generate(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("from app.service import run\n\nif __name__ == '__main__':\n    run()\n", encoding="utf-8")
    (tmp_path / "src" / "app").mkdir()
    (tmp_path / "src" / "app" / "service.py").write_text("def run():\n    return 1\n", encoding="utf-8")

    init_result = runner.invoke(app, ["init", str(tmp_path)])
    assert init_result.exit_code == 0
    assert (tmp_path / ".aicontext.toml").exists()
    assert (tmp_path / ".ai" / "history.yaml").exists()

    generate_result = runner.invoke(app, ["generate", str(tmp_path)])
    assert generate_result.exit_code == 0
    assert (tmp_path / ".ai" / "context.yaml").exists()
    assert (tmp_path / ".ai" / "memory.yaml").exists()
    assert "Project:" in generate_result.stdout
    context = yaml.safe_load((tmp_path / ".ai" / "context.yaml").read_text(encoding="utf-8"))
    memory = yaml.safe_load((tmp_path / ".ai" / "memory.yaml").read_text(encoding="utf-8"))
    assert context["architecture"]["core_modules"][0]["pagerank_score"] > 0
    assert context["architecture"]["top_pagerank_nodes"][0]["path"] == "src/app/service.py"
    assert context["metrics"]["top_ranked_file_metadata"][0]["pagerank_score"] > 0
    assert memory["central_files"][0]["path"] == "src/app/service.py"
    assert any(item["implementation"] == "src/app/service.py" for item in memory["test_mappings"]) is False

    inspect_routes_result = runner.invoke(app, ["inspect-routes", str(tmp_path)])
    assert inspect_routes_result.exit_code == 0
    assert "Task routes:" in inspect_routes_result.stdout
    assert "Top anchors:" in inspect_routes_result.stdout

    plan_result = runner.invoke(app, ["plan", "update service logic", str(tmp_path)])
    assert plan_result.exit_code == 0
    assert "Read first:" in plan_result.stdout
    assert "Edit candidates:" in plan_result.stdout
    assert "Likely tests:" in plan_result.stdout
    assert "Working cluster:" in plan_result.stdout


def test_cli_plan_supports_json_output(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("from app.service import run\n\nif __name__ == '__main__':\n    run()\n", encoding="utf-8")
    (tmp_path / "src" / "app").mkdir()
    (tmp_path / "src" / "app" / "service.py").write_text("def run():\n    return 1\n", encoding="utf-8")

    init_result = runner.invoke(app, ["init", str(tmp_path)])
    assert init_result.exit_code == 0
    generate_result = runner.invoke(app, ["generate", str(tmp_path)])
    assert generate_result.exit_code == 0

    monkeypatch.chdir(tmp_path)
    plan_result = runner.invoke(app, ["plan", "update service logic", "--json"])

    assert plan_result.exit_code == 0
    data = json.loads(plan_result.stdout)
    assert set(data) == {"read_first", "edit_candidates", "impacted_files", "likely_tests", "working_cluster"}
    assert isinstance(data["read_first"], list)
    assert any(item["path"] == "src/app/service.py" for item in data["read_first"])
    assert isinstance(data["read_first"][0]["reasons"], list)
    assert any(item["path"] == "src/app/service.py" for item in data["working_cluster"])


def test_cli_plan_text_output_still_works_without_json(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("from app.service import run\n\nif __name__ == '__main__':\n    run()\n", encoding="utf-8")
    (tmp_path / "src" / "app").mkdir()
    (tmp_path / "src" / "app" / "service.py").write_text("def run():\n    return 1\n", encoding="utf-8")

    init_result = runner.invoke(app, ["init", str(tmp_path)])
    assert init_result.exit_code == 0
    generate_result = runner.invoke(app, ["generate", str(tmp_path)])
    assert generate_result.exit_code == 0

    monkeypatch.chdir(tmp_path)
    plan_result = runner.invoke(app, ["plan", "update service logic"])

    assert plan_result.exit_code == 0
    assert "Read first:" in plan_result.stdout
    assert "Edit candidates:" in plan_result.stdout
    assert "Impacted files:" in plan_result.stdout
    assert "Likely tests:" in plan_result.stdout
