from __future__ import annotations

from pathlib import Path
from typing import Any

from ai_context_map.commands.inspect_cmd import inspect_context
from ai_context_map.config import load_config
from ai_context_map.emitter.yaml_writer import write_context_data

SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".md", ".toml", ".yaml", ".yml"}
IGNORED_PARTS = {".ai", ".git", ".venv", "node_modules", "__pycache__"}


def check_context(root: Path) -> list[str]:
    context = inspect_context(root)
    context_path = root / load_config(root).output_path
    warnings = [
        *_missing_referenced_files(root, context),
        *_empty_sections(context),
        *_stale_context(root, context, context_path),
        *_export_warnings(root, context, context_path),
    ]
    if (
        context.get("drift_warnings") != warnings
        or context.get("validation_warnings") != warnings
    ):
        context["drift_warnings"] = warnings
        context["validation_warnings"] = warnings
        write_context_data(context, context_path)
    return warnings


def _missing_referenced_files(root: Path, context: dict[str, Any]) -> list[str]:
    warnings = []
    key_files = context.get("navigation_map", {}).get("key_files", [])
    for item in key_files:
        path = item.get("path")
        if path and not (root / path).exists():
            warnings.append(f"Referenced important file no longer exists: {path}")
    return warnings


def _empty_sections(context: dict[str, Any]) -> list[str]:
    warnings = []
    for section in ("project_goals", "constraints", "current_tasks", "decisions"):
        if not context.get(section):
            warnings.append(f"Important context section is empty: {section}")
    return warnings


def _stale_context(
    root: Path, context: dict[str, Any], context_path: Path
) -> list[str]:
    generated = set(context.get("generated_outputs", []))
    context_mtime = context_path.stat().st_mtime
    for path in root.rglob("*"):
        if (
            path.is_file()
            and path.suffix.lower() in SOURCE_SUFFIXES
            and not IGNORED_PARTS.intersection(path.relative_to(root).parts)
            and str(path.relative_to(root)) not in generated
            and path.stat().st_mtime > context_mtime
        ):
            return [
                f"Canonical context is older than source or documentation: {path.relative_to(root)}"
            ]
    return []


def _export_warnings(
    root: Path, context: dict[str, Any], context_path: Path
) -> list[str]:
    warnings = []
    agents_export = root / ".ai" / "exports" / "AGENTS.md"
    if not agents_export.exists():
        warnings.append("Missing compiled AGENTS.md export: .ai/exports/AGENTS.md")

    context_mtime = context_path.stat().st_mtime
    for output in context.get("generated_outputs", []):
        path = Path(output)
        path = path if path.is_absolute() else root / path
        if not path.exists():
            warnings.append(f"Generated output is missing: {output}")
        elif path.stat().st_mtime < context_mtime:
            warnings.append(f"Generated output is stale: {output}")
    return warnings
