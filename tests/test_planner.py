import json

from ai_context_map.graph.ranking import RankedFile
from ai_context_map.memory.models import FileMemory, MemoryLink, RepositoryMemory
from ai_context_map.models.graph import DependencyEdge, FileNode
from ai_context_map.planner import (
    PlannedFile,
    _build_test_candidates,
    _is_test_like_path,
    _module_key,
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
    assert "auth/security keyword signal" in reasons["src/api/auth_routes.py"]
    assert "nearby module for test-related task" in reasons["src/core/auth.py"]


def test_blend_planner_scores_uses_weighted_sum() -> None:
    score = blend_planner_scores(structural=0.8, task_prior=1.0, memory=0.5)

    assert round(score, 3) == 0.816


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
    assert "task-intent match: api/routing" in candidates[0].reasons
    service_candidate = next(item for item in candidates if item.path == "src/core/service.py")
    assert any(reason.startswith("co-change boost from src/api/routes.py") for reason in service_candidate.reasons)


def test_build_plan_candidates_prioritizes_refactor_utils_and_models() -> None:
    nodes = {
        "src/core/service.py": FileNode(path="src/core/service.py", language="python", role="business_logic"),
        "src/utils/model_utils.py": FileNode(path="src/utils/model_utils.py", language="python", role="utility"),
        "src/models/user_model.py": FileNode(path="src/models/user_model.py", language="python", role="data_model"),
    }
    ranked = [
        RankedFile(path="src/core/service.py", score=9.0, reasons=["central in dependency graph"]),
        RankedFile(path="src/models/user_model.py", score=5.0, reasons=["role classified as \"data_model\""]),
        RankedFile(path="src/utils/model_utils.py", score=4.0, reasons=["role classified as \"utility\""]),
    ]

    candidates = build_plan_candidates("refactor shared utils and models", nodes, ranked, RepositoryMemory())

    assert candidates[0].path in {"src/models/user_model.py", "src/utils/model_utils.py"}
    assert "task-intent match: refactor/shared code" in candidates[0].reasons


def test_build_plan_candidates_prioritizes_cli_packaging_metadata_paths() -> None:
    nodes = {
        "src/ai_context_map/cli.py": FileNode(path="src/ai_context_map/cli.py", language="python", role="entrypoint"),
        "src/ai_context_map/version_metadata.py": FileNode(
            path="src/ai_context_map/version_metadata.py", language="python", role="config"
        ),
        "src/core/service.py": FileNode(path="src/core/service.py", language="python", role="business_logic"),
    }
    ranked = [
        RankedFile(path="src/core/service.py", score=9.0, reasons=["central in dependency graph"]),
        RankedFile(path="src/ai_context_map/cli.py", score=4.0, reasons=["filename suggests entrypoint"]),
        RankedFile(path="src/ai_context_map/version_metadata.py", score=3.0, reasons=["role classified as \"config\""]),
    ]

    candidates = build_plan_candidates("update cli packaging metadata and version", nodes, ranked, RepositoryMemory())

    assert candidates[0].path in {"src/ai_context_map/cli.py", "src/ai_context_map/version_metadata.py"}
    assert any(
        reason in {"task-intent match: cli/packaging/metadata", "metadata/config signal"}
        for reason in candidates[0].reasons
    )


def test_build_plan_candidates_uses_memory_more_for_compatibility_tasks() -> None:
    nodes = {
        "src/api/routes.py": FileNode(path="src/api/routes.py", language="python", role="api"),
        "src/api/compat.py": FileNode(path="src/api/compat.py", language="python", role="api"),
        "src/core/service.py": FileNode(path="src/core/service.py", language="python", role="business_logic"),
    }
    ranked = [
        RankedFile(path="src/core/service.py", score=9.0, reasons=["central in dependency graph"]),
        RankedFile(path="src/api/routes.py", score=7.0, reasons=["API module"]),
        RankedFile(path="src/api/compat.py", score=2.0, reasons=["API module"]),
    ]
    memory = RepositoryMemory(
        files=[
            FileMemory(
                path="src/api/routes.py",
                related=[MemoryLink(path="src/api/compat.py", count=4, weight=0.95)],
            )
        ]
    )

    candidates = build_plan_candidates("maintain routing compatibility for legacy clients", nodes, ranked, memory)

    compat_candidate = next(item for item in candidates if item.path == "src/api/compat.py")
    service_candidate = next(item for item in candidates if item.path == "src/core/service.py")
    assert compat_candidate.score > service_candidate.score
    assert "task-intent match: compatibility/co-change" in compat_candidate.reasons
    assert any(reason.startswith("co-change boost from src/api/routes.py") for reason in compat_candidate.reasons)


def test_build_plan_candidates_restores_structural_api_route_bugfix_priority() -> None:
    nodes = {
        "fastapi/routing.py": FileNode(path="fastapi/routing.py", language="python", role="api"),
        "fastapi/applications.py": FileNode(path="fastapi/applications.py", language="python", role="business_logic"),
        "fastapi/openapi/models.py": FileNode(path="fastapi/openapi/models.py", language="python", role="data_model"),
        "tests/test_extra_routes.py": FileNode(path="tests/test_extra_routes.py", language="python", role="test"),
        "docs_src/response_model/tutorial001.py": FileNode(
            path="docs_src/response_model/tutorial001.py", language="python", role="unknown"
        ),
    }
    ranked = [
        RankedFile(path="fastapi/routing.py", score=11.0, reasons=["central in dependency graph"]),
        RankedFile(path="fastapi/applications.py", score=10.0, reasons=["high PageRank in dependency graph"]),
        RankedFile(path="fastapi/openapi/models.py", score=7.0, reasons=["role classified as \"data_model\""]),
        RankedFile(path="tests/test_extra_routes.py", score=3.0, reasons=["role classified as \"test\""]),
        RankedFile(path="docs_src/response_model/tutorial001.py", score=2.0, reasons=["located in source directory"]),
    ]

    candidates = build_plan_candidates("fix API route bug in router handling", nodes, ranked, RepositoryMemory())

    assert candidates[0].path == "fastapi/routing.py"
    ranked_paths = [item.path for item in candidates]

    assert "fastapi/applications.py" in ranked_paths[:3]
    assert ranked_paths[-1] == "docs_src/response_model/tutorial001.py"


def test_build_plan_candidates_boosts_route_runtime_over_package_noise() -> None:
    nodes = {
        "fastapi/routing.py": FileNode(path="fastapi/routing.py", language="python", role="api"),
        "fastapi/applications.py": FileNode(path="fastapi/applications.py", language="python", role="business_logic"),
        "fastapi/__init__.py": FileNode(path="fastapi/__init__.py", language="python", role="unknown"),
        "fastapi/testclient.py": FileNode(path="fastapi/testclient.py", language="python", role="unknown"),
    }
    ranked = [
        RankedFile(path="fastapi/routing.py", score=10.0, reasons=["central in dependency graph"]),
        RankedFile(path="fastapi/applications.py", score=9.5, reasons=["high PageRank in dependency graph"]),
        RankedFile(path="fastapi/__init__.py", score=9.0, reasons=["central in dependency graph"]),
        RankedFile(path="fastapi/testclient.py", score=8.9, reasons=["central in dependency graph"]),
    ]

    candidates = build_plan_candidates("API route bugfix", nodes, ranked, RepositoryMemory())
    ranked_paths = [item.path for item in candidates]

    assert ranked_paths[:2] == ["fastapi/routing.py", "fastapi/applications.py"]
    assert "route-oriented runtime signal" in candidates[0].reasons


def test_build_plan_candidates_restores_auth_runtime_over_docs_and_tests() -> None:
    nodes = {
        "fastapi/security/oauth2.py": FileNode(path="fastapi/security/oauth2.py", language="python", role="unknown"),
        "fastapi/param_functions.py": FileNode(path="fastapi/param_functions.py", language="python", role="unknown"),
        "tests/test_security_oauth2.py": FileNode(path="tests/test_security_oauth2.py", language="python", role="test"),
        "SECURITY.md": FileNode(path="SECURITY.md", language="markdown", role="unknown"),
    }
    ranked = [
        RankedFile(path="fastapi/param_functions.py", score=10.0, reasons=["central in dependency graph"]),
        RankedFile(path="fastapi/security/oauth2.py", score=8.5, reasons=["high PageRank in dependency graph"]),
        RankedFile(path="tests/test_security_oauth2.py", score=4.0, reasons=["role classified as \"test\""]),
        RankedFile(path="SECURITY.md", score=1.0, reasons=["located in source directory"]),
    ]

    candidates = build_plan_candidates("investigate auth security behavior", nodes, ranked, RepositoryMemory())
    ranked_paths = [item.path for item in candidates]

    assert ranked_paths[:2] == ["fastapi/security/oauth2.py", "fastapi/param_functions.py"]
    assert set(ranked_paths[-2:]) == {"SECURITY.md", "tests/test_security_oauth2.py"}


def test_build_plan_candidates_prioritizes_dependency_specific_tests_over_generic_test_utils() -> None:
    nodes = {
        "fastapi/dependencies/utils.py": FileNode(path="fastapi/dependencies/utils.py", language="python", role="unknown"),
        "fastapi/param_functions.py": FileNode(path="fastapi/param_functions.py", language="python", role="unknown"),
        "tests/test_dependency_overrides.py": FileNode(
            path="tests/test_dependency_overrides.py", language="python", role="test"
        ),
        "tests/test_dependencies_utils.py": FileNode(
            path="tests/test_dependencies_utils.py", language="python", role="test"
        ),
        "tests/utils.py": FileNode(path="tests/utils.py", language="python", role="test"),
    }
    ranked = [
        RankedFile(path="tests/utils.py", score=10.0, reasons=["central in dependency graph"]),
        RankedFile(path="fastapi/dependencies/utils.py", score=7.0, reasons=["central in dependency graph"]),
        RankedFile(path="tests/test_dependencies_utils.py", score=6.5, reasons=["high PageRank in dependency graph"]),
        RankedFile(path="tests/test_dependency_overrides.py", score=6.0, reasons=["high PageRank in dependency graph"]),
        RankedFile(path="fastapi/param_functions.py", score=5.0, reasons=["central in dependency graph"]),
    ]

    candidates = build_plan_candidates("dependency test debug", nodes, ranked, RepositoryMemory())
    ranked_paths = [item.path for item in candidates]

    assert ranked_paths[0] == "tests/test_dependencies_utils.py"
    assert ranked_paths.index("tests/test_dependencies_utils.py") < ranked_paths.index("tests/utils.py")
    assert "fastapi/dependencies/utils.py" in ranked_paths[:4]


def test_build_plan_candidates_keeps_response_model_test_debug_runtime_files_visible() -> None:
    nodes = {
        "fastapi/routing.py": FileNode(path="fastapi/routing.py", language="python", role="api"),
        "fastapi/utils.py": FileNode(path="fastapi/utils.py", language="python", role="utility"),
        "fastapi/openapi/models.py": FileNode(path="fastapi/openapi/models.py", language="python", role="data_model"),
        "tests/test_response_model_data_filter.py": FileNode(
            path="tests/test_response_model_data_filter.py", language="python", role="test"
        ),
        "docs_src/response_model/tutorial001.py": FileNode(
            path="docs_src/response_model/tutorial001.py", language="python", role="unknown"
        ),
    }
    ranked = [
        RankedFile(path="fastapi/routing.py", score=10.0, reasons=["central in dependency graph"]),
        RankedFile(path="fastapi/openapi/models.py", score=8.0, reasons=["role classified as \"data_model\""]),
        RankedFile(path="fastapi/utils.py", score=7.0, reasons=["high PageRank in dependency graph"]),
        RankedFile(path="tests/test_response_model_data_filter.py", score=3.5, reasons=["role classified as \"test\""]),
        RankedFile(path="docs_src/response_model/tutorial001.py", score=2.0, reasons=["located in source directory"]),
    ]

    candidates = build_plan_candidates("debug failing response model test", nodes, ranked, RepositoryMemory())
    ranked_paths = [item.path for item in candidates]

    assert "tests/test_response_model_data_filter.py" in ranked_paths[:3]
    assert "fastapi/routing.py" in ranked_paths[:4]
    assert ranked_paths.index("docs_src/response_model/tutorial001.py") > ranked_paths.index("fastapi/routing.py")


def test_build_plan_candidates_boosts_response_model_runtime_and_matching_tests() -> None:
    nodes = {
        "fastapi/routing.py": FileNode(path="fastapi/routing.py", language="python", role="api"),
        "fastapi/openapi/models.py": FileNode(path="fastapi/openapi/models.py", language="python", role="data_model"),
        "fastapi/utils.py": FileNode(path="fastapi/utils.py", language="python", role="utility"),
        "tests/test_response_model_invalid.py": FileNode(
            path="tests/test_response_model_invalid.py", language="python", role="test"
        ),
        "tests/test_openapi_schema_type.py": FileNode(
            path="tests/test_openapi_schema_type.py", language="python", role="test"
        ),
    }
    ranked = [
        RankedFile(path="fastapi/utils.py", score=9.0, reasons=["central in dependency graph"]),
        RankedFile(path="fastapi/routing.py", score=8.5, reasons=["central in dependency graph"]),
        RankedFile(path="fastapi/openapi/models.py", score=8.0, reasons=["role classified as \"data_model\""]),
        RankedFile(path="tests/test_openapi_schema_type.py", score=6.5, reasons=["high PageRank in dependency graph"]),
        RankedFile(path="tests/test_response_model_invalid.py", score=6.0, reasons=["high PageRank in dependency graph"]),
    ]

    candidates = build_plan_candidates("response model test debug", nodes, ranked, RepositoryMemory())
    ranked_paths = [item.path for item in candidates]

    assert "fastapi/routing.py" in ranked_paths[:3]
    assert "fastapi/openapi/models.py" in ranked_paths[:3]
    assert ranked_paths.index("tests/test_response_model_invalid.py") < ranked_paths.index("tests/test_openapi_schema_type.py")


def test_build_plan_candidates_auth_security_surfaces_dependency_helpers() -> None:
    nodes = {
        "fastapi/security/oauth2.py": FileNode(path="fastapi/security/oauth2.py", language="python", role="unknown"),
        "fastapi/param_functions.py": FileNode(path="fastapi/param_functions.py", language="python", role="unknown"),
        "fastapi/dependencies/utils.py": FileNode(path="fastapi/dependencies/utils.py", language="python", role="unknown"),
        "tests/test_security_oauth2.py": FileNode(path="tests/test_security_oauth2.py", language="python", role="test"),
        "SECURITY.md": FileNode(path="SECURITY.md", language="markdown", role="unknown"),
    }
    ranked = [
        RankedFile(path="fastapi/security/oauth2.py", score=8.5, reasons=["high PageRank in dependency graph"]),
        RankedFile(path="fastapi/param_functions.py", score=8.0, reasons=["central in dependency graph"]),
        RankedFile(path="fastapi/dependencies/utils.py", score=7.5, reasons=["central in dependency graph"]),
        RankedFile(path="tests/test_security_oauth2.py", score=6.0, reasons=["high PageRank in dependency graph"]),
        RankedFile(path="SECURITY.md", score=1.0, reasons=["located in source directory"]),
    ]

    candidates = build_plan_candidates("auth/security intent", nodes, ranked, RepositoryMemory())
    ranked_paths = [item.path for item in candidates]

    assert ranked_paths[:3] == [
        "fastapi/security/oauth2.py",
        "fastapi/param_functions.py",
        "fastapi/dependencies/utils.py",
    ]


def test_build_plan_candidates_recognizes_authentication_authorization_synonyms() -> None:
    nodes = {
        "src/security/token_service.py": FileNode(
            path="src/security/token_service.py", language="python", role="business_logic"
        ),
        "src/api/dependency_provider.py": FileNode(
            path="src/api/dependency_provider.py", language="python", role="api"
        ),
        "src/domain/user_profile.py": FileNode(
            path="src/domain/user_profile.py", language="python", role="data_model"
        ),
        "docs/security.md": FileNode(path="docs/security.md", language="markdown", role="unknown"),
    }
    ranked = [
        RankedFile(path="src/domain/user_profile.py", score=9.0, reasons=["central in dependency graph"]),
        RankedFile(path="src/security/token_service.py", score=7.5, reasons=["high PageRank in dependency graph"]),
        RankedFile(path="src/api/dependency_provider.py", score=7.0, reasons=["API module"]),
        RankedFile(path="docs/security.md", score=1.0, reasons=["located in source directory"]),
    ]

    candidates = build_plan_candidates(
        "debug bearer token authentication authorization scope handling",
        nodes,
        ranked,
        RepositoryMemory(),
    )
    ranked_paths = [item.path for item in candidates]

    assert ranked_paths[:2] == [
        "src/security/token_service.py",
        "src/api/dependency_provider.py",
    ]
    assert ranked_paths[-1] == "docs/security.md"


def test_task_prior_scores_auth_security_does_not_boost_generic_user_modules() -> None:
    nodes = {
        "src/domain/user_profile.py": FileNode(
            path="src/domain/user_profile.py", language="python", role="data_model"
        ),
        "src/config/settings.py": FileNode(path="src/config/settings.py", language="python", role="config"),
        "src/security/token_service.py": FileNode(
            path="src/security/token_service.py", language="python", role="business_logic"
        ),
    }

    scores, reasons = task_prior_scores("fix authentication bearer token bug", nodes)

    assert scores["src/security/token_service.py"] > scores["src/domain/user_profile.py"]
    assert scores["src/security/token_service.py"] > scores["src/config/settings.py"]
    assert "auth/security keyword signal" in reasons["src/security/token_service.py"]
    assert "auth/security keyword signal" not in reasons.get("src/domain/user_profile.py", [])
    assert "auth/security keyword signal" not in reasons.get("src/config/settings.py", [])


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

    tests = _build_test_candidates("inspect command", candidates, edit_candidates=[])

    assert [item.path for item in tests] == ["tests/test_cli.py"]


def test_task_prior_scores_does_not_treat_testclient_as_a_test_file() -> None:
    nodes = {
        "fastapi/testclient.py": FileNode(path="fastapi/testclient.py", language="python", role="unknown"),
        "tests/test_client.py": FileNode(path="tests/test_client.py", language="python", role="test"),
    }

    scores, reasons = task_prior_scores("debug failing dependency test", nodes)

    assert "test relevance" not in reasons.get("fastapi/testclient.py", [])
    assert "test relevance" in reasons["tests/test_client.py"]
    assert scores["tests/test_client.py"] > scores["fastapi/testclient.py"]


def test_module_key_ignores_init_files() -> None:
    assert _module_key("fastapi/__init__.py") == ""
    assert _module_key("tests/test_auth.py") == "auth"


def test_render_task_plan_outputs_sections() -> None:
    from ai_context_map.planner import TaskPlan, PlannedFile

    text = render_task_plan(
        TaskPlan(
            task="fix login bug",
            read_first=[PlannedFile(path="src/api/auth_routes.py", score=1.0, reasons=["auth/security keyword signal"])],
            likely_edit_candidates=[PlannedFile(path="src/core/auth_service.py", score=0.9, reasons=["central in dependency graph"])],
            likely_impacted_files=[PlannedFile(path="src/core/session.py", score=0.7, reasons=["co-change boost from src/core/auth_service.py"])],
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
            read_first=[PlannedFile(path="src/api/auth_routes.py", score=1.0, reasons=["auth/security keyword signal"])],
            likely_edit_candidates=[PlannedFile(path="src/core/auth_service.py", score=0.9, reasons=["central in dependency graph"])],
            likely_impacted_files=[
                PlannedFile(
                    path="src/core/session.py",
                    score=0.7,
                    reasons=["co-change boost from src/core/auth_service.py"],
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
            "reasons": ["auth/security keyword signal"],
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
            PlannedFile(path="src/b.py", score=1.0, reasons=["auth/security keyword signal"]),
        ],
        likely_edit_candidates=[PlannedFile(path="src/c.py", score=0.9, reasons=["central in dependency graph"])],
        likely_impacted_files=[],
        likely_tests=[PlannedFile(path="tests/test_a.py", score=0.4, reasons=["looks like related test file"])],
    )

    first = render_task_plan_json(plan)
    second = render_task_plan_json(plan)

    assert first == second
    assert json.loads(first)["read_first"][0]["path"] == "src/a.py"
