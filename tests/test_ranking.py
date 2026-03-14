from ai_context_map.config import Config
from ai_context_map.graph.ranking import rank_files
from ai_context_map.models.graph import DependencyEdge, FileNode


def test_ranking_prefers_central_service_module() -> None:
    nodes = {
        "src/main.py": FileNode(path="src/main.py", language="python", role="entrypoint"),
        "src/app/service.py": FileNode(path="src/app/service.py", language="python", role="business_logic"),
        "src/utils.py": FileNode(path="src/utils.py", language="python", role="utility"),
    }
    edges = [
        DependencyEdge(source="src/main.py", target="src/app/service.py"),
        DependencyEdge(source="src/utils.py", target="src/app/service.py"),
    ]

    ranked = rank_files(nodes, edges, Config())

    assert ranked[0].path == "src/app/service.py"

