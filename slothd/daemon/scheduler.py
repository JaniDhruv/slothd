"""Scheduler — runs the slothd engine on a slow, steady schedule.

Only triggers organization when the system is idle (cross-platform).
Optionally uses Gemma 3 / llama AI classification instead of dumb
extension-based sorting.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler

from slothd.daemon.idle_detector import is_idle
from slothd.engine.organizer import OperationLog, execute_moves, plan_moves
from slothd.engine.scanner import scan_directory

logger = logging.getLogger(__name__)


def _run_organize_cycle(
    target_dirs: list[Path],
    output_dir: Path | None,
    ops_db_path: Path,
    idle_threshold: int,
    max_file_size_mb: int,
    batch_size: int,
    require_idle: bool = True,
    use_ai: bool = False,
    ollama_host: str = "http://localhost:11434",
    ollama_model: str = "gemma3",
) -> None:
    """Single cycle of the organize daemon.

    Checks idle status, scans, optionally classifies with AI, and organizes.
    """
    if require_idle and not is_idle(idle_threshold):
        logger.debug("System is active — skipping this cycle (sloth is waiting...)")
        return

    logger.info("🦥 System is idle — slothd is waking up...")

    ops_log = OperationLog(ops_db_path)

    try:
        all_files = []
        for target_dir in target_dirs:
            if target_dir.is_dir():
                files = scan_directory(
                    target_dir,
                    max_file_size_mb=max_file_size_mb,
                    skip_organized=True,  # Never re-process organized files
                )
                all_files.extend(files)

        if not all_files:
            logger.info("No files to organize. Going back to sleep... 💤")
            return

        batch = all_files[:batch_size]

        # Optionally classify with AI (Gemma 3 / Llama)
        if use_ai:
            try:
                from slothd.engine.classifier import classify_batch

                logger.info("🧠 Running AI classification on %d files...", len(batch))
                classify_batch(
                    batch,
                    ollama_host=ollama_host,
                    model=ollama_model,
                    batch_size=batch_size,
                )
                logger.info("✅ AI classification complete.")
            except Exception as e:
                logger.warning(
                    "AI classification failed, falling back to extension-based: %s", e
                )

        # Use the first target dir (or explicit output_dir) as the
        # organization root so all files consolidate under one tree.
        base_dir = output_dir or target_dirs[0]

        moves = plan_moves(batch, base_dir)

        if not moves:
            logger.info("All files are already organized. 💤")
            return

        batch_id = str(uuid.uuid4())[:8]
        executed = execute_moves(moves, ops_log, batch_id)
        logger.info(
            "🦥 Organized %d files in batch %s. Going back to sleep... 💤",
            len(executed),
            batch_id,
        )
    finally:
        ops_log.close()


def start_daemon(
    target_dirs: list[Path],
    output_dir: Path | None = None,
    ops_db_path: Path = Path.home() / ".slothd" / "operations.db",
    idle_threshold: int = 300,
    interval_minutes: int = 5,
    max_file_size_mb: int = 50,
    batch_size: int = 20,
    use_ai: bool = False,
    ollama_host: str = "http://localhost:11434",
    ollama_model: str = "gemma3",
) -> None:
    """Start the slothd daemon — runs on a schedule, waits for idle.

    Args:
        target_dirs: Directories to watch and organize.
        output_dir: Base directory for organized files.
        ops_db_path: Path to SQLite operations database.
        idle_threshold: Seconds of idle time before activating.
        interval_minutes: How often to check for idle (minutes).
        max_file_size_mb: Maximum file size to process.
        batch_size: Files per batch.
        use_ai: If True, classify files with Gemma 3 / Llama via Ollama.
        ollama_host: Ollama API host URL.
        ollama_model: Ollama model name for classification.
    """
    scheduler = BlockingScheduler()

    scheduler.add_job(
        _run_organize_cycle,
        "interval",
        minutes=interval_minutes,
        args=[target_dirs, output_dir, ops_db_path, idle_threshold, max_file_size_mb, batch_size],
        kwargs={"use_ai": use_ai, "ollama_host": ollama_host, "ollama_model": ollama_model},
        id="slothd_organize",
        name="slothd file organization",
    )

    ai_status = "✅ AI (Ollama)" if use_ai else "❌ extension-only"
    logger.info(
        "🦥 slothd daemon started. Checking every %d minutes, "
        "idle threshold: %d seconds, AI: %s. Press Ctrl+C to stop.",
        interval_minutes,
        idle_threshold,
        ai_status,
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("🦥 slothd daemon stopped. Sweet dreams!")
