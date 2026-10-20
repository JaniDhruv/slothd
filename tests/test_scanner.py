"""Tests for the file scanner module."""

from __future__ import annotations

from pathlib import Path

from slothd.engine.scanner import (
    compute_file_hash,
    find_duplicates,
    group_by_category,
    scan_directory,
    scan_file,
)


class TestScanFile:
    """Tests for scan_file()."""

    def test_scan_text_file(self, tmp_path: Path) -> None:
        """Scanning a text file produces correct metadata."""
        f = tmp_path / "hello.txt"
        f.write_text("Hello, world!")

        result = scan_file(f)

        assert result.name == "hello.txt"
        assert result.extension == ".txt"
        assert result.basic_category == "Documents"
        assert result.size_bytes == 13
        assert result.mime_type == "text/plain"
        assert result.content_hash  # Should be non-empty

    def test_scan_image_file(self, tmp_path: Path) -> None:
        """Scanning an image file marks it as vision-compatible."""
        f = tmp_path / "photo.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\n test data")

        result = scan_file(f)

        assert result.extension == ".png"
        assert result.basic_category == "Images"
        assert result.is_image is True
        assert result.is_pdf is False

    def test_scan_pdf_file(self, tmp_path: Path) -> None:
        """Scanning a PDF file marks it as needing pymupdf conversion."""
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF-1.4 content")

        result = scan_file(f)

        assert result.extension == ".pdf"
        assert result.basic_category == "Documents"
        assert result.is_pdf is True
        assert result.is_image is False

    def test_scan_unknown_extension(self, tmp_path: Path) -> None:
        """Unknown extensions get categorized as 'Other'."""
        f = tmp_path / "weird.xyz"
        f.write_bytes(b"mystery content")

        result = scan_file(f)

        assert result.basic_category == "Other"

    def test_scan_file_to_dict(self, tmp_path: Path) -> None:
        """to_dict() produces a JSON-serializable dictionary."""
        f = tmp_path / "test.txt"
        f.write_text("test")

        result = scan_file(f)
        d = result.to_dict()

        assert isinstance(d, dict)
        assert "path" in d
        assert "content_hash" in d
        assert isinstance(d["size_mb"], float)


class TestScanDirectory:
    """Tests for scan_directory()."""

    def test_scan_messy_downloads(self, messy_downloads: Path) -> None:
        """Scanning a messy folder finds all non-hidden, non-empty files."""
        files = scan_directory(messy_downloads)

        # Should find all 18 files we created in the fixture
        assert len(files) == 18

    def test_scan_empty_directory(self, empty_dir: Path) -> None:
        """Scanning an empty directory returns no files."""
        files = scan_directory(empty_dir)
        assert files == []

    def test_scan_skips_hidden_files(self, tmp_path: Path) -> None:
        """Hidden files (starting with .) are skipped by default."""
        (tmp_path / ".hidden_file").write_text("secret")
        (tmp_path / "visible.txt").write_text("public")

        files = scan_directory(tmp_path)

        assert len(files) == 1
        assert files[0].name == "visible.txt"

    def test_scan_includes_hidden_when_requested(self, tmp_path: Path) -> None:
        """Hidden files are included when skip_hidden=False."""
        (tmp_path / ".hidden_file").write_text("secret")
        (tmp_path / "visible.txt").write_text("public")

        files = scan_directory(tmp_path, skip_hidden=False)

        assert len(files) == 2

    def test_scan_respects_size_limit(self, tmp_path: Path) -> None:
        """Files over the size limit are skipped."""
        small = tmp_path / "small.txt"
        small.write_text("tiny")

        big = tmp_path / "big.bin"
        big.write_bytes(b"x" * (2 * 1024 * 1024))  # 2 MB

        files = scan_directory(tmp_path, max_file_size_mb=1)

        assert len(files) == 1
        assert files[0].name == "small.txt"

    def test_scan_non_recursive(self, tmp_path: Path) -> None:
        """Non-recursive scan only gets files in the root directory."""
        (tmp_path / "root.txt").write_text("root file")
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "nested.txt").write_text("nested file")

        files = scan_directory(tmp_path, recursive=False)

        assert len(files) == 1
        assert files[0].name == "root.txt"

    def test_scan_not_a_directory(self, tmp_path: Path) -> None:
        """Scanning a non-directory raises NotADirectoryError."""
        f = tmp_path / "file.txt"
        f.write_text("test")

        import pytest

        with pytest.raises(NotADirectoryError):
            scan_directory(f)

    def test_scan_skips_zero_byte_files(self, tmp_path: Path) -> None:
        """Zero-byte files are skipped."""
        (tmp_path / "empty.txt").write_bytes(b"")
        (tmp_path / "notempty.txt").write_text("content")

        files = scan_directory(tmp_path)

        assert len(files) == 1
        assert files[0].name == "notempty.txt"


class TestGroupByCategory:
    """Tests for group_by_category()."""

    def test_groups_by_extension(self, messy_downloads: Path) -> None:
        """Files are grouped correctly by their extension-based category."""
        files = scan_directory(messy_downloads)
        groups = group_by_category(files)

        assert "Documents" in groups
        assert "Images" in groups
        assert "Archives" in groups
        assert "Code" in groups

    def test_groups_count(self, messy_downloads: Path) -> None:
        """Total files across all groups equals total scanned."""
        files = scan_directory(messy_downloads)
        groups = group_by_category(files)

        total = sum(len(fs) for fs in groups.values())
        assert total == len(files)


class TestFindDuplicates:
    """Tests for find_duplicates()."""

    def test_finds_exact_duplicates(self, messy_downloads: Path) -> None:
        """Finds files with identical content hashes."""
        files = scan_directory(messy_downloads)
        dupes = find_duplicates(files)

        # We created notes.txt and notes_copy.txt with identical content
        assert len(dupes) >= 1

        # Find the duplicate set containing "notes"
        dupe_names = []
        for hash_val, dupe_files in dupes.items():
            dupe_names.extend(f.name for f in dupe_files)

        assert "notes.txt" in dupe_names
        assert "notes_copy.txt" in dupe_names

    def test_no_false_duplicates(self, small_dir: Path) -> None:
        """Non-duplicate files produce no results."""
        files = scan_directory(small_dir)
        dupes = find_duplicates(files)

        assert len(dupes) == 0


class TestComputeFileHash:
    """Tests for compute_file_hash()."""

    def test_same_content_same_hash(self, tmp_path: Path) -> None:
        """Files with identical content produce the same hash."""
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("identical content")
        f2.write_text("identical content")

        assert compute_file_hash(f1) == compute_file_hash(f2)

    def test_different_content_different_hash(self, tmp_path: Path) -> None:
        """Files with different content produce different hashes."""
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("content A")
        f2.write_text("content B")

        assert compute_file_hash(f1) != compute_file_hash(f2)
