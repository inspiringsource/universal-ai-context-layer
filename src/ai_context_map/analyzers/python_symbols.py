from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class PythonSymbol:
    name: str
    symbol_type: str
    line: int | None
    reasons: list[str] = field(default_factory=list)


class PythonSymbolAnalyzer:
    def extract(self, path: Path) -> list[PythonSymbol]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        extractor = _SymbolExtractor()
        extractor.visit(tree)
        return extractor.symbols


class _SymbolExtractor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.symbols: list[PythonSymbol] = []
        self._class_stack: list[str] = []
        self._app_names: set[str] = set()

    def visit_Assign(self, node: ast.Assign) -> None:
        names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        if names and _looks_like_app_initialization(node.value):
            for name in names:
                self._app_names.add(name)
                self.symbols.append(
                    PythonSymbol(
                        name=name,
                        symbol_type="entrypoint",
                        line=getattr(node, "lineno", None),
                        reasons=["app initialization pattern"],
                    )
                )
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        if _is_main_guard(node.test):
            self.symbols.append(
                PythonSymbol(
                    name="__main__",
                    symbol_type="entrypoint",
                    line=getattr(node, "lineno", None),
                    reasons=["contains __main__ entrypoint"],
                )
            )
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.symbols.append(
            PythonSymbol(
                name=node.name,
                symbol_type="class",
                line=getattr(node, "lineno", None),
                reasons=["top-level class definition"],
            )
        )
        self._class_stack.append(node.name)
        for child in node.body:
            self.visit(child)
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._record_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._record_function(node)

    def _record_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if self._class_stack:
            self.symbols.append(
                PythonSymbol(
                    name=f"{self._class_stack[-1]}.{node.name}",
                    symbol_type="method",
                    line=getattr(node, "lineno", None),
                    reasons=["class method on important type"],
                )
            )
            return

        route_reason = _route_reason(node, self._app_names)
        if route_reason is not None:
            self.symbols.append(
                PythonSymbol(
                    name=node.name,
                    symbol_type="route_handler",
                    line=getattr(node, "lineno", None),
                    reasons=[route_reason],
                )
            )
            return

        self.symbols.append(
            PythonSymbol(
                name=node.name,
                symbol_type="function",
                line=getattr(node, "lineno", None),
                reasons=["top-level function"],
            )
        )


def _is_main_guard(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Name)
        and node.left.id == "__name__"
        and len(node.ops) == 1
        and isinstance(node.ops[0], ast.Eq)
        and len(node.comparators) == 1
        and isinstance(node.comparators[0], ast.Constant)
        and node.comparators[0].value == "__main__"
    )


def _looks_like_app_initialization(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func_name = _dotted_name(node.func).lower()
    return func_name.endswith(("fastapi", "flask", "application", "app"))


def _route_reason(node: ast.FunctionDef | ast.AsyncFunctionDef, app_names: set[str]) -> str | None:
    for decorator in node.decorator_list:
        name = _decorator_name(decorator)
        if not name:
            continue
        lowered = name.lower()
        if any(lowered.endswith(f".{method}") for method in ("get", "post", "put", "delete", "patch", "options")):
            return "contains route handlers"
        if app_names and any(lowered.startswith(f"{app_name.lower()}.") for app_name in app_names):
            return "contains route handlers"
        if ".route" in lowered or lowered.endswith(".api_route"):
            return "contains route handlers"
    return None


def _decorator_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call):
        return _dotted_name(node.func)
    return _dotted_name(node)


def _dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""
