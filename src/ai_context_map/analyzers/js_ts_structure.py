"""Tree-sitter structural extraction for JavaScript, JSX, TypeScript, and TSX.

Everything returned here is a syntax fact about one file: declarations, their
source ranges and compact signatures, import/re-export specifiers, and the
names used in call expressions. Nothing here claims which file or function a
call reaches at runtime; import resolution lives in `resolve_module`, and any
call-target matching is done (and labelled as inferred) by the caller.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import cache
from importlib.metadata import version
from pathlib import Path
from posixpath import normpath
from typing import Any

import tree_sitter
import tree_sitter_javascript
import tree_sitter_typescript

# Bump when the shape or meaning of extracted facts changes.
EXTRACTOR_VERSION = 1
GRAMMAR_BY_SUFFIX = {
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
}
RESOLVE_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx")
# Compiled TypeScript ESM imports name the emitted file (`./a.js` for `a.ts`).
EMITTED_TO_SOURCE = {
    ".js": (".ts", ".tsx"),
    ".jsx": (".tsx",),
    ".mjs": (".mts",),
    ".cjs": (".cts",),
}
MAX_SIGNATURE = 160
MAX_CALLS = 12
MAX_ERROR_LINES = 5
FUNCTION_VALUES = {
    "arrow_function",
    "function_expression",
    "function",
    "generator_function",
}
RECOVERY_DECLARATION = re.compile(
    r"(?P<export>export\s+)?(?:declare\s+)?(?:default\s+)?(?:abstract\s+)?"
    r"(?:async\s+)?(?P<keyword>function\*?|class|interface|type|enum|namespace|const|let|var)"
    r"\s+(?P<name>[A-Za-z_$][\w$]*)"
)
SIGNATURE_MODIFIERS = {
    "async",
    "*",
    "static",
    "get",
    "set",
    "abstract",
    "accessibility_modifier",
    "override_modifier",
    "readonly",
}
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "all"}
CLASS_DECLARATIONS = {"class_declaration", "abstract_class_declaration"}


def parser_versions() -> str:
    """Identify the parser stack; cached extraction is only valid for the same one."""
    return (
        ";".join(
            f"{name} {version(name)}"
            for name in (
                "tree-sitter",
                "tree-sitter-javascript",
                "tree-sitter-typescript",
            )
        )
        + f";extractor {EXTRACTOR_VERSION}"
    )


@cache
def _parser(grammar: str) -> tree_sitter.Parser:
    language = {
        "javascript": tree_sitter_javascript.language,
        "typescript": tree_sitter_typescript.language_typescript,
        "tsx": tree_sitter_typescript.language_tsx,
    }[grammar]()
    return tree_sitter.Parser(tree_sitter.Language(language))


@dataclass(slots=True)
class FileStructure:
    grammar: str
    symbols: list[dict[str, Any]] = field(default_factory=list)
    imports: list[dict[str, Any]] = field(default_factory=list)
    identifiers: set[str] = field(default_factory=set)
    # Exported name -> local binding with no declaration here (an import).
    export_bindings: dict[str, str] = field(default_factory=dict)
    # Names introduced by variable declarations at any depth (not uses).
    declared_names: set[str] = field(default_factory=set)
    error_lines: list[int] = field(default_factory=list)

    @property
    def parse_status(self) -> str:
        return "partial" if self.error_lines else "ok"


def _text(node: tree_sitter.Node | None) -> str:
    if node is None or node.text is None:
        return ""
    return node.text.decode("utf-8", "replace")


def _compact(text: str, limit: int = MAX_SIGNATURE) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"([(\[<{]) ", r"\1", text)
    text = re.sub(r",? ([)\]>}])", r"\1", text)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _string_value(node: tree_sitter.Node | None) -> str | None:
    """Literal module specifier, or None for template/computed values."""
    if node is None:
        return None
    if node.type == "string":
        return "".join(
            _text(child) for child in node.named_children if child.type != "comment"
        )
    if node.type == "template_string" and not any(
        child.type == "template_substitution" for child in node.named_children
    ):
        return _text(node)[1:-1]
    return None


def _line(node: tree_sitter.Node) -> int:
    return node.start_point.row + 1


def _end_line(node: tree_sitter.Node) -> int:
    end = node.end_point
    # A node ending at column 0 finished on the previous line.
    return end.row + (1 if end.column else 0) or 1


class _Extractor:
    def __init__(self, data: bytes, grammar: str) -> None:
        self.result = FileStructure(grammar=grammar)
        self.tree = _parser(grammar).parse(data)
        self.scope: list[str] = []
        # Innermost recorded symbol that owns call expressions.
        self.owner: list[dict[str, Any] | None] = [None]
        self.pending_overloads: dict[str, int] = {}
        self.data = data
        self.error_regions: list[tuple[int, int]] = []
        self.local_exports: dict[str, list[str]] = {}

    def run(self) -> FileStructure:
        root = self.tree.root_node
        self._collect_errors(root)
        for child in root.named_children:
            self._visit(child)
        self._recover_declarations()
        self._apply_local_exports()
        self._assign_ids()
        return self.result

    # -- errors -------------------------------------------------------------

    def _collect_errors(self, root: tree_sitter.Node) -> None:
        if not root.has_error:
            return
        lines: list[int] = []
        stack = [root]
        while stack:
            node = stack.pop()
            if node.is_error or node.is_missing:
                if _line(node) not in lines:
                    lines.append(_line(node))
                if node.is_error:
                    self.error_regions.append(
                        (node.start_point.row, node.end_point.row)
                    )
                continue
            if node.has_error:
                stack.extend(reversed(node.children))
        self.result.error_lines = sorted(lines)[:MAX_ERROR_LINES] or [_line(root)]

    def _recover_declarations(self) -> None:
        """Line-scan declaration headers inside ERROR regions only.

        The grammar may reject valid code it does not support; such regions
        would otherwise lose every declaration. Recovered entries are labelled,
        their ranges are estimates, and comments/strings are skipped.
        """
        if not self.error_regions:
            return
        lines = self.data.decode("utf-8", "replace").splitlines()
        known = {(symbol["name"], symbol["line"]) for symbol in self.result.symbols}
        starts = sorted(
            {symbol["line"] for symbol in self.result.symbols if "parent" not in symbol}
        )
        recovered: list[dict[str, Any]] = []
        rows = sorted(
            {row for start, end in self.error_regions for row in range(start, end + 1)}
        )
        region_end = {
            row: max(end for start, end in self.error_regions if start <= row <= end)
            for row in rows
        }
        for row in rows:
            if row >= len(lines):
                break
            match = RECOVERY_DECLARATION.match(lines[row])
            if match is None or (match["name"], row + 1) in known:
                continue
            node = self.tree.root_node.descendant_for_point_range(
                (row, match.start("keyword")), (row, match.start("keyword"))
            )
            if node is not None and node.type in {
                "comment",
                "string_fragment",
                "template_string",
                "string",
            }:
                continue
            kind = {"let": "let", "var": "var", "const": "const"}.get(
                match["keyword"],
                "function"
                if match["keyword"].startswith("function")
                else match["keyword"],
            )
            recovered.append(
                {
                    "name": match["name"],
                    "line": row + 1,
                    "end_line": region_end[row] + 1,
                    "kind": kind,
                    "signature": _compact(
                        lines[row].rstrip("{ ").removeprefix("export ")
                    ),
                    "recovered": True,
                    "syntax_error": True,
                    **({"exported": True} if match["export"] else {}),
                }
            )
        all_starts = sorted(set(starts) | {item["line"] for item in recovered})
        for item in recovered:
            later = [line for line in all_starts if line > item["line"]]
            if later:
                item["end_line"] = max(
                    item["line"], min(item["end_line"], later[0] - 1)
                )
        self.result.symbols.extend(recovered)
        self.result.symbols.sort(key=lambda symbol: symbol["line"])

    # -- symbols ------------------------------------------------------------

    def _record(
        self,
        node: tree_sitter.Node,
        name: str,
        kind: str,
        signature: str,
        outer: tree_sitter.Node | None = None,
        exported: bool = False,
    ) -> dict[str, Any]:
        """Record a declaration; `outer` is the statement including export/decorators."""
        span = outer or node
        qualified = ".".join([*self.scope, name])
        # `line` is the declaration itself; `doc_line` adds decorators and comments.
        start = _line(node)
        doc = min(self._leading_comment_line(span) or _line(span), _line(span))
        if self.scope and name:
            signature = re.sub(
                rf"(?<![\w$.#]){re.escape(name)}(?=[(<\s:=]|$)",
                lambda _: qualified,
                signature,
                count=1,
            )
        symbol: dict[str, Any] = {
            "name": qualified,
            "line": start,
            "end_line": _end_line(span),
            "kind": kind,
            "signature": _compact(signature),
        }
        if doc < start:
            symbol["doc_line"] = doc
        if self.scope:
            symbol["parent"] = ".".join(self.scope)
        if exported:
            symbol["exported"] = True
        if span.has_error or any(
            owner is not None and owner.get("syntax_error") for owner in self.owner
        ):
            symbol["syntax_error"] = True
        overload_start = self.pending_overloads.pop(qualified, None)
        if overload_start is not None and kind in {"function", "method"}:
            symbol["line"] = overload_start
            symbol["overloads"] = True
        self.result.symbols.append(symbol)
        return symbol

    def _leading_comment_line(self, node: tree_sitter.Node) -> int | None:
        """First line of comments directly above a declaration (JSDoc and similar)."""
        first = None
        current = node
        while (
            previous := current.prev_sibling
        ) is not None and previous.type == "comment":
            if _end_line(previous) < _line(current) - 1:
                break
            first = _line(previous)
            current = previous
        return first

    def _visit(
        self, node: tree_sitter.Node, exported: bool = False, outer=None
    ) -> None:
        kind = node.type
        if kind == "comment":
            return
        if kind == "export_statement":
            self._visit_export(node)
            return
        if kind in {"import_statement"}:
            self._visit_import(node)
            return
        if kind == "ambient_declaration":
            for child in node.named_children:
                self._visit(child, exported, outer or node)
            return
        if kind in {"function_declaration", "generator_function_declaration"}:
            self._function(node, exported, outer)
            return
        if kind == "function_signature":
            name = _text(node.child_by_field_name("name"))
            following = (outer or node).next_named_sibling
            while following is not None and following.type == "comment":
                following = following.next_named_sibling
            if following is not None and following.type == "export_statement":
                following = following.child_by_field_name("declaration")
            if (
                following is not None
                and following.type in {"function_declaration", "function_signature"}
                and _text(following.child_by_field_name("name")) == name
            ):
                # Overload signature: attach it to the implementation's range.
                key = ".".join([*self.scope, name])
                self.pending_overloads.setdefault(key, _line(outer or node))
                return
            self._function(node, exported, outer)
            return
        if kind in CLASS_DECLARATIONS or (kind == "class" and outer is not None):
            self._class(node, exported, outer)
            return
        if kind == "interface_declaration":
            name = _text(node.child_by_field_name("name"))
            header = _text(node)[: self._body_offset(node)]
            self._record(node, name, "interface", header, outer, exported)
            self._walk_for_calls(node)
            return
        if kind == "type_alias_declaration":
            name = _text(node.child_by_field_name("name"))
            self._record(node, name, "type", _text(node).rstrip(";"), outer, exported)
            return
        if kind == "enum_declaration":
            name = _text(node.child_by_field_name("name"))
            header = _text(node)[: self._body_offset(node)]
            self._record(node, name, "enum", header, outer, exported)
            return
        if kind in {"internal_module", "module"}:
            self._namespace(node, exported, outer)
            return
        if kind in {"lexical_declaration", "variable_declaration"}:
            for declarator in node.named_children:
                if declarator.type == "variable_declarator":
                    self._declarator(declarator, node, exported, outer)
                else:
                    self._walk_for_calls(declarator)
            return
        if kind == "expression_statement":
            expression = node.named_children[0] if node.named_children else None
            if expression is not None and expression.type == "internal_module":
                self._namespace(expression, exported, outer or node)
                return
            if (
                expression is not None
                and expression.type == "assignment_expression"
                and self._commonjs(expression, node)
            ):
                return
        self._walk_for_calls(node)

    def _body_offset(self, node: tree_sitter.Node) -> int:
        body = node.child_by_field_name("body")
        return (body.start_byte if body else node.end_byte) - node.start_byte

    def _function(self, node, exported: bool, outer) -> None:
        name = _text(node.child_by_field_name("name"))
        if not name:
            return
        symbol = self._record(
            node,
            name,
            "function",
            self._callable_signature(node, name),
            outer,
            exported,
        )
        self._body(node, name, symbol)

    def _callable_signature(self, node, name: str, value=None) -> str:
        """`async name<T>(params): Return` from the declaration or a function value."""
        source = value or node
        # Modifiers are direct children: `async`, `*`, `static`, `get`, `private`...
        prefix = "".join(
            _text(child) + " "
            for child in source.children
            if child.type in SIGNATURE_MODIFIERS
        )
        type_parameters = _text(source.child_by_field_name("type_parameters"))
        parameters = source.child_by_field_name("parameters")
        params = (
            _text(parameters)
            if parameters is not None
            else f"({_text(source.child_by_field_name('parameter'))})"
        )
        returns = _text(source.child_by_field_name("return_type"))
        return f"{prefix}{name}{type_parameters}{params}{returns}"

    def _body(self, node, name: str, symbol: dict[str, Any] | None) -> None:
        body = node.child_by_field_name("body")
        if body is None:
            return
        self.scope.append(name)
        self.owner.append(symbol)
        if body.type in {"statement_block", "class_body"}:
            for child in body.named_children:
                self._visit(child)
        else:
            self._walk_for_calls(body)
        self.owner.pop()
        self.scope.pop()

    def _class(self, node, exported: bool, outer, name: str | None = None) -> None:
        name = name or _text(node.child_by_field_name("name"))
        if not name:
            # Anonymous class (e.g. `export default class {}`).
            name = (
                "default"
                if outer is not None and outer.type == "export_statement"
                else ""
            )
            if not name:
                self._walk_for_calls(node)
                return
        header = _text(node)[: self._body_offset(node)]
        if node.type == "class" and not header.lstrip().startswith("class "):
            header = header.lstrip()
        header = re.sub(r"^(?:@[^\n]*\n\s*)+", "", header)
        symbol = self._record(node, name, "class", header, outer, exported)
        body = node.child_by_field_name("body")
        if body is None:
            return
        self.scope.append(name)
        self.owner.append(symbol)
        members = body.named_children
        for position, member in enumerate(members):
            following = next(
                (m for m in members[position + 1 :] if m.type != "comment"), None
            )
            name = _text(member.child_by_field_name("name"))
            if (
                member.type == "method_signature"
                and following is not None
                and following.type in {"method_definition", "method_signature"}
                and _text(following.child_by_field_name("name")) == name
            ):
                # Overload signature: the implementation's range starts here.
                key = ".".join([*self.scope, name])
                self.pending_overloads.setdefault(key, _line(member))
                continue
            self._member(member)
        self.owner.pop()
        self.scope.pop()

    def _member(self, member) -> None:
        if member.type in {
            "method_definition",
            "abstract_method_signature",
            "method_signature",
        }:
            name = _text(member.child_by_field_name("name"))
            symbol = self._record(
                member, name, "method", self._callable_signature(member, name)
            )
            self._body(member, name, symbol)
        elif member.type in {"public_field_definition", "field_definition"}:
            name = _text(
                member.child_by_field_name("name")
                or member.child_by_field_name("property")
            )
            value = member.child_by_field_name("value")
            if value is not None and value.type in FUNCTION_VALUES and name:
                symbol = self._record(
                    member,
                    name,
                    "method",
                    self._callable_signature(member, name, value),
                )
                self._body(value, name, symbol)
            elif value is not None:
                self._walk_for_calls(value)
        elif member.type == "class_static_block":
            self._walk_for_calls(member)

    def _namespace(self, node, exported: bool, outer) -> None:
        name_node = node.child_by_field_name("name")
        name = (
            _string_value(name_node)
            if name_node and name_node.type == "string"
            else _text(name_node)
        )
        if not name:
            return
        keyword = "module" if node.type == "module" else "namespace"
        symbol = self._record(
            node, name, "namespace", f"{keyword} {_text(name_node)}", outer, exported
        )
        self._body(node, name, symbol)

    def _declarator(self, declarator, statement, exported: bool, outer) -> None:
        name_node = declarator.child_by_field_name("name")
        value = declarator.child_by_field_name("value")
        if name_node is None or name_node.type != "identifier":
            # Destructuring: no single declaration to point at.
            if value is not None:
                self._walk_for_calls(value)
            return
        name = _text(name_node)
        self.result.declared_names.add(name)
        span = outer or statement
        keyword = statement.children[0].type if statement.children else "const"
        if value is not None and value.type in FUNCTION_VALUES:
            symbol = self._record(
                declarator,
                name,
                "function",
                self._callable_signature(declarator, name, value),
                span,
                exported,
            )
            self._body(value, name, symbol)
        elif value is not None and value.type == "class":
            self._class(value, exported, span, name=name)
        elif (
            value is not None and value.type == "object" and not self._inside_function()
        ):
            symbol = self._record(
                declarator, name, keyword, f"{keyword} {name}", span, exported
            )
            self._object(value, name, symbol)
        else:
            if exported or not self._inside_function():
                type_annotation = _text(declarator.child_by_field_name("type"))
                self._record(
                    declarator,
                    name,
                    keyword,
                    f"{keyword} {name}{type_annotation}",
                    span,
                    exported,
                )
            if value is not None:
                self._walk_for_calls(value)

    def _inside_function(self) -> bool:
        return any(
            symbol is not None and symbol["kind"] in {"function", "method"}
            for symbol in self.owner
        )

    def _object(self, node, name: str, owner: dict[str, Any] | None) -> None:
        """Methods of an object literal bound to a name: `api.charge`."""
        self.scope.append(name)
        self.owner.append(owner)
        for member in node.named_children:
            if member.type == "method_definition":
                self._member(member)
            elif member.type == "pair":
                key = member.child_by_field_name("key")
                value = member.child_by_field_name("value")
                if (
                    key is not None
                    and key.type in {"property_identifier", "string"}
                    and value is not None
                    and value.type in FUNCTION_VALUES
                ):
                    key_name = (
                        _string_value(key) if key.type == "string" else _text(key)
                    )
                    symbol = self._record(
                        member,
                        key_name or _text(key),
                        "method",
                        self._callable_signature(member, key_name or _text(key), value),
                    )
                    self._body(value, key_name or _text(key), symbol)
                else:
                    self._walk_for_calls(member)
            else:
                self._walk_for_calls(member)
        self.owner.pop()
        self.scope.pop()

    def _commonjs(self, expression, statement) -> bool:
        """`module.exports = ...`, `exports.x = ...`, `module.exports.x = ...`."""
        if self.scope:
            return False
        left = _text(expression.child_by_field_name("left"))
        right = expression.child_by_field_name("right")
        if right is None:
            return False
        if left == "module.exports":
            if right.type == "identifier":
                self.local_exports.setdefault(_text(right), []).append("module.exports")
                return True
            if right.type == "object":
                for member in right.named_children:
                    if member.type == "shorthand_property_identifier":
                        self.local_exports.setdefault(_text(member), []).append(
                            _text(member)
                        )
                    elif member.type == "pair" and (
                        (value := member.child_by_field_name("value")) is not None
                        and value.type == "identifier"
                    ):
                        self.local_exports.setdefault(_text(value), []).append(
                            _text(member.child_by_field_name("key"))
                        )
                symbol = self._record(
                    expression,
                    "module.exports",
                    "const",
                    "module.exports = {…}",
                    statement,
                    True,
                )
                self._object(right, "module.exports", symbol)
                # `module.exports.x` keeps the conventional name `x` for lookup.
                for item in self.result.symbols:
                    if item.get("parent") == "module.exports":
                        item["exported"] = True
                return True
            if right.type in FUNCTION_VALUES | {"class"}:
                name = _text(right.child_by_field_name("name")) or "module.exports"
                if right.type == "class":
                    self._class(right, True, statement, name=name)
                else:
                    symbol = self._record(
                        right,
                        name,
                        "function",
                        self._callable_signature(right, name, right),
                        statement,
                        True,
                    )
                    self._body(right, name, symbol)
                return True
            return False
        match = re.fullmatch(r"(?:module\.)?exports\.([A-Za-z_$][\w$]*)", left)
        if match is None:
            return False
        name = match.group(1)
        if right.type in FUNCTION_VALUES:
            symbol = self._record(
                right,
                name,
                "function",
                self._callable_signature(right, name, right),
                statement,
                True,
            )
            self._body(right, name, symbol)
        elif right.type == "class":
            self._class(right, True, statement, name=name)
        elif right.type == "identifier":
            self.local_exports.setdefault(_text(right), []).append(name)
        else:
            self._record(right, name, "const", f"exports.{name}", statement, True)
            self._walk_for_calls(right)
        return True

    def _visit_export(self, node) -> None:
        source = _string_value(node.child_by_field_name("source"))
        declaration = node.child_by_field_name("declaration")
        is_default = any(child.type == "default" for child in node.children)
        if source is not None:
            names = self._export_names(node)
            self._import(
                node, source, "reexport", names, type_only=self._type_only(node)
            )
            return
        if declaration is not None:
            if (
                is_default
                and declaration.type
                in {"function_declaration", "generator_function_declaration"}
                and not declaration.child_by_field_name("name")
            ):
                symbol = self._record(
                    declaration,
                    "default",
                    "function",
                    self._callable_signature(declaration, "default"),
                    node,
                    True,
                )
                symbol["default"] = True
                self._body(declaration, "default", symbol)
                return
            before = len(self.result.symbols)
            self._visit(declaration, exported=True, outer=node)
            if is_default and len(self.result.symbols) > before:
                self.result.symbols[before]["default"] = True
            return
        value = node.child_by_field_name("value")
        if value is not None:
            if value.type == "identifier":
                self.local_exports.setdefault(_text(value), []).append("default")
            elif value.type in FUNCTION_VALUES:
                name = _text(value.child_by_field_name("name")) or "default"
                symbol = self._record(
                    value,
                    name,
                    "function",
                    self._callable_signature(value, name, value),
                    node,
                    True,
                )
                symbol["default"] = True
                self._body(value, name, symbol)
            elif value.type == "class":
                before = len(self.result.symbols)
                self._class(
                    value,
                    True,
                    node,
                    name=_text(value.child_by_field_name("name")) or "default",
                )
                if len(self.result.symbols) > before:
                    self.result.symbols[before]["default"] = True
            elif value.type == "object":
                # `export default { a, b: c, m() {} }`: members reachable as default.x
                for member in value.named_children:
                    if member.type == "shorthand_property_identifier":
                        self.local_exports.setdefault(_text(member), []).append(
                            "default." + _text(member)
                        )
                    elif member.type == "pair" and (
                        (target := member.child_by_field_name("value")) is not None
                        and target.type == "identifier"
                    ):
                        key = _text(member.child_by_field_name("key"))
                        self.local_exports.setdefault(_text(target), []).append(
                            "default." + key
                        )
                symbol = self._record(
                    value, "default", "const", "default {…}", node, True
                )
                symbol["default"] = True
                self._object(value, "default", symbol)
            else:
                # `export default <expression>`: a declaration to point at.
                symbol = self._record(
                    value,
                    "default",
                    "value",
                    "default = " + _compact(_text(value).split("\n", 1)[0], 60),
                    node,
                    True,
                )
                symbol["default"] = True
                self.owner.append(symbol)
                self._walk_for_calls(value)
                self.owner.pop()
            return
        for clause in node.named_children:
            if clause.type == "export_clause":
                for specifier in clause.named_children:
                    if specifier.type == "export_specifier":
                        local = _text(specifier.child_by_field_name("name"))
                        alias = _text(specifier.child_by_field_name("alias")) or local
                        self.local_exports.setdefault(local, []).append(alias)
            elif clause.type == "identifier":  # TS `export = name`
                self.local_exports.setdefault(_text(clause), []).append("export=")

    def _export_names(self, node) -> list[str]:
        names: list[str] = []
        for child in node.named_children:
            if child.type == "export_clause":
                for specifier in child.named_children:
                    if specifier.type == "export_specifier":
                        local = _text(specifier.child_by_field_name("name"))
                        alias = _text(specifier.child_by_field_name("alias"))
                        names.append(f"{local} as {alias}" if alias else local)
            elif child.type == "namespace_export":
                names.append("* as " + _text(child.named_children[-1]))
        return names or ["*"]

    def _apply_local_exports(self) -> None:
        declared = {s["name"] for s in self.result.symbols if "parent" not in s}
        for local, aliases in self.local_exports.items():
            if local not in declared:
                # e.g. `import { Hono } from './hono'; export { Hono }`.
                for alias in aliases:
                    self.result.export_bindings[alias] = local
        for symbol in self.result.symbols:
            if "parent" in symbol:
                continue
            aliases = self.local_exports.get(symbol["name"])
            if aliases:
                symbol["exported"] = True
                other = [alias for alias in aliases if alias != symbol["name"]]
                if "default" in other:
                    symbol["default"] = True
                if [alias for alias in other if alias != "default"]:
                    symbol["export_as"] = sorted(set(other) - {"default"})

    def _assign_ids(self) -> None:
        """Stable within a file: the qualified name, plus `#n` for later duplicates."""
        seen: dict[str, int] = {}
        for symbol in self.result.symbols:
            count = seen.get(symbol["name"], 0) + 1
            seen[symbol["name"]] = count
            if count > 1:
                symbol["id"] = f"{symbol['name']}#{count}"

    # -- imports and calls ----------------------------------------------------

    def _type_only(self, node) -> bool:
        return any(child.type == "type" for child in node.children)

    def _visit_import(self, node) -> None:
        source = _string_value(node.child_by_field_name("source"))
        names: list[str] = []
        kind = "import"
        for child in node.named_children:
            if child.type == "import_clause":
                for part in child.named_children:
                    if part.type == "identifier":
                        names.append(f"default as {_text(part)}")
                    elif part.type == "namespace_import":
                        names.append(f"* as {_text(part.named_children[-1])}")
                    elif part.type == "named_imports":
                        for specifier in part.named_children:
                            if specifier.type == "import_specifier":
                                name = _text(specifier.child_by_field_name("name"))
                                alias = _text(specifier.child_by_field_name("alias"))
                                names.append(f"{name} as {alias}" if alias else name)
            elif child.type == "import_require_clause":
                kind = "import-require"
                source = _string_value(child.child_by_field_name("source"))
                names.append(f"* as {_text(child.named_children[0])}")
        if source is not None:
            self._import(node, source, kind, names, self._type_only(node))

    def _import(
        self, node, source: str, kind: str, names: list[str], type_only=False
    ) -> None:
        entry: dict[str, Any] = {"spec": source, "kind": kind, "line": _line(node)}
        if names:
            entry["names"] = names
        if type_only:
            entry["type_only"] = True
        self.result.imports.append(entry)

    def _walk_for_calls(self, node) -> None:
        """Record imports/calls and nested declarations inside expressions."""
        stack = [node]
        while stack:
            current = stack.pop()
            kind = current.type
            if kind == "comment":
                continue
            if kind in {
                "identifier",
                "property_identifier",
                "type_identifier",
                "shorthand_property_identifier",
            }:
                name = _text(current)
                self.result.identifiers.add(name)
                owner = self.owner[-1]
                if owner is not None:
                    # Body vocabulary of the innermost declaration (for ranking).
                    owner.setdefault("identifiers", set()).add(name)
                continue
            if kind in {"string", "template_string"}:
                continue
            if kind == "variable_declarator":
                name = current.child_by_field_name("name")
                if name is not None and name.type == "identifier":
                    self.result.declared_names.add(_text(name))
            if kind == "call_expression":
                function = current.child_by_field_name("function")
                arguments = current.child_by_field_name("arguments")
                first = (
                    arguments.named_children[0]
                    if arguments and arguments.named_children
                    else None
                )
                if function is not None and function.type == "import":
                    spec = _string_value(first)
                    if spec is not None:
                        self._import(current, spec, "dynamic-import", [])
                    else:
                        self._import(
                            current,
                            _compact(_text(first), 60),
                            "dynamic-import-unresolvable",
                            [],
                        )
                elif (
                    function is not None
                    and _text(function) == "require"
                    and first is not None
                ):
                    spec = _string_value(first)
                    if spec is not None:
                        self._import(current, spec, "require", [])
                elif function is not None:
                    self._note_call(function)
                if function is not None and first is not None:
                    self._note_route(current, function, first)
            elif kind in {"jsx_opening_element", "jsx_self_closing_element"}:
                name = current.child_by_field_name("name")
                # Capitalised JSX names are components; lowercase ones are DOM tags.
                if name is not None and _text(name)[:1].isupper():
                    self._note_call(name, "<", ">")
            elif kind == "new_expression":
                constructor = current.child_by_field_name("constructor")
                if constructor is not None:
                    self._note_call(constructor, "new ")
            elif (
                kind
                in {
                    "function_declaration",
                    "generator_function_declaration",
                    "class_declaration",
                }
                and self.owner[-1] is not None
            ):
                # Named declaration nested inside an expression body.
                self._visit(current)
                continue
            stack.extend(reversed(current.children))

    def _note_route(self, call, function, first) -> None:
        """`app.get("/path", handler)`: a route registration, by call shape only.

        Requires a function as the last argument, so client calls such as
        `axios.get("/users", {params})` are not mistaken for registrations.
        """
        if function.type != "member_expression":
            return
        method = _text(function.child_by_field_name("property"))
        path = _string_value(first)
        if method not in HTTP_METHODS or not path or not path.startswith("/"):
            return
        arguments = call.child_by_field_name("arguments")
        last = arguments.named_children[-1] if arguments.named_children else None
        if last is None or last is first or last.type not in FUNCTION_VALUES:
            return
        callee = _text(function.child_by_field_name("object"))
        self._record(
            call,
            f"{method.upper()} {path}",
            "route",
            f"{method.upper()} {_compact(path, 80)} via {_compact(callee, 30)}.{method}(…)",
        )

    def _note_call(self, function, prefix: str = "", suffix: str = "") -> None:
        if function.type not in {
            "identifier",
            "member_expression",
            "nested_identifier",
            "jsx_namespace_name",
        }:
            return
        callee = _text(function)
        if "(" in callee or "\n" in callee or len(callee) > 60:
            return
        owner = self.owner[-1]
        if owner is None:
            return
        calls = owner.setdefault("calls", [])
        name = prefix + callee + suffix
        if name not in calls and len(calls) < MAX_CALLS:
            calls.append(name)


def extract_structure(data: bytes, suffix: str) -> FileStructure:
    """Parse one file. Partial syntax is reported, never raised."""
    grammar = GRAMMAR_BY_SUFFIX.get(suffix.lower())
    if grammar is None:
        raise ValueError(f"No Tree-sitter grammar configured for {suffix!r}")
    extractor = _Extractor(data, grammar)
    return extractor.run()


# -- module resolution ---------------------------------------------------------


@dataclass(slots=True)
class ResolverConfig:
    """`compilerOptions.baseUrl`/`paths` from a root tsconfig.json or jsconfig.json."""

    source: str | None = None
    base_url: str | None = None
    paths: dict[str, list[str]] = field(default_factory=dict)
    note: str | None = None


def _strip_jsonc(text: str) -> str:
    out: list[str] = []
    index = 0
    in_string = False
    while index < len(text):
        char = text[index]
        if in_string:
            out.append(char)
            if char == "\\" and index + 1 < len(text):
                out.append(text[index + 1])
                index += 1
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
            out.append(char)
        elif text.startswith("//", index):
            index = text.find("\n", index)
            if index == -1:
                break
            continue
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            index = len(text) if end == -1 else end + 2
            continue
        else:
            out.append(char)
        index += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def load_resolver_config(root: Path) -> ResolverConfig:
    """Read alias settings from the root config only; `extends` is not followed."""
    for name in ("tsconfig.json", "jsconfig.json"):
        path = root / name
        if not path.is_file() or path.is_symlink():
            continue
        try:
            data = json.loads(_strip_jsonc(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return ResolverConfig(
                source=name,
                note=f"{name} unreadable ({type(exc).__name__}); aliases unresolved",
            )
        options = data.get("compilerOptions") or {}
        base_url = options.get("baseUrl")
        paths = options.get("paths") or {}
        note = (
            f"{name} uses `extends`; inherited aliases are not read"
            if "extends" in data and not paths
            else None
        )
        return ResolverConfig(
            source=name,
            base_url=normpath(base_url) if isinstance(base_url, str) else None,
            paths={
                key: [item for item in value if isinstance(item, str)]
                for key, value in paths.items()
                if isinstance(value, list)
            },
            note=note,
        )
    return ResolverConfig()


def _file_candidates(target: str, typescript_first: bool = False) -> list[str]:
    suffix = Path(target).suffix
    sources = [
        target[: -len(suffix)] + emitted
        for emitted in EMITTED_TO_SOURCE.get(suffix, ())
    ]
    # TypeScript resolves `./a.js` to `a.ts` before an emitted `a.js`.
    candidates = [*sources, target] if typescript_first else [target, *sources]
    candidates += [target + ext for ext in RESOLVE_EXTENSIONS]
    candidates += [f"{target}/index{ext}" for ext in RESOLVE_EXTENSIONS]
    return [normpath(candidate) for candidate in candidates]


def _match_files(
    target: str, known: set[str] | dict[str, Any], typescript_first: bool = False
) -> list[str]:
    if target.startswith("../") or target == "..":
        return []
    found: list[str] = []
    for candidate in _file_candidates(target, typescript_first):
        if candidate in known and candidate not in found:
            found.append(candidate)
    return found


def resolve_module(
    importer: str, spec: str, known: set[str] | dict[str, Any], config: ResolverConfig
) -> tuple[str | None, str, list[str]]:
    """Resolve a specifier to an indexed file.

    Returns (target, status, alternatives). Status is one of: resolved,
    ambiguous (several indexed files fit; TypeScript-style order chose the first),
    alias (resolved through tsconfig/jsconfig paths or baseUrl), unresolved,
    package (bare specifier, not resolved into node_modules), or non-literal.
    """
    if spec.startswith("."):
        target = normpath(f"{Path(importer).parent.as_posix()}/{spec}")
        found = _match_files(target, known, Path(importer).suffix in {".ts", ".tsx"})
        if not found:
            return None, "unresolved", []
        # Several sibling files fit (`a.ts` and `a.js`); a directory index after a
        # file is not a tie, because TypeScript and bundlers try the file first.
        siblings = [path for path in found if not path.startswith(target + "/")]
        if len(siblings) > 1:
            return found[0], "ambiguous", siblings[1:]
        return found[0], "resolved", []
    if spec.startswith("/"):
        return None, "unresolved", []
    for pattern, replacements in config.paths.items():
        if "*" in pattern:
            prefix, _, suffix = pattern.partition("*")
            if not (
                spec.startswith(prefix)
                and spec.endswith(suffix)
                and len(spec) >= len(prefix) + len(suffix)
            ):
                continue
            star = spec[len(prefix) : len(spec) - len(suffix)]
        elif spec != pattern:
            continue
        else:
            star = ""
        for replacement in replacements:
            base = config.base_url or "."
            target = normpath(f"{base}/{replacement.replace('*', star)}")
            found = _match_files(target, known, True)
            if found:
                return found[0], "alias", found[1:]
        return None, "unresolved", []
    if config.base_url is not None:
        found = _match_files(normpath(f"{config.base_url}/{spec}"), known, True)
        if found:
            return found[0], "alias", found[1:]
    return None, "package", []
