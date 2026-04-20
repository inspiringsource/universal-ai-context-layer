from __future__ import annotations

from pathlib import Path

import typer

from ai_context_map.commands.generate_cmd import generate_context
from ai_context_map.commands.init_cmd import run_init
from ai_context_map.commands.inspect_cmd import inspect_context


app = typer.Typer(help="Generate AI-readable repository context maps.")


@app.command()
def init(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, resolve_path=True)) -> None:
    """Initialize config and provenance files."""
    created = run_init(path)
    if created:
        typer.echo("Created:")
        for item in created:
            typer.echo(f"  - {item}")
    else:
        typer.echo("Nothing to create.")


@app.command()
def generate(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, resolve_path=True)) -> None:
    """Generate .ai/context.yaml for a repository."""
    document = generate_context(path)
    typer.echo(f"Project: {document.project.name}")
    typer.echo(f"Languages: {', '.join(document.project.detected_languages) or 'none'}")
    typer.echo(f"Source files: {document.metrics['source_files_analyzed']}")
    typer.echo(f"Edges: {document.metrics['graph_edges']}")
    typer.echo("Top entry points:")
    for entry in document.architecture["entry_points"][:3]:
        typer.echo(f"  - {entry.path} ({entry.confidence:.2f})")


@app.command()
def inspect(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, resolve_path=True)) -> None:
    """Print top results from an existing context file."""
    document = inspect_context(path)
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
def inspect_routes(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, resolve_path=True)) -> None:
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
        typer.echo(f"  - {anchor['file']}{line} -> {anchor['symbol']} [{anchor['symbol_type']}]")
    typer.echo("Importance reasons:")
    for module in document.get("architecture", {}).get("core_modules", [])[:5]:
        typer.echo(f"  - {module['path']}: {', '.join(module.get('reasons', []))}")


if __name__ == "__main__":
    app()
