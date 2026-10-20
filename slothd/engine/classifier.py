"""AI Classifier — Uses Gemma 3 Vision via Ollama to classify files.

This module handles:
1. PDF → PNG conversion via pymupdf for Gemma 3 Vision
2. Structured JSON output from Gemma 3 via Ollama's format parameter
3. Text-based classification for non-image files
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

import ollama
from pydantic import BaseModel, Field

from slothd.engine.scanner import ScannedFile

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
#  Pydantic schema for Gemma 3 structured output                              #
# --------------------------------------------------------------------------- #


class FileClassification(BaseModel):
    """Schema for Gemma 3's structured output.

    Passed to Ollama's `format` parameter to force valid JSON at the
    grammar/token level — no markdown backtick wrapping, no hallucinated keys.
    """

    category: str = Field(
        description="High-level category: Documents, Images, Receipts, Screenshots, "
        "Invoices, Medical, Legal, Tax, Travel, Personal, Work, Code, Other",
    )
    subcategory: str = Field(
        description="More specific classification within the category, "
        "e.g. 'Bank Statement', 'Grocery Receipt', 'Flight Booking'",
    )
    description: str = Field(
        description="Brief 1-sentence description of the file's content",
    )
    date: str | None = Field(
        default=None,
        description="Date found in the document in YYYY-MM-DD format, or null if none found",
    )
    vendor: str | None = Field(
        default=None,
        description="Company, vendor, or organization name found, or null if none found",
    )
    proposed_name: str = Field(
        description="A clean, descriptive filename (without extension) using the format: "
        "Category_Vendor_Date_Description, e.g. 'Receipt_Amazon_2026-10-15_Headphones'",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence score from 0.0 to 1.0",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Relevant tags for search indexing",
    )


# --------------------------------------------------------------------------- #
#  PDF handling via pymupdf                                                    #
# --------------------------------------------------------------------------- #


def extract_pdf_content(path: Path) -> tuple[str, bytes | None]:
    """Extract text and/or a rendered image from a PDF's first page.

    Uses pymupdf (fitz) to:
    - Extract text from digital PDFs
    - Render scanned/image PDFs to PNG for Gemma 3 Vision

    Args:
        path: Path to the PDF file.

    Returns:
        Tuple of (extracted_text, png_bytes_or_None).
        If the PDF has text, png_bytes will be None.
        If the PDF is scanned/image-only, text will be empty and png_bytes will contain
        a rendered PNG of the first page.
    """
    import fitz  # pymupdf

    doc = fitz.open(str(path))
    if doc.page_count == 0:
        doc.close()
        return "", None

    page = doc[0]
    text = page.get_text().strip()

    png_bytes = None
    if len(text) < 50:
        # Likely a scanned PDF — render to PNG for vision classification
        mat = fitz.Matrix(2.0, 2.0)  # 2x zoom for better quality
        pix = page.get_pixmap(matrix=mat)
        png_bytes = pix.tobytes("png")

    doc.close()
    return text, png_bytes


def read_image_as_base64(path: Path) -> str:
    """Read an image file and return its base64-encoded content.

    Args:
        path: Path to the image file.

    Returns:
        Base64-encoded string of the image bytes.
    """
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def read_text_file(path: Path, max_chars: int = 2000) -> str:
    """Read the first N characters of a text file for classification.

    Args:
        path: Path to the text file.
        max_chars: Maximum number of characters to read.

    Returns:
        First max_chars characters of the file, or empty string on error.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(max_chars)
    except (UnicodeDecodeError, OSError):
        return ""


# --------------------------------------------------------------------------- #
#  Classification prompts                                                      #
# --------------------------------------------------------------------------- #

VISION_PROMPT = """You are a file classification AI. Analyze this image and classify it.

Determine:
1. What category this file belongs to (Documents, Receipts, Screenshots, Invoices, etc.)
2. Any dates, vendor/company names, or amounts visible
3. A clean, descriptive filename

Be precise with dates (YYYY-MM-DD format) and vendor names.
If you can't determine something, set it to null."""

TEXT_PROMPT_TEMPLATE = """You are a file classification AI. Analyze this file and classify it.

Filename: {filename}
File extension: {extension}
File size: {size_mb:.2f} MB
Content preview:
---
{content_preview}
---

Determine:
1. What category this file belongs to (Documents, Receipts, Code, etc.)
2. Any dates, vendor/company names found in the content
3. A clean, descriptive filename

Be precise with dates (YYYY-MM-DD format) and vendor names.
If you can't determine something, set it to null."""


# --------------------------------------------------------------------------- #
#  Classifier                                                                  #
# --------------------------------------------------------------------------- #


def classify_file(
    scanned_file: ScannedFile,
    *,
    ollama_host: str = "http://localhost:11434",
    model: str = "gemma3",
) -> FileClassification:
    """Classify a single file using Gemma 3 via Ollama.

    Uses structured outputs to guarantee valid JSON. Handles three cases:
    1. Image files → Gemma 3 Vision with base64 image
    2. PDF files → Extract text or render to PNG, then classify
    3. Text files → Send content preview for text-based classification

    Args:
        scanned_file: The ScannedFile to classify.
        ollama_host: Ollama API host.
        model: Ollama model name.

    Returns:
        FileClassification with category, date, vendor, proposed name, etc.
    """
    client = ollama.Client(host=ollama_host)
    schema = FileClassification.model_json_schema()

    if scanned_file.is_image:
        return _classify_image(client, scanned_file, model, schema)
    elif scanned_file.is_pdf:
        return _classify_pdf(client, scanned_file, model, schema)
    else:
        return _classify_text(client, scanned_file, model, schema)


def _classify_image(
    client: Any,
    scanned_file: ScannedFile,
    model: str,
    schema: dict,
) -> FileClassification:
    """Classify an image file using Gemma 3 Vision."""
    img_b64 = read_image_as_base64(scanned_file.path)

    response = client.chat(
        model=model,
        messages=[
            {
                "role": "user",
                "content": VISION_PROMPT,
                "images": [img_b64],
            }
        ],
        format=schema,
    )

    return FileClassification.model_validate_json(response.message.content)


def _classify_pdf(
    client: Any,
    scanned_file: ScannedFile,
    model: str,
    schema: dict,
) -> FileClassification:
    """Classify a PDF by extracting text or rendering to PNG."""
    text, png_bytes = extract_pdf_content(scanned_file.path)

    if png_bytes is not None:
        # Scanned PDF — use vision
        img_b64 = base64.b64encode(png_bytes).decode("utf-8")
        response = client.chat(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": VISION_PROMPT,
                    "images": [img_b64],
                }
            ],
            format=schema,
        )
    else:
        # Digital PDF with text
        prompt = TEXT_PROMPT_TEMPLATE.format(
            filename=scanned_file.name,
            extension=scanned_file.extension,
            size_mb=scanned_file.size_mb,
            content_preview=text[:2000],
        )
        response = client.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            format=schema,
        )

    return FileClassification.model_validate_json(response.message.content)


def _classify_text(
    client: Any,
    scanned_file: ScannedFile,
    model: str,
    schema: dict,
) -> FileClassification:
    """Classify a text-based file using content preview."""
    content = read_text_file(scanned_file.path)

    prompt = TEXT_PROMPT_TEMPLATE.format(
        filename=scanned_file.name,
        extension=scanned_file.extension,
        size_mb=scanned_file.size_mb,
        content_preview=content
        if content
        else "(binary file — classify by name and extension only)",
    )

    response = client.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        format=schema,
    )

    return FileClassification.model_validate_json(response.message.content)


def apply_classification(scanned_file: ScannedFile, classification: FileClassification) -> None:
    """Apply a classification result back to a ScannedFile.

    Mutates the ScannedFile in-place to set all AI-derived fields.

    Args:
        scanned_file: The file to update.
        classification: The AI classification result.
    """
    scanned_file.ai_category = classification.category
    scanned_file.ai_subcategory = classification.subcategory
    scanned_file.ai_description = classification.description
    scanned_file.ai_date = classification.date
    scanned_file.ai_vendor = classification.vendor
    scanned_file.ai_proposed_name = classification.proposed_name
    scanned_file.ai_confidence = classification.confidence
    scanned_file.tags = classification.tags


def classify_batch(
    files: list[ScannedFile],
    *,
    ollama_host: str = "http://localhost:11434",
    model: str = "gemma3",
    batch_size: int = 20,
) -> list[tuple[ScannedFile, FileClassification]]:
    """Classify a batch of files, applying results in-place.

    Args:
        files: List of files to classify.
        ollama_host: Ollama API host.
        model: Ollama model name.
        batch_size: Maximum files to process in one batch.

    Returns:
        List of (ScannedFile, FileClassification) tuples for successfully classified files.
    """
    results: list[tuple[ScannedFile, FileClassification]] = []

    for scanned_file in files[:batch_size]:
        try:
            classification = classify_file(
                scanned_file,
                ollama_host=ollama_host,
                model=model,
            )
            apply_classification(scanned_file, classification)
            results.append((scanned_file, classification))
            logger.info("Classified: %s → %s", scanned_file.name, classification.category)
        except Exception as e:
            logger.warning("Failed to classify %s: %s", scanned_file.name, e)
            # Fall back to extension-based classification
            scanned_file.ai_category = scanned_file.basic_category
            scanned_file.ai_confidence = 0.0

    return results
