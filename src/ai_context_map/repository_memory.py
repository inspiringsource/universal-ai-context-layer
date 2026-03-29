from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from ai_context_map.graph.ranking import RankedFile
from ai_context_map.models.context import TaskRouteFile
from ai_context_map.models.graph import DependencyEdge, FileNode
from ai_context_map.models.memory import (
    CentralFile,
    ClusterSeed,
    RepositoryMemoryDocument,
    RepositoryZone,
    TaskRoutePrior,
    TestMapping,
)
from ai_context_map.models.repo import ScanResult


ZONE_ORDER = (
    "api",
    "config",
    "core",
    "service",
    "tests",
    "utils",
    "cli",
    "models_schema",
    "other",
)

TEST_DIRECTORY_NAMES = {"test", "tests", "__tests__"}
TEST_FILE_PREFIXES = ("test_",)
TEST_FILE_SUFFIXES = ("_test", "_spec", ".spec", ".test")


def build_repository_memory(
    scan_result: ScanResult,
    nodes: dict[str, FileNode],
    edges: list[DependencyEdge],
    ranked_files: list[RankedFile],
    task_routes: dict[str, list[TaskRouteFile]],
) -> RepositoryMemoryDocument:
    repository_zones = _build_repository_zones(scan_result)
    test_mappings = detect_test_mappings(scan_result.files)
    central_files = _build_central_files(ranked_files)
    task_route_priors = _build_task_route_priors(task_routes)
    cluster_seeds = generate_cluster_seeds(nodes, edges, ranked_files, test_mappings)
    return RepositoryMemoryDocument(
        memory_version=1,
        repository_zones=repository_zones,
        cluster_seeds=cluster_seeds,
        test_mappings=test_mappings,
        central_files=central_files,
        task_route_priors=task_route_priors,
    )


def classify_repository_zone(relative_path: str) -> str:
    path = Path(relative_path)
    lowered = relative_path.lower()
    parts = [part.lower() for part in path.parts]
    stem = path.stem.lower()

    if any(part in TEST_DIRECTORY_NAMES for part in parts) or stem.startswith("test_") or any(
        marker in stem for marker in ("_test", "_spec")
    ):
        return "tests"
    if any(part in {"api", "apis"} for part in parts) or any(marker in stem for marker in ("route", "router", "endpoint")):
        return "api"
    if any(part in {"config", "configs", "settings"} for part in parts) or any(
        marker in lowered for marker in (".toml", ".yaml", ".yml", ".json", ".ini", ".env")
    ):
        return "config"
    if any(part in {"cli", "bin", "cmd", "commands"} for part in parts) or stem in {"main", "__main__", "manage"}:
        return "cli"
    if any(part in {"utils", "util", "helpers", "helper", "common"} for part in parts):
        return "utils"
    if any(part in {"models", "model", "schema", "schemas", "dto", "entities"} for part in parts) or any(
        marker in stem for marker in ("model", "schema", "dto", "entity")
    ):
        return "models_schema"
    if any(part in {"services", "service"} for part in parts) or "service" in stem:
        return "service"
    if any(part in {"core", "domain", "logic"} for part in parts) or any(marker in stem for marker in ("core", "logic")):
        return "core"
    return "other"


def detect_test_mappings(files: list[object]) -> list[TestMapping]:
    file_paths = sorted(_relative_path(item) for item in files)
    path_set = set(file_paths)
    basename_index: dict[str, list[str]] = defaultdict(list)
    test_files = [path for path in file_paths if _looks_like_test_path(path)]
    for test_path in test_files:
        basename_index[_normalize_test_name(Path(test_path).stem)].append(test_path)

    mappings: list[TestMapping] = []
    for path in file_paths:
        if _looks_like_test_path(path):
            continue
        base_name = Path(path).stem.lower()
        direct_candidates = sorted(
            candidate
            for candidate in _candidate_test_paths(path)
            if candidate in path_set
        )
        related_by_name = sorted(
            candidate for candidate in basename_index.get(base_name, []) if _suffix_matches(Path(path), Path(candidate))
        )
        tests = sorted(set(direct_candidates + related_by_name))
        if tests:
            mappings.append(TestMapping(implementation=path, tests=tests))
    mappings.sort(key=lambda item: item.implementation)
    return mappings


def generate_cluster_seeds(
    nodes: dict[str, FileNode],
    edges: list[DependencyEdge],
    ranked_files: list[RankedFile],
    test_mappings: list[TestMapping],
) -> list[ClusterSeed]:
    adjacency: dict[str, set[str]] = {path: set() for path in nodes}
    for edge in sorted(edges, key=lambda item: (item.source, item.target)):
        if edge.source in adjacency:
            adjacency[edge.source].add(edge.target)
        if edge.target in adjacency:
            adjacency[edge.target].add(edge.source)

    test_lookup = {mapping.implementation: mapping.tests for mapping in test_mappings}
    ranked_lookup = {item.path: item for item in ranked_files}
    by_role: dict[str, list[str]] = defaultdict(list)
    by_directory: dict[str, list[str]] = defaultdict(list)
    for path, node in sorted(nodes.items()):
        if node.role != "unknown":
            by_role[node.role].append(path)
        directory = str(Path(path).parent)
        by_directory[directory].append(path)

    seeds: list[ClusterSeed] = []
    seen_groups: set[tuple[str, ...]] = set()
    for item in ranked_files[:8]:
        related = {item.path}
        signals: list[str] = []

        neighbors = sorted(adjacency.get(item.path, set()))
        if neighbors:
            related.update(neighbors[:3])
            signals.append("graph_neighbors")

        if item.path in test_lookup:
            related.update(test_lookup[item.path])
            signals.append("test_association")

        same_directory = [path for path in by_directory.get(str(Path(item.path).parent), []) if path != item.path]
        if same_directory:
            related.update(same_directory[:2])
            signals.append("directory_similarity")

        node = nodes.get(item.path)
        if node and node.role != "unknown":
            same_role = [path for path in by_role.get(node.role, []) if path != item.path]
            if same_role:
                same_role.sort(
                    key=lambda path: (
                        -(ranked_lookup.get(path).score if ranked_lookup.get(path) else 0.0),
                        path,
                    )
                )
                related.update(same_role[:2])
                signals.append("role_similarity")

        group = tuple(sorted(related))
        if len(group) < 2 or group in seen_groups:
            continue
        seen_groups.add(group)
        seeds.append(ClusterSeed(label=item.path, files=list(group), signals=signals))

    seeds.sort(key=lambda item: item.label)
    return seeds


def _build_repository_zones(scan_result: ScanResult) -> list[RepositoryZone]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for item in scan_result.files:
        zone = classify_repository_zone(item.relative_path)
        grouped[zone].append(item.relative_path)

    zones: list[RepositoryZone] = []
    for zone in ZONE_ORDER:
        paths = sorted(grouped.get(zone, []))
        if paths:
            zones.append(RepositoryZone(name=zone, paths=paths))
    return zones


def _build_central_files(ranked_files: list[RankedFile]) -> list[CentralFile]:
    return [
        CentralFile(path=item.path, score=item.score, reasons=item.reasons[:3])
        for item in ranked_files[:8]
        if item.score > 0
    ]


def _build_task_route_priors(task_routes: dict[str, list[TaskRouteFile]]) -> list[TaskRoutePrior]:
    priors = [
        TaskRoutePrior(
            category=category,
            files=[item.path for item in files[:5]],
        )
        for category, files in sorted(task_routes.items())
        if files
    ]
    return priors


def _relative_path(item: object) -> str:
    if hasattr(item, "relative_path"):
        return str(getattr(item, "relative_path"))
    return str(item)


def _looks_like_test_path(relative_path: str) -> bool:
    path = Path(relative_path)
    stem = path.stem.lower()
    parts = [part.lower() for part in path.parts]
    return any(part in TEST_DIRECTORY_NAMES for part in parts) or stem.startswith("test_") or any(
        marker in stem for marker in ("_test", "_spec")
    )


def _candidate_test_paths(relative_path: str) -> list[str]:
    path = Path(relative_path)
    stem = path.stem
    suffix = path.suffix
    directory = path.parent
    candidates = [
        str(Path(f"test_{stem}{suffix}")),
        str(Path(f"{stem}_test{suffix}")),
        str(directory / f"test_{stem}{suffix}"),
        str(directory / f"{stem}_test{suffix}"),
        str(Path("tests") / directory / f"test_{stem}{suffix}"),
        str(Path("tests") / directory / f"{stem}_test{suffix}"),
        str(Path("tests") / f"test_{stem}{suffix}"),
        str(Path("tests") / f"{stem}_test{suffix}"),
    ]
    return candidates


def _normalize_test_name(stem: str) -> str:
    normalized = stem.lower()
    for prefix in TEST_FILE_PREFIXES:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
    for suffix in TEST_FILE_SUFFIXES:
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
    return normalized


def _suffix_matches(source: Path, target: Path) -> bool:
    source_parts = tuple(part.lower() for part in source.with_suffix("").parts)
    target_parts = tuple(part.lower() for part in target.with_suffix("").parts)
    normalized_target = tuple(_normalize_test_name(part) for part in target_parts)
    if not normalized_target:
        return False
    return normalized_target[-len(source_parts) :] == source_parts
