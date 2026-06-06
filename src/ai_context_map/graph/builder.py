from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from ai_context_map.analyzers.js_ts_analyzer import JsTsAnalyzer
from ai_context_map.analyzers.python_analyzer import PythonAnalyzer
from ai_context_map.graph.roles import classify_role
from ai_context_map.models.graph import DependencyEdge, FileNode, ImportReference
from ai_context_map.models.repo import RepositoryFile, ScanResult

SOURCE_ROOT_HINTS = {"src", "app", "lib"}
JS_EXTENSIONS = [".js", ".jsx", ".ts", ".tsx"]


class GraphBuilder:
    def __init__(self) -> None:
        self.python_analyzer = PythonAnalyzer()
        self.js_analyzer = JsTsAnalyzer()

    def build(
        self, scan_result: ScanResult
    ) -> tuple[dict[str, FileNode], list[DependencyEdge]]:
        source_files = [
            item for item in scan_result.files if item.is_source and item.language
        ]
        nodes = {
            item.relative_path: FileNode(
                path=item.relative_path,
                language=item.language or "unknown",
                role=classify_role(item.relative_path),
                size_bytes=item.size_bytes,
            )
            for item in source_files
        }
        python_modules = self._build_python_module_map(source_files)
        edges: set[tuple[str, str]] = set()

        for item in source_files:
            node = nodes[item.relative_path]
            imports = self._analyze(item)
            node.imports = imports
            resolved = self._resolve_imports(item, imports, python_modules, nodes)
            for target in resolved:
                if target != item.relative_path:
                    edges.add((item.relative_path, target))

        edge_list = [
            DependencyEdge(source=source, target=target)
            for source, target in sorted(edges)
        ]
        return nodes, edge_list

    def _analyze(self, item: RepositoryFile) -> list[ImportReference]:
        if item.language == "python":
            return self.python_analyzer.analyze(item.path)
        if item.language in {"javascript", "typescript"}:
            return self.js_analyzer.analyze(item.path)
        return []

    def _build_python_module_map(self, files: list[RepositoryFile]) -> dict[str, str]:
        module_map: dict[str, str] = {}
        for item in files:
            if item.language != "python":
                continue
            for module_name in self._module_name_candidates(Path(item.relative_path)):
                module_map[module_name] = item.relative_path
        return module_map

    def _module_name_candidates(self, relative_path: Path) -> list[str]:
        parts = list(relative_path.with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        candidates: list[str] = []
        if parts:
            candidates.append(".".join(parts))
        if parts and parts[0] in SOURCE_ROOT_HINTS and len(parts) > 1:
            candidates.append(".".join(parts[1:]))
        return [candidate for candidate in candidates if candidate]

    def _resolve_imports(
        self,
        item: RepositoryFile,
        imports: list[ImportReference],
        python_modules: dict[str, str],
        nodes: dict[str, FileNode],
    ) -> set[str]:
        resolved: set[str] = set()
        if item.language == "python":
            current_module = self._module_name_candidates(Path(item.relative_path))
            current_module_name = current_module[0] if current_module else ""
            current_package_parts = current_module_name.split(".")
            if Path(item.relative_path).stem != "__init__" and current_package_parts:
                current_package_parts = current_package_parts[:-1]
            for ref in imports:
                for module_name in self._expand_python_reference(
                    ref, current_package_parts
                ):
                    if module_name in python_modules:
                        resolved.add(python_modules[module_name])
        elif item.language in {"javascript", "typescript"}:
            base_dir = Path(item.relative_path).parent
            for ref in imports:
                if not ref.module or not ref.module.startswith("."):
                    continue
                module_path = self._resolve_js_path(base_dir, ref.module, nodes)
                if module_path:
                    resolved.add(module_path)
        return resolved

    def _expand_python_reference(
        self, ref: ImportReference, current_package_parts: list[str]
    ) -> list[str]:
        if ref.level:
            ascend = max(ref.level - 1, 0)
            base_parts = (
                current_package_parts[: len(current_package_parts) - ascend]
                if ascend
                else current_package_parts
            )
            module_parts = ref.module.split(".") if ref.module else []
            base_module = ".".join([*base_parts, *module_parts]).strip(".")
            candidates = [base_module] if base_module else []
            for name in ref.names:
                combined = ".".join([part for part in [base_module, name] if part])
                if combined:
                    candidates.append(combined)
            return candidates
        candidates: list[str] = []
        if ref.module:
            candidates.append(ref.module)
            for name in ref.names:
                candidates.append(f"{ref.module}.{name}")
        return candidates

    def _resolve_js_path(
        self, base_dir: Path, module: str, nodes: dict[str, FileNode]
    ) -> str | None:
        target_base = (base_dir / module).as_posix()
        candidates = [target_base]
        candidates.extend(target_base + ext for ext in JS_EXTENSIONS)
        candidates.extend(
            (Path(target_base) / f"index{ext}").as_posix() for ext in JS_EXTENSIONS
        )
        for candidate in candidates:
            if candidate in nodes:
                return candidate
        return None


def graph_metrics(edges: list[DependencyEdge]) -> dict[str, dict[str, int]]:
    incoming: dict[str, int] = defaultdict(int)
    outgoing: dict[str, int] = defaultdict(int)
    for edge in edges:
        outgoing[edge.source] += 1
        incoming[edge.target] += 1
    return {"incoming": dict(incoming), "outgoing": dict(outgoing)}
