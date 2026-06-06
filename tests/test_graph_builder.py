from pathlib import Path

from ai_context_map.config import Config
from ai_context_map.graph.builder import GraphBuilder
from ai_context_map.scanner.walker import scan_repository


def test_graph_builder_resolves_local_python_imports(tmp_path: Path) -> None:
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    (tmp_path / "src" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "pkg" / "service.py").write_text(
        "VALUE = 1\n", encoding="utf-8"
    )
    (tmp_path / "src" / "main.py").write_text(
        "from pkg import service\n", encoding="utf-8"
    )

    scan_result = scan_repository(tmp_path, Config())
    _nodes, edges = GraphBuilder().build(scan_result)

    assert any(
        edge.source == "src/main.py" and edge.target == "src/pkg/service.py"
        for edge in edges
    )
