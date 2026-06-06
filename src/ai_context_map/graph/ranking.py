from __future__ import annotations

from dataclasses import dataclass
from math import isclose

from ai_context_map.config import Config
from ai_context_map.models.graph import DependencyEdge, FileNode


@dataclass(slots=True)
class RankedFile:
    path: str
    score: float
    reasons: list[str]
    in_degree: int = 0
    out_degree: int = 0
    centrality: float = 0.0
    pagerank_score: float = 0.0
    heuristic_score: float = 0.0


ROLE_WEIGHTS = {
    "entrypoint": 2.5,
    "api": 2.0,
    "business_logic": 2.5,
    "data_model": 1.5,
    "config": 0.5,
    "utility": -0.5,
    "test": -2.5,
    "storage": 1.5,
    "ui": 0.5,
    "unknown": 0.0,
}

SOURCE_ROOT_BONUS = 1.0
CENTRALITY_IN_WEIGHT = 1.5
CENTRALITY_OUT_WEIGHT = 0.5
PAGERANK_WEIGHT = 0.45
HEURISTIC_WEIGHT = 0.35
ENTRYPOINT_WEIGHT = 0.20


def rank_files(
    nodes: dict[str, FileNode], edges: list[DependencyEdge], config: Config
) -> list[RankedFile]:
    incoming = dict.fromkeys(nodes, 0)
    outgoing = dict.fromkeys(nodes, 0)
    imported_by_api: set[str] = set()
    for edge in edges:
        incoming[edge.target] = incoming.get(edge.target, 0) + 1
        outgoing[edge.source] = outgoing.get(edge.source, 0) + 1
        if nodes.get(edge.source) and nodes[edge.source].role == "api":
            imported_by_api.add(edge.target)

    pagerank_scores = _compute_pagerank(nodes, edges)
    heuristic_scores: dict[str, float] = {}
    entrypoint_signals: dict[str, float] = {}
    file_details: dict[str, tuple[list[str], int, int, float]] = {}

    for path, node in nodes.items():
        score = 0.0
        reasons: list[str] = []
        lower_path = path.lower()
        entrypoint_signal = 0.0
        for pattern, weight in config.filename_weights.items():
            if pattern in lower_path:
                score += weight
                reasons.append(f'filename pattern matched "{pattern}"')
                if pattern in {"main", "app", "server", "cli"}:
                    entrypoint_signal = max(entrypoint_signal, 1.0)
        in_degree = incoming.get(path, 0)
        out_degree = outgoing.get(path, 0)
        if in_degree:
            score += in_degree * 2.0
            reasons.append(
                "high incoming dependency count"
                if in_degree > 1
                else "has incoming dependencies"
            )
        if out_degree:
            score += out_degree * 0.75
            reasons.append(
                "high outgoing dependency count"
                if out_degree > 2
                else "has outgoing dependencies"
            )
        centrality = round(
            (in_degree * CENTRALITY_IN_WEIGHT) + (out_degree * CENTRALITY_OUT_WEIGHT), 2
        )
        if centrality >= 3.0:
            score += centrality
            reasons.append("central in dependency graph")
        role_weight = ROLE_WEIGHTS.get(node.role, 0.0)
        if role_weight:
            score += role_weight
            if node.role == "business_logic":
                reasons.append("located in core/service module")
            elif node.role == "entrypoint":
                reasons.append("filename suggests entrypoint")
                entrypoint_signal = max(entrypoint_signal, 1.0)
            else:
                reasons.append(f'role classified as "{node.role}"')
        if node.role == "api":
            reasons.append("API module")
        if path in imported_by_api:
            reasons.append("imported by API layer")
        if path.startswith(("src/", "app/", "lib/")):
            score += SOURCE_ROOT_BONUS
            reasons.append("located in source directory")
        if node.role in {"config", "test"} and score < 6.0:
            score -= 1.5
            reasons.append("deprioritized non-runtime file")
        if node.size_bytes > 2_000:
            score += 0.5
            reasons.append("larger implementation file")
        heuristic_scores[path] = score
        entrypoint_signals[path] = entrypoint_signal
        file_details[path] = (_unique(reasons), in_degree, out_degree, centrality)

    normalized_heuristics = _normalize_scores(heuristic_scores)
    normalized_pagerank = _normalize_scores(pagerank_scores)
    score_scale = max(max(heuristic_scores.values(), default=0.0), 1.0)

    ranked: list[RankedFile] = []
    for path in nodes:
        reasons, in_degree, out_degree, centrality = file_details[path]
        pagerank_score = pagerank_scores.get(path, 0.0)
        heuristic_score = heuristic_scores.get(path, 0.0)
        blended_score = (
            (normalized_pagerank.get(path, 0.0) * PAGERANK_WEIGHT)
            + (normalized_heuristics.get(path, 0.0) * HEURISTIC_WEIGHT)
            + (entrypoint_signals.get(path, 0.0) * ENTRYPOINT_WEIGHT)
        ) * score_scale
        if pagerank_score > 0.0 and "central in dependency graph" not in reasons:
            reasons = [*reasons, "high PageRank in dependency graph"]
        ranked.append(
            RankedFile(
                path=path,
                score=round(blended_score, 2),
                reasons=reasons,
                in_degree=in_degree,
                out_degree=out_degree,
                centrality=centrality,
                pagerank_score=round(pagerank_score, 6),
                heuristic_score=round(heuristic_score, 2),
            )
        )

    ranked.sort(
        key=lambda item: (
            -item.score,
            -item.pagerank_score,
            -item.heuristic_score,
            item.path,
        )
    )
    return ranked


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _compute_pagerank(
    nodes: dict[str, FileNode],
    edges: list[DependencyEdge],
    damping: float = 0.85,
    max_iterations: int = 100,
    tolerance: float = 1e-9,
) -> dict[str, float]:
    if not nodes:
        return {}

    paths = sorted(nodes)
    count = len(paths)
    base_score = 1.0 / count
    outgoing: dict[str, set[str]] = {path: set() for path in paths}
    incoming: dict[str, list[str]] = {path: [] for path in paths}

    for edge in sorted(edges, key=lambda item: (item.source, item.target)):
        if edge.source not in nodes or edge.target not in nodes:
            continue
        if edge.target in outgoing[edge.source]:
            continue
        outgoing[edge.source].add(edge.target)
        incoming[edge.target].append(edge.source)

    scores = dict.fromkeys(paths, base_score)
    teleport = (1.0 - damping) / count

    for _ in range(max_iterations):
        sink_total = sum(scores[path] for path in paths if not outgoing[path])
        next_scores: dict[str, float] = {}
        max_delta = 0.0
        for path in paths:
            inbound_total = sum(
                scores[source] / len(outgoing[source]) for source in incoming[path]
            )
            score = teleport + (damping * ((sink_total / count) + inbound_total))
            next_scores[path] = score
            max_delta = max(max_delta, abs(score - scores[path]))
        scores = next_scores
        if max_delta <= tolerance:
            break

    total = sum(scores.values())
    if isclose(total, 0.0):
        return dict.fromkeys(paths, 0.0)
    return {path: scores[path] / total for path in paths}


def _normalize_scores(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    minimum = min(scores.values())
    maximum = max(scores.values())
    if isclose(maximum, minimum):
        return dict.fromkeys(scores, 0.0)
    scale = maximum - minimum
    return {path: (value - minimum) / scale for path, value in scores.items()}
