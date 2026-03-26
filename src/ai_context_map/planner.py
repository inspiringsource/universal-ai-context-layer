from __future__ import annotations

from dataclasses import dataclass, field
from math import isclose
from pathlib import Path
import subprocess

from ai_context_map.config import load_config
from ai_context_map.graph.builder import GraphBuilder
from ai_context_map.graph.ranking import RankedFile, rank_files
from ai_context_map.memory.git_history import extract_git_cochange_memory
from ai_context_map.memory.io import read_memory_yaml
from ai_context_map.memory.models import RepositoryMemory
from ai_context_map.models.graph import FileNode
from ai_context_map.scanner.walker import scan_repository


# Weighted sum for planner ranking. Keep these in one place so the blend stays inspectable.
PLANNER_STRUCTURAL_WEIGHT = 0.50
PLANNER_TASK_PRIOR_WEIGHT = 0.35
PLANNER_MEMORY_WEIGHT = 0.15
TASK_RELATED_TEST_BOOST = 2.0
SECTION_LIMIT = 5


@dataclass(frozen=True, slots=True)
class TaskPriorRule:
    keywords: tuple[str, ...]
    path_terms: tuple[str, ...]
    roles: tuple[str, ...]
    boost: float


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
        keywords=("auth", "login", "session"),
        path_terms=("auth", "login", "session", "service", "route", "routes"),
        roles=("api", "business_logic"),
        boost=3.0,
    ),
    TaskPriorRule(
        keywords=("api", "endpoint", "route"),
        path_terms=("api", "route", "routes", "controller", "schema"),
        roles=("api", "data_model"),
        boost=2.5,
    ),
    TaskPriorRule(
        keywords=("config", "env", "settings"),
        path_terms=("config", "settings", "env"),
        roles=("config",),
        boost=3.0,
    ),
    TaskPriorRule(
        keywords=("test", "failing", "test failure"),
        path_terms=("test", "tests", "spec"),
        roles=("test",),
        boost=3.0,
    ),
    TaskPriorRule(
        keywords=("refactor", "shared", "common", "util"),
        path_terms=("util", "utils", "shared", "common", "core"),
        roles=("utility", "business_logic"),
        boost=2.0,
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

    read_first = _select_top(candidates, limit=SECTION_LIMIT)
    read_first_paths = {item.path for item in read_first}

    edit_candidates = _select_top(
        [item for item in candidates if nodes[item.path].role != "test"],
        limit=SECTION_LIMIT,
    )
    edit_paths = {item.path for item in edit_candidates}

    impacted_candidates = [
        item
        for item in candidates
        if item.path not in read_first_paths
        and item.path not in edit_paths
        and nodes[item.path].role != "test"
        and any(reason.startswith("frequently co-changed with") for reason in item.reasons)
    ]
    if not impacted_candidates:
        impacted_candidates = [
            item
            for item in candidates
            if item.path not in read_first_paths and item.path not in edit_paths and nodes[item.path].role != "test"
        ]
    likely_impacted_files = _select_top(impacted_candidates, limit=SECTION_LIMIT)

    likely_tests = _select_top(_build_test_candidates(candidates, edit_candidates), limit=SECTION_LIMIT)

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
    memory_raw, memory_reasons = memory_boost_scores(memory, task_prior_raw)

    structural_scores = _normalize_scores(structural_raw)
    task_scores = _normalize_scores(task_prior_raw)
    memory_scores = _normalize_scores(memory_raw)

    candidates: list[PlannedFile] = []
    for path in sorted(nodes):
        ranked_item = ranked_by_path[path]
        reasons: list[str] = []
        structural_reason = _structural_reason(ranked_item)
        if structural_reason:
            reasons.append(structural_reason)
        reasons.extend(task_prior_reasons.get(path, []))
        reasons.extend(memory_reasons.get(path, []))
        final_score = blend_planner_scores(
            structural_scores.get(path, 0.0),
            task_scores.get(path, 0.0),
            memory_scores.get(path, 0.0),
        )
        candidates.append(
            PlannedFile(
                path=path,
                score=round(final_score, 4),
                reasons=_unique(reasons)[:3],
            )
        )

    candidates.sort(key=lambda item: (-item.score, item.path))
    return candidates


def task_prior_scores(
    task: str, nodes: dict[str, FileNode]
) -> tuple[dict[str, float], dict[str, list[str]]]:
    lowered_task = task.lower()
    raw_scores = {path: 0.0 for path in nodes}
    reasons: dict[str, list[str]] = {path: [] for path in nodes}
    module_to_tests = _module_to_test_paths(nodes)
    test_task_active = _task_contains_any(lowered_task, ("test", "failing", "test failure"))

    for rule in TASK_PRIOR_RULES:
        matched_keyword = next((keyword for keyword in rule.keywords if keyword in lowered_task), None)
        if not matched_keyword:
            continue
        for path, node in nodes.items():
            lowered_path = path.lower()
            matches_path = any(term in lowered_path for term in rule.path_terms)
            matches_role = node.role in rule.roles
            if not matches_path and not matches_role:
                continue
            raw_scores[path] += rule.boost
            reasons[path].append(f'matched task keyword "{matched_keyword}"')

    if test_task_active:
        for path, node in nodes.items():
            if node.role == "test":
                continue
            module_key = _module_key(path)
            if not module_key or module_key not in module_to_tests:
                continue
            raw_scores[path] += TASK_RELATED_TEST_BOOST
            reasons[path].append("nearby module for test-related task")

    return raw_scores, {path: _unique(items) for path, items in reasons.items() if items}


def memory_boost_scores(
    memory: RepositoryMemory | None, task_prior_raw: dict[str, float]
) -> tuple[dict[str, float], dict[str, list[str]]]:
    if memory is None:
        return {}, {}

    seed_paths = [
        path
        for path, _score in sorted(task_prior_raw.items(), key=lambda item: (-item[1], item[0]))
        if _score > 0
    ][:3]
    if not seed_paths:
        return {}, {}

    memory_map = {item.path: item.related for item in memory.files}
    raw_scores: dict[str, float] = {}
    reasons: dict[str, list[str]] = {}
    for seed_path in seed_paths:
        for link in memory_map.get(seed_path, []):
            if link.path in seed_paths:
                continue
            raw_scores[link.path] = raw_scores.get(link.path, 0.0) + link.weight
            reasons.setdefault(link.path, []).append(f"frequently co-changed with {seed_path}")
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


def _render_section(title: str, items: list[PlannedFile]) -> list[str]:
    lines = [f"{title}:"]
    if not items:
        lines.append("  - none")
        return lines
    for item in items:
        reason_text = "; ".join(item.reasons) if item.reasons else "no additional signals"
        lines.append(f"  - {item.path}: {reason_text}")
    return lines


def _build_test_candidates(candidates: list[PlannedFile], edit_candidates: list[PlannedFile]) -> list[PlannedFile]:
    edit_module_keys = {_module_key(item.path) for item in edit_candidates if _module_key(item.path)}
    test_candidates: list[PlannedFile] = []
    for item in candidates:
        lowered = item.path.lower()
        if "test" not in lowered and "spec" not in lowered:
            continue
        score = item.score
        reasons = list(item.reasons)
        if _module_key(item.path) in edit_module_keys and "looks like related test file" not in reasons:
            score += 0.2
            reasons.append("looks like related test file")
        test_candidates.append(PlannedFile(path=item.path, score=round(score, 4), reasons=_unique(reasons)[:3]))
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
        if node.role != "test":
            continue
        module_key = _module_key(path)
        if not module_key:
            continue
        mapping.setdefault(module_key, []).append(path)
    return mapping


def _module_key(path: str) -> str:
    stem = Path(path).stem.lower()
    for prefix in ("test_",):
        if stem.startswith(prefix):
            stem = stem[len(prefix) :]
    for suffix in ("_test", ".spec", ".test"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    return stem


def _select_top(items: list[PlannedFile], limit: int) -> list[PlannedFile]:
    ordered = sorted(items, key=lambda item: (-item.score, item.path))
    return ordered[:limit]


def _task_contains_any(task: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in task for keyword in keywords)


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
