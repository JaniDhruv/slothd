"""CLI interface for slothd.

Usage:
    slothd                             — Interactive command picker
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
import time
import uuid
from pathlib import Path

import click
from rich.markup import escape
from rich.text import Text

from slothd import __version__, ui
from slothd.config import SlothdConfig
from slothd.ui import console


class SlothdGroup(click.Group):
    """Turns uncaught exceptions into one clean error line (full traceback with -vv)."""

    def invoke(self, ctx: click.Context):
        try:
            return super().invoke(ctx)
        except (click.ClickException, click.Abort, click.exceptions.Exit):
            raise
        except KeyboardInterrupt:
            console.print(f"\n  {ui.G.rail_end} [muted]Cancelled.[/]")
            raise SystemExit(130) from None
        except Exception as exc:  # noqa: BLE001
            if ctx.params.get("verbose", 0) >= 2:
                console.print_exception(show_locals=False)
            else:
                message, hint = ui.friendly_error(exc)
                ui.fail(message, hint)
            raise SystemExit(1) from None


@click.group(cls=SlothdGroup, invoke_without_command=True)
@click.version_option(version=__version__, prog_name="slothd")
@click.option("-v", "--verbose", count=True, help="-v for info logs, -vv for debug + tracebacks")
@click.option("-i", "--interactive", is_flag=True, help="Launch interactive command picker")
@click.pass_context
def cli(ctx: click.Context, verbose: int, interactive: bool) -> None:
    """🦥 slothd — The Sloth Daemon: local-first AI file tidier."""
    ui.setup_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["config"] = SlothdConfig.from_env()
    ctx.obj["verbose"] = verbose

    if ctx.invoked_subcommand:
        ui.header(ctx.invoked_subcommand, __version__)
        return

    # If --interactive flag or bare `slothd` with no subcommand -> interactive picker
    if interactive or not ctx.invoked_subcommand:
        _run_interactive(ctx)


def _run_interactive(ctx: click.Context) -> None:
    """Launch the interactive command picker in a loop until exit or Ctrl+C."""
    first_run = True
    while True:
        try:
            choice = ui.interactive_picker(__version__, show_banner=first_run)
            first_run = False
            if not choice or choice == "exit":
                if choice == "exit":
                    console.print()
                    console.print(
                        Text.assemble(
                            ("  ", ""),
                            (ui.G.ok, "ok"),
                            (" ", ""),
                            ("Goodbye! Have a productive, slothful day.", "brand"),
                        )
                    )
                    console.print()
                break

            console.print()

            try:
                if choice == "scan":
                    directory = ui.prompt_source_directory("Which directory to scan?")
                    if directory:
                        ui.header("scan", __version__)
                        ctx.invoke(scan, directory=directory)
                        ui.prompt_press_enter()

                elif choice == "organize":
                    directory = ui.prompt_source_directory("Which directory to organize?")
                    if not directory:
                        continue
                    ok, output_dir = ui.prompt_destination_directory(directory)
                    if not ok:
                        continue
                    use_ai = ui.prompt_confirm("Use AI classification (Gemma 3)?", default=False)
                    if use_ai is None:
                        continue
                    ui.header("organize", __version__)
                    ctx.invoke(organize, directory=directory, output=output_dir, ai=use_ai)

                    apply = ui.prompt_confirm("Apply these planned moves now?", default=False)
                    if apply:
                        ui.header("organize", __version__)
                        ctx.invoke(organize, directory=directory, output=output_dir, go=True, ai=use_ai)
                    ui.prompt_press_enter()

                elif choice == "organize-go":
                    directory = ui.prompt_source_directory("Which directory to organize?")
                    if not directory:
                        continue
                    ok, output_dir = ui.prompt_destination_directory(directory)
                    if not ok:
                        continue
                    use_ai = ui.prompt_confirm("Use AI classification (Gemma 3)?", default=True)
                    if use_ai is None:
                        continue
                    dest_label = ui.tilde(output_dir) if output_dir else f"{ui.tilde(directory)} (in-place)"
                    confirm = ui.prompt_confirm(f"Move files to {dest_label}?", default=True)
                    if not confirm:
                        ui.warn("Cancelled.")
                        continue
                    ui.header("organize", __version__)
                    ctx.invoke(organize, directory=directory, output=output_dir, go=True, ai=use_ai)
                    ui.prompt_press_enter()

                elif choice == "predict":
                    directory = ui.prompt_source_directory("Which directory to analyze with TabPFN?")
                    if directory:
                        ui.header("predict", __version__)
                        ctx.invoke(predict, directory=directory)
                        organize_now = ui.prompt_confirm("Would you like to preview organizing this directory?", default=False)
                        if organize_now:
                            ok, output_dir = ui.prompt_destination_directory(directory)
                            if ok:
                                use_ai = ui.prompt_confirm("Use AI classification (Gemma 3)?", default=False)
                                ui.header("organize", __version__)
                                ctx.invoke(organize, directory=directory, output=output_dir, ai=bool(use_ai))
                                apply = ui.prompt_confirm("Apply these planned moves now?", default=False)
                                if apply:
                                    ui.header("organize", __version__)
                                    ctx.invoke(organize, directory=directory, output=output_dir, go=True, ai=bool(use_ai))
                        ui.prompt_press_enter()

                elif choice == "undo":
                    ui.header("undo", __version__)
                    ctx.invoke(undo)
                    ui.prompt_press_enter()

                elif choice == "search":
                    query = ui.prompt_text("What are you looking for?")
                    if query:
                        ui.header("search", __version__)
                        ctx.invoke(search, query=query)
                        ui.prompt_press_enter()

                elif choice == "daemon":
                    directory = ui.prompt_source_directory("Which directory should daemon watch?")
                    if not directory:
                        continue
                    ok, output_dir = ui.prompt_destination_directory(directory)
                    if not ok:
                        continue
                    use_ai = ui.prompt_confirm("Enable AI classification (Gemma 3)?", default=False)
                    if use_ai is None:
                        continue
                    ui.header("daemon", __version__)
                    ctx.invoke(daemon, watch=directory, output=output_dir, use_ai=use_ai)

                elif choice == "serve":
                    ui.header("serve", __version__)
                    ctx.invoke(serve)

                elif choice == "briefing":
                    ui.header("briefing", __version__)
                    ctx.invoke(briefing)
                    ui.prompt_press_enter()

            except KeyboardInterrupt:
                console.print(f"\n  {ui.G.rail_end} [muted]Stopped.[/]\n")
            except Exception as exc:  # noqa: BLE001
                if ctx.obj.get("verbose", 0) >= 2:
                    console.print_exception(show_locals=False)
                else:
                    message, hint = ui.friendly_error(exc)
                    ui.fail(message, hint)

            console.print()

        except (KeyboardInterrupt, EOFError):
            console.print()
            break


# --------------------------------------------------------------------------- #
# scan
# --------------------------------------------------------------------------- #


@cli.command()
@click.argument("directory", type=click.Path(exists=True, path_type=Path))
@click.option("--max-size", default=50, help="Max file size in MB")
@click.option("--no-recursive", is_flag=True, help="Don't descend into subdirectories")
@click.pass_context
def scan(ctx: click.Context, directory: Path, max_size: int, no_recursive: bool) -> None:
    """Scan a directory and display file statistics."""
    from slothd.engine.scanner import find_duplicates, group_by_category, scan_directory

    ui.step_open(f"Scanning {ui.tilde(directory)}")

    with ui.step(f"Scanning {ui.tilde(directory)}") as s:
        files = scan_directory(directory, max_file_size_mb=max_size, recursive=not no_recursive)
        total = sum(f.size_bytes for f in files)
        s.done(f"Scanned {ui.plural(len(files), 'file')} [muted]{ui.G.dot} {ui.fmt_size(total)}[/]")

    if not files:
        ui.warn("No files found.")
        ui.step_close()
        return

    groups = group_by_category(files)
    rows = sorted(
        ((name, len(items), sum(f.size_bytes for f in items)) for name, items in groups.items()),
        key=lambda row: -row[1],
    )
    ui.section("Files by category")
    ui.category_chart(rows)

    dupes = find_duplicates(files)
    if dupes:
        console.print()
        ui.duplicates_block(dupes)

    ui.step_close()
    ui.next_steps([(f"slothd organize {ui.shell_arg(ui.tilde(directory))}", "preview a tidy-up (dry-run)")])


# --------------------------------------------------------------------------- #
# predict (Prior Labs TabPFN tabular anomaly detection)
# --------------------------------------------------------------------------- #


@cli.command()
@click.argument("directory", type=click.Path(exists=True, path_type=Path))
@click.option("--max-size", default=500, help="Max file size in MB")
@click.option("--no-recursive", is_flag=True, help="Don't descend into subdirectories")
@click.pass_context
def predict(ctx: click.Context, directory: Path, max_size: int, no_recursive: bool) -> None:
    """Predict file categories and spot disk clutter anomalies using Prior Labs TabPFN."""
    from slothd.engine.scanner import scan_directory
    from slothd.engine.tabular_predictor import TabPFNPredictor

    ui.step_open(f"TabPFN Tabular Analysis on {ui.tilde(directory)}")

    with ui.step(f"Scanning {ui.tilde(directory)}") as s:
        files = scan_directory(directory, max_file_size_mb=max_size, recursive=not no_recursive)
        s.done(f"Scanned {ui.plural(len(files), 'file')}")

    if not files:
        ui.warn("No files found.")
        ui.step_close()
        return

    with ui.step("Running Prior Labs TabPFN anomaly detection") as s:
        predictor = TabPFNPredictor()
        result = predictor.analyze_directory(files, base_dir=directory)
        s.done(f"Analyzed with {result.model_used} [muted]{ui.G.dot} {len(result.anomalies)} anomalies[/]")

    ui.anomalies_table(result)
    ui.step_close()
    ui.next_steps([
        (f"slothd organize {ui.shell_arg(ui.tilde(directory))}", "preview auto-sorting this directory"),
        (f"slothd scan {ui.shell_arg(ui.tilde(directory))}", "inspect category breakdown & duplicates"),
    ])


# --------------------------------------------------------------------------- #
# organize
# --------------------------------------------------------------------------- #


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
    started = time.perf_counter()

    mode = ui.badge("LIVE", bg="#4ade80") if go else ui.badge("DRY RUN", bg="#fbbf24")

    dest_display = ui.tilde(output) if output else f"{ui.tilde(directory)} (in-place)"
    ui.step_open("Configuration")
    ui.kv(
        [
            ("Target", ui.tilde(directory)),
            ("Destination", dest_display),
            ("Mode", mode),
            ("AI", ui.toggle("ai", ai, "Gemma 3")),
            ("Web", ui.toggle("web", enrich_online and bool(config.serpapi_key), "SerpApi")),
        ]
    )
    console.print()

    # Step 1: Scan
    with ui.step("Scanning") as s:
        files = scan_directory(directory, max_file_size_mb=max_size)
        s.done(f"Scanned {ui.plural(len(files), 'file')}")

    if not files:
        ui.warn("No files found to organize.")
        ui.step_close()
        return

    # Step 2: AI classification (optional)
    if ai:
        from slothd.engine.classifier import classify_batch

        with ui.step("Classifying with Gemma 3") as s:
            results = classify_batch(
                files,
                ollama_host=config.ollama_host,
                model=config.ollama_model,
                batch_size=batch_size,
            )
            if results:
                s.done(f"Classified {ui.plural(len(results), 'file')} with [accent]Gemma 3[/]")
            else:
                s.done("Using local heuristic classification (Ollama offline)", warn=True)

        # Step 2b: online enrichment (opt-in)
        if enrich_online and not config.serpapi_key:
            ui.warn("--enrich-online needs SERPAPI_KEY; skipping web grounding.")
        elif enrich_online:
            from slothd.engine.enricher import enrich_file_metadata
            from slothd.integrations.serpapi_client import SerpApiClient

            with ui.step("Enriching via SerpApi") as s:
                serp_client = SerpApiClient(config.serpapi_key)
                enriched = sum(1 for f in files[:batch_size] if enrich_file_metadata(f, serp_client))
                s.done(f"Enriched {ui.plural(enriched, 'file')} via SerpApi")

    # Step 3: plan moves
    base_dir = output or directory
    with ui.step("Planning moves") as s:
        moves = plan_moves(files, base_dir)
        s.done(f"Planned {ui.plural(len(moves), 'move')}")

    if not moves:
        ui.success("All files are already organized!")
        ui.step_close()
        return

    # Step 4: show the plan
    ui.section(f"Plan {ui.G.dot} {ui.plural(len(moves), 'file')}")
    ui.moves_tree(moves, base_dir)

    # Step 5: execute or stop
    if not go:
        json_path = Path.home() / ".slothd" / "last_plan.json"
        json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(json_path, "w") as f:
            json.dump([m.to_dict() for m in moves], f, indent=2)

        console.print()
        ui.warn(f"Dry run {ui.G.dot} nothing was moved. [muted]Plan saved to {ui.tilde(json_path)}[/]")
        ui.step_close()

        flags = "".join([" --ai" if ai else "", " --enrich-online" if enrich_online else ""])
        out = f" -o {ui.shell_arg(ui.tilde(output))}" if output else ""
        ui.next_steps(
            [(f"slothd organize {ui.shell_arg(ui.tilde(directory))}{flags}{out} --go", "apply these moves")]
        )
        return

    ops_log = OperationLog(config.ops_db_path)
    search_engine = SearchEngine(
        db_url=config.db_url,
        ollama_host=config.ollama_host,
        embed_model=config.embed_model,
    )
    batch_id = str(uuid.uuid4())[:8]

    try:
        console.print()
        with ui.step(f"Moving {ui.plural(len(moves), 'file')}") as s:
            executed = execute_moves(moves, ops_log, batch_id)
            s.done(f"Moved {ui.plural(len(executed), 'file')}")

        # Index in vector search
        with ui.step("Indexing for search") as s:
            indexed = 0
            files_by_source = {f.path: f for f in files}
            for move in executed:
                f = files_by_source.get(move.source)
                if f:
                    f.path = move.destination
                    try:
                        search_engine.index_scanned_file(f)
                        indexed += 1
                    except Exception:  # noqa: BLE001
                        pass
            if indexed == len(executed):
                s.done(f"Indexed {indexed:,} files for [accent]slothd search[/]")
            else:
                s.done(f"Indexed {indexed:,}/{len(executed):,} files [muted](run with -v to see why)[/]", warn=True)

        ui.step_close()
        console.print()
        ui.success(f"Organized {ui.plural(len(executed), 'file')}", time.perf_counter() - started)
        ui.kv([("Batch", Text(batch_id, style="num")), ("Undo", Text("slothd undo", style="accent"))])
        console.print()
    finally:
        ops_log.close()


# --------------------------------------------------------------------------- #
# undo
# --------------------------------------------------------------------------- #


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
            ui.warn("Nothing to undo — no recent batches found.")
            return

        operations = ops_log.get_batch_operations(batch_id)
        ui.step_open(f"Undoing batch {batch_id}")
        with ui.step(f"Restoring {ui.plural(len(operations), 'file')}") as s:
            restored = undo_last_batch(ops_log)
            ok = restored == len(operations)
            s.done(f"Restored {restored}/{len(operations)} files from batch [num]{batch_id}[/]", warn=not ok)
        ui.step_close()
        console.print()
    finally:
        ops_log.close()


# --------------------------------------------------------------------------- #
# search
# --------------------------------------------------------------------------- #


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

    with ui.step(f'Searching for "{query}"') as s:
        hits = engine.search(query, limit=limit)
        s.done(f'{ui.plural(len(hits), "match", "matches")} for "{escape(query)}"', warn=not hits)

    if not hits:
        ui.next_steps([("slothd organize ~/Downloads --go", "index some files first")])
        return

    console.print()
    ui.search_results(hits)


# --------------------------------------------------------------------------- #
# briefing
# --------------------------------------------------------------------------- #


def _play_audio_file(file_path: Path) -> bool:
    """Attempt to play or open the audio file with the system default player."""
    import os
    import subprocess
    import sys

    try:
        if sys.platform == "win32" and hasattr(os, "startfile"):
            os.startfile(str(file_path))
            return True
        elif sys.platform == "darwin":
            subprocess.Popen(["afplay", str(file_path)])
            return True
        else:
            subprocess.Popen(["xdg-open", str(file_path)])
            return True
    except Exception:
        return False


@cli.command()
@click.option("--save", "-s", type=click.Path(path_type=Path), help="Save audio file to path")
@click.option("--play", "-p", is_flag=True, help="Play audio file using default player after generation")
@click.pass_context
def briefing(ctx: click.Context, save: Path | None, play: bool = False) -> None:
    """Generate and display a sloth voice briefing of organized files."""
    from rich.panel import Panel

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
            Text(f"\"{script}\"", style="italic"),
            title="[brand]ElevenLabs sloth briefing[/]",
            title_align="left",
            border_style="track",
            padding=(1, 2),
        )
    )

    with ui.step("Synthesizing voice with ElevenLabs") as s:
        client = ElevenLabsClient(api_key=config.elevenlabs_api_key, voice_id=config.elevenlabs_voice_id)
        audio_bytes = client.text_to_speech(script)
        s.done(f"Generated {ui.fmt_size(len(audio_bytes))} of audio")

    # If save was not specified via CLI flag, ask interactively
    if not save:
        save_confirm = ui.prompt_confirm("Save this voice briefing to an audio file?", default=True)
        if save_confirm:
            default_name = "sloth_briefing.mp3" if audio_bytes[:3] == b"ID3" or b"LAME" in audio_bytes[:50] or audio_bytes[:2] == b"\xff\xfb" else "sloth_briefing.wav"
            chosen_name = ui.prompt_text("Filename to save as:", default=default_name)
            if chosen_name:
                save = Path(chosen_name).resolve()

    if save:
        save.write_bytes(audio_bytes)
        ui.success(f"Saved to [path]{ui.tilde(save)}[/]")

        # Offer to play audio
        should_play = play
        if not should_play:
            play_confirm = ui.prompt_confirm("Play audio briefing now?", default=True)
            should_play = bool(play_confirm)

        if should_play:
            ui.info(f"Playing [path]{ui.tilde(save)}[/]...")
            _play_audio_file(save)
    else:
        ui.next_steps([("slothd briefing --save briefing.mp3", "write the audio to a file")])


# --------------------------------------------------------------------------- #
# daemon
# --------------------------------------------------------------------------- #


@cli.command()
@click.option("--interval", default=5, help="Check interval in minutes")
@click.option("--idle-threshold", default=300, help="Idle time threshold in seconds")
@click.option("--use-ai", is_flag=True, help="Enable AI classification via Ollama (Gemma 3)")
@click.option("--watch", "-w", type=click.Path(path_type=Path), help="Directory to watch (default: from config)")
@click.option("--output", "-o", type=click.Path(path_type=Path), help="Output directory for organized files")
@click.pass_context
def daemon(
    ctx: click.Context,
    interval: int,
    idle_threshold: int,
    use_ai: bool,
    watch: Path | None = None,
    output: Path | None = None,
) -> None:
    """Start the slothd daemon — organizes files when system is idle."""
    from slothd.daemon.scheduler import start_daemon

    config = ctx.obj["config"]
    target_dirs = [watch] if watch else config.target_dirs
    output_dir = output if output is not None else config.output_dir

    ui.step_open("Daemon configuration")
    ui.kv(
        [
            ("Watching", ", ".join(ui.tilde(d) for d in target_dirs)),
            ("Destination", ui.tilde(output_dir) if output_dir else "In-place"),
            ("Checks", f"every {interval} min"),
            ("Idle after", f"{idle_threshold}s without input"),
            ("AI", ui.toggle("ai", use_ai, "Gemma 3")),
        ]
    )
    console.print()
    ui.info("Daemon running. Sleeping until you step away. [muted]ctrl+c to stop[/]")
    ui.step_close()
    console.print()

    start_daemon(
        target_dirs=target_dirs,
        output_dir=output_dir,
        ops_db_path=config.ops_db_path,
        idle_threshold=idle_threshold,
        interval_minutes=interval,
        max_file_size_mb=config.max_file_size_mb,
        batch_size=config.batch_size,
        use_ai=use_ai,
        ollama_host=config.ollama_host,
        ollama_model=config.ollama_model,
    )


# --------------------------------------------------------------------------- #
# serve
# --------------------------------------------------------------------------- #


@cli.command()
@click.option("--host", default="127.0.0.1", help="Host to bind to (0.0.0.0 exposes it to your network)")
@click.option("--port", default=8000, help="Port to serve on")
@click.pass_context
def serve(ctx: click.Context, host: str, port: int) -> None:
    """Start the web dashboard."""
    import uvicorn

    ui.server_ready(host, port, __version__)

    uvicorn.run(
        "slothd.web.app:app",
        host=host,
        port=port,
        reload=True,
        log_level="info" if ctx.obj["verbose"] else "warning",
    )


if __name__ == "__main__":
    cli()
