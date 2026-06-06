from __future__ import annotations

from pathlib import Path

from ai_context_map.commands.inspect_cmd import inspect_context
from ai_context_map.emitter.portable_writer import write_portable_exports


def export_context(root: Path, output_dir: Path | None = None) -> list[Path]:
    context = inspect_context(root)
    destination = output_dir if output_dir is not None else root / ".ai" / "exports"
    return write_portable_exports(context, destination)
