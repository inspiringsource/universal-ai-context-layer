import json

from ai_context_map.graph.ranking import RankedFile
from ai_context_map.memory.models import FileMemory, MemoryLink, RepositoryMemory
from ai_context_map.models.graph import DependencyEdge, FileNode
from ai_context_map.planner import (
    PlannedFile,
    _build_test_candidates,
    _is_test_like_path,
    build_plan_candidates,
    build_impacted_candidates,
    blend_planner_scores,
    render_task_plan,
    render_task_plan_json,
    task_prior_scores,
    task_plan_to_dict,
)


def test_task_prior_scores_match_keywords() -> None:
    nodes = {
        "src/api/auth_routes.py": FileNode(path="src/api/auth_routes.py", language="python", role="api"),
        "src/core/auth.py": FileNode(path="src/core/auth.py", language="python", role="business_logic"),
        "src/core/session_service.py": FileNode(
            path="src/core/session_service.py", language="python", role="business_logic"
        ),
        "src/config/settings.py": FileNode(path="src/config/settings.py", language="python", role="config"),
        "tests/test_auth.py": FileNode(path="tests/test_auth.py", language="python", role="test"),
    }

    scores, reasons = task_prior_scores("fix failing auth test", nodes)

    assert scores["src/api/auth_routes.py"] > 0
    assert scores["src/core/session_service.py"] > 0
    assert scores["tests/test_auth.py"] > 0
    assert "matched task keyword \"auth\"" in reasons["src/api/auth_routes.py"]
    assert "nearby module for test-related task" in reasons["src/core/auth.py"]


def test_blend_planner_scores_uses_weighted_sum() -> None:
    score = blend_planner_scores(structural=0.8, task_prior=1.0, memory=0.5)

    assert score == 0.825


def test_build_plan_candidates_is_deterministic() -> None:
    nodes = {
        "src/a.py": FileNode(path="src/a.py", language="python", role="unknown"),
        "src/b.py": FileNode(path="src/b.py", language="python", role="unknown"),
    }
    ranked = [
        RankedFile(path="src/a.py", score=1.0, reasons=["central in dependency graph"]),
        RankedFile(path="src/b.py", score=1.0, reasons=["central in dependency graph"]),
    ]

    candidates = build_plan_candidates("investigate task", nodes, ranked, RepositoryMemory())

    assert [item.path for item in candidates] == ["src/a.py", "src/b.py"]


def test_build_plan_candidates_blends_memory_and_task_priors() -> None:
    nodes = {
        "src/api/routes.py": FileNode(path="src/api/routes.py", language="python", role="api"),
        "src/core/service.py": FileNode(path="src/core/service.py", language="python", role="business_logic"),
        "tests/test_routes.py": FileNode(path="tests/test_routes.py", language="python", role="test"),
    }
    ranked = [
        RankedFile(path="src/core/service.py", score=9.0, reasons=["central in dependency graph"]),
        RankedFile(path="src/api/routes.py", score=6.0, reasons=["central in dependency graph"]),
        RankedFile(path="tests/test_routes.py", score=1.0, reasons=["role classified as \"test\""]),
    ]
    memory = RepositoryMemory(
        files=[
            FileMemory(
                path="src/api/routes.py",
                related=[MemoryLink(path="src/core/service.py", count=3, weight=0.9)],
            )
        ]
    )

    candidates = build_plan_candidates("add api endpoint", nodes, ranked, memory)

    assert candidates[0].path == "src/api/routes.py"
    assert "matched task keyword \"api\"" in candidates[0].reasons
    service_candidate = next(item for item in candidates if item.path == "src/core/service.py")
    assert any(reason.startswith("frequently co-changed with src/api/routes.py") for reason in service_candidate.reasons)


def test_build_impacted_candidates_uses_selected_edit_candidates_and_reasons() -> None:
    nodes = {
        "src/api/routes.py": FileNode(path="src/api/routes.py", language="python", role="api"),
        "src/main.py": FileNode(path="src/main.py", language="python", role="entrypoint"),
        "src/core/service.py": FileNode(path="src/core/service.py", language="python", role="business_logic"),
        "src/core/repository.py": FileNode(path="src/core/repository.py", language="python", role="storage"),
        "tests/test_service.py": FileNode(path="tests/test_service.py", language="python", role="test"),
    }
    edges = [
        DependencyEdge(source="src/api/routes.py", target="src/core/service.py"),
        DependencyEdge(source="src/main.py", target="src/api/routes.py"),
        DependencyEdge(source="src/core/service.py", target="src/core/repository.py"),
        DependencyEdge(source="tests/test_service.py", target="src/core/service.py"),
    ]
    ranked = [
        RankedFile(path="src/core/service.py", score=10.0, reasons=["central in dependency graph"]),
        RankedFile(path="src/api/routes.py", score=8.0, reasons=["API module"]),
        RankedFile(path="src/core/repository.py", score=6.0, reasons=["central in dependency graph"]),
        RankedFile(path="src/main.py", score=4.0, reasons=["filename suggests entrypoint"]),
        RankedFile(path="tests/test_service.py", score=2.0, reasons=["role classified as \"test\""]),
    ]
    memory = RepositoryMemory(
        files=[
            FileMemory(
                path="src/core/service.py",
                related=[MemoryLink(path="src/api/routes.py", count=3, weight=0.8)],
            )
        ]
    )

    impacted = build_impacted_candidates(
        nodes=nodes,
        edges=edges,
        ranked=ranked,
        edit_candidates=[PlannedFile(path="src/core/service.py", score=1.0, reasons=["selected for editing"])],
        memory=memory,
    )

    impacted_by_path = {item.path: item for item in impacted}
    assert impacted
    assert "src/api/routes.py" in impacted_by_path
    assert "tests/test_service.py" in impacted_by_path
    assert "src/core/repository.py" in impacted_by_path
    assert "depends on selected edit candidate" in impacted_by_path["src/api/routes.py"].reasons
    assert "frequently co-changed with selected file" in impacted_by_path["src/api/routes.py"].reasons
    assert "neighboring module in dependency graph" in impacted_by_path["src/core/repository.py"].reasons
    assert "appears to be a related test file" in impacted_by_path["tests/test_service.py"].reasons


def test_build_impacted_candidates_is_deterministic() -> None:
    nodes = {
        "src/a.py": FileNode(path="src/a.py", language="python", role="business_logic"),
        "src/b.py": FileNode(path="src/b.py", language="python", role="api"),
        "src/c.py": FileNode(path="src/c.py", language="python", role="unknown"),
    }
    edges = [
        DependencyEdge(source="src/b.py", target="src/a.py"),
        DependencyEdge(source="src/a.py", target="src/c.py"),
    ]
    ranked = [
        RankedFile(path="src/a.py", score=10.0, reasons=["central in dependency graph"]),
        RankedFile(path="src/b.py", score=5.0, reasons=["API module"]),
        RankedFile(path="src/c.py", score=5.0, reasons=["central in dependency graph"]),
    ]

    first = build_impacted_candidates(
        nodes=nodes,
        edges=edges,
        ranked=ranked,
        edit_candidates=[PlannedFile(path="src/a.py", score=1.0, reasons=["selected"])],
    )
    second = build_impacted_candidates(
        nodes=nodes,
        edges=edges,
        ranked=ranked,
        edit_candidates=[PlannedFile(path="src/a.py", score=1.0, reasons=["selected"])],
    )

    assert [(item.path, item.score, item.reasons) for item in first] == [
        (item.path, item.score, item.reasons) for item in second
    ]


def test_is_test_like_path_avoids_inspect_false_positive() -> None:
    assert not _is_test_like_path("src/ai_context_map/commands/inspect_cmd.py")
    assert _is_test_like_path("tests/test_cli.py")
    assert _is_test_like_path("src/app/user.spec.ts")


def test_build_test_candidates_excludes_non_test_paths_with_spec_substring() -> None:
    candidates = [
        PlannedFile(
            path="src/ai_context_map/commands/inspect_cmd.py",
            score=0.9,
            reasons=["high PageRank in dependency graph"],
        ),
        PlannedFile(
            path="tests/test_cli.py",
            score=0.5,
            reasons=["high PageRank in dependency graph"],
        ),
    ]

    tests = _build_test_candidates(candidates, edit_candidates=[])

    assert [item.path for item in tests] == ["tests/test_cli.py"]


def test_render_task_plan_outputs_sections() -> None:
    from ai_context_map.planner import TaskPlan, PlannedFile

    text = render_task_plan(
        TaskPlan(
            task="fix login bug",
            read_first=[PlannedFile(path="src/api/auth_routes.py", score=1.0, reasons=["matched task keyword \"auth\""])],
            likely_edit_candidates=[PlannedFile(path="src/core/auth_service.py", score=0.9, reasons=["central in dependency graph"])],
            likely_impacted_files=[PlannedFile(path="src/core/session.py", score=0.7, reasons=["frequently co-changed with src/core/auth_service.py"])],
            likely_tests=[PlannedFile(path="tests/test_auth.py", score=0.5, reasons=["looks like related test file"])],
        )
    )

    assert "Read first:" in text
    assert "Likely edit candidates:" in text
    assert "Likely impacted files:" in text
    assert "Likely tests:" in text
    assert "src/api/auth_routes.py" in text


def test_task_plan_to_dict_has_required_keys_and_file_shape() -> None:
    from ai_context_map.planner import PlannedFile, TaskPlan

    payload = task_plan_to_dict(
        TaskPlan(
            task="fix login bug",
            read_first=[PlannedFile(path="src/api/auth_routes.py", score=1.0, reasons=["matched task keyword \"auth\""])],
            likely_edit_candidates=[PlannedFile(path="src/core/auth_service.py", score=0.9, reasons=["central in dependency graph"])],
            likely_impacted_files=[
                PlannedFile(
                    path="src/core/session.py",
                    score=0.7,
                    reasons=["frequently co-changed with src/core/auth_service.py"],
                )
            ],
            likely_tests=[PlannedFile(path="tests/test_auth.py", score=0.5, reasons=["looks like related test file"])],
        )
    )

    assert list(payload) == ["task", "read_first", "edit_candidates", "impacted_files", "likely_tests"]
    assert payload["task"] == "fix login bug"
    assert payload["read_first"] == [
        {
            "path": "src/api/auth_routes.py",
            "reasons": ['matched task keyword "auth"'],
            "score": 1.0,
        }
    ]
    assert payload["edit_candidates"][0]["path"] == "src/core/auth_service.py"
    assert payload["impacted_files"][0]["path"] == "src/core/session.py"
    assert payload["likely_tests"][0]["path"] == "tests/test_auth.py"


def test_render_task_plan_json_is_deterministic() -> None:
    from ai_context_map.planner import PlannedFile, TaskPlan

    plan = TaskPlan(
        task="fix login bug",
        read_first=[
            PlannedFile(path="src/a.py", score=1.0, reasons=["central in dependency graph"]),
            PlannedFile(path="src/b.py", score=1.0, reasons=["matched task keyword \"login\""]),
        ],
        likely_edit_candidates=[PlannedFile(path="src/c.py", score=0.9, reasons=["central in dependency graph"])],
        likely_impacted_files=[],
        likely_tests=[PlannedFile(path="tests/test_a.py", score=0.4, reasons=["looks like related test file"])],
    )

    first = render_task_plan_json(plan)
    second = render_task_plan_json(plan)

    assert first == second
    assert json.loads(first)["read_first"][0]["path"] == "src/a.py"
