from __future__ import annotations

from dataclasses import dataclass, field
import json
from math import isclose
from pathlib import Path
import re
import subprocess

from ai_context_map.config import load_config
from ai_context_map.graph.builder import GraphBuilder
from ai_context_map.graph.ranking import RankedFile, rank_files
from ai_context_map.memory.git_history import extract_git_cochange_memory
from ai_context_map.memory.io import read_memory_yaml
from ai_context_map.memory.models import RepositoryMemory
from ai_context_map.models.graph import DependencyEdge, FileNode
from ai_context_map.scanner.walker import scan_repository


# Weighted sum for planner ranking. Keep these in one place so the blend stays inspectable.
PLANNER_STRUCTURAL_WEIGHT = 0.42
PLANNER_TASK_PRIOR_WEIGHT = 0.38
PLANNER_MEMORY_WEIGHT = 0.20
TASK_RELATED_TEST_BOOST = 2.0
SECTION_LIMIT = 5
IMPACT_DEPENDENT_BOOST = 3.0
IMPACT_NEIGHBOR_BOOST = 1.5
IMPACT_MEMORY_BOOST = 2.0
IMPACT_RELATED_TEST_BOOST = 2.5
IMPACT_STRUCTURAL_TIEBREAKER = 0.25
MEMORY_SEED_LIMIT = 4
MAX_REASON_COUNT = 4
TASK_PATH_TOKEN_BOOST = 0.6
TASK_ROLE_MATCH_FACTOR = 0.3
TASK_PATH_AND_ROLE_BONUS = 0.4
COMPATIBILITY_MEMORY_MULTIPLIER = 1.25
TASK_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
TASK_STOPWORDS = {
    "a",
    "an",
    "and",
    "bug",
    "change",
    "changes",
    "debug",
    "fix",
    "for",
    "implement",
    "improve",
    "in",
    "issue",
    "make",
    "on",
    "support",
    "the",
    "to",
    "update",
    "with",
}
COMPATIBILITY_TASK_KEYWORDS = (
    "compat",
    "compatibility",
    "backward",
    "backwards",
    "legacy",
    "migration",
    "cochange",
    "co-change",
)
DOC_TASK_KEYWORDS = ("doc", "docs", "documentation", "tutorial", "example", "examples", "guide")
TEST_TASK_KEYWORDS = ("test", "tests", "failing", "debug")
ROUTE_TASK_KEYWORDS = ("api", "endpoint", "route", "router", "routing")
DEPENDENCY_TASK_KEYWORDS = ("dependency", "dependencies", "depends", "inject", "override", "overrides")
AUTH_TASK_KEYWORDS = (
    "auth",
    "authentication",
    "authorization",
    "login",
    "session",
    "security",
    "secure",
    "token",
    "oauth",
    "jwt",
    "password",
    "credential",
    "credentials",
    "permission",
    "permissions",
    "scope",
    "scopes",
    "bearer",
)
ROUTE_RUNTIME_TERMS = ("route", "router", "routing", "endpoint", "request", "handler", "application", "app")
DEPENDENCY_PATH_TERMS = ("dependency", "dependencies", "depends", "inject", "override", "overrides", "provider")
RESPONSE_MODEL_TASK_TERMS = ("response", "responses", "model", "models", "schema", "schemas", "serialize")
AUTH_PATH_TERMS = (
    "auth",
    "authentication",
    "authorization",
    "login",
    "session",
    "security",
    "token",
    "oauth",
    "jwt",
    "password",
    "credential",
    "credentials",
    "permission",
    "permissions",
    "scope",
    "scopes",
    "bearer",
)
NON_RUNTIME_PREFIXES = ("docs/", "docs_src/", "examples/")
DOC_LIKE_FILENAMES = {"readme", "security", "contributing", "changelog", "history"}
DOC_LIKE_SUFFIXES = (".md", ".rst")


@dataclass(frozen=True, slots=True)
class TaskPriorRule:
    keywords: tuple[str, ...]
    path_terms: tuple[str, ...]
    roles: tuple[str, ...]
    boost: float
    reason: str


@dataclass(slots=True)
class PlannedFile:
    path: str
    score: float
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TaskPlan:
    task: str
    read_first: list[PlannedFile] = field(default_factory=list)
    likely_edit_candidates: list[PlannedFile] = field(default_factory=list)
    likely_impacted_files: list[PlannedFile] = field(default_factory=list)
    likely_tests: list[PlannedFile] = field(default_factory=list)


TASK_PRIOR_RULES = [
    TaskPriorRule(
        keywords=AUTH_TASK_KEYWORDS,
        path_terms=AUTH_PATH_TERMS,
        roles=("api", "business_logic"),
        boost=3.4,
        reason="auth/security keyword signal",
    ),
    TaskPriorRule(
        keywords=("api", "endpoint", "route", "router", "routing", "request", "response"),
        path_terms=("route", "router", "routing", "routes", "controller", "schema"),
        roles=("api", "data_model"),
        boost=2.5,
        reason="task-intent match: api/routing",
    ),
    TaskPriorRule(
        keywords=("config", "env", "settings", "metadata", "version"),
        path_terms=("config", "settings", "env", "metadata", "version"),
        roles=("config",),
        boost=3.0,
        reason="metadata/config signal",
    ),
    TaskPriorRule(
        keywords=("test", "failing", "test failure"),
        path_terms=("test", "tests", "spec"),
        roles=("test",),
        boost=3.0,
        reason="test relevance",
    ),
    TaskPriorRule(
        keywords=("refactor", "shared", "common", "util", "utils", "model", "models", "cleanup"),
        path_terms=("util", "utils", "shared", "common", "core", "model", "models", "schema"),
        roles=("utility", "business_logic", "data_model"),
        boost=2.8,
        reason="task-intent match: refactor/shared code",
    ),
    TaskPriorRule(
        keywords=("cli", "command", "packaging", "package", "release", "publish", "entrypoint", "metadata", "version", "export", "exports"),
        path_terms=("cli", "command", "version", "package", "metadata", "main", "release"),
        roles=("entrypoint", "config"),
        boost=3.2,
        reason="task-intent match: cli/packaging/metadata",
    ),
    TaskPriorRule(
        keywords=("compatibility", "compatible", "compat", "backward", "backwards", "legacy", "migration", "cochange", "co-change"),
        path_terms=("compat", "compatibility", "legacy", "migration", "adapter", "adapters", "route", "router", "routes"),
        roles=("api", "business_logic", "data_model"),
        boost=3.1,
        reason="task-intent match: compatibility/co-change",
    ),
]


def plan_task(root: Path, task: str) -> TaskPlan:
    config = load_config(root)
    scan_result = scan_repository(root, config)
    nodes, edges = GraphBuilder().build(scan_result)
    ranked = rank_files(nodes, edges, config)
    memory = _load_repository_memory(root)

    candidates = build_plan_candidates(task, nodes, ranked, memory)
    if not candidates:
        return TaskPlan(task=task)

    read_first_pool = [
        item
        for item in candidates
        if _is_runtime_priority_path(task, item.path) and not _is_test_like_path(item.path)
    ]
    read_first = _select_top(read_first_pool or candidates, limit=SECTION_LIMIT)
    read_first_paths = {item.path for item in read_first}

    edit_pool = [
        item
        for item in candidates
        if not _is_test_like_path(item.path) and _is_runtime_priority_path(task, item.path)
    ]
    edit_candidates = _select_top(edit_pool or [item for item in candidates if not _is_test_like_path(item.path)], limit=SECTION_LIMIT)
    edit_paths = {item.path for item in edit_candidates}

    impacted_candidates = build_impacted_candidates(
        nodes=nodes,
        edges=edges,
        ranked=ranked,
        edit_candidates=edit_candidates,
        memory=memory,
    )
    likely_impacted_files = _select_top(
        [item for item in impacted_candidates if item.path not in read_first_paths and item.path not in edit_paths],
        limit=SECTION_LIMIT,
    )
    if not likely_impacted_files:
        likely_impacted_files = _select_top(
            [item for item in impacted_candidates if item.path not in edit_paths],
            limit=SECTION_LIMIT,
        )
    if not likely_impacted_files:
        likely_impacted_files = _select_top(impacted_candidates, limit=SECTION_LIMIT)

    likely_tests = _select_top(_build_test_candidates(task, candidates, edit_candidates), limit=SECTION_LIMIT)

    return TaskPlan(
        task=task,
        read_first=read_first,
        likely_edit_candidates=edit_candidates,
        likely_impacted_files=likely_impacted_files,
        likely_tests=likely_tests,
    )


def build_plan_candidates(
    task: str,
    nodes: dict[str, FileNode],
    ranked: list[RankedFile],
    memory: RepositoryMemory | None = None,
) -> list[PlannedFile]:
    ranked_by_path = {item.path: item for item in ranked}
    structural_raw = {item.path: item.score for item in ranked}
    task_prior_raw, task_prior_reasons = task_prior_scores(task, nodes)
    memory_raw, memory_reasons = memory_boost_scores(memory, task, task_prior_raw, structural_raw)

    structural_scores = _normalize_scores(structural_raw)
    task_scores = _normalize_scores(task_prior_raw)
    memory_scores = _normalize_scores(memory_raw)
    task_signal_active = any(score > 0.0 for score in task_scores.values())

    candidates: list[PlannedFile] = []
    for path in sorted(nodes):
        ranked_item = ranked_by_path[path]
        structural_reason = _structural_reason(ranked_item)
        reasons = _unique(
            task_prior_reasons.get(path, [])
            + memory_reasons.get(path, [])
            + ([structural_reason] if structural_reason else [])
        )
        final_score = blend_planner_scores(
            structural_scores.get(path, 0.0),
            task_scores.get(path, 0.0),
            memory_scores.get(path, 0.0),
        )
        if task_signal_active and task_scores.get(path, 0.0) == 0.0 and memory_scores.get(path, 0.0) == 0.0:
            final_score *= 0.88
        final_score *= _candidate_context_multiplier(task, path)
        candidates.append(
            PlannedFile(
                path=path,
                score=round(final_score, 4),
                reasons=reasons[:MAX_REASON_COUNT],
            )
        )

    candidates.sort(key=lambda item: (-item.score, item.path))
    return candidates


def build_impacted_candidates(
    nodes: dict[str, FileNode],
    edges: list[DependencyEdge],
    ranked: list[RankedFile],
    edit_candidates: list[PlannedFile],
    memory: RepositoryMemory | None = None,
) -> list[PlannedFile]:
    if not edit_candidates:
        return []

    incoming_neighbors, outgoing_neighbors = _build_graph_neighbors(edges, nodes)
    memory_neighbors = _build_memory_neighbors(memory, nodes)
    structural_scores = _normalize_scores({item.path: item.score for item in ranked})
    edit_paths = [item.path for item in edit_candidates]
    related_tests = _build_related_test_map(nodes, incoming_neighbors)

    scores: dict[str, float] = {}
    reasons: dict[str, list[str]] = {}
    for selected_path in edit_paths:
        for path in incoming_neighbors.get(selected_path, []):
            if path == selected_path:
                continue
            scores[path] = scores.get(path, 0.0) + IMPACT_DEPENDENT_BOOST
            reasons.setdefault(path, []).append("depends on selected edit candidate")
        for path in outgoing_neighbors.get(selected_path, []):
            if path == selected_path:
                continue
            scores[path] = scores.get(path, 0.0) + IMPACT_NEIGHBOR_BOOST
            reasons.setdefault(path, []).append("neighboring module in dependency graph")
        for path, weight in memory_neighbors.get(selected_path, []):
            if path == selected_path:
                continue
            scores[path] = scores.get(path, 0.0) + (weight * IMPACT_MEMORY_BOOST)
            reasons.setdefault(path, []).append("frequently co-changed with selected file")
        for path in related_tests.get(selected_path, []):
            if path == selected_path:
                continue
            scores[path] = scores.get(path, 0.0) + IMPACT_RELATED_TEST_BOOST
            reasons.setdefault(path, []).append("appears to be a related test file")

    impacted: list[PlannedFile] = []
    for path in sorted(scores):
        if path not in nodes:
            continue
        score = scores[path] + (structural_scores.get(path, 0.0) * IMPACT_STRUCTURAL_TIEBREAKER)
        impacted.append(
            PlannedFile(
                path=path,
                score=round(score, 4),
                reasons=_unique(reasons.get(path, []))[:MAX_REASON_COUNT],
            )
        )

    impacted.sort(key=lambda item: (-item.score, item.path))
    return impacted


def task_prior_scores(
    task: str, nodes: dict[str, FileNode]
) -> tuple[dict[str, float], dict[str, list[str]]]:
    lowered_task = task.lower()
    task_tokens = _tokenize_terms(lowered_task)
    raw_scores = {path: 0.0 for path in nodes}
    reasons: dict[str, list[str]] = {path: [] for path in nodes}
    module_to_tests = _module_to_test_paths(nodes)
    test_task_active = _task_contains_any(lowered_task, ("test", "failing", "test failure"))
    route_task_active = any(token in task_tokens for token in ROUTE_TASK_KEYWORDS)
    dependency_task_active = any(_normalize_term(token) in task_tokens for token in DEPENDENCY_TASK_KEYWORDS)
    response_model_task_active = {"response", "model"}.issubset(task_tokens)
    auth_task_active = any(token in task_tokens for token in AUTH_TASK_KEYWORDS)

    for rule in TASK_PRIOR_RULES:
        if not any(_matches_task_keyword(lowered_task, task_tokens, keyword) for keyword in rule.keywords):
            continue
        for path, node in nodes.items():
            path_terms = _path_terms(path)
            matches_path = any(_path_matches_term(path_terms, term) for term in rule.path_terms)
            matches_role = node.role in rule.roles
            if rule.reason == "task-intent match: cli/packaging/metadata" and matches_role:
                matches_role = matches_path or _is_package_metadata_path(path)
            if not matches_path and not matches_role:
                continue
            score = 0.0
            if matches_path:
                score += rule.boost
            if matches_role:
                score += rule.boost * TASK_ROLE_MATCH_FACTOR
            if matches_path and matches_role:
                score += TASK_PATH_AND_ROLE_BONUS
            raw_scores[path] += score
            reasons[path].append(rule.reason)

    for path in sorted(nodes):
        overlap = sorted(task_tokens.intersection(_path_terms(path)))
        if {"metadata", "version", "package", "packaging", "export"}.intersection(task_tokens) and _is_package_metadata_path(path):
            raw_scores[path] += 2.6
            reasons[path].append("metadata/config signal")
        if not overlap:
            continue
        raw_scores[path] += min(len(overlap), 3) * TASK_PATH_TOKEN_BOOST
        reasons[path].append(f'task-intent match: path tokens ({", ".join(overlap[:2])})')

    if test_task_active:
        for path, node in nodes.items():
            if node.role == "test":
                continue
            module_key = _module_key(path)
            if not module_key or module_key not in module_to_tests:
                continue
            raw_scores[path] += TASK_RELATED_TEST_BOOST
            reasons[path].append("nearby module for test-related task")

    for path, node in nodes.items():
        path_terms = _path_terms(path)
        if _is_doc_like_path(path):
            continue
        is_test_path = node.role == "test" or _is_test_like_path(path)

        if route_task_active and not is_test_path:
            route_signal = 0.0
            if node.role == "api" or _has_any_term(path_terms, ROUTE_RUNTIME_TERMS):
                route_signal += 2.1
            if _has_any_term(path_terms, ("application", "app")):
                route_signal += 0.8
            if route_signal > 0.0:
                raw_scores[path] += route_signal
                reasons[path].append("route-oriented runtime signal")

        if dependency_task_active:
            dependency_signal = 0.0
            dependency_match = _has_any_term(path_terms, DEPENDENCY_PATH_TERMS)
            if dependency_match:
                dependency_signal += 3.2 if is_test_path else 2.4
            if test_task_active and not is_test_path and _has_any_term(path_terms, ("param", "params")):
                dependency_signal += 0.6
            if test_task_active and is_test_path and not dependency_match:
                dependency_signal -= 3.0
            if dependency_signal != 0.0:
                raw_scores[path] += dependency_signal
                reasons[path].append("dependency-oriented pairing signal")

        if response_model_task_active:
            response_signal = 0.0
            response_term_match = _has_any_term(path_terms, ("response", "responses", "serialize"))
            model_term_match = _has_any_term(path_terms, ("model", "models", "schema", "schemas", "openapi"))
            if response_term_match and model_term_match:
                response_signal += 3.2 if is_test_path else 2.8
            elif response_term_match or model_term_match:
                response_signal += 1.5 if is_test_path else 1.3
            if is_test_path and (response_term_match ^ model_term_match):
                response_signal -= 1.2
            if not is_test_path and (node.role in {"api", "data_model"} or _has_any_term(path_terms, ("openapi", "routing"))):
                response_signal += 1.0
            if test_task_active and not is_test_path and response_signal > 0.0:
                response_signal += 0.8
            if response_signal > 0.0:
                raw_scores[path] += response_signal
                reasons[path].append("response/model signal")

        if auth_task_active:
            auth_signal = 0.0
            if _has_any_term(path_terms, AUTH_PATH_TERMS):
                auth_signal += 1.0 if is_test_path else 2.4
            if not is_test_path and _has_any_term(path_terms, ("dependency", "dependencies", "param", "params", "override")):
                auth_signal += 1.2
            if auth_signal > 0.0:
                raw_scores[path] += auth_signal
                reasons[path].append("auth/security runtime signal")

    return raw_scores, {path: _unique(items) for path, items in reasons.items() if items}


def memory_boost_scores(
    memory: RepositoryMemory | None,
    task: str,
    task_prior_raw: dict[str, float],
    structural_raw: dict[str, float],
) -> tuple[dict[str, float], dict[str, list[str]]]:
    if memory is None:
        return {}, {}

    normalized_task = _normalize_scores(task_prior_raw)
    normalized_structural = _normalize_scores(structural_raw)
    preliminary_scores: dict[str, float] = {}
    for path in sorted(structural_raw):
        task_score = normalized_task.get(path, 0.0)
        if task_prior_raw.get(path, 0.0) <= 0.0 and task_score <= 0.0:
            continue
        preliminary_scores[path] = (task_score * 1.05) + (normalized_structural.get(path, 0.0) * 0.55)

    seed_paths = [
        path
        for path, _score in sorted(preliminary_scores.items(), key=lambda item: (-item[1], item[0]))
    ][:MEMORY_SEED_LIMIT]
    if not seed_paths:
        return {}, {}

    memory_map = {item.path: item.related for item in memory.files}
    raw_scores: dict[str, float] = {}
    reasons: dict[str, list[str]] = {}
    memory_multiplier = (
        COMPATIBILITY_MEMORY_MULTIPLIER if _task_contains_any(task.lower(), COMPATIBILITY_TASK_KEYWORDS) else 1.0
    )
    for seed_path in seed_paths:
        for link in memory_map.get(seed_path, []):
            if link.path == seed_path:
                continue
            seed_strength = 0.75 + normalized_task.get(seed_path, 0.0)
            if task_prior_raw.get(link.path, 0.0) > 0.0:
                seed_strength += 0.2
            raw_scores[link.path] = raw_scores.get(link.path, 0.0) + (link.weight * seed_strength * memory_multiplier)
            reasons.setdefault(link.path, []).append(f"co-change boost from {seed_path}")
    return raw_scores, {path: _unique(items) for path, items in reasons.items()}


def blend_planner_scores(structural: float, task_prior: float, memory: float) -> float:
    return (
        (structural * PLANNER_STRUCTURAL_WEIGHT)
        + (task_prior * PLANNER_TASK_PRIOR_WEIGHT)
        + (memory * PLANNER_MEMORY_WEIGHT)
    )


def render_task_plan(plan: TaskPlan) -> str:
    lines = [f"Task: {plan.task}"]
    lines.extend(_render_section("Read first", plan.read_first))
    lines.extend(_render_section("Likely edit candidates", plan.likely_edit_candidates))
    lines.extend(_render_section("Likely impacted files", plan.likely_impacted_files))
    lines.extend(_render_section("Likely tests", plan.likely_tests))
    return "\n".join(lines)


def render_task_plan_json(plan: TaskPlan) -> str:
    return json.dumps(task_plan_to_dict(plan), indent=2)


def task_plan_to_dict(plan: TaskPlan) -> dict[str, object]:
    return {
        "task": plan.task,
        "read_first": [_planned_file_to_dict(item) for item in plan.read_first],
        "edit_candidates": [_planned_file_to_dict(item) for item in plan.likely_edit_candidates],
        "impacted_files": [_planned_file_to_dict(item) for item in plan.likely_impacted_files],
        "likely_tests": [_planned_file_to_dict(item) for item in plan.likely_tests],
    }


def _render_section(title: str, items: list[PlannedFile]) -> list[str]:
    lines = [f"{title}:"]
    if not items:
        lines.append("  - none")
        return lines
    for item in items:
        reason_text = "; ".join(item.reasons) if item.reasons else "no additional signals"
        lines.append(f"  - {item.path}: {reason_text}")
    return lines


def _planned_file_to_dict(item: PlannedFile) -> dict[str, object]:
    return {
        "path": item.path,
        "reasons": list(item.reasons),
        "score": item.score,
    }


def _build_test_candidates(
    task: str, candidates: list[PlannedFile], edit_candidates: list[PlannedFile]
) -> list[PlannedFile]:
    lowered_task = task.lower()
    task_tokens = _tokenize_terms(lowered_task)
    edit_module_keys = {_module_key(item.path) for item in edit_candidates if _module_key(item.path)}
    test_candidates: list[PlannedFile] = []
    for item in candidates:
        if not _is_test_like_path(item.path):
            continue
        score = item.score
        reasons = list(item.reasons)
        path_terms = _path_terms(item.path)
        if _module_key(item.path) in edit_module_keys and "looks like related test file" not in reasons:
            score += 0.2
            reasons.append("looks like related test file")
        if any(token in task_tokens for token in ROUTE_TASK_KEYWORDS) and _has_any_term(path_terms, ROUTE_RUNTIME_TERMS):
            score += 0.35
        if any(_normalize_term(token) in task_tokens for token in DEPENDENCY_TASK_KEYWORDS):
            if _has_any_term(path_terms, DEPENDENCY_PATH_TERMS):
                score += 0.6
        if {"response", "model"}.issubset(task_tokens):
            response_term_match = _has_any_term(path_terms, ("response", "responses", "serialize"))
            model_term_match = _has_any_term(path_terms, ("model", "models", "schema", "schemas", "openapi"))
            if response_term_match and model_term_match:
                score += 0.8
            elif response_term_match or model_term_match:
                score += 0.25
        if any(token in task_tokens for token in AUTH_TASK_KEYWORDS) and _has_any_term(path_terms, AUTH_PATH_TERMS):
            score += 0.45
        test_candidates.append(
            PlannedFile(path=item.path, score=round(score, 4), reasons=_unique(reasons)[:MAX_REASON_COUNT])
        )
    test_candidates.sort(key=lambda item: (-item.score, item.path))
    return test_candidates


def _structural_reason(item: RankedFile) -> str | None:
    for reason in item.reasons:
        if reason in {"central in dependency graph", "high PageRank in dependency graph"}:
            return reason
    return item.reasons[0] if item.reasons else None


def _module_to_test_paths(nodes: dict[str, FileNode]) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for path, node in nodes.items():
        if node.role != "test" and not _is_test_like_path(path):
            continue
        module_key = _module_key(path)
        if not module_key:
            continue
        mapping.setdefault(module_key, []).append(path)
    return mapping


def _build_related_test_map(
    nodes: dict[str, FileNode], incoming_neighbors: dict[str, list[str]]
) -> dict[str, list[str]]:
    module_to_tests = _module_to_test_paths(nodes)
    related: dict[str, list[str]] = {}
    for path, node in nodes.items():
        if node.role == "test" or _is_test_like_path(path):
            continue
        candidates = list(module_to_tests.get(_module_key(path), []))
        for dependent in incoming_neighbors.get(path, []):
            if nodes.get(dependent) and (nodes[dependent].role == "test" or _is_test_like_path(dependent)):
                candidates.append(dependent)
        related[path] = sorted(_unique(candidates))
    return related


def _build_graph_neighbors(
    edges: list[DependencyEdge], nodes: dict[str, FileNode]
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    incoming: dict[str, set[str]] = {path: set() for path in nodes}
    outgoing: dict[str, set[str]] = {path: set() for path in nodes}
    for edge in sorted(edges, key=lambda item: (item.source, item.target)):
        if edge.source not in nodes or edge.target not in nodes:
            continue
        incoming[edge.target].add(edge.source)
        outgoing[edge.source].add(edge.target)
    return (
        {path: sorted(neighbors) for path, neighbors in incoming.items()},
        {path: sorted(neighbors) for path, neighbors in outgoing.items()},
    )


def _build_memory_neighbors(
    memory: RepositoryMemory | None, nodes: dict[str, FileNode]
) -> dict[str, list[tuple[str, float]]]:
    if memory is None:
        return {}

    neighbor_weights: dict[str, dict[str, float]] = {}
    for file_memory in sorted(memory.files, key=lambda item: item.path):
        if file_memory.path not in nodes:
            continue
        for link in sorted(file_memory.related, key=lambda item: item.path):
            if link.path not in nodes or link.path == file_memory.path:
                continue
            neighbor_weights.setdefault(file_memory.path, {})
            neighbor_weights[file_memory.path][link.path] = max(
                neighbor_weights[file_memory.path].get(link.path, 0.0),
                link.weight,
            )
            neighbor_weights.setdefault(link.path, {})
            neighbor_weights[link.path][file_memory.path] = max(
                neighbor_weights[link.path].get(file_memory.path, 0.0),
                link.weight,
            )

    return {
        path: sorted(related.items(), key=lambda item: (-item[1], item[0]))
        for path, related in sorted(neighbor_weights.items())
    }


def _module_key(path: str) -> str:
    stem = Path(path).stem.lower()
    if stem == "__init__":
        return ""
    for prefix in ("test_",):
        if stem.startswith(prefix):
            stem = stem[len(prefix) :]
    for suffix in ("_test", ".spec", ".test"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    return stem


def _is_test_like_path(path: str) -> bool:
    lowered_parts = [part.lower() for part in Path(path).parts]
    stem = Path(path).stem.lower()
    return (
        any(part in {"test", "tests", "spec", "specs"} for part in lowered_parts)
        or stem == "test"
        or stem == "spec"
        or stem.startswith("test_")
        or stem.endswith("_test")
        or stem.endswith(".test")
        or stem.endswith(".spec")
    )


def _select_top(items: list[PlannedFile], limit: int) -> list[PlannedFile]:
    ordered = sorted(items, key=lambda item: (-item.score, item.path))
    return ordered[:limit]


def _task_contains_any(task: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in task for keyword in keywords)


def _matches_task_keyword(task: str, task_tokens: set[str], keyword: str) -> bool:
    if " " in keyword or "-" in keyword:
        return keyword in task
    return _normalize_term(keyword) in task_tokens


def _tokenize_terms(value: str) -> set[str]:
    tokens = {_normalize_term(token) for token in TASK_TOKEN_PATTERN.findall(value.lower())}
    return {token for token in tokens if len(token) >= 3 and token not in TASK_STOPWORDS}


def _path_terms(path: str) -> set[str]:
    normalized = path.lower().replace("__init__", " init ")
    return _tokenize_terms(normalized.replace("/", " ").replace(".", " ").replace("_", " "))


def _path_matches_term(path_terms: set[str], term: str) -> bool:
    normalized_term = _normalize_term(term)
    return normalized_term in path_terms


def _has_any_term(path_terms: set[str], terms: tuple[str, ...]) -> bool:
    return any(_normalize_term(term) in path_terms for term in terms)


def _normalize_term(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _is_package_metadata_path(path: str) -> bool:
    lowered = path.lower()
    if _is_doc_like_path(path) or lowered.startswith("tests/"):
        return False
    return lowered.endswith("/__init__.py") or lowered.endswith("_version.py") or "version" in lowered


def _is_runtime_priority_path(task: str, path: str) -> bool:
    lowered_task = task.lower()
    if _is_test_like_path(path):
        return _task_contains_any(lowered_task, TEST_TASK_KEYWORDS)
    if _is_doc_like_path(path) or path.lower().startswith("scripts/"):
        return _task_contains_any(lowered_task, DOC_TASK_KEYWORDS)
    return True


def _candidate_context_multiplier(task: str, path: str) -> float:
    lowered_task = task.lower()
    task_tokens = _tokenize_terms(lowered_task)
    multiplier = 1.0
    if _is_doc_like_path(path) and not _task_contains_any(lowered_task, DOC_TASK_KEYWORDS):
        multiplier *= 0.58
    if _is_test_like_path(path) and not _task_contains_any(lowered_task, TEST_TASK_KEYWORDS):
        multiplier *= 0.55
    if path.lower().endswith("/__init__.py") and not _task_contains_any(
        lowered_task, ("metadata", "version", "package", "packaging", "export", "exports")
    ):
        multiplier *= 0.42
    if Path(path).stem.lower() == "testclient" and "test client" not in lowered_task and "testclient" not in lowered_task:
        multiplier *= 0.48
    focused_runtime_task = any(token in task_tokens for token in ROUTE_TASK_KEYWORDS) or any(
        _normalize_term(token) in task_tokens for token in DEPENDENCY_TASK_KEYWORDS
    ) or {"response", "model"}.issubset(task_tokens) or any(token in task_tokens for token in AUTH_TASK_KEYWORDS)
    stem = Path(path).stem.lower()
    if focused_runtime_task and _is_package_metadata_path(path):
        multiplier *= 0.7
    if focused_runtime_task and stem == "cli" and "cli" not in task_tokens:
        multiplier *= 0.72
    if focused_runtime_task and stem == "testclient" and "testclient" not in task_tokens:
        multiplier *= 0.62
    return multiplier


def _is_doc_like_path(path: str) -> bool:
    lowered = path.lower()
    if lowered.startswith(NON_RUNTIME_PREFIXES):
        return True
    stem = Path(path).stem.lower()
    return lowered.endswith(DOC_LIKE_SUFFIXES) or stem in DOC_LIKE_FILENAMES


def _load_repository_memory(root: Path) -> RepositoryMemory | None:
    path = root / ".ai" / "memory.yaml"
    if path.exists():
        return read_memory_yaml(path)
    try:
        return extract_git_cochange_memory(root)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def _normalize_scores(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    minimum = min(scores.values())
    maximum = max(scores.values())
    if isclose(maximum, minimum):
        return {path: 0.0 if isclose(maximum, 0.0) else 1.0 for path in scores}
    scale = maximum - minimum
    return {path: (value - minimum) / scale for path, value in scores.items()}


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
