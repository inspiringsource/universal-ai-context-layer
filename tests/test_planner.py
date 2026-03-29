from pathlib import Path

import yaml

from ai_context_map.models.memory import (
    CentralFile,
    ClusterSeed,
    RepositoryMemoryDocument,
    RepositoryZone,
    TaskRoutePrior,
    TestMapping,
)
from ai_context_map.navigation.planner import load_task_plan, plan_task


def _context_document() -> dict:
    return {
        "architecture": {
            "core_modules": [
                {"path": "src/core/service.py", "score": 11.0, "reasons": ["located in core/service module"]},
                {"path": "src/api/routes.py", "score": 9.0, "reasons": ["contains route handlers"]},
                {"path": "src/config/settings.py", "score": 7.0, "reasons": ["configuration entrypoint"]},
            ]
        },
        "navigation_map": {
            "key_files": [
                {"path": "src/api/routes.py", "role": "api", "importance": "critical"},
                {"path": "src/core/service.py", "role": "business_logic", "importance": "high"},
                {"path": "src/config/settings.py", "role": "config", "importance": "high"},
            ]
        },
        "hotspots": [
            {"path": "src/core/service.py", "reason": "high dependency centrality"},
        ],
        "anchors": [{"file": "src/api/routes.py", "symbol": "list_items", "symbol_type": "route_handler"}],
        "task_routes": {
            "api_change": [{"path": "src/api/routes.py", "reasons": ["contains route handlers", "API module"]}],
            "model_or_logic_change": [
                {"path": "src/core/service.py", "reasons": ["located in core/service module"]}
            ],
            "config_change": [{"path": "src/config/settings.py", "reasons": ["configuration entrypoint"]}],
            "test_work": [{"path": "tests/test_routes.py", "reasons": ["test file"]}],
        },
    }


def _memory_document() -> RepositoryMemoryDocument:
    return RepositoryMemoryDocument(
        memory_version=1,
        repository_zones=[
            RepositoryZone(name="api", paths=["src/api/routes.py"]),
            RepositoryZone(name="service", paths=["src/core/service.py"]),
            RepositoryZone(name="config", paths=["src/config/settings.py"]),
        ],
        cluster_seeds=[
            ClusterSeed(
                label="src/api/routes.py",
                files=["src/api/routes.py", "src/core/service.py", "tests/test_routes.py"],
                signals=["graph_neighbors", "test_association"],
            ),
            ClusterSeed(
                label="src/config/settings.py",
                files=["src/config/settings.py"],
                signals=["directory_similarity"],
            ),
        ],
        test_mappings=[
            TestMapping(implementation="src/api/routes.py", tests=["tests/test_routes.py"]),
            TestMapping(implementation="src/core/service.py", tests=["tests/test_service.py"]),
        ],
        central_files=[
            CentralFile(path="src/api/routes.py", score=9.0, reasons=["API module"]),
            CentralFile(path="src/core/service.py", score=11.0, reasons=["central in dependency graph"]),
        ],
        task_route_priors=[
            TaskRoutePrior(category="api_change", files=["src/api/routes.py"]),
            TaskRoutePrior(category="config_change", files=["src/config/settings.py"]),
        ],
    )


def test_planner_consults_memory_first_before_refinement() -> None:
    plan = plan_task("update the api route handler", _context_document(), _memory_document())

    assert plan.read_first[0].path == "src/api/routes.py"
    assert "matched repository zone \"api\"" in plan.read_first[0].reasons
    assert "selected from memory cluster" in plan.read_first[0].reasons
    assert plan.working_cluster[0].path == "src/api/routes.py"


def test_relevant_zones_and_clusters_influence_shortlist() -> None:
    plan = plan_task("change the api response route", _context_document(), _memory_document())

    read_paths = [item.path for item in plan.read_first]
    edit_paths = [item.path for item in plan.edit_candidates]
    assert "src/api/routes.py" in read_paths
    assert "src/core/service.py" in read_paths
    assert "src/api/routes.py" in edit_paths
    assert "src/config/settings.py" not in edit_paths


def test_test_mappings_improve_likely_tests() -> None:
    plan = plan_task("update api route behavior", _context_document(), _memory_document())

    assert plan.likely_tests[0].path == "tests/test_routes.py"
    assert "related test mapping" in plan.likely_tests[0].reasons


def test_working_cluster_forms_from_memory_signals() -> None:
    plan = plan_task("update api route behavior", _context_document(), _memory_document())

    assert [item.path for item in plan.working_cluster] == [
        "src/api/routes.py",
        "src/core/service.py",
        "tests/test_routes.py",
    ]
    assert "primary file in working cluster" in plan.working_cluster[0].reasons
    assert "neighboring file in working cluster" in plan.working_cluster[1].reasons


def test_cluster_aware_planning_improves_impacted_files() -> None:
    plan = plan_task("update api route behavior", _context_document(), _memory_document())

    impacted_paths = [item.path for item in plan.impacted_files]
    assert "src/core/service.py" in impacted_paths
    assert "tests/test_routes.py" in impacted_paths


def test_fallback_behavior_still_works_without_memory() -> None:
    plan = plan_task("change configuration settings", _context_document(), None)

    assert plan.read_first[0].path == "src/config/settings.py"
    assert plan.edit_candidates[0].path == "src/config/settings.py"
    assert plan.working_cluster == []


def test_planner_ordering_is_deterministic_for_equal_scores() -> None:
    context = {
        "architecture": {"core_modules": [{"path": "src/a.py"}, {"path": "src/b.py"}]},
        "navigation_map": {"key_files": []},
        "hotspots": [],
        "anchors": [],
        "task_routes": {"feature_work": [{"path": "src/a.py", "reasons": []}, {"path": "src/b.py", "reasons": []}]},
    }
    memory = RepositoryMemoryDocument(
        memory_version=1,
        repository_zones=[RepositoryZone(name="other", paths=["src/a.py", "src/b.py"])],
        cluster_seeds=[],
        test_mappings=[],
        central_files=[],
        task_route_priors=[TaskRoutePrior(category="feature_work", files=["src/a.py", "src/b.py"])],
    )

    plan = plan_task("implement feature", context, memory)

    assert [item.path for item in plan.read_first[:2]] == ["src/a.py", "src/b.py"]
    assert [item.path for item in plan.edit_candidates[:2]] == ["src/a.py", "src/b.py"]
    assert plan.working_cluster == []


def test_load_task_plan_reads_context_and_memory_files(tmp_path: Path) -> None:
    ai_dir = tmp_path / ".ai"
    ai_dir.mkdir()
    (ai_dir / "context.yaml").write_text(yaml.safe_dump(_context_document(), sort_keys=False), encoding="utf-8")
    memory = _memory_document()
    (ai_dir / "memory.yaml").write_text(
        yaml.safe_dump(
            {
                "memory_version": memory.memory_version,
                "repository_zones": [{"name": item.name, "paths": item.paths} for item in memory.repository_zones],
                "cluster_seeds": [
                    {"label": item.label, "files": item.files, "signals": item.signals}
                    for item in memory.cluster_seeds
                ],
                "test_mappings": [
                    {"implementation": item.implementation, "tests": item.tests}
                    for item in memory.test_mappings
                ],
                "central_files": [
                    {"path": item.path, "score": item.score, "reasons": item.reasons}
                    for item in memory.central_files
                ],
                "task_route_priors": [
                    {"category": item.category, "files": item.files}
                    for item in memory.task_route_priors
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    plan = load_task_plan(tmp_path, "update api route behavior")

    assert plan.read_first[0].path == "src/api/routes.py"
