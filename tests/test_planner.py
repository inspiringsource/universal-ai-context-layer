from ai_context_map.graph.ranking import RankedFile
from ai_context_map.memory.models import FileMemory, MemoryLink, RepositoryMemory
from ai_context_map.models.graph import FileNode
from ai_context_map.planner import (
    build_plan_candidates,
    blend_planner_scores,
    render_task_plan,
    task_prior_scores,
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
