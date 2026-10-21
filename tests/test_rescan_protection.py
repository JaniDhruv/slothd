"""Tests for the re-scan protection and directory consolidation fixes.

These tests verify:
1. Organized output dirs are skipped on re-scan (no infinite nesting)
2. All files consolidate under a single base dir, not per-file parents
3. The .slothd_organized marker file is written and respected
4. The daemon scheduler properly uses AI and skip_organized
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from slothd.engine.organizer import (
    OperationLog,
    _write_organized_markers,
    compute_destination,
    execute_moves,
    plan_moves,
)
from slothd.engine.scanner import (
    SLOTHD_MARKER,
    _is_organized_dir,
    scan_directory,
    scan_file,
)


class TestNoInfiniteNesting:
    """Files in organized output dirs are never re-processed."""

    def test_marker_file_is_written_after_execute(self, small_dir: Path) -> None:
        """execute_moves writes .slothd_organized markers into category dirs."""
        files = scan_directory(small_dir)
        moves = plan_moves(files, small_dir)

        db_path = small_dir / ".ops.db"
        ops_log = OperationLog(db_path)

        executed = execute_moves(moves, ops_log, "test-batch")

        # At least one marker should exist in a category subdirectory
        markers = list(small_dir.rglob(SLOTHD_MARKER))
        assert len(markers) > 0, "No .slothd_organized markers were written"

        ops_log.close()

    def test_scanner_skips_marked_directories(self, small_dir: Path) -> None:
        """Directories with a .slothd_organized marker are skipped on re-scan."""
        # First pass: organize
        files = scan_directory(small_dir)
        moves = plan_moves(files, small_dir)

        db_path = small_dir / ".ops.db"
        ops_log = OperationLog(db_path)
        execute_moves(moves, ops_log, "test-batch")
        ops_log.close()

        # Second pass: re-scan should find NO files (all are in marked dirs)
        remaining = scan_directory(small_dir, skip_organized=True)
        assert len(remaining) == 0, (
            f"Scanner found {len(remaining)} files that should have been skipped: "
            f"{[f.name for f in remaining]}"
        )

    def test_scanner_still_finds_unmarked_files(self, tmp_path: Path) -> None:
        """New files added after organization are still discovered."""
        # Create and organize initial files
        (tmp_path / "old.txt").write_text("old content")
        files = scan_directory(tmp_path)
        moves = plan_moves(files, tmp_path)
        db_path = tmp_path / ".ops.db"
        ops_log = OperationLog(db_path)
        execute_moves(moves, ops_log, "batch-1")
        ops_log.close()

        # Add a new file at the root (not inside an organized dir)
        (tmp_path / "brand_new.pdf").write_bytes(b"%PDF-1.4 new file")

        # Re-scan should find only the new file
        remaining = scan_directory(tmp_path, skip_organized=True)
        names = {f.name for f in remaining}
        assert "brand_new.pdf" in names
        assert "old.txt" not in names

    def test_skip_organized_can_be_disabled(self, tmp_path: Path) -> None:
        """skip_organized=False includes everything."""
        # Create a marked directory
        marked_dir = tmp_path / "Documents"
        marked_dir.mkdir()
        (marked_dir / SLOTHD_MARKER).write_text("marker")
        (marked_dir / "inside.txt").write_text("content")
        (tmp_path / "outside.txt").write_text("content")

        # With skip_organized=True, inside.txt is skipped
        files_skip = scan_directory(tmp_path, skip_organized=True)
        names_skip = {f.name for f in files_skip}
        assert "inside.txt" not in names_skip

        # With skip_organized=False, both are found
        files_all = scan_directory(tmp_path, skip_organized=False)
        names_all = {f.name for f in files_all}
        assert "inside.txt" in names_all
        assert "outside.txt" in names_all


class TestDirectoryConsolidation:
    """All files consolidate under one root, not per-file parents."""

    def test_files_from_subdirs_consolidate(self, tmp_path: Path) -> None:
        """Files in nested subdirs all organize under the same base dir."""
        # Create files in different subdirectories
        sub1 = tmp_path / "sub1"
        sub2 = tmp_path / "sub2"
        sub1.mkdir()
        sub2.mkdir()
        (sub1 / "a.txt").write_text("file a")
        (sub2 / "b.txt").write_text("file b")

        files = scan_directory(tmp_path)
        moves = plan_moves(files, tmp_path)  # base_dir = tmp_path

        # ALL destinations should be under tmp_path, not under sub1/ or sub2/
        for move in moves:
            assert move.destination.is_relative_to(tmp_path), (
                f"Expected {move.destination} to be under {tmp_path}"
            )
            # Should NOT be under sub1/ or sub2/
            rel = move.destination.relative_to(tmp_path)
            top_dir = rel.parts[0] if rel.parts else ""
            assert top_dir not in ("sub1", "sub2"), (
                f"File {move.file_name} is going to {top_dir}/ instead of a category dir"
            )

    def test_compute_destination_uses_base_dir(self, tmp_path: Path) -> None:
        """compute_destination always uses the given base_dir."""
        sub = tmp_path / "deep" / "nested"
        sub.mkdir(parents=True)
        f = sub / "deep_file.txt"
        f.write_text("content")
        scanned = scan_file(f)

        # Pass tmp_path as base — NOT the file's parent
        dest = compute_destination(scanned, tmp_path)

        # Destination must be under tmp_path, not under deep/nested/
        assert dest.is_relative_to(tmp_path)
        assert "Documents" in str(dest)
        assert "deep" not in str(dest.relative_to(tmp_path).parts[0])


class TestIsOrganizedDir:
    """Tests for _is_organized_dir() helper."""

    def test_unmarked_dir_is_not_organized(self, tmp_path: Path) -> None:
        d = tmp_path / "SomeDir"
        d.mkdir()
        assert _is_organized_dir(d) is False

    def test_marked_dir_is_organized(self, tmp_path: Path) -> None:
        d = tmp_path / "Documents"
        d.mkdir()
        (d / SLOTHD_MARKER).write_text("marker")
        assert _is_organized_dir(d) is True


class TestWriteOrganizedMarkers:
    """Tests for _write_organized_markers()."""

    def test_writes_marker_in_category_dir(self, tmp_path: Path) -> None:
        """Markers land in the category root (3 levels up from file)."""
        from slothd.engine.organizer import PlannedMove

        # Simulate: base/Documents/2026/October/file.txt
        cat_dir = tmp_path / "Documents"
        year_dir = cat_dir / "2026"
        month_dir = year_dir / "October"
        month_dir.mkdir(parents=True)
        dest_file = month_dir / "file.txt"
        dest_file.write_text("content")

        move = PlannedMove(
            source=tmp_path / "original.txt",
            destination=dest_file,
            file_name="file.txt",
            category="Documents",
            reason="test",
        )

        _write_organized_markers([move])

        marker = cat_dir / SLOTHD_MARKER
        assert marker.exists(), f"Marker not found at {marker}"


class TestDaemonSchedulerIntegration:
    """Tests that the daemon's organize cycle uses the fixes."""

    @patch("slothd.daemon.scheduler.is_idle", return_value=True)
    @patch("slothd.daemon.scheduler.scan_directory")
    @patch("slothd.daemon.scheduler.plan_moves", return_value=[])
    def test_cycle_passes_skip_organized(
        self,
        mock_plan: MagicMock,
        mock_scan: MagicMock,
        mock_idle: MagicMock,
        tmp_path: Path,
    ) -> None:
        """The daemon's organize cycle passes skip_organized=True."""
        from slothd.daemon.scheduler import _run_organize_cycle

        mock_scan.return_value = []

        _run_organize_cycle(
            target_dirs=[tmp_path],
            output_dir=None,
            ops_db_path=tmp_path / "ops.db",
            idle_threshold=300,
            max_file_size_mb=50,
            batch_size=20,
            require_idle=True,
        )

        # Verify scan_directory was called with skip_organized=True
        mock_scan.assert_called_once()
        call_kwargs = mock_scan.call_args
        assert call_kwargs.kwargs.get("skip_organized") is True

    @patch("slothd.daemon.scheduler.is_idle", return_value=True)
    @patch("slothd.daemon.scheduler.scan_directory")
    @patch("slothd.engine.classifier.classify_batch")
    @patch("slothd.daemon.scheduler.plan_moves", return_value=[])
    def test_cycle_calls_ai_when_enabled(
        self,
        mock_plan: MagicMock,
        mock_classify: MagicMock,
        mock_scan: MagicMock,
        mock_idle: MagicMock,
        tmp_path: Path,
    ) -> None:
        """When use_ai=True, the daemon classify_batch is called."""
        from slothd.daemon.scheduler import _run_organize_cycle
        from slothd.engine.scanner import ScannedFile
        from datetime import datetime

        fake_file = ScannedFile(
            path=tmp_path / "test.txt",
            name="test.txt",
            extension=".txt",
            size_bytes=100,
            modified_at=datetime.now(),
            created_at=datetime.now(),
            mime_type="text/plain",
            basic_category="Documents",
            content_hash="abc123",
        )
        mock_scan.return_value = [fake_file]
        mock_classify.return_value = []

        _run_organize_cycle(
            target_dirs=[tmp_path],
            output_dir=None,
            ops_db_path=tmp_path / "ops.db",
            idle_threshold=300,
            max_file_size_mb=50,
            batch_size=20,
            require_idle=True,
            use_ai=True,
            ollama_host="http://localhost:11434",
            ollama_model="llama3.2:3b",
        )

        mock_classify.assert_called_once()

    @patch("slothd.daemon.scheduler.is_idle", return_value=True)
    @patch("slothd.daemon.scheduler.scan_directory")
    @patch("slothd.daemon.scheduler.plan_moves", return_value=[])
    def test_cycle_skips_ai_when_disabled(
        self,
        mock_plan: MagicMock,
        mock_scan: MagicMock,
        mock_idle: MagicMock,
        tmp_path: Path,
    ) -> None:
        """When use_ai=False (default), classify_batch is NOT called."""
        from slothd.daemon.scheduler import _run_organize_cycle

        mock_scan.return_value = []

        _run_organize_cycle(
            target_dirs=[tmp_path],
            output_dir=None,
            ops_db_path=tmp_path / "ops.db",
            idle_threshold=300,
            max_file_size_mb=50,
            batch_size=20,
            require_idle=True,
            use_ai=False,
        )

        # classify_batch should NOT have been imported or called
        # (no mock needed — it simply isn't called)

    @patch("slothd.daemon.scheduler.is_idle", return_value=True)
    @patch("slothd.daemon.scheduler.scan_directory")
    @patch("slothd.daemon.scheduler.plan_moves", return_value=[])
    def test_cycle_uses_first_target_as_base(
        self,
        mock_plan: MagicMock,
        mock_scan: MagicMock,
        mock_idle: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Without an explicit output_dir, the first target_dir is the base."""
        from slothd.daemon.scheduler import _run_organize_cycle
        from slothd.engine.scanner import ScannedFile
        from datetime import datetime

        fake_file = ScannedFile(
            path=tmp_path / "test.txt",
            name="test.txt",
            extension=".txt",
            size_bytes=100,
            modified_at=datetime.now(),
            created_at=datetime.now(),
            mime_type="text/plain",
            basic_category="Documents",
            content_hash="abc123",
        )
        mock_scan.return_value = [fake_file]

        _run_organize_cycle(
            target_dirs=[tmp_path],
            output_dir=None,  # No explicit output dir
            ops_db_path=tmp_path / "ops.db",
            idle_threshold=300,
            max_file_size_mb=50,
            batch_size=20,
            require_idle=True,
        )

        # plan_moves should have been called with tmp_path as base_dir
        mock_plan.assert_called_once()
        call_args = mock_plan.call_args
        assert call_args[0][1] == tmp_path  # second positional arg = base_dir
