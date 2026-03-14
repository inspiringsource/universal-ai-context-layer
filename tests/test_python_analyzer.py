from pathlib import Path

from ai_context_map.analyzers.python_analyzer import PythonAnalyzer


def test_python_analyzer_parses_absolute_and_relative_imports(tmp_path: Path) -> None:
    file_path = tmp_path / "module.py"
    file_path.write_text(
        "import pkg.core\nfrom . import utils\nfrom ..services import api\n",
        encoding="utf-8",
    )

    refs = PythonAnalyzer().analyze(file_path)

    assert any(ref.module == "pkg.core" and ref.level == 0 for ref in refs)
    assert any(ref.level == 1 and ref.names == ["utils"] for ref in refs)
    assert any(ref.module == "services" and ref.level == 2 and ref.names == ["api"] for ref in refs)

