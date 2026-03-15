from __future__ import annotations

from collections import Counter
from pathlib import Path
from time import perf_counter

from ai_context_map.config import load_config
from ai_context_map.emitter.yaml_writer import write_context_yaml
from ai_context_map.graph.builder import GraphBuilder, graph_metrics
from ai_context_map.graph.ranking import rank_files
from ai_context_map.graph.roles import classify_directory_role
from ai_context_map.navigation.anchors import build_anchors
from ai_context_map.navigation.routes import build_task_routes
from ai_context_map.models.context import (
    ContextDocument,
    CoreModule,
    DirectoryRole,
    EntryPoint,
    Hotspot,
    KeyFile,
    NavigationMap,
    ProjectSummary,
    ProvenanceInfo,
)
from ai_context_map.scanner.walker import scan_repository


def generate_context(root: Path) -> ContextDocument:
    started = perf_counter()
    config = load_config(root)
    scan_result = scan_repository(root, config)
    nodes, edges = GraphBuilder().build(scan_result)
    ranked = rank_files(nodes, edges, config)
    metrics = graph_metrics(edges)
    anchors = build_anchors(root, nodes, ranked[:10])
    task_routes = build_task_routes(nodes, edges, ranked)

    entry_points: list[EntryPoint] = []
    core_modules: list[CoreModule] = []
    key_files: list[KeyFile] = []
    hotspots: list[Hotspot] = []

    for item in ranked:
        node = nodes[item.path]
        if node.role in {"test", "config"} and item.score < 8:
            continue
        importance = "critical" if item.score >= 8 else "high" if item.score >= 4 else "medium"
        if len(key_files) < 8:
            key_files.append(KeyFile(path=item.path, role=node.role, importance=importance))
        if node.role == "entrypoint" or any("main" in reason or "entrypoint" in reason for reason in item.reasons):
            confidence = min(0.99, 0.45 + (item.score / 20.0))
            entry_points.append(
                EntryPoint(path=item.path, confidence=round(confidence, 2), reasons=item.reasons[:3])
            )
        core_modules.append(
            CoreModule(
                path=item.path,
                score=item.score,
                reasons=item.reasons[:3],
                pagerank_score=item.pagerank_score,
            )
        )
        if item.pagerank_score > 0.0 and (metrics["incoming"].get(item.path, 0) >= 2 or item.pagerank_score >= 0.15):
            hotspots.append(
                Hotspot(
                    path=item.path,
                    reason="high dependency centrality",
                    score=item.score,
                    pagerank_score=item.pagerank_score,
                )
            )

    dir_counter = Counter(Path(path).parts[0] for path in nodes if Path(path).parts)
    directories = [
        DirectoryRole(path=directory, role=classify_directory_role(directory))
        for directory, _count in sorted(dir_counter.items())
    ]

    detected_languages = sorted(scan_result.languages)
    architecture = {
        "entry_points": entry_points[:5],
        "core_modules": core_modules[:10],
        "top_pagerank_nodes": [
            {"path": item.path, "pagerank_score": item.pagerank_score}
            for item in sorted(ranked, key=lambda ranked_item: (-ranked_item.pagerank_score, ranked_item.path))[:5]
            if item.pagerank_score > 0.0
        ],
        "layers": _infer_layers(nodes),
    }
    document = ContextDocument(
        aicontext_version=2,
        project=ProjectSummary(
            name=root.resolve().name,
            root=".",
            detected_languages=detected_languages,
            summary=None,
        ),
        architecture=architecture,
        navigation_map=NavigationMap(directories=directories, key_files=key_files),
        hotspots=hotspots[:10],
        anchors=anchors,
        task_routes=task_routes,
        constraints=[],
        known_issues=[],
        provenance=ProvenanceInfo(enabled=False, history_file=".ai/history.yaml"),
        metrics={
            "files_scanned": len(scan_result.files),
            "source_files_analyzed": len(nodes),
            "graph_edges": len(edges),
            "generation_time_ms": round((perf_counter() - started) * 1000, 2),
            "top_ranked_files": [item.path for item in ranked[:5]],
            "top_ranked_file_metadata": [
                {"path": item.path, "score": item.score, "pagerank_score": item.pagerank_score}
                for item in ranked[:5]
            ],
        },
    )
    output_path = root / config.output_path
    write_context_yaml(document, output_path)
    return document


def _infer_layers(nodes: dict[str, object]) -> list[dict[str, str]]:
    layers: list[dict[str, str]] = []
    for directory in ("src", "app", "api", "core", "services", "models", "tests"):
        if any(path.startswith(f"{directory}/") or path == directory for path in nodes):
            layers.append({"name": directory, "role": classify_directory_role(directory)})
    return layers
