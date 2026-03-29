from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from ai_context_map.emitter.yaml_writer import read_memory_yaml
from ai_context_map.models.memory import RepositoryMemoryDocument
from ai_context_map.models.planning import PlannedFile, TaskPlan


TASK_CATEGORY_KEYWORDS = {
    "bugfix": {"bug", "debug", "error", "fail", "failure", "fix"},
    "feature_work": {"add", "build", "feature", "implement", "support"},
    "api_change": {"api", "endpoint", "handler", "http", "request", "response", "route", "router"},
    "model_or_logic_change": {"algorithm", "core", "domain", "logic", "model", "schema", "service"},
    "config_change": {"config", "configuration", "env", "setting", "settings", "toml", "yaml"},
    "test_work": {"integration", "pytest", "spec", "test", "tests", "unit"},
}

ZONE_KEYWORDS = {
    "api": {"api", "endpoint", "route", "router"},
    "config": {"config", "configuration", "env", "setting", "settings", "toml", "yaml"},
    "core": {"core", "domain", "logic"},
    "service": {"service", "services"},
    "tests": {"integration", "pytest", "spec", "test", "tests", "unit"},
    "utils": {"helper", "helpers", "util", "utils"},
    "cli": {"cli", "command", "commands", "terminal"},
    "models_schema": {"dto", "entity", "model", "models", "schema"},
}

IMPORTANCE_SCORES = {"critical": 3.0, "high": 2.0, "medium": 1.0}


def plan_task(task: str, context: dict[str, Any], memory: RepositoryMemoryDocument | None = None) -> TaskPlan:
    tokens = _tokenize(task)
    categories = _detect_categories(tokens)
    zones = _detect_zones(tokens, categories)
    known_paths = _collect_known_paths(context, memory)

    stage_one_scores: dict[str, float] = defaultdict(float)
    stage_one_reasons: dict[str, list[str]] = defaultdict(list)
    narrowed_region: set[str] = set()

    if memory is not None:
        _apply_memory_stage(task, tokens, categories, zones, memory, stage_one_scores, stage_one_reasons)
        narrowed_region = {path for path, score in stage_one_scores.items() if score > 0}

    candidate_paths = narrowed_region or set(known_paths)
    working_cluster = _build_working_cluster(
        task,
        tokens,
        zones,
        context,
        memory,
        candidate_paths,
        stage_one_scores,
        stage_one_reasons,
    )
    final_scores = {
        "read_first": defaultdict(float),
        "edit_candidates": defaultdict(float),
        "impacted_files": defaultdict(float),
        "likely_tests": defaultdict(float),
    }
    final_reasons: dict[str, list[str]] = defaultdict(list)

    for path, reasons in stage_one_reasons.items():
        if path not in candidate_paths and not _is_test_path(path):
            continue
        for reason in reasons:
            _add_reason(final_reasons[path], reason)

    _apply_context_refinement(context, candidate_paths, categories, final_scores, final_reasons)
    _apply_memory_refinement(memory, candidate_paths, final_scores, final_reasons, working_cluster)
    _apply_working_cluster_influence(working_cluster, final_scores, final_reasons)

    if not narrowed_region:
        _apply_fallback_scores(context, categories, final_scores, final_reasons)

    return TaskPlan(
        read_first=_rank_section(candidate_paths, final_scores["read_first"], final_reasons, allow_tests=True),
        edit_candidates=_rank_section(candidate_paths, final_scores["edit_candidates"], final_reasons, allow_tests=False),
        impacted_files=_rank_section(candidate_paths, final_scores["impacted_files"], final_reasons, allow_tests=True),
        likely_tests=_rank_section(candidate_paths, final_scores["likely_tests"], final_reasons, allow_tests=True, tests_only=True),
        working_cluster=working_cluster,
    )


def load_task_plan(root: Path, task: str) -> TaskPlan:
    from ai_context_map.commands.inspect_cmd import inspect_context

    context = inspect_context(root)
    memory_path = root / ".ai" / "memory.yaml"
    memory = read_memory_yaml(memory_path) if memory_path.exists() else None
    return plan_task(task, context, memory)


def _apply_memory_stage(
    task: str,
    tokens: set[str],
    categories: set[str],
    zones: set[str],
    memory: RepositoryMemoryDocument,
    scores: dict[str, float],
    reasons: dict[str, list[str]],
) -> None:
    for zone in memory.repository_zones:
        if zone.name not in zones:
            continue
        for path in zone.paths:
            scores[path] += 3.0
            _add_reason(reasons[path], f'matched repository zone "{zone.name}"')

    for prior in memory.task_route_priors:
        if prior.category not in categories:
            continue
        for path in prior.files:
            scores[path] += 4.0
            _add_reason(reasons[path], "task-route prior match")

    for seed in memory.cluster_seeds:
        relevance = _cluster_relevance(seed, task, tokens, zones, scores)
        if relevance < 3:
            continue
        for path in seed.files:
            scores[path] += 3.5
            _add_reason(reasons[path], "selected from memory cluster")

    zone_matched_paths = {path for path, path_reasons in reasons.items() if any("matched repository zone" in reason for reason in path_reasons)}
    for file in memory.central_files:
        if file.path in zone_matched_paths or file.path in scores:
            scores[file.path] += 2.5
            _add_reason(reasons[file.path], "central file in relevant zone")


def _apply_context_refinement(
    context: dict[str, Any],
    candidate_paths: set[str],
    categories: set[str],
    scores: dict[str, dict[str, float]],
    reasons: dict[str, list[str]],
) -> None:
    route_lookup = context.get("task_routes", {})
    matched_route_paths: set[str] = set()
    for category in sorted(categories):
        for item in route_lookup.get(category, []):
            path = item["path"]
            if path not in candidate_paths:
                continue
            matched_route_paths.add(path)
            scores["read_first"][path] += 4.0
            scores["edit_candidates"][path] += 4.5
            scores["impacted_files"][path] += 3.5
            for reason in item.get("reasons", [])[:3]:
                _add_reason(reasons[path], reason)

    for module in context.get("architecture", {}).get("core_modules", []):
        path = module["path"]
        if path not in candidate_paths:
            continue
        scores["read_first"][path] += 2.5
        scores["edit_candidates"][path] += 2.0
        scores["impacted_files"][path] += 2.0

    for item in context.get("navigation_map", {}).get("key_files", []):
        path = item["path"]
        if path not in candidate_paths:
            continue
        importance = item.get("importance", "medium")
        scores["read_first"][path] += IMPORTANCE_SCORES.get(importance, 1.0)
        scores["edit_candidates"][path] += IMPORTANCE_SCORES.get(importance, 1.0)

    for hotspot in context.get("hotspots", []):
        path = hotspot["path"]
        if path not in candidate_paths:
            continue
        scores["read_first"][path] += 1.5
        scores["impacted_files"][path] += 2.5

    if "test_work" in categories:
        for item in route_lookup.get("test_work", []):
            path = item["path"]
            if path not in candidate_paths:
                continue
            scores["likely_tests"][path] += 4.0
            _add_reason(reasons[path], "task-route prior match")

    for path in matched_route_paths:
        scores["read_first"][path] += 0.5


def _apply_memory_refinement(
    memory: RepositoryMemoryDocument | None,
    candidate_paths: set[str],
    scores: dict[str, dict[str, float]],
    reasons: dict[str, list[str]],
    working_cluster: list[PlannedFile],
) -> None:
    if memory is None:
        return

    working_cluster_paths = {item.path for item in working_cluster}
    for file in memory.central_files:
        if file.path not in candidate_paths:
            continue
        scores["read_first"][file.path] += 2.0
        scores["edit_candidates"][file.path] += 1.5
        scores["impacted_files"][file.path] += 1.5

    for mapping in memory.test_mappings:
        if mapping.implementation not in candidate_paths and mapping.implementation not in working_cluster_paths:
            continue
        for test_path in mapping.tests:
            scores["likely_tests"][test_path] += 5.0
            scores["impacted_files"][test_path] += 1.5
            _add_reason(reasons[test_path], "related test mapping")

    for seed in memory.cluster_seeds:
        cluster_hits = [path for path in seed.files if path in candidate_paths]
        if not cluster_hits:
            continue
        for path in cluster_hits:
            scores["read_first"][path] += 1.0
            scores["edit_candidates"][path] += 1.0
            scores["impacted_files"][path] += 1.5
            _add_reason(reasons[path], "selected from relevant memory cluster")


def _apply_working_cluster_influence(
    working_cluster: list[PlannedFile],
    scores: dict[str, dict[str, float]],
    reasons: dict[str, list[str]],
) -> None:
    if not working_cluster:
        return
    for index, item in enumerate(working_cluster):
        if _is_test_path(item.path):
            scores["likely_tests"][item.path] += 4.0
            scores["impacted_files"][item.path] += 1.0
        else:
            scores["impacted_files"][item.path] += 2.5
        if index == 0:
            scores["read_first"][item.path] += 5.0
            scores["edit_candidates"][item.path] += 5.0
            _add_reason(reasons[item.path], "primary file in working cluster")
        elif index <= 2:
            scores["read_first"][item.path] += 2.5
            scores["edit_candidates"][item.path] += 2.0
            _add_reason(reasons[item.path], "neighboring file in working cluster")
        else:
            scores["read_first"][item.path] += 1.0
            if not _is_test_path(item.path):
                scores["edit_candidates"][item.path] += 0.5
            _add_reason(reasons[item.path], "same repo zone as likely edit candidate")


def _apply_fallback_scores(
    context: dict[str, Any],
    categories: set[str],
    scores: dict[str, dict[str, float]],
    reasons: dict[str, list[str]],
) -> None:
    for module in context.get("architecture", {}).get("core_modules", [])[:5]:
        path = module["path"]
        scores["read_first"][path] += 2.0
        scores["edit_candidates"][path] += 2.0
        scores["impacted_files"][path] += 2.0

    for hotspot in context.get("hotspots", [])[:5]:
        path = hotspot["path"]
        scores["impacted_files"][path] += 1.0

    for category in sorted(categories):
        for item in context.get("task_routes", {}).get(category, [])[:5]:
            path = item["path"]
            scores["read_first"][path] += 3.0
            scores["edit_candidates"][path] += 3.0
            if category == "test_work":
                scores["likely_tests"][path] += 3.0
            for reason in item.get("reasons", [])[:3]:
                _add_reason(reasons[path], reason)


def _build_working_cluster(
    task: str,
    tokens: set[str],
    zones: set[str],
    context: dict[str, Any],
    memory: RepositoryMemoryDocument | None,
    candidate_paths: set[str],
    stage_one_scores: dict[str, float],
    stage_one_reasons: dict[str, list[str]],
) -> list[PlannedFile]:
    if memory is None:
        return []

    route_paths = {
        item["path"]
        for files in context.get("task_routes", {}).values()
        for item in files
        if item["path"] in candidate_paths
    }
    central_paths = {item.path for item in memory.central_files if item.path in candidate_paths}
    test_lookup = {mapping.implementation: mapping.tests for mapping in memory.test_mappings}

    seed_candidates: list[tuple[float, str, list[str], list[str]]] = []
    for seed in memory.cluster_seeds:
        matched_files = [path for path in seed.files if path in candidate_paths]
        if len(matched_files) < 2:
            continue
        relevance = float(_cluster_relevance(seed, task, tokens, zones, stage_one_scores))
        if relevance < 3:
            continue
        relevance += sum(1.0 for path in matched_files if path in route_paths)
        relevance += sum(0.5 for path in matched_files if path in central_paths)
        seed_candidates.append((relevance, seed.label, matched_files, seed.signals))

    if not seed_candidates:
        return []

    seed_candidates.sort(key=lambda item: (-item[0], item[1]))
    _score, _label, matched_files, _signals = seed_candidates[0]

    cluster_scores: dict[str, float] = defaultdict(float)
    cluster_reasons: dict[str, list[str]] = defaultdict(list)
    for path in matched_files:
        cluster_scores[path] += stage_one_scores.get(path, 0.0)
        _add_reason(cluster_reasons[path], "selected from relevant memory cluster")

    primary_path = _select_primary_cluster_file(matched_files, route_paths, central_paths, stage_one_scores)
    cluster_scores[primary_path] += 6.0
    _add_reason(cluster_reasons[primary_path], "primary file in working cluster")

    primary_zone = _zone_from_path(primary_path)
    for path in matched_files:
        if path == primary_path:
            continue
        if _is_test_path(path):
            cluster_scores[path] += 2.0
            _add_reason(cluster_reasons[path], "related test mapping")
            continue
        if _zone_from_path(path) == primary_zone:
            cluster_scores[path] += 2.5
            _add_reason(cluster_reasons[path], "same repo zone as likely edit candidate")
        else:
            cluster_scores[path] += 2.0
            _add_reason(cluster_reasons[path], "neighboring file in working cluster")
        if path in central_paths:
            cluster_scores[path] += 1.0
            _add_reason(cluster_reasons[path], "central file in relevant region")

    for test_path in test_lookup.get(primary_path, []):
        cluster_scores[test_path] += 3.0
        _add_reason(cluster_reasons[test_path], "related test mapping")

    ranked_cluster = sorted(cluster_scores.items(), key=lambda item: (-item[1], item[0]))
    if len(ranked_cluster) < 2:
        return []
    return [PlannedFile(path=path, reasons=cluster_reasons[path][:4]) for path, _score in ranked_cluster[:5]]


def _select_primary_cluster_file(
    matched_files: list[str],
    route_paths: set[str],
    central_paths: set[str],
    stage_one_scores: dict[str, float],
) -> str:
    ranked = sorted(
        (
            (
                path in route_paths,
                path in central_paths,
                not _is_test_path(path),
                stage_one_scores.get(path, 0.0),
                path,
            )
            for path in matched_files
        ),
        key=lambda item: (-int(item[0]), -int(item[1]), -int(item[2]), -item[3], item[4]),
    )
    return ranked[0][4]


def _rank_section(
    candidate_paths: set[str],
    section_scores: dict[str, float],
    reasons: dict[str, list[str]],
    *,
    allow_tests: bool,
    tests_only: bool = False,
) -> list[PlannedFile]:
    scored_paths = []
    for path, score in section_scores.items():
        if score <= 0:
            continue
        if path not in candidate_paths and not _is_test_path(path):
            continue
        if tests_only and not _is_test_path(path):
            continue
        if not allow_tests and _is_test_path(path):
            continue
        scored_paths.append((score, path))
    scored_paths.sort(key=lambda item: (-item[0], item[1]))
    return [PlannedFile(path=path, reasons=reasons.get(path, [])[:4]) for _score, path in scored_paths[:5]]


def _collect_known_paths(context: dict[str, Any], memory: RepositoryMemoryDocument | None) -> list[str]:
    paths: set[str] = set()
    for module in context.get("architecture", {}).get("core_modules", []):
        paths.add(module["path"])
    for hotspot in context.get("hotspots", []):
        paths.add(hotspot["path"])
    for item in context.get("navigation_map", {}).get("key_files", []):
        paths.add(item["path"])
    for files in context.get("task_routes", {}).values():
        for item in files:
            paths.add(item["path"])
    for anchor in context.get("anchors", []):
        paths.add(anchor["file"])
    if memory is not None:
        for zone in memory.repository_zones:
            paths.update(zone.paths)
        for seed in memory.cluster_seeds:
            paths.update(seed.files)
        for file in memory.central_files:
            paths.add(file.path)
        for mapping in memory.test_mappings:
            paths.add(mapping.implementation)
            paths.update(mapping.tests)
    return sorted(paths)


def _detect_categories(tokens: set[str]) -> set[str]:
    categories = {
        category
        for category, keywords in TASK_CATEGORY_KEYWORDS.items()
        if tokens & keywords
    }
    return categories or {"feature_work"}


def _detect_zones(tokens: set[str], categories: set[str]) -> set[str]:
    zones = {zone for zone, keywords in ZONE_KEYWORDS.items() if tokens & keywords}
    if "api_change" in categories:
        zones.add("api")
    if "config_change" in categories:
        zones.add("config")
    if "test_work" in categories:
        zones.add("tests")
    if "model_or_logic_change" in categories:
        zones.update({"core", "service", "models_schema"})
    return zones


def _tokenize(task: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", task.lower()))


def _cluster_relevance(
    seed: Any,
    task: str,
    tokens: set[str],
    zones: set[str],
    current_scores: dict[str, float],
) -> int:
    relevance = 0
    path_tokens = _path_tokens(seed.label)
    if tokens & path_tokens:
        relevance += 2
    if any(path in current_scores for path in seed.files):
        relevance += 2
    if zones and any(_zone_from_path(path) in zones for path in seed.files):
        relevance += 1
    if task.lower() in seed.label.lower():
        relevance += 1
    return relevance


def _path_tokens(path: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", path.lower()))


def _zone_from_path(path: str) -> str:
    lowered = path.lower()
    if "tests/" in lowered or lowered.startswith("tests/") or "/test_" in lowered or lowered.startswith("test_"):
        return "tests"
    if "api" in lowered or "route" in lowered or "router" in lowered:
        return "api"
    if "config" in lowered or "settings" in lowered:
        return "config"
    if "service" in lowered:
        return "service"
    if "model" in lowered or "schema" in lowered:
        return "models_schema"
    if "cli" in lowered or "command" in lowered:
        return "cli"
    if "util" in lowered or "helper" in lowered:
        return "utils"
    if "core" in lowered or "logic" in lowered or "domain" in lowered:
        return "core"
    return "other"


def _is_test_path(path: str) -> bool:
    lowered = path.lower()
    return lowered.startswith("tests/") or "/tests/" in lowered or Path(path).stem.lower().startswith("test_") or "_test" in Path(path).stem.lower()


def _add_reason(existing: list[str], reason: str) -> None:
    if reason not in existing:
        existing.append(reason)
