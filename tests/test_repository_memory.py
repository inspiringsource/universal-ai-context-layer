from pathlib import Path

from ai_context_map.graph.ranking import RankedFile
from ai_context_map.models.context import TaskRouteFile
from ai_context_map.models.graph import DependencyEdge, FileNode
from ai_context_map.models.memory import (
    CentralFile,
    ClusterSeed,
    RepositoryMemoryDocument,
    RepositoryZone,
    TaskRoutePrior,
    TestMapping,
)
from ai_context_map.models.repo import RepositoryFile, ScanResult
from ai_context_map.repository_memory import (
    build_repository_memory,
    classify_repository_zone,
    detect_test_mappings,
    generate_cluster_seeds,
)


def _repo_file(relative_path: str) -> RepositoryFile:
    return RepositoryFile(
        path=Path("/repo") / relative_path,
        relative_path=relative_path,
        language="python",
        extension=".py",
        is_source=True,
        size_bytes=100,
    )


def test_classify_repository_zone() -> None:
    assert classify_repository_zone("src/api/routes.py") == "api"
    assert classify_repository_zone("config/settings.py") == "config"
    assert classify_repository_zone("src/core/engine.py") == "core"
    assert classify_repository_zone("src/services/payment_service.py") == "service"
    assert classify_repository_zone("tests/test_routes.py") == "tests"
    assert classify_repository_zone("src/utils/helpers.py") == "utils"
    assert classify_repository_zone("src/cli/main.py") == "cli"
    assert classify_repository_zone("src/models/schema.py") == "models_schema"


def test_detect_test_mappings_uses_conventions_and_is_deterministic() -> None:
    files = [
        _repo_file("src/api/routes.py"),
        _repo_file("src/services/service.py"),
        _repo_file("src/foo.py"),
        _repo_file("tests/src/api/test_routes.py"),
        _repo_file("tests/test_service.py"),
        _repo_file("test_foo.py"),
    ]

    mappings = detect_test_mappings(files)

    assert mappings == [
        TestMapping(implementation="src/api/routes.py", tests=["tests/src/api/test_routes.py"]),
        TestMapping(implementation="src/foo.py", tests=["test_foo.py"]),
        TestMapping(implementation="src/services/service.py", tests=["tests/test_service.py"]),
    ]


def test_generate_cluster_seeds_uses_graph_tests_and_similarity() -> None:
    nodes = {
        "src/api/routes.py": FileNode(path="src/api/routes.py", language="python", role="api"),
        "src/services/service.py": FileNode(path="src/services/service.py", language="python", role="business_logic"),
        "src/services/helpers.py": FileNode(path="src/services/helpers.py", language="python", role="business_logic"),
        "src/models/user.py": FileNode(path="src/models/user.py", language="python", role="data_model"),
        "tests/test_service.py": FileNode(path="tests/test_service.py", language="python", role="test"),
    }
    edges = [
        DependencyEdge(source="src/api/routes.py", target="src/services/service.py"),
        DependencyEdge(source="src/services/service.py", target="src/models/user.py"),
    ]
    ranked = [
        RankedFile(path="src/services/service.py", score=9.2, reasons=["central in dependency graph"]),
        RankedFile(path="src/api/routes.py", score=8.0, reasons=["API module"]),
        RankedFile(path="src/services/helpers.py", score=4.5, reasons=["located in core/service module"]),
        RankedFile(path="src/models/user.py", score=4.0, reasons=["role classified as \"data_model\""]),
        RankedFile(path="tests/test_service.py", score=2.0, reasons=["test file"]),
    ]
    test_mappings = [
        TestMapping(implementation="src/services/service.py", tests=["tests/test_service.py"])
    ]

    seeds = generate_cluster_seeds(nodes, edges, ranked, test_mappings)

    service_seed = next(item for item in seeds if item.label == "src/services/service.py")
    assert service_seed.files == [
        "src/api/routes.py",
        "src/models/user.py",
        "src/services/helpers.py",
        "src/services/service.py",
        "tests/test_service.py",
    ]
    assert service_seed.signals == [
        "graph_neighbors",
        "test_association",
        "directory_similarity",
        "role_similarity",
    ]
    assert seeds == sorted(seeds, key=lambda item: item.label)


def test_build_repository_memory_collects_new_memory_signals() -> None:
    scan_result = ScanResult(
        root=Path("/repo"),
        files=[
            _repo_file("src/api/routes.py"),
            _repo_file("src/services/service.py"),
            _repo_file("src/models/user.py"),
            _repo_file("tests/test_service.py"),
        ],
        languages={"python"},
    )
    nodes = {
        "src/api/routes.py": FileNode(path="src/api/routes.py", language="python", role="api"),
        "src/services/service.py": FileNode(path="src/services/service.py", language="python", role="business_logic"),
        "src/models/user.py": FileNode(path="src/models/user.py", language="python", role="data_model"),
        "tests/test_service.py": FileNode(path="tests/test_service.py", language="python", role="test"),
    }
    edges = [
        DependencyEdge(source="src/api/routes.py", target="src/services/service.py"),
        DependencyEdge(source="src/services/service.py", target="src/models/user.py"),
    ]
    ranked = [
        RankedFile(path="src/services/service.py", score=9.2, reasons=["central in dependency graph"]),
        RankedFile(path="src/api/routes.py", score=8.0, reasons=["API module"]),
        RankedFile(path="src/models/user.py", score=4.0, reasons=["role classified as \"data_model\""]),
        RankedFile(path="tests/test_service.py", score=2.0, reasons=["test file"]),
    ]
    task_routes = {
        "api_change": [TaskRouteFile(path="src/api/routes.py", reasons=["API module"])],
        "test_work": [TaskRouteFile(path="tests/test_service.py", reasons=["test file"])],
    }

    document = build_repository_memory(scan_result, nodes, edges, ranked, task_routes)

    assert [zone.name for zone in document.repository_zones] == ["api", "service", "tests", "models_schema"]
    assert document.test_mappings == [
        TestMapping(implementation="src/services/service.py", tests=["tests/test_service.py"])
    ]
    assert document.central_files[:2] == [
        CentralFile(path="src/services/service.py", score=9.2, reasons=["central in dependency graph"]),
        CentralFile(path="src/api/routes.py", score=8.0, reasons=["API module"]),
    ]
    assert document.task_route_priors == [
        TaskRoutePrior(category="api_change", files=["src/api/routes.py"]),
        TaskRoutePrior(category="test_work", files=["tests/test_service.py"]),
    ]


def test_repository_memory_document_round_trip(tmp_path: Path) -> None:
    from ai_context_map.emitter.yaml_writer import read_memory_yaml, write_memory_yaml

    output = tmp_path / ".ai" / "memory.yaml"
    document = RepositoryMemoryDocument(
        memory_version=1,
        repository_zones=[RepositoryZone(name="api", paths=["src/api/routes.py"])],
        cluster_seeds=[
            ClusterSeed(
                label="src/services/service.py",
                files=["src/api/routes.py", "src/services/service.py"],
                signals=["graph_neighbors"],
            )
        ],
        test_mappings=[TestMapping(implementation="src/services/service.py", tests=["tests/test_service.py"])],
        central_files=[CentralFile(path="src/services/service.py", score=9.2, reasons=["central in dependency graph"])],
        task_route_priors=[TaskRoutePrior(category="api_change", files=["src/api/routes.py"])],
    )

    write_memory_yaml(document, output)
    loaded = read_memory_yaml(output)

    assert loaded == document
