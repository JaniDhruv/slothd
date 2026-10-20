"""Tests for the AI classifier — mocked Ollama, no GPU required.

These tests verify the classifier's logic (PDF handling, prompt construction,
schema parsing) without requiring Ollama or Gemma 3 to be running.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slothd.engine.classifier import (
    FileClassification,
    apply_classification,
    read_text_file,
)
from slothd.engine.scanner import scan_file


class TestFileClassificationSchema:
    """Tests for the Pydantic schema used with Ollama structured outputs."""

    def test_valid_classification(self) -> None:
        """A complete classification parses correctly."""
        data = {
            "category": "Receipts",
            "subcategory": "Online Purchase",
            "description": "Amazon order receipt for headphones",
            "date": "2026-10-15",
            "vendor": "Amazon",
            "proposed_name": "Receipt_Amazon_2026-10-15_Headphones",
            "confidence": 0.95,
            "tags": ["receipt", "amazon", "purchase"],
        }

        result = FileClassification(**data)

        assert result.category == "Receipts"
        assert result.vendor == "Amazon"
        assert result.confidence == 0.95

    def test_minimal_classification(self) -> None:
        """Classification with optional fields omitted."""
        data = {
            "category": "Other",
            "subcategory": "Unknown",
            "description": "Unidentified file",
            "date": None,
            "vendor": None,
            "proposed_name": "Unknown_File",
            "confidence": 0.3,
        }

        result = FileClassification(**data)

        assert result.date is None
        assert result.vendor is None
        assert result.tags == []

    def test_schema_is_json_serializable(self) -> None:
        """The schema can be serialized to JSON (required for Ollama's format param)."""
        schema = FileClassification.model_json_schema()
        json_str = json.dumps(schema)

        assert "category" in json_str
        assert "proposed_name" in json_str

    def test_confidence_bounds(self) -> None:
        """Confidence must be between 0.0 and 1.0."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            FileClassification(
                category="Test",
                subcategory="Test",
                description="Test",
                proposed_name="Test",
                confidence=1.5,  # Invalid: > 1.0
            )


class TestApplyClassification:
    """Tests for apply_classification()."""

    def test_applies_all_fields(self, tmp_path: Path) -> None:
        """All classification fields are written to the ScannedFile."""
        f = tmp_path / "receipt.png"
        f.write_bytes(b"\x89PNG test")
        scanned = scan_file(f)

        classification = FileClassification(
            category="Receipts",
            subcategory="Restaurant",
            description="Lunch receipt from Chipotle",
            date="2026-10-18",
            vendor="Chipotle",
            proposed_name="Receipt_Chipotle_2026-10-18_Lunch",
            confidence=0.92,
            tags=["food", "receipt"],
        )

        apply_classification(scanned, classification)

        assert scanned.ai_category == "Receipts"
        assert scanned.ai_vendor == "Chipotle"
        assert scanned.ai_date == "2026-10-18"
        assert scanned.ai_proposed_name == "Receipt_Chipotle_2026-10-18_Lunch"
        assert scanned.ai_confidence == 0.92
        assert "food" in scanned.tags


class TestReadTextFile:
    """Tests for read_text_file()."""

    def test_reads_text_content(self, tmp_path: Path) -> None:
        """Reads text file content up to max_chars."""
        f = tmp_path / "notes.txt"
        f.write_text("Hello, world! This is a test document.")

        content = read_text_file(f)
        assert "Hello, world!" in content

    def test_truncates_long_content(self, tmp_path: Path) -> None:
        """Content is truncated at max_chars."""
        f = tmp_path / "long.txt"
        f.write_text("x" * 5000)

        content = read_text_file(f, max_chars=100)
        assert len(content) == 100

    def test_handles_binary_gracefully(self, tmp_path: Path) -> None:
        """Binary files return content with replacements, not errors."""
        f = tmp_path / "binary.bin"
        f.write_bytes(b"\x00\x01\x02\xff\xfe\xfd")

        content = read_text_file(f)
        # Should not raise, may contain replacement characters
        assert isinstance(content, str)


class TestClassifyFileWithMockedOllama:
    """Tests for classify_file() with a mocked Ollama client.

    These verify the classification pipeline without requiring a GPU or
    Ollama to be running. The Ollama client is fully mocked.
    """

    def _make_mock_response(self, classification_data: dict) -> MagicMock:
        """Create a mock Ollama response."""
        mock_response = MagicMock()
        mock_response.message.content = json.dumps(classification_data)
        return mock_response

    @patch("slothd.engine.classifier.ollama")
    def test_classify_image_file(self, mock_ollama_module, tmp_path: Path) -> None:
        """Image files use the vision endpoint with base64 data."""
        from slothd.engine.classifier import classify_file

        # Create a test image
        f = tmp_path / "photo.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\n test data")
        scanned = scan_file(f)

        # Mock Ollama response
        mock_client = MagicMock()
        mock_ollama_module.Client.return_value = mock_client
        mock_client.chat.return_value = self._make_mock_response(
            {
                "category": "Screenshots",
                "subcategory": "Desktop Screenshot",
                "description": "A screenshot of a desktop application",
                "date": "2026-10-15",
                "vendor": None,
                "proposed_name": "Screenshot_Desktop_2026-10-15",
                "confidence": 0.88,
                "tags": ["screenshot"],
            }
        )

        result = classify_file(scanned)

        assert result.category == "Screenshots"
        assert result.confidence == 0.88

        # Verify the vision endpoint was called with images
        call_args = mock_client.chat.call_args
        messages = call_args.kwargs.get("messages") or call_args[1].get("messages")
        assert "images" in messages[0]

    @patch("slothd.engine.classifier.ollama")
    def test_classify_text_file(self, mock_ollama_module, tmp_path: Path) -> None:
        """Text files use the text prompt with content preview."""
        from slothd.engine.classifier import classify_file

        f = tmp_path / "notes.txt"
        f.write_text("Q4 planning meeting notes for Project Atlas")
        scanned = scan_file(f)

        mock_client = MagicMock()
        mock_ollama_module.Client.return_value = mock_client
        mock_client.chat.return_value = self._make_mock_response(
            {
                "category": "Documents",
                "subcategory": "Meeting Notes",
                "description": "Q4 planning meeting notes",
                "date": None,
                "vendor": None,
                "proposed_name": "Notes_Q4_Planning_ProjectAtlas",
                "confidence": 0.85,
                "tags": ["meeting", "planning"],
            }
        )

        result = classify_file(scanned)

        assert result.category == "Documents"
        assert result.subcategory == "Meeting Notes"

        # Verify NO images were sent (text-only prompt)
        call_args = mock_client.chat.call_args
        messages = call_args.kwargs.get("messages") or call_args[1].get("messages")
        assert "images" not in messages[0]
