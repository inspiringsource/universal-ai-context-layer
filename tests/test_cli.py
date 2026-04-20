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
    assert "Project:" in generate_result.stdout
    context = yaml.safe_load((tmp_path / ".ai" / "context.yaml").read_text(encoding="utf-8"))
    assert context["architecture"]["core_modules"][0]["pagerank_score"] > 0
    assert context["architecture"]["top_pagerank_nodes"][0]["path"] == "src/app/service.py"
    assert context["metrics"]["top_ranked_file_metadata"][0]["pagerank_score"] > 0

    inspect_routes_result = runner.invoke(app, ["inspect-routes", str(tmp_path)])
    assert inspect_routes_result.exit_code == 0
    assert "Task routes:" in inspect_routes_result.stdout
    assert "Top anchors:" in inspect_routes_result.stdout


def test_cli_plan_outputs_task_sections(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "api").mkdir()
    (tmp_path / "src" / "api" / "auth_routes.py").write_text("from src.core.auth_service import login\n", encoding="utf-8")
    (tmp_path / "src" / "core").mkdir()
    (tmp_path / "src" / "core" / "auth_service.py").write_text("def login():\n    return True\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_auth.py").write_text("from src.core.auth_service import login\n", encoding="utf-8")

    plan_result = runner.invoke(app, ["plan", "fix failing auth test", str(tmp_path)])

    assert plan_result.exit_code == 0
    assert "Read first:" in plan_result.stdout
    assert "Likely edit candidates:" in plan_result.stdout
    assert "Likely impacted files:" in plan_result.stdout
    assert "Likely tests:" in plan_result.stdout
    assert "src/api/auth_routes.py" in plan_result.stdout or "src/core/auth_service.py" in plan_result.stdout


def test_cli_plan_json_outputs_machine_readable_sections(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "api").mkdir()
    (tmp_path / "src" / "api" / "auth_routes.py").write_text("from src.core.auth_service import login\n", encoding="utf-8")
    (tmp_path / "src" / "core").mkdir()
    (tmp_path / "src" / "core" / "auth_service.py").write_text("def login():\n    return True\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_auth.py").write_text("from src.core.auth_service import login\n", encoding="utf-8")

    plan_result = runner.invoke(app, ["plan", "fix login bug", str(tmp_path), "--json"])

    assert plan_result.exit_code == 0
    payload = json.loads(plan_result.stdout)
    assert list(payload) == ["task", "read_first", "edit_candidates", "impacted_files", "likely_tests"]
    assert payload["task"] == "fix login bug"
    assert isinstance(payload["read_first"], list)
    assert isinstance(payload["edit_candidates"], list)
    assert isinstance(payload["impacted_files"], list)
    assert isinstance(payload["likely_tests"], list)
    if payload["read_first"]:
        assert list(payload["read_first"][0]) == ["path", "reasons", "score"]


def test_cli_plan_json_is_deterministic(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "api").mkdir()
    (tmp_path / "src" / "api" / "routes.py").write_text("from src.core.service import run\n", encoding="utf-8")
    (tmp_path / "src" / "core").mkdir()
    (tmp_path / "src" / "core" / "service.py").write_text("def run():\n    return True\n", encoding="utf-8")

    first = runner.invoke(app, ["plan", "add api endpoint", str(tmp_path), "--json"])
    second = runner.invoke(app, ["plan", "add api endpoint", str(tmp_path), "--json"])

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert first.stdout == second.stdout


def test_cli_plan_impacted_files_are_derived_from_edit_candidates(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "api").mkdir()
    (tmp_path / "src" / "api" / "routes.py").write_text("from src.core.service import run\n", encoding="utf-8")
    (tmp_path / "src" / "core").mkdir()
    (tmp_path / "src" / "core" / "service.py").write_text("from src.core.repo import load\n\ndef run():\n    return load()\n", encoding="utf-8")
    (tmp_path / "src" / "core" / "repo.py").write_text("def load():\n    return True\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_service.py").write_text("from src.core.service import run\n", encoding="utf-8")

    plan_result = runner.invoke(app, ["plan", "add api endpoint", str(tmp_path), "--json"])

    assert plan_result.exit_code == 0
    payload = json.loads(plan_result.stdout)
    edit_paths = {item["path"] for item in payload["edit_candidates"]}
    impacted_paths = [item["path"] for item in payload["impacted_files"]]

    assert impacted_paths
    assert any(path not in edit_paths for path in impacted_paths)
    assert any(
        reason in {
            "depends on selected edit candidate",
            "neighboring module in dependency graph",
            "appears to be a related test file",
        }
        for item in payload["impacted_files"]
        for reason in item["reasons"]
    )
