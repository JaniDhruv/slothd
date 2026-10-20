"""File scanner — walks target directories and gathers file metadata.

This module is the first stage of the slothd pipeline. It walks directories,
identifies files by extension and basic metadata, and prepares them for
classification by Gemma 3.
"""

from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# File categories based on extension (before AI classification)
EXTENSION_CATEGORIES: dict[str, str] = {
    # Images
    ".png": "Images",
    ".jpg": "Images",
    ".jpeg": "Images",
    ".gif": "Images",
    ".bmp": "Images",
    ".webp": "Images",
    ".svg": "Images",
    ".ico": "Images",
    ".tiff": "Images",
    ".heic": "Images",
    # Documents
    ".pdf": "Documents",
    ".doc": "Documents",
    ".docx": "Documents",
    ".txt": "Documents",
    ".rtf": "Documents",
    ".odt": "Documents",
    ".md": "Documents",
    ".tex": "Documents",
    # Spreadsheets
    ".xls": "Spreadsheets",
    ".xlsx": "Spreadsheets",
    ".csv": "Spreadsheets",
    ".ods": "Spreadsheets",
    # Presentations
    ".ppt": "Presentations",
    ".pptx": "Presentations",
    ".odp": "Presentations",
    # Archives
    ".zip": "Archives",
    ".rar": "Archives",
    ".7z": "Archives",
    ".tar": "Archives",
    ".gz": "Archives",
    ".bz2": "Archives",
    # Audio
    ".mp3": "Audio",
    ".wav": "Audio",
    ".flac": "Audio",
    ".aac": "Audio",
    ".ogg": "Audio",
    ".m4a": "Audio",
    # Video
    ".mp4": "Video",
    ".mkv": "Video",
    ".avi": "Video",
    ".mov": "Video",
    ".wmv": "Video",
    ".webm": "Video",
    # Code
    ".py": "Code",
    ".js": "Code",
    ".ts": "Code",
    ".html": "Code",
    ".css": "Code",
    ".java": "Code",
    ".c": "Code",
    ".cpp": "Code",
    ".rs": "Code",
    ".go": "Code",
    ".rb": "Code",
    ".php": "Code",
    ".json": "Code",
    ".yaml": "Code",
    ".yml": "Code",
    ".xml": "Code",
    ".sql": "Code",
    ".sh": "Code",
    ".bat": "Code",
    ".ps1": "Code",
    # Executables / Installers
    ".exe": "Installers",
    ".msi": "Installers",
    ".dmg": "Installers",
    ".deb": "Installers",
    ".rpm": "Installers",
    ".appimage": "Installers",
    # Fonts
    ".ttf": "Fonts",
    ".otf": "Fonts",
    ".woff": "Fonts",
    ".woff2": "Fonts",
    # Data
    ".db": "Data",
    ".sqlite": "Data",
    ".sqlite3": "Data",
}

# Image extensions that Gemma 3 Vision can process directly
VISION_EXTENSIONS: set[str] = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

# PDF extensions that need pymupdf conversion
PDF_EXTENSIONS: set[str] = {".pdf"}


@dataclass
class ScannedFile:
    """Represents a file discovered during scanning.

    This is the data transfer object passed from the scanner to the classifier.
    """

    path: Path
    name: str
    extension: str
    size_bytes: int
    modified_at: datetime
    created_at: datetime
    mime_type: str | None
    basic_category: str  # Extension-based category (pre-AI)
    content_hash: str  # SHA-256 hash for deduplication

    # Set after AI classification
    ai_category: str | None = None
    ai_subcategory: str | None = None
    ai_description: str | None = None
    ai_date: str | None = None
    ai_vendor: str | None = None
    ai_proposed_name: str | None = None
    ai_confidence: float | None = None

    # Enrichment metadata
    tags: list[str] = field(default_factory=list)

    @property
    def is_image(self) -> bool:
        """Whether this file can be processed by Gemma 3 Vision directly."""
        return self.extension.lower() in VISION_EXTENSIONS

    @property
    def is_pdf(self) -> bool:
        """Whether this file is a PDF (needs pymupdf conversion)."""
        return self.extension.lower() in PDF_EXTENSIONS

    @property
    def size_mb(self) -> float:
        """File size in megabytes."""
        return self.size_bytes / (1024 * 1024)

    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON output / API responses."""
        return {
            "path": str(self.path),
            "name": self.name,
            "extension": self.extension,
            "size_bytes": self.size_bytes,
            "size_mb": round(self.size_mb, 2),
            "modified_at": self.modified_at.isoformat(),
            "created_at": self.created_at.isoformat(),
            "mime_type": self.mime_type,
            "basic_category": self.basic_category,
            "content_hash": self.content_hash,
            "ai_category": self.ai_category,
            "ai_subcategory": self.ai_subcategory,
            "ai_description": self.ai_description,
            "ai_date": self.ai_date,
            "ai_vendor": self.ai_vendor,
            "ai_proposed_name": self.ai_proposed_name,
            "ai_confidence": self.ai_confidence,
            "tags": self.tags,
        }


def compute_file_hash(path: Path, chunk_size: int = 8192) -> str:
    """Compute SHA-256 hash of a file for deduplication.

    Args:
        path: Path to the file.
        chunk_size: Read buffer size in bytes.

    Returns:
        Hex-encoded SHA-256 hash string.
    """
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            sha256.update(chunk)
    return sha256.hexdigest()


def scan_file(path: Path) -> ScannedFile:
    """Scan a single file and extract its metadata.

    Args:
        path: Path to the file to scan.

    Returns:
        ScannedFile with metadata populated.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        PermissionError: If the file isn't readable.
    """
    stat = path.stat()
    ext = path.suffix.lower()
    mime, _ = mimetypes.guess_type(str(path))

    return ScannedFile(
        path=path.resolve(),
        name=path.name,
        extension=ext,
        size_bytes=stat.st_size,
        modified_at=datetime.fromtimestamp(stat.st_mtime),
        created_at=datetime.fromtimestamp(stat.st_ctime),
        mime_type=mime,
        basic_category=EXTENSION_CATEGORIES.get(ext, "Other"),
        content_hash=compute_file_hash(path),
    )


def scan_directory(
    directory: Path,
    *,
    max_file_size_mb: int = 50,
    recursive: bool = True,
    skip_hidden: bool = True,
) -> list[ScannedFile]:
    """Walk a directory and scan all files.

    Args:
        directory: Root directory to scan.
        max_file_size_mb: Skip files larger than this (MB).
        recursive: Whether to descend into subdirectories.
        skip_hidden: Whether to skip hidden files/directories (starting with '.').

    Returns:
        List of ScannedFile objects for all discovered files.
    """
    if not directory.is_dir():
        raise NotADirectoryError(f"Not a directory: {directory}")

    files: list[ScannedFile] = []
    max_bytes = max_file_size_mb * 1024 * 1024
    pattern = "**/*" if recursive else "*"

    for item in directory.glob(pattern):
        # Skip directories
        if item.is_dir():
            continue

        # Skip hidden files/dirs
        if skip_hidden and any(part.startswith(".") for part in item.parts):
            continue

        # Skip files over size limit
        try:
            if item.stat().st_size > max_bytes:
                continue
            if item.stat().st_size == 0:
                continue
        except OSError:
            continue

        try:
            scanned = scan_file(item)
            files.append(scanned)
        except (PermissionError, OSError):
            # Skip files we can't read
            continue

    return files


def group_by_category(files: list[ScannedFile]) -> dict[str, list[ScannedFile]]:
    """Group scanned files by their basic (extension-based) category.

    Args:
        files: List of scanned files.

    Returns:
        Dictionary mapping category names to lists of files.
    """
    groups: dict[str, list[ScannedFile]] = {}
    for f in files:
        category = f.basic_category
        if category not in groups:
            groups[category] = []
        groups[category].append(f)
    return groups


def find_duplicates(files: list[ScannedFile]) -> dict[str, list[ScannedFile]]:
    """Find files with identical content hashes (exact duplicates).

    Args:
        files: List of scanned files.

    Returns:
        Dictionary mapping content hashes to lists of duplicate files.
        Only includes hashes with 2+ files.
    """
    by_hash: dict[str, list[ScannedFile]] = {}
    for f in files:
        if f.content_hash not in by_hash:
            by_hash[f.content_hash] = []
        by_hash[f.content_hash].append(f)
    return {h: fs for h, fs in by_hash.items() if len(fs) > 1}
