"""Tests for the file organizer module."""

from __future__ import annotations

from pathlib import Path

from slothd.engine.organizer import (
    OperationLog,
    PlannedMove,
    compute_destination,
    execute_moves,
    plan_moves,
    resolve_collision,
    undo_last_batch,
)
from slothd.engine.scanner import scan_directory, scan_file


class TestComputeDestination:
    """Tests for compute_destination()."""

    def test_basic_destination(self, tmp_path: Path) -> None:
        """Files get organized into Category/Year/Month structure."""
        f = tmp_path / "notes.txt"
        f.write_text("test content")
        scanned = scan_file(f)

        dest = compute_destination(scanned, tmp_path)

        # Should be something like: tmp_path/Documents/2026/October/notes.txt
        assert "Documents" in str(dest)
        assert dest.name == "notes.txt"

    def test_ai_classification_overrides_extension(self, tmp_path: Path) -> None:
        """AI category takes precedence over extension-based category."""
        f = tmp_path / "receipt.png"
        f.write_bytes(b"\x89PNG test")
        scanned = scan_file(f)
        scanned.ai_category = "Receipts"
        scanned.ai_vendor = "Amazon"
        scanned.ai_date = "2026-10-15"
        scanned.ai_proposed_name = "Receipt_Amazon_2026-10-15_Headphones"

        dest = compute_destination(scanned, tmp_path)

        assert "Receipts" in str(dest)
        assert "2026" in str(dest)
        assert "October" in str(dest)
        assert "Amazon" in dest.name

    def test_falls_back_to_extension_category(self, tmp_path: Path) -> None:
        """Without AI classification, uses extension-based category."""
        f = tmp_path / "data.csv"
        f.write_text("a,b,c")
        scanned = scan_file(f)

        dest = compute_destination(scanned, tmp_path)

        assert "Spreadsheets" in str(dest)


class TestResolveCollision:
    """Tests for resolve_collision()."""

    def test_no_collision_returns_same_path(self, tmp_path: Path) -> None:
        """If no file exists at the destination, return it unchanged."""
        dest = tmp_path / "new_file.txt"
        assert resolve_collision(dest) == dest

    def test_collision_appends_counter(self, tmp_path: Path) -> None:
        """If a file exists, append _1, _2, etc."""
        existing = tmp_path / "notes.txt"
        existing.write_text("existing")

        result = resolve_collision(tmp_path / "notes.txt")

        assert result == tmp_path / "notes_1.txt"
        assert not result.exists()

    def test_multiple_collisions(self, tmp_path: Path) -> None:
        """Handles multiple collisions by incrementing counter."""
        (tmp_path / "notes.txt").write_text("v1")
        (tmp_path / "notes_1.txt").write_text("v2")
        (tmp_path / "notes_2.txt").write_text("v3")

        result = resolve_collision(tmp_path / "notes.txt")

        assert result == tmp_path / "notes_3.txt"


class TestPlanMoves:
    """Tests for plan_moves()."""

    def test_plans_moves_for_all_files(self, messy_downloads: Path) -> None:
        """All files get planned moves."""
        files = scan_directory(messy_downloads)
        moves = plan_moves(files, messy_downloads)

        # All files should have planned moves (since none are organized yet)
        assert len(moves) > 0
        assert len(moves) <= len(files)

    def test_planned_move_has_category(self, small_dir: Path) -> None:
        """Each planned move includes the target category."""
        files = scan_directory(small_dir)
        moves = plan_moves(files, small_dir)

        for move in moves:
            assert move.category in ("Documents", "Images", "Archives", "Other", "Code")

    def test_planned_move_serializable(self, small_dir: Path) -> None:
        """PlannedMove.to_dict() produces JSON-serializable output."""
        files = scan_directory(small_dir)
        moves = plan_moves(files, small_dir)

        for move in moves:
            d = move.to_dict()
            assert isinstance(d["source"], str)
            assert isinstance(d["destination"], str)
            assert isinstance(d["category"], str)


class TestOperationLog:
    """Tests for the SQLite operation log."""

    def test_log_and_retrieve_operations(self, tmp_path: Path) -> None:
        """Operations can be logged and retrieved."""
        db_path = tmp_path / "ops.db"
        log = OperationLog(db_path)

        log.log_operation("batch-1", Path("/old/a.txt"), Path("/new/a.txt"))
        log.log_operation("batch-1", Path("/old/b.txt"), Path("/new/b.txt"))
        log.log_batch("batch-1", 2)

        ops = log.get_batch_operations("batch-1")
        assert len(ops) == 2
        log.close()

    def test_get_last_batch(self, tmp_path: Path) -> None:
        """get_last_batch returns the most recent non-undone batch."""
        db_path = tmp_path / "ops.db"
        log = OperationLog(db_path)

        log.log_batch("batch-1", 3)
        log.log_batch("batch-2", 5)

        assert log.get_last_batch() == "batch-2"
        log.close()

    def test_mark_batch_undone(self, tmp_path: Path) -> None:
        """Marking a batch as undone excludes it from get_last_batch."""
        db_path = tmp_path / "ops.db"
        log = OperationLog(db_path)

        log.log_batch("batch-1", 3)
        log.log_batch("batch-2", 5)
        log.mark_batch_undone("batch-2")

        assert log.get_last_batch() == "batch-1"
        log.close()

    def test_stats(self, tmp_path: Path) -> None:
        """get_stats returns correct counts."""
        db_path = tmp_path / "ops.db"
        log = OperationLog(db_path)

        log.log_operation("b1", Path("/a"), Path("/b"))
        log.log_operation("b1", Path("/c"), Path("/d"))
        log.log_batch("b1", 2)

        stats = log.get_stats()
        assert stats["total_operations"] == 2
        assert stats["total_batches"] == 1
        assert stats["undone_batches"] == 0
        log.close()

    def test_empty_log(self, tmp_path: Path) -> None:
        """Empty log returns None for last batch and zero stats."""
        db_path = tmp_path / "ops.db"
        log = OperationLog(db_path)

        assert log.get_last_batch() is None
        assert log.get_stats()["total_operations"] == 0
        log.close()


class TestExecuteMoves:
    """Tests for execute_moves() — actual file operations."""

    def test_moves_files_to_destination(self, small_dir: Path) -> None:
        """Files are actually moved to their planned destinations."""
        files = scan_directory(small_dir)
        moves = plan_moves(files, small_dir)

        db_path = small_dir / ".ops.db"
        ops_log = OperationLog(db_path)

        executed = execute_moves(moves, ops_log, "test-batch")

        assert len(executed) > 0
        for move in executed:
            assert move.destination.exists()
            assert not move.source.exists()

        ops_log.close()

    def test_creates_directories(self, tmp_path: Path) -> None:
        """Destination directories are created automatically."""
        f = tmp_path / "test.txt"
        f.write_text("content")

        scanned = scan_file(f)
        dest = compute_destination(scanned, tmp_path)
        move = PlannedMove(
            source=scanned.path,
            destination=dest,
            file_name=scanned.name,
            category=scanned.basic_category,
            reason="test",
        )

        db_path = tmp_path / ".ops.db"
        ops_log = OperationLog(db_path)

        executed = execute_moves([move], ops_log, "test-batch")

        assert len(executed) == 1
        assert executed[0].destination.parent.is_dir()
        ops_log.close()


class TestUndoLastBatch:
    """Tests for undo_last_batch() — reversal of file moves."""

    def test_undo_restores_files(self, small_dir: Path) -> None:
        """Undo moves files back to their original locations."""
        files = scan_directory(small_dir)
        original_names = {f.name for f in files}

        moves = plan_moves(files, small_dir)

        db_path = small_dir / ".ops.db"
        ops_log = OperationLog(db_path)

        execute_moves(moves, ops_log, "test-batch")

        # Verify files moved away
        current_root_files = {f.name for f in small_dir.iterdir() if f.is_file()}
        assert len(current_root_files & original_names) < len(original_names)

        # Undo
        restored = undo_last_batch(ops_log)

        assert restored > 0

        # Verify files are back
        final_root_files = {f.name for f in small_dir.iterdir() if f.is_file()}
        assert original_names.issubset(final_root_files)

        ops_log.close()

    def test_undo_empty_log(self, tmp_path: Path) -> None:
        """Undoing with no batches returns 0."""
        db_path = tmp_path / "ops.db"
        ops_log = OperationLog(db_path)

        result = undo_last_batch(ops_log)

        assert result == 0
        ops_log.close()
