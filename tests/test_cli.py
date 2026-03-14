from pathlib import Path

from typer.testing import CliRunner

from ai_context_map.cli import app


runner = CliRunner()


def test_cli_init_and_generate(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")

    init_result = runner.invoke(app, ["init", str(tmp_path)])
    assert init_result.exit_code == 0
    assert (tmp_path / ".aicontext.toml").exists()
    assert (tmp_path / ".ai" / "history.yaml").exists()

    generate_result = runner.invoke(app, ["generate", str(tmp_path)])
    assert generate_result.exit_code == 0
    assert (tmp_path / ".ai" / "context.yaml").exists()
    assert "Project:" in generate_result.stdout
