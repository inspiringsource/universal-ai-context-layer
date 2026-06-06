from __future__ import annotations

from pathlib import Path

from ai_context_map.analyzers.python_symbols import PythonSymbolAnalyzer
from ai_context_map.graph.ranking import RankedFile
from ai_context_map.models.context import Anchor
from ai_context_map.models.graph import FileNode

MAX_ANCHORS = 12
MAX_SYMBOLS_PER_FILE = 3
IMPORTANT_ROLES = {"entrypoint", "api", "business_logic", "data_model", "storage"}


def build_anchors(
    root: Path, nodes: dict[str, FileNode], ranked_files: list[RankedFile]
) -> list[Anchor]:
    analyzer = PythonSymbolAnalyzer()
    anchors: list[Anchor] = []
    for item in ranked_files:
        node = nodes[item.path]
        if node.language != "python":
            continue
        if not _should_extract_from_file(item, node):
            continue
        path = root / item.path
        if not path.exists():
            continue
        symbols = analyzer.extract(path)
        for symbol in _select_symbols(symbols, item):
            anchors.append(
                Anchor(
                    file=item.path,
                    symbol=symbol.name,
                    symbol_type=symbol.symbol_type,
                    line=symbol.line,
                    reasons=symbol.reasons,
                )
            )
            if len(anchors) >= MAX_ANCHORS:
                return anchors
    return anchors


def _should_extract_from_file(item: RankedFile, node: FileNode) -> bool:
    if node.role == "test":
        return False
    if node.role in IMPORTANT_ROLES:
        return True
    return item.score >= 6.0


def _select_symbols(symbols: list, item: RankedFile) -> list:
    priority = {
        "entrypoint": 0,
        "route_handler": 1,
        "class": 2,
        "method": 3,
        "function": 4,
    }
    selected = []
    for symbol in symbols:
        if symbol.symbol_type == "function" and item.score < 7.0:
            continue
        selected.append(symbol)
    selected.sort(
        key=lambda symbol: (
            priority.get(symbol.symbol_type, 99),
            symbol.line or 0,
            symbol.name,
        )
    )
    return selected[:MAX_SYMBOLS_PER_FILE]
