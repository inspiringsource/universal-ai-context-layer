from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ai_context_map.commands.check_cmd import check_context
from ai_context_map.commands.export_cmd import export_context
from ai_context_map.commands.generate_cmd import generate_context
from ai_context_map.commands.init_cmd import run_init
from ai_context_map.commands.inspect_cmd import inspect_context

app = typer.Typer(
    help="aicontext: context compiler and maintenance CLI for AI-assisted development."
)


@app.command()
def init(
    path: Annotated[
        Path, typer.Argument(exists=True, file_okay=False, resolve_path=True)
    ] = Path(),
) -> None:
    """Initialize config and provenance files."""
    created = run_init(path)
    if created:
        typer.echo("Created:")
        for item in created:
            typer.echo(f"  - {item}")
    else:
        typer.echo("Nothing to create.")


@app.command()
def generate(
    path: Annotated[
        Path, typer.Argument(exists=True, file_okay=False, resolve_path=True)
    ] = Path(),
) -> None:
    """Generate the canonical UACL context file at .ai/context.yaml."""
    document = generate_context(path)
    typer.echo(f"Project: {document.project.name}")
    typer.echo(f"Languages: {', '.join(document.project.detected_languages) or 'none'}")
    typer.echo(f"Source files: {document.metrics['source_files_analyzed']}")
    typer.echo(f"Edges: {document.metrics['graph_edges']}")
    typer.echo("Top entry points:")
    for entry in document.architecture["entry_points"][:3]:
        typer.echo(f"  - {entry.path} ({entry.confidence:.2f})")


@app.command("export")
def export(
    path: Annotated[
        Path, typer.Argument(exists=True, file_okay=False, resolve_path=True)
    ] = Path(),
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir",
            "-o",
            file_okay=False,
            resolve_path=True,
            help="Directory for preferred UACL exports and compatibility aliases.",
        ),
    ] = None,
    write_agents_md: Annotated[
        bool,
        typer.Option(
            "--write-agents-md",
            help="Also write AGENTS.md at the repository root.",
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Allow --write-agents-md to replace an existing root AGENTS.md.",
        ),
    ] = False,
) -> None:
    """Compile AGENTS.md, Markdown, and JSON context outputs."""
    written, warnings = export_context(path, output_dir, write_agents_md, force)
    typer.echo("Exported:")
    for item in written:
        typer.echo(f"  - {item}")
    for warning in warnings:
        typer.echo(f"Warning: {warning}", err=True)


@app.command()
def check(
    path: Annotated[
        Path, typer.Argument(exists=True, file_okay=False, resolve_path=True)
    ] = Path(),
) -> None:
    """Check the canonical context and compiled outputs for drift."""
    warnings = check_context(path)
    if not warnings:
        typer.echo("Context check passed: no drift warnings.")
        return
    typer.echo(f"Context check found {len(warnings)} warning(s):")
    for warning in warnings:
        typer.echo(f"  - {warning}")


@app.command()
def inspect(
    path: Annotated[
        Path, typer.Argument(exists=True, file_okay=False, resolve_path=True)
    ] = Path(),
) -> None:
    """Print top results from an existing context file."""
    document = inspect_context(path)
    typer.echo("Project goals:")
    for goal in document.get("project_goals", [])[:5]:
        typer.echo(f"  - {goal}")
    typer.echo("Current tasks:")
    for task in document.get("current_tasks", [])[:5]:
        typer.echo(f"  - {task}")
    typer.echo("Decisions:")
    for decision in document.get("decisions", [])[:5]:
        if isinstance(decision, dict):
            title = (
                decision.get("title") or decision.get("decision") or "Untitled decision"
            )
        else:
            title = decision
        typer.echo(f"  - {title}")
    typer.echo("Entry points:")
    for entry in document.get("architecture", {}).get("entry_points", [])[:5]:
        typer.echo(f"  - {entry['path']} ({entry['confidence']})")
    typer.echo("Core modules:")
    for module in document.get("architecture", {}).get("core_modules", [])[:5]:
        typer.echo(f"  - {module['path']} ({module['score']})")
    typer.echo("Hotspots:")
    for hotspot in document.get("hotspots", [])[:5]:
        typer.echo(f"  - {hotspot['path']}: {hotspot['reason']}")


@app.command("inspect-routes")
def inspect_routes(
    path: Annotated[
        Path, typer.Argument(exists=True, file_okay=False, resolve_path=True)
    ] = Path(),
) -> None:
    """Print the planning-oriented routes derived from the generated context file."""
    document = inspect_context(path)
    typer.echo("Task routes:")
    for category, files in document.get("task_routes", {}).items():
        typer.echo(f"{category}:")
        for item in files[:3]:
            typer.echo(f"  - {item['path']}: {', '.join(item.get('reasons', []))}")
    typer.echo("Top anchors:")
    for anchor in document.get("anchors", [])[:5]:
        line = f":{anchor['line']}" if anchor.get("line") else ""
        typer.echo(
            f"  - {anchor['file']}{line} -> {anchor['symbol']} [{anchor['symbol_type']}]"
        )
    typer.echo("Importance reasons:")
    for module in document.get("architecture", {}).get("core_modules", [])[:5]:
        typer.echo(f"  - {module['path']}: {', '.join(module.get('reasons', []))}")


if __name__ == "__main__":
    app()
