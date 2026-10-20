"""CLI interface for slothd.

Usage:
    slothd scan ~/Downloads            — Scan and show file stats
    slothd organize ~/Downloads        — Organize files (dry-run by default)
    slothd organize ~/Downloads --go   — Actually move files
    slothd undo                        — Undo the last batch of moves
    slothd search "warranty pdf"       — Search indexed files (requires Tiger Data)
    slothd daemon                      — Start the idle-watching daemon
    slothd serve                       — Start the web dashboard
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from slothd import __version__
from slothd.config import SlothdConfig

# Ensure UTF-8 encoding on Windows PowerShell / cmd
for stream in (sys.stdout, sys.stderr):
    reconfigure_fn = getattr(stream, "reconfigure", None)
    if callable(reconfigure_fn):
        try:
            reconfigure_fn(encoding="utf-8", errors="replace")
        except Exception:
            pass

console = Console()


def _setup_logging(verbose: bool) -> None:
    """Configure logging with rich formatting."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@click.group()
@click.version_option(version=__version__, prog_name="slothd")
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """🦥 slothd — The Sloth Daemon: local-first AI file tidier."""
    _setup_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["config"] = SlothdConfig.from_env()


@cli.command()
@click.argument("directory", type=click.Path(exists=True, path_type=Path))
@click.option("--max-size", default=50, help="Max file size in MB")
@click.option("--no-recursive", is_flag=True, help="Don't descend into subdirectories")
@click.pass_context
def scan(ctx: click.Context, directory: Path, max_size: int, no_recursive: bool) -> None:
    """Scan a directory and display file statistics."""
    from slothd.engine.scanner import find_duplicates, group_by_category, scan_directory

    console.print(
        Panel(
            f"[bold cyan]🦥 Scanning:[/] {directory}",
            subtitle="slothd scanner",
        )
    )

    files = scan_directory(
        directory,
        max_file_size_mb=max_size,
        recursive=not no_recursive,
    )

    if not files:
        console.print("[yellow]No files found.[/]")
        return

    # Summary stats
    total_size = sum(f.size_bytes for f in files)
    console.print(
        f"\n[bold]Found {len(files)} files[/] ({total_size / (1024 * 1024):.1f} MB total)\n"
    )

    # Category breakdown
    groups = group_by_category(files)
    table = Table(title="📁 Files by Category", show_lines=True)
    table.add_column("Category", style="cyan", justify="left")
    table.add_column("Count", style="green", justify="right")
    table.add_column("Size (MB)", style="yellow", justify="right")

    for category, cat_files in sorted(groups.items(), key=lambda x: -len(x[1])):
        size = sum(f.size_bytes for f in cat_files) / (1024 * 1024)
        table.add_row(category, str(len(cat_files)), f"{size:.1f}")

    console.print(table)

    # Duplicates
    dupes = find_duplicates(files)
    if dupes:
        console.print(f"\n[bold red]⚠ Found {len(dupes)} sets of duplicate files![/]")
        for hash_val, dupe_files in list(dupes.items())[:5]:
            names = ", ".join(f.name for f in dupe_files)
            console.print(f"  [dim]{hash_val[:12]}...[/] → {names}")


@cli.command()
@click.argument("directory", type=click.Path(exists=True, path_type=Path))
@click.option("--output", "-o", type=click.Path(path_type=Path), help="Output directory")
@click.option("--go", is_flag=True, help="Actually move files (default is dry-run)")
@click.option("--ai", is_flag=True, help="Use Gemma 3 for AI classification (requires Ollama)")
@click.option(
    "--enrich-online", is_flag=True, help="SerpApi web grounding for vendor & details (opt-in)"
)
@click.option("--max-size", default=50, help="Max file size in MB")
@click.option("--batch-size", default=20, help="Files per batch for AI classification")
@click.pass_context
def organize(
    ctx: click.Context,
    directory: Path,
    output: Path | None,
    go: bool,
    ai: bool,
    enrich_online: bool,
    max_size: int,
    batch_size: int,
) -> None:
    """Organize files in a directory — dry-run by default.

    Use --go to actually move files. Use --ai to enable Gemma 3 classification.
    Use --enrich-online to enable SerpApi web grounding.
    """
    from slothd.engine.organizer import OperationLog, execute_moves, plan_moves
    from slothd.engine.scanner import scan_directory
    from slothd.engine.search import SearchEngine

    config = ctx.obj["config"]

    mode = "[bold green]LIVE[/]" if go else "[bold yellow]DRY-RUN[/]"
    console.print(
        Panel(
            f"[bold cyan]🦥 Organizing:[/] {directory}\n"
            f"Mode: {mode}  |  AI: {'✅' if ai else '❌'}  |  Web Grounding: {'✅' if enrich_online else '❌'}",
            subtitle="slothd organizer",
        )
    )

    # Step 1: Scan
    console.print("\n[dim]Scanning...[/]")
    files = scan_directory(directory, max_file_size_mb=max_size)

    if not files:
        console.print("[yellow]No files found to organize.[/]")
        return

    console.print(f"Found [bold]{len(files)}[/] files.")

    # Step 2: AI Classification (optional)
    if ai:
        console.print("\n[dim]Classifying with Gemma 3...[/]")
        from slothd.engine.classifier import classify_batch

        results = classify_batch(
            files,
            ollama_host=config.ollama_host,
            model=config.ollama_model,
            batch_size=batch_size,
        )
        console.print(f"Classified [bold]{len(results)}[/] files with AI.")

        # Step 2b: Online enrichment (opt-in)
        if enrich_online and config.serpapi_key:
            console.print("[dim]Enriching with SerpApi web grounding...[/]")
            from slothd.engine.enricher import enrich_file_metadata
            from slothd.integrations.serpapi_client import SerpApiClient

            serp_client = SerpApiClient(config.serpapi_key)
            enriched_count = sum(
                1 for f in files[:batch_size] if enrich_file_metadata(f, serp_client)
            )
            console.print(f"Enriched [bold]{enriched_count}[/] files via SerpApi.")

    # Step 3: Plan moves
    base_dir = output or directory
    moves = plan_moves(files, base_dir)

    if not moves:
        console.print("[green]✅ All files are already organized![/]")
        return

    # Step 4: Display plan
    table = Table(title=f"📋 Planned Moves ({len(moves)} files)", show_lines=True)
    table.add_column("File", style="white", max_width=30)
    table.add_column("→ Destination", style="cyan", max_width=50)
    table.add_column("Reason", style="dim")

    for move in moves[:50]:  # Show first 50
        table.add_row(
            move.file_name,
            str(move.destination.relative_to(base_dir))
            if move.destination.is_relative_to(base_dir)
            else str(move.destination),
            move.reason,
        )

    if len(moves) > 50:
        table.add_row(f"... and {len(moves) - 50} more", "", "")

    console.print(table)

    # Step 5: Execute or stop
    if not go:
        console.print(
            "\n[bold yellow]🦥 Dry-run complete.[/] Use [bold]--go[/] to actually move these files."
        )
        # Output JSON for programmatic consumption
        json_output = [m.to_dict() for m in moves]
        json_path = Path.home() / ".slothd" / "last_plan.json"
        json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(json_path, "w") as f:
            json.dump(json_output, f, indent=2)
        console.print(f"[dim]Plan saved to {json_path}[/]")
        return

    # Actually move files
    ops_log = OperationLog(config.ops_db_path)
    search_engine = SearchEngine(
        db_url=config.db_url,
        ollama_host=config.ollama_host,
        embed_model=config.embed_model,
    )
    batch_id = str(uuid.uuid4())[:8]

    try:
        executed = execute_moves(moves, ops_log, batch_id)
        # Index in vector search
        for f in files[: len(executed)]:
            try:
                search_engine.index_scanned_file(f)
            except Exception:
                pass

        console.print(
            f"\n[bold green]✅ Organized {len(executed)} files![/] "
            f"Batch ID: [bold]{batch_id}[/]\n"
            f"[dim]Indexed in Tiger Data / local vector search. Run [bold]slothd undo[/] to reverse this.[/]"
        )
    finally:
        ops_log.close()


@cli.command()
@click.pass_context
def undo(ctx: click.Context) -> None:
    """Undo the most recent batch of file moves."""
    from slothd.engine.organizer import OperationLog, undo_last_batch

    config = ctx.obj["config"]
    ops_log = OperationLog(config.ops_db_path)

    try:
        batch_id = ops_log.get_last_batch()
        if not batch_id:
            console.print("[yellow]Nothing to undo — no recent batches found.[/]")
            return

        operations = ops_log.get_batch_operations(batch_id)
        console.print(f"[bold]Undoing batch [cyan]{batch_id}[/] ({len(operations)} files)...[/]")

        restored = undo_last_batch(ops_log)
        console.print(f"[bold green]✅ Restored {restored}/{len(operations)} files.[/]")
    finally:
        ops_log.close()


@cli.command()
@click.argument("query")
@click.option("--limit", "-l", default=5, help="Number of results to return")
@click.pass_context
def search(ctx: click.Context, query: str, limit: int) -> None:
    """Search indexed files using natural language (Tiger Data pgvector / Local)."""
    from slothd.engine.search import SearchEngine

    config = ctx.obj["config"]
    engine = SearchEngine(
        db_url=config.db_url,
        ollama_host=config.ollama_host,
        embed_model=config.embed_model,
    )

    console.print(
        Panel(
            f'[bold cyan]🔍 Natural Language Search:[/] "{query}"',
            subtitle="Tiger Data pgvector + nomic-embed-text",
        )
    )

    hits = engine.search(query, limit=limit)

    if not hits:
        console.print(
            "[yellow]No matching files found. Try organizing files first to index them.[/]"
        )
        return

    table = Table(title=f"🎯 Search Matches ({len(hits)} hits)", show_lines=True)
    table.add_column("Score", style="bold green", justify="center")
    table.add_column("File Name", style="bold white", max_width=30)
    table.add_column("Category", style="cyan")
    table.add_column("Vendor / Date", style="yellow")
    table.add_column("Path", style="dim", max_width=50)

    for h in hits:
        score_pct = f"{int(h.similarity_score * 100)}%"
        vendor_date = f"{h.vendor or '—'} ({h.file_date or '—'})"
        table.add_row(score_pct, h.file_name, h.category, vendor_date, str(h.file_path))

    console.print(table)


@cli.command()
@click.option("--save", "-s", type=click.Path(path_type=Path), help="Save audio file to path")
@click.pass_context
def briefing(ctx: click.Context, save: Path | None) -> None:
    """Generate and display a sloth voice briefing of organized files."""
    from slothd.engine.organizer import OperationLog
    from slothd.integrations.elevenlabs import ElevenLabsClient, generate_briefing_script

    config = ctx.obj["config"]
    ops_log = OperationLog(config.ops_db_path)
    stats = ops_log.get_stats()
    ops_log.close()

    total_ops = stats.get("total_operations", 0)
    script = generate_briefing_script(
        total_files=total_ops,
        categories={"Documents": total_ops} if total_ops > 0 else {},
    )

    console.print(
        Panel(
            f'[italic white]"{script}"[/]',
            title="🦥 ElevenLabs Sloth Briefing",
            subtitle="Voice summary",
        )
    )

    client = ElevenLabsClient()
    audio_bytes = client.text_to_speech(script)

    if save:
        save.write_bytes(audio_bytes)
        console.print(f"[green]Audio briefing saved to:[/] {save}")
    else:
        console.print(
            f"[dim]Generated {len(audio_bytes)} bytes audio briefing (use --save to write to file)[/]"
        )


@cli.command()
@click.option("--interval", default=5, help="Check interval in minutes")
@click.option("--idle-threshold", default=300, help="Idle time threshold in seconds")
@click.pass_context
def daemon(ctx: click.Context, interval: int, idle_threshold: int) -> None:
    """Start the slothd daemon — organizes files when system is idle."""
    from slothd.daemon.scheduler import start_daemon

    config = ctx.obj["config"]

    console.print(
        Panel(
            f"[bold cyan]🦥 Starting slothd daemon[/]\n"
            f"Watching: {', '.join(str(d) for d in config.target_dirs)}\n"
            f"Interval: {interval} min  |  Idle threshold: {idle_threshold}s",
            subtitle="slothd daemon",
        )
    )

    start_daemon(
        target_dirs=config.target_dirs,
        output_dir=config.output_dir,
        ops_db_path=config.ops_db_path,
        idle_threshold=idle_threshold,
        interval_minutes=interval,
        max_file_size_mb=config.max_file_size_mb,
        batch_size=config.batch_size,
    )


@cli.command()
@click.option("--host", default="0.0.0.0", help="Host to bind to")
@click.option("--port", default=8000, help="Port to serve on")
@click.pass_context
def serve(ctx: click.Context, host: str, port: int) -> None:
    """Start the web dashboard."""
    import uvicorn

    console.print(
        Panel(
            f"[bold cyan]🦥 Starting web dashboard[/]\nURL: http://localhost:{port}",
            subtitle="slothd dashboard",
        )
    )

    uvicorn.run(
        "slothd.web.app:app",
        host=host,
        port=port,
        reload=True,
    )


if __name__ == "__main__":
    cli()
