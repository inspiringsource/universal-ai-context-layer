from __future__ import annotations

from dataclasses import dataclass

from ai_context_map.config import Config
from ai_context_map.models.graph import DependencyEdge, FileNode


@dataclass(slots=True)
class RankedFile:
    path: str
    score: float
    reasons: list[str]


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


def rank_files(
    nodes: dict[str, FileNode], edges: list[DependencyEdge], config: Config
) -> list[RankedFile]:
    incoming = {path: 0 for path in nodes}
    outgoing = {path: 0 for path in nodes}
    for edge in edges:
        incoming[edge.target] = incoming.get(edge.target, 0) + 1
        outgoing[edge.source] = outgoing.get(edge.source, 0) + 1

    ranked: list[RankedFile] = []
    for path, node in nodes.items():
        score = 0.0
        reasons: list[str] = []
        lower_path = path.lower()
        for pattern, weight in config.filename_weights.items():
            if pattern in lower_path:
                score += weight
                reasons.append(f'filename pattern matched "{pattern}"')
        in_degree = incoming.get(path, 0)
        out_degree = outgoing.get(path, 0)
        if in_degree:
            score += in_degree * 2.0
            reasons.append("high incoming dependency count" if in_degree > 1 else "has incoming dependencies")
        if out_degree:
            score += out_degree * 0.75
            reasons.append("high outgoing dependency count" if out_degree > 2 else "has outgoing dependencies")
        role_weight = ROLE_WEIGHTS.get(node.role, 0.0)
        if role_weight:
            score += role_weight
            reasons.append(f'role classified as "{node.role}"')
        if path.startswith(("src/", "app/", "lib/")):
            score += SOURCE_ROOT_BONUS
            reasons.append("located in source directory")
        if node.size_bytes > 2_000:
            score += 0.5
            reasons.append("larger implementation file")
        ranked.append(RankedFile(path=path, score=round(score, 2), reasons=_unique(reasons)))

    ranked.sort(key=lambda item: (-item.score, item.path))
    return ranked


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result

