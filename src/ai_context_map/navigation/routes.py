from __future__ import annotations

from ai_context_map.graph.ranking import RankedFile
from ai_context_map.models.context import TaskRouteFile
from ai_context_map.models.graph import DependencyEdge, FileNode

TASK_CATEGORIES = (
    "bugfix",
    "feature_work",
    "api_change",
    "model_or_logic_change",
    "config_change",
    "test_work",
)


def build_task_routes(
    nodes: dict[str, FileNode],
    edges: list[DependencyEdge],
    ranked_files: list[RankedFile],
) -> dict[str, list[TaskRouteFile]]:
    # Reuse the ranked graph output to produce small, task-specific starting
    # points instead of forcing callers to search the whole repo again.
    incoming = dict.fromkeys(nodes, 0)
    referenced_by_tests: set[str] = set()
    for edge in edges:
        incoming[edge.target] = incoming.get(edge.target, 0) + 1
        if nodes.get(edge.source) and nodes[edge.source].role == "test":
            referenced_by_tests.add(edge.target)

    routes: dict[str, list[TaskRouteFile]] = {}
    for category in TASK_CATEGORIES:
        scored: list[tuple[float, str, list[str]]] = []
        for item in ranked_files:
            node = nodes[item.path]
            score, reasons = _score_for_task(
                category, item, node, incoming.get(item.path, 0), referenced_by_tests
            )
            if score <= 0 or (
                not reasons and category not in {"bugfix", "feature_work"}
            ):
                continue
            scored.append((score, item.path, reasons))
        if not scored and category in {"bugfix", "feature_work"}:
            for item in ranked_files[:5]:
                fallback_reasons = _fallback_reasons(category, item)
                if fallback_reasons:
                    scored.append((item.score * 0.1, item.path, fallback_reasons))
        scored.sort(key=lambda value: (-value[0], value[1]))
        routes[category] = [
            TaskRouteFile(path=path, reasons=reasons[:3])
            for _score, path, reasons in scored[:5]
        ]
    return routes


def _score_for_task(
    category: str,
    item: RankedFile,
    node: FileNode,
    incoming_count: int,
    referenced_by_tests: set[str],
) -> tuple[float, list[str]]:
    path = item.path.lower()
    score = item.score * 0.4
    if category == "test_work":
        score = item.score * 0.15
    reasons: list[str] = []

    if category == "bugfix":
        score += min(incoming_count, 4) * 1.5
        if incoming_count:
            reasons.append("central in dependency graph")
        if node.role in {"business_logic", "api", "entrypoint"}:
            score += 2.0
            reasons.append("likely execution path for behavior fixes")
    elif category == "feature_work":
        if node.role in {"business_logic", "api", "entrypoint"}:
            score += 2.5
            reasons.append("supports new feature wiring")
        if any(pattern in path for pattern in ("service", "core", "feature", "app")):
            score += 1.5
            reasons.append("located in core/service module")
        if incoming_count >= 2:
            score += 1.0
            reasons.append("central in dependency graph")
    elif category == "api_change":
        if any(reason == "contains route handlers" for reason in item.reasons):
            score += 4.0
            reasons.append("contains route handlers")
        if node.role == "api":
            score += 3.0
            reasons.append("API module")
        if node.role == "entrypoint":
            score += 2.0
            reasons.append("app/main entrypoint")
    elif category == "model_or_logic_change":
        if node.role == "business_logic":
            score += 4.0
            reasons.append("located in core/service module")
        if any(
            pattern in path
            for pattern in ("detector", "algorithm", "/core/", "service")
        ):
            score += 2.0
            reasons.append("core detector logic")
    elif category == "config_change":
        if node.role == "config" or any(
            pattern in path for pattern in ("config", "settings", ".env", "toml")
        ):
            score += 5.0
            reasons.append("configuration entrypoint")
    elif category == "test_work":
        if node.role == "test":
            score += 5.0
            reasons.append("test file")
        if item.path in referenced_by_tests:
            score += 3.0
            reasons.append("module referenced by tests")

    return score, _unique(reasons)


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _fallback_reasons(category: str, item: RankedFile) -> list[str]:
    reasons: list[str] = []
    if "central in dependency graph" in item.reasons:
        reasons.append("central in dependency graph")
    if category == "feature_work" and any(
        reason in item.reasons
        for reason in ("located in core/service module", "filename suggests entrypoint")
    ):
        reasons.append("supports new feature wiring")
    return reasons
