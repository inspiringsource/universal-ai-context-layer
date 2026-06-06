from __future__ import annotations

from pathlib import Path

from ai_context_map.commands.inspect_cmd import inspect_context
from ai_context_map.config import load_config
from ai_context_map.emitter.portable_writer import (
    render_agents_markdown,
    write_portable_exports,
)
from ai_context_map.emitter.yaml_writer import write_context_data


def export_context(
    root: Path,
    output_dir: Path | None = None,
    write_agents_md: bool = False,
    force: bool = False,
) -> tuple[list[Path], list[str]]:
    context = inspect_context(root)
    destination = output_dir if output_dir is not None else root / ".ai" / "exports"
    expected = [
        destination / "AGENTS.md",
        destination / "UACL_CONTEXT.md",
        destination / "uacl-context.json",
        destination / "AI_CONTEXT.md",
        destination / "project-context.json",
    ]
    warnings: list[str] = []
    root_agents = root / "AGENTS.md"
    if write_agents_md:
        if root_agents.exists() and not force:
            warnings.append(
                "Root AGENTS.md already exists and was not overwritten. Use --force to replace it."
            )
        else:
            expected.append(root_agents)

    context["generated_outputs"] = [
        _relative_or_absolute(path, root) for path in expected
    ]
    context["drift_warnings"] = []
    context["validation_warnings"] = []
    write_context_data(context, root / load_config(root).output_path)

    written = write_portable_exports(context, destination)
    if write_agents_md and (not root_agents.exists() or force):
        root_agents.write_text(render_agents_markdown(context), encoding="utf-8")
        written.append(root_agents)
    return written, warnings


def _relative_or_absolute(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
