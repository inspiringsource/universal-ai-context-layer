from pathlib import Path

from ai_context_map.config import Config
from ai_context_map.scanner.walker import scan_repository


def test_scanner_ignores_common_dirs(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('x')\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("export {}\n", encoding="utf-8")

    result = scan_repository(tmp_path, Config())

    paths = [item.relative_path for item in result.files]
    assert "src/app.py" in paths
    assert "node_modules/x.js" not in paths
