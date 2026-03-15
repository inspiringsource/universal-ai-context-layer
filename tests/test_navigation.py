from pathlib import Path

from ai_context_map.config import Config
from ai_context_map.graph.ranking import RankedFile, rank_files
from ai_context_map.models.graph import DependencyEdge, FileNode
from ai_context_map.navigation.anchors import build_anchors
from ai_context_map.navigation.routes import build_task_routes


def test_anchor_generation_uses_top_ranked_python_files(tmp_path: Path) -> None:
    app_dir = tmp_path / "src" / "api"
    app_dir.mkdir(parents=True)
    file_path = app_dir / "routes.py"
    file_path.write_text(
        "\n".join(
            [
                "from fastapi import FastAPI",
                "app = FastAPI()",
                "@app.get('/items')",
                "def list_items():",
                "    return []",
            ]
        ),
        encoding="utf-8",
    )
    nodes = {
        "src/api/routes.py": FileNode(path="src/api/routes.py", language="python", role="api"),
        "tests/test_routes.py": FileNode(path="tests/test_routes.py", language="python", role="test"),
    }
    ranked = [
        RankedFile(path="src/api/routes.py", score=10.0, reasons=["contains route handlers"]),
        RankedFile(path="tests/test_routes.py", score=9.0, reasons=["test file"]),
    ]

    anchors = build_anchors(tmp_path, nodes, ranked)

    assert len(anchors) == 2
    assert anchors[0].file == "src/api/routes.py"
    assert anchors[0].symbol_type == "entrypoint"
    assert any(anchor.symbol_type == "route_handler" for anchor in anchors)


def test_task_routes_prioritize_api_logic_and_tests() -> None:
    nodes = {
        "src/main.py": FileNode(path="src/main.py", language="python", role="entrypoint"),
        "src/api/routes.py": FileNode(path="src/api/routes.py", language="python", role="api"),
        "src/core/service.py": FileNode(path="src/core/service.py", language="python", role="business_logic"),
        "tests/test_service.py": FileNode(path="tests/test_service.py", language="python", role="test"),
    }
    edges = [
        DependencyEdge(source="src/main.py", target="src/api/routes.py"),
        DependencyEdge(source="src/api/routes.py", target="src/core/service.py"),
        DependencyEdge(source="tests/test_service.py", target="src/core/service.py"),
    ]
    ranked = [
        RankedFile(path="src/core/service.py", score=11.0, reasons=["located in core/service module"]),
        RankedFile(path="src/api/routes.py", score=10.0, reasons=["contains route handlers"]),
        RankedFile(path="src/main.py", score=8.0, reasons=["filename suggests entrypoint"]),
        RankedFile(path="tests/test_service.py", score=5.0, reasons=["test file"]),
    ]

    routes = build_task_routes(nodes, edges, ranked)

    assert routes["api_change"][0].path == "src/api/routes.py"
    assert routes["model_or_logic_change"][0].path == "src/core/service.py"
    assert routes["test_work"][0].path == "tests/test_service.py"
    assert any(item.path == "src/core/service.py" for item in routes["test_work"])


def test_ranking_adds_graph_reasons_and_deprioritizes_tests() -> None:
    nodes = {
        "src/api/routes.py": FileNode(path="src/api/routes.py", language="python", role="api"),
        "src/core/service.py": FileNode(path="src/core/service.py", language="python", role="business_logic"),
        "tests/test_service.py": FileNode(path="tests/test_service.py", language="python", role="test"),
    }
    edges = [
        DependencyEdge(source="src/api/routes.py", target="src/core/service.py"),
        DependencyEdge(source="tests/test_service.py", target="src/core/service.py"),
    ]

    ranked = rank_files(nodes, edges, Config())
    service = next(item for item in ranked if item.path == "src/core/service.py")
    test_file = next(item for item in ranked if item.path == "tests/test_service.py")

    assert service.in_degree == 2
    assert "central in dependency graph" in service.reasons
    assert "imported by API layer" in service.reasons
    assert ranked[0].path == "src/core/service.py"
    assert test_file.score < service.score
