"""Shared test fixtures for slothd tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def messy_downloads(tmp_path: Path) -> Path:
    """Create a realistic messy Downloads folder for testing.

    Returns a tmp_path populated with various file types mimicking
    a real user's disorganized Downloads folder.
    """
    # Documents
    (tmp_path / "report.pdf").write_bytes(b"%PDF-1.4 fake pdf content for testing")
    (tmp_path / "notes.txt").write_text("Meeting notes from last week about Q4 planning")
    (tmp_path / "resume_v3_final_FINAL.docx").write_bytes(b"PK fake docx content")
    (tmp_path / "tax_2025.pdf").write_bytes(b"%PDF-1.4 tax document for 2025 fiscal year")

    # Images
    # Create a minimal valid PNG (1x1 pixel, red)
    png_header = b"\x89PNG\r\n\x1a\n"
    png_data = (
        png_header
        + b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
        + b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    (tmp_path / "screenshot_2026-10-15.png").write_bytes(png_data)
    (tmp_path / "IMG_4521.jpg").write_bytes(b"\xff\xd8\xff\xe0 fake jpeg content")
    (tmp_path / "photo_vacation.webp").write_bytes(b"RIFF fake webp content")

    # Archives
    (tmp_path / "project-backup.zip").write_bytes(b"PK\x03\x04 fake zip content")
    (tmp_path / "node_modules.tar.gz").write_bytes(b"\x1f\x8b fake gzip content")

    # Code
    (tmp_path / "script.py").write_text("print('hello world')")
    (tmp_path / "config.json").write_text('{"key": "value", "debug": true}')

    # Spreadsheets
    (tmp_path / "budget_2026.xlsx").write_bytes(b"PK fake xlsx content")
    (tmp_path / "data_export.csv").write_text("name,email,phone\nJohn,john@test.com,555-1234")

    # Random / Other
    (tmp_path / "mystery_file.xyz").write_bytes(b"some unknown content")
    (tmp_path / "installer_v2.exe").write_bytes(b"MZ fake exe content")

    # Audio / Video
    (tmp_path / "podcast_episode.mp3").write_bytes(b"ID3 fake mp3 content")
    (tmp_path / "demo_recording.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42 fake mp4")

    # Duplicates (same content = same hash)
    (tmp_path / "notes_copy.txt").write_text("Meeting notes from last week about Q4 planning")

    return tmp_path


@pytest.fixture
def small_dir(tmp_path: Path) -> Path:
    """Create a small directory with just 3 files for focused tests."""
    (tmp_path / "document.pdf").write_bytes(b"%PDF-1.4 test pdf")
    (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n test png data")
    (tmp_path / "archive.zip").write_bytes(b"PK\x03\x04 test zip")
    return tmp_path


@pytest.fixture
def empty_dir(tmp_path: Path) -> Path:
    """Create an empty directory."""
    return tmp_path


@pytest.fixture
def dir_with_collision(tmp_path: Path) -> Path:
    """Create a directory with files that would collide after organization.

    Two text files that would both go to Documents/ with the same name.
    """
    (tmp_path / "notes.txt").write_text("First version of notes")

    # Pre-create the destination with an existing file
    docs_dir = tmp_path / "Documents"
    docs_dir.mkdir()
    (docs_dir / "notes.txt").write_text("Already existing notes")

    return tmp_path
