from ai_context_map.config import Config
from ai_context_map.graph.ranking import rank_files
from ai_context_map.models.graph import DependencyEdge, FileNode


def test_ranking_prefers_central_service_module() -> None:
    nodes = {
        "src/main.py": FileNode(
            path="src/main.py", language="python", role="entrypoint"
        ),
        "src/app/service.py": FileNode(
            path="src/app/service.py", language="python", role="business_logic"
        ),
        "src/utils.py": FileNode(
            path="src/utils.py", language="python", role="utility"
        ),
    }
    edges = [
        DependencyEdge(source="src/main.py", target="src/app/service.py"),
        DependencyEdge(source="src/utils.py", target="src/app/service.py"),
    ]

    ranked = rank_files(nodes, edges, Config())

    assert ranked[0].path == "src/app/service.py"
    assert ranked[0].pagerank_score > ranked[1].pagerank_score


def test_ranking_handles_empty_graph() -> None:
    assert rank_files({}, [], Config()) == []


def test_ranking_is_deterministic_for_equal_scores() -> None:
    nodes = {
        "src/a.py": FileNode(path="src/a.py", language="python"),
        "src/b.py": FileNode(path="src/b.py", language="python"),
    }

    ranked = rank_files(nodes, [], Config())

    assert [item.path for item in ranked] == ["src/a.py", "src/b.py"]
