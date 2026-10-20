"""File organizer — moves/renames files based on AI classification.

This module handles the actual file operations:
1. Compute destination paths from classification results
2. Handle naming collisions safely
3. Log every operation to SQLite for undo/rollback
4. Support dry-run mode (default) for previewing changes
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from slothd.engine.scanner import ScannedFile

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
#  Operation log (SQLite) for undo/rollback                                   #
# --------------------------------------------------------------------------- #

CREATE_OPS_TABLE = """
CREATE TABLE IF NOT EXISTS operations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id    TEXT    NOT NULL,
    old_path    TEXT    NOT NULL,
    new_path    TEXT    NOT NULL,
    operation   TEXT    NOT NULL DEFAULT 'move',
    created_at  TEXT    NOT NULL,
    undone      INTEGER NOT NULL DEFAULT 0
);
"""

CREATE_BATCH_TABLE = """
CREATE TABLE IF NOT EXISTS batches (
    batch_id    TEXT PRIMARY KEY,
    file_count  INTEGER NOT NULL,
    created_at  TEXT    NOT NULL,
    undone      INTEGER NOT NULL DEFAULT 0
);
"""


class OperationLog:
    """SQLite-backed log of all file operations for undo/rollback.

    Every move is recorded so it can be reversed with `slothd undo`.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute(CREATE_OPS_TABLE)
        self.conn.execute(CREATE_BATCH_TABLE)
        self.conn.commit()

    def log_operation(
        self,
        batch_id: str,
        old_path: Path,
        new_path: Path,
        operation: str = "move",
    ) -> None:
        """Log a single file operation."""
        self.conn.execute(
            "INSERT INTO operations (batch_id, old_path, new_path, operation, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (batch_id, str(old_path), str(new_path), operation, datetime.now().isoformat()),
        )
        self.conn.commit()

    def log_batch(self, batch_id: str, file_count: int) -> None:
        """Log a batch of operations."""
        self.conn.execute(
            "INSERT INTO batches (batch_id, file_count, created_at) VALUES (?, ?, ?)",
            (batch_id, file_count, datetime.now().isoformat()),
        )
        self.conn.commit()

    def get_last_batch(self) -> str | None:
        """Get the most recent non-undone batch ID."""
        cursor = self.conn.execute(
            "SELECT batch_id FROM batches WHERE undone = 0 ORDER BY created_at DESC, rowid DESC LIMIT 1"
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def get_batch_operations(self, batch_id: str) -> list[tuple[str, str]]:
        """Get all operations in a batch as (old_path, new_path) tuples."""
        cursor = self.conn.execute(
            "SELECT old_path, new_path FROM operations WHERE batch_id = ? AND undone = 0 ORDER BY id ASC",
            (batch_id,),
        )
        return cursor.fetchall()

    def mark_batch_undone(self, batch_id: str) -> None:
        """Mark all operations in a batch as undone."""
        self.conn.execute("UPDATE operations SET undone = 1 WHERE batch_id = ?", (batch_id,))
        self.conn.execute("UPDATE batches SET undone = 1 WHERE batch_id = ?", (batch_id,))
        self.conn.commit()

    def get_recent_batches(self, limit: int = 10) -> list[dict]:
        """Get recent batches for the dashboard."""
        cursor = self.conn.execute(
            "SELECT batch_id, file_count, created_at, undone FROM batches "
            "ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (limit,),
        )
        return [
            {
                "batch_id": row[0],
                "file_count": row[1],
                "created_at": row[2],
                "undone": bool(row[3]),
            }
            for row in cursor.fetchall()
        ]

    def get_stats(self) -> dict:
        """Get overall operation statistics."""
        total_ops = self.conn.execute(
            "SELECT COUNT(*) FROM operations WHERE undone = 0"
        ).fetchone()[0]
        total_batches = self.conn.execute(
            "SELECT COUNT(*) FROM batches WHERE undone = 0"
        ).fetchone()[0]
        undone_batches = self.conn.execute(
            "SELECT COUNT(*) FROM batches WHERE undone = 1"
        ).fetchone()[0]
        return {
            "total_operations": total_ops,
            "total_batches": total_batches,
            "undone_batches": undone_batches,
        }

    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()


# --------------------------------------------------------------------------- #
#  Planned move                                                                #
# --------------------------------------------------------------------------- #


@dataclass
class PlannedMove:
    """Represents a planned file move (dry-run output)."""

    source: Path
    destination: Path
    file_name: str
    category: str
    reason: str  # Human-readable explanation

    def to_dict(self) -> dict:
        return {
            "source": str(self.source),
            "destination": str(self.destination),
            "file_name": self.file_name,
            "category": self.category,
            "reason": self.reason,
        }


# --------------------------------------------------------------------------- #
#  Path computation                                                            #
# --------------------------------------------------------------------------- #


def compute_destination(
    scanned_file: ScannedFile,
    base_dir: Path | None = None,
) -> Path:
    """Compute the organized destination path for a file.

    Uses AI classification (if available) or falls back to extension-based
    category. Organizes into: base_dir/Category/YYYY/Month/proposed_name.ext

    Args:
        scanned_file: The classified file.
        base_dir: Base directory for organized files. If None, uses the file's
            parent directory.

    Returns:
        Full destination Path.
    """
    base = base_dir or scanned_file.path.parent

    # Use AI category if available, otherwise fall back to extension-based
    category = scanned_file.ai_category or scanned_file.basic_category

    # Use AI date for year/month structure, or file modification date
    if scanned_file.ai_date:
        try:
            date = datetime.strptime(scanned_file.ai_date, "%Y-%m-%d")
        except ValueError:
            date = scanned_file.modified_at
    else:
        date = scanned_file.modified_at

    year = str(date.year)
    month = date.strftime("%B")  # Full month name

    # Use AI proposed name or original filename
    if scanned_file.ai_proposed_name:
        new_name = f"{scanned_file.ai_proposed_name}{scanned_file.extension}"
    else:
        new_name = scanned_file.name

    # Clean the filename
    new_name = _sanitize_filename(new_name)

    return base / category / year / month / new_name


def _sanitize_filename(name: str) -> str:
    """Remove problematic characters from filenames."""
    # Replace characters that are invalid on Windows/Linux
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, "_")
    # Collapse multiple underscores
    while "__" in name:
        name = name.replace("__", "_")
    return name.strip("_. ")


def resolve_collision(dest: Path) -> Path:
    """Resolve filename collisions by appending a counter.

    Args:
        dest: Intended destination path.

    Returns:
        A path that doesn't conflict with existing files.
    """
    if not dest.exists():
        return dest

    stem = dest.stem
    suffix = dest.suffix
    parent = dest.parent
    counter = 1

    while True:
        new_dest = parent / f"{stem}_{counter}{suffix}"
        if not new_dest.exists():
            return new_dest
        counter += 1


# --------------------------------------------------------------------------- #
#  Core organize function                                                      #
# --------------------------------------------------------------------------- #


def plan_moves(
    files: list[ScannedFile],
    base_dir: Path | None = None,
) -> list[PlannedMove]:
    """Plan all file moves without executing them (dry-run).

    Args:
        files: List of classified ScannedFile objects.
        base_dir: Base directory for organized files.

    Returns:
        List of PlannedMove objects describing what would happen.
    """
    moves: list[PlannedMove] = []
    used_destinations: set[str] = set()

    for f in files:
        dest = compute_destination(f, base_dir)

        # Avoid planning two files to the same destination
        dest_str = str(dest)
        if dest_str in used_destinations:
            dest = resolve_collision(dest)
            dest_str = str(dest)

        used_destinations.add(dest_str)

        # Skip if source == destination (file is already organized)
        if f.path.resolve() == dest.resolve():
            continue

        category = f.ai_category or f.basic_category
        reason = f"Classified as '{category}'"
        if f.ai_vendor:
            reason += f" from {f.ai_vendor}"
        if f.ai_date:
            reason += f" dated {f.ai_date}"

        moves.append(
            PlannedMove(
                source=f.path,
                destination=dest,
                file_name=f.name,
                category=category,
                reason=reason,
            )
        )

    return moves


def execute_moves(
    moves: list[PlannedMove],
    ops_log: OperationLog,
    batch_id: str,
) -> list[PlannedMove]:
    """Execute planned moves — actually move the files.

    Every operation is logged to SQLite for undo capability.

    Args:
        moves: List of planned moves to execute.
        ops_log: OperationLog instance for recording moves.
        batch_id: Unique ID for this batch of operations.

    Returns:
        List of successfully executed moves.
    """
    executed: list[PlannedMove] = []

    for move in moves:
        try:
            # Resolve any collisions with files that already exist on disk
            final_dest = resolve_collision(move.destination)

            # Create destination directory
            final_dest.parent.mkdir(parents=True, exist_ok=True)

            # Move the file
            shutil.move(str(move.source), str(final_dest))

            # Log for undo
            ops_log.log_operation(batch_id, move.source, final_dest)

            # Update the planned move with the actual destination
            move.destination = final_dest
            executed.append(move)

            logger.info("Moved: %s → %s", move.source.name, final_dest)

        except OSError as e:
            logger.error("Failed to move %s: %s", move.source, e)

    # Log the batch
    ops_log.log_batch(batch_id, len(executed))

    return executed


def undo_last_batch(ops_log: OperationLog) -> int:
    """Undo the most recent batch of file moves.

    Moves all files back to their original locations.

    Args:
        ops_log: OperationLog instance.

    Returns:
        Number of files successfully moved back.
    """
    batch_id = ops_log.get_last_batch()
    if not batch_id:
        logger.info("No batches to undo.")
        return 0

    operations = ops_log.get_batch_operations(batch_id)
    restored = 0

    for old_path_str, new_path_str in operations:
        old_path = Path(old_path_str)
        new_path = Path(new_path_str)

        if not new_path.exists():
            logger.warning("Cannot undo: file not found at %s", new_path)
            continue

        try:
            # Ensure the original directory still exists
            old_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(new_path), str(old_path))
            restored += 1
            logger.info("Restored: %s → %s", new_path.name, old_path)
        except OSError as e:
            logger.error("Failed to restore %s: %s", new_path, e)

    ops_log.mark_batch_undone(batch_id)
    logger.info("Undone batch %s: restored %d/%d files", batch_id, restored, len(operations))

    return restored
