from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Annotated

import typer

from ai_context_map.commands.check_cmd import check_context
from ai_context_map.commands.export_cmd import export_context
from ai_context_map.commands.generate_cmd import generate_context
from ai_context_map.commands.init_cmd import run_init
from ai_context_map.commands.inspect_cmd import inspect_context
from ai_context_map.navigation.index import (
    load_index,
    pack_context,
    render_brief,
)
from ai_context_map.workstate.checkpoint import (
    TEMPLATE,
    briefing_sections,
    is_current,
    load_checkpoint,
    render_checkpoint,
    update_checkpoint,
)
from ai_context_map.workstate.evidence import (
    EXIT_CAPTURE_FAILED,
    CaptureError,
    full_stream_path,
    list_evidence,
    run_capture,
    show_evidence,
)
from ai_context_map.workstate.store import find_root

app = typer.Typer(
    help="aicontext: context compiler and maintenance CLI for AI-assisted development."
)
checkpoint_app = typer.Typer(
    help="Record and inspect an explicit working checkpoint in .ai/work/."
)
evidence_app = typer.Typer(help="Retrieve captured command output in bounded views.")
app.add_typer(checkpoint_app, name="checkpoint")
app.add_typer(evidence_app, name="evidence")

RootOption = Annotated[
    Path | None,
    typer.Option(
        "--root",
        file_okay=False,
        resolve_path=True,
        help="Repository root (default: nearest ancestor with .ai or .git).",
    ),
]


def _root(root: Path | None) -> Path:
    return root or find_root(Path.cwd())


def _fail(exc: Exception) -> typer.Exit:
    typer.echo(f"Error: {exc}", err=True)
    return typer.Exit(1)


@app.command()
def pack(
    path: Annotated[
        Path, typer.Argument(exists=True, file_okay=False, resolve_path=True)
    ] = Path(),
    task: Annotated[
        str, typer.Option("--task", help="Task or symbol to prioritize.")
    ] = "",
    max_chars: Annotated[
        int,
        typer.Option(
            "--max-chars",
            min=1200,
            help="Entry-file character budget; not a token estimate.",
        ),
    ] = 6000,
) -> None:
    """Build a small START_HERE.md (with the working checkpoint) and a pointer index."""
    try:
        state = load_checkpoint(path)
        if not task and state is not None:
            # Default the pointer query to the recorded objective and next action.
            task = " ".join(
                r["text"]
                for r in state["records"]
                if r["kind"] in {"objective", "next"} and is_current(r)
            )
        sections = briefing_sections(path, state)
        output, index, brief = pack_context(path, task, max_chars, sections)
    except (ValueError, OSError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Entry file: {output}")
    typer.echo(
        "Checkpoint: "
        + (
            "none recorded (entry file says so)"
            if state is None
            else f"{sections[2]['current']} current records; see entry-file footer for omissions"
        )
    )
    typer.echo(f"Indexed files: {len(index['records'])}")
    typer.echo(
        f"Entry size: {len(brief)} characters (budget {max_chars}); no model calls."
    )
    typer.echo(
        "In a fresh agent session: read .ai/START_HERE.md and follow its references."
    )
    for warning in index["warnings"]:
        typer.echo(f"Warning: {warning}", err=True)


@app.command("find")
def find_references(
    query: Annotated[str, typer.Argument(help="Task, filename, symbol, or heading.")],
    path: Annotated[
        Path, typer.Argument(exists=True, file_okay=False, resolve_path=True)
    ] = Path(),
    limit: Annotated[int, typer.Option("--limit", min=1, max=20)] = 6,
    max_chars: Annotated[int, typer.Option("--max-chars", min=1200)] = 6000,
) -> None:
    """Retrieve a bounded set of references without loading source bodies."""
    try:
        typer.echo(
            render_brief(path, load_index(path), query, max_chars, limit), nl=False
        )
    except (ValueError, OSError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)
def capture(
    command: Annotated[
        list[str], typer.Argument(help="Command and arguments, after --.")
    ],
    label: Annotated[str, typer.Option("--label", help="Short description.")] = "",
    preview_lines: Annotated[int, typer.Option("--preview-lines", min=0, max=200)] = 12,
    preview_chars: Annotated[
        int, typer.Option("--preview-chars", min=200, max=20000)
    ] = 1500,
    root: RootOption = None,
) -> None:
    """Run a command (no shell), keep full output on disk, print a bounded receipt.

    Example: aicontext capture --label "tests" -- uv run pytest -q
    Exits with the command's status; 125 if evidence could not be preserved.
    """
    try:
        code, receipt = run_capture(
            _root(root), command, label, preview_lines, preview_chars
        )
    except CaptureError as exc:
        typer.echo(f"Capture failed: {exc}", err=True)
        raise typer.Exit(EXIT_CAPTURE_FAILED) from exc
    typer.echo(receipt, nl=False)
    raise typer.Exit(code)


@evidence_app.command("show")
def evidence_show(
    evidence_id: Annotated[str, typer.Argument(help="Evidence ID, e.g. ev-...")],
    stream: Annotated[
        str | None, typer.Option("--stream", help="stdout or stderr.")
    ] = None,
    lines: Annotated[
        str | None, typer.Option("--lines", help="Line range such as 120-180.")
    ] = None,
    grep: Annotated[
        str | None, typer.Option("--grep", help="Show lines matching a regex.")
    ] = None,
    full: Annotated[
        bool, typer.Option("--full", help="Print one raw stream, unbounded.")
    ] = False,
    max_chars: Annotated[int, typer.Option("--max-chars", min=200)] = 4000,
    root: RootOption = None,
) -> None:
    """Show captured output: bounded and line-numbered unless --full."""
    if stream not in {None, "stdout", "stderr"}:
        raise _fail(ValueError("--stream must be stdout or stderr."))
    try:
        if full:
            path, integrity = full_stream_path(
                _root(root), evidence_id, stream or "stdout"
            )
            if integrity != "current":
                typer.echo(
                    f"WARNING: {path.name} is {integrity}; not the original capture.",
                    err=True,
                )
            with path.open("rb") as handle:
                sys.stdout.flush()
                shutil.copyfileobj(handle, sys.stdout.buffer)
            return
        typer.echo(
            show_evidence(_root(root), evidence_id, stream, lines, grep, max_chars),
            nl=False,
        )
    except (ValueError, OSError) as exc:
        raise _fail(exc) from exc


@evidence_app.command("list")
def evidence_list(
    limit: Annotated[int, typer.Option("--limit", min=1)] = 20,
    root: RootOption = None,
) -> None:
    """List captured evidence, newest first, with integrity status."""
    try:
        typer.echo(list_evidence(_root(root), limit), nl=False)
    except (ValueError, OSError) as exc:
        raise _fail(exc) from exc


@checkpoint_app.command("update")
def checkpoint_update(
    source: Annotated[
        str, typer.Argument(help="JSON file path, or - for standard input.")
    ] = "-",
    root: RootOption = None,
) -> None:
    """Add, replace, or supersede checkpoint records from JSON (atomic, validated)."""
    try:
        raw = sys.stdin.read() if source == "-" else Path(source).read_text("utf-8")
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise _fail(ValueError(f"Cannot read JSON input: {exc}")) from exc
    try:
        for line in update_checkpoint(_root(root), payload):
            typer.echo(line)
    except (ValueError, OSError) as exc:
        typer.echo("Checkpoint unchanged.", err=True)
        raise _fail(exc) from exc


@checkpoint_app.command("show")
def checkpoint_show(
    show_all: Annotated[
        bool, typer.Option("--all", help="Include superseded and retired records.")
    ] = False,
    record_id: Annotated[
        str | None, typer.Option("--id", help="Print one record as JSON.")
    ] = None,
    as_json: Annotated[
        bool, typer.Option("--json", help="Raw checkpoint JSON.")
    ] = False,
    root: RootOption = None,
) -> None:
    """Print the current checkpoint."""
    try:
        state = load_checkpoint(_root(root))
        if as_json:
            typer.echo(json.dumps(state, indent=2, ensure_ascii=False))
            return
        typer.echo(render_checkpoint(_root(root), state, show_all, record_id), nl=False)
    except (ValueError, OSError) as exc:
        raise _fail(exc) from exc


@checkpoint_app.command("template")
def checkpoint_template() -> None:
    """Print an example update payload covering every record kind."""
    typer.echo(json.dumps(TEMPLATE, indent=2))


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
