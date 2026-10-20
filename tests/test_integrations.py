"""Tests for external integrations (Tiger Data, Sentry, SerpApi, ElevenLabs)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slothd.engine.enricher import enrich_file_metadata
from slothd.engine.scanner import scan_file
from slothd.integrations.elevenlabs import (
    ElevenLabsClient,
    _generate_demo_audio_wav,
    generate_briefing_script,
)
from slothd.integrations.sentry_tracing import (
    capture_exception,
    init_sentry,
    trace_span,
)
from slothd.integrations.serpapi_client import SerpApiClient
from slothd.integrations.tiger_data import TigerDataClient


# ---------------------------------------------------------------------------
# Tiger Data pgvector Tests
# ---------------------------------------------------------------------------
class TestTigerDataClient:
    """Tests for Tiger Data client with mocked PostgreSQL connection."""

    def test_availability_false_when_unreachable(self) -> None:
        client = TigerDataClient("postgresql://slothd:slothd@localhost:9999/nonexistent")
        assert client.is_available() is False

    @patch("psycopg.connect")
    def test_init_db_success(self, mock_connect) -> None:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        with patch("pgvector.psycopg.register_vector"):
            client = TigerDataClient("postgresql://test:test@localhost:5432/test")
            assert client.init_db() is True
            assert mock_cursor.execute.call_count >= 2

    @patch("psycopg.connect")
    def test_search_similar(self, mock_connect) -> None:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        mock_cursor.fetchall.return_value = [
            (
                "/home/user/docs/invoice.pdf",
                "invoice.pdf",
                "Documents",
                "Invoice",
                "AWS cloud hosting invoice",
                "Amazon Web Services",
                "2026-10-01",
                ["aws", "invoice"],
                0.92,
            )
        ]

        with patch("pgvector.psycopg.register_vector"):
            client = TigerDataClient("postgresql://test:test@localhost:5432/test")
            hits = client.search_similar([0.1] * 768, limit=1)

            assert len(hits) == 1
            assert hits[0].file_name == "invoice.pdf"
            assert hits[0].vendor == "Amazon Web Services"
            assert pytest.approx(hits[0].similarity, 0.01) == 0.92


# ---------------------------------------------------------------------------
# SerpApi Tests
# ---------------------------------------------------------------------------
class TestSerpApiClient:
    """Tests for SerpApi web grounding client."""

    def test_not_available_without_key(self) -> None:
        client = SerpApiClient(api_key=None)
        assert client.is_available() is False
        assert client.search_entity("Amazon") is None

    def test_available_with_key(self) -> None:
        client = SerpApiClient(api_key="test_serp_key")
        assert client.is_available() is True

    @patch("serpapi.GoogleSearch")
    def test_search_entity_returns_data(self, mock_search_cls) -> None:
        mock_search = MagicMock()
        mock_search.get_dict.return_value = {
            "knowledge_graph": {
                "title": "Amazon.com, Inc.",
                "description": "Multinational technology and e-commerce company",
            },
            "organic_results": [{"link": "https://www.amazon.com"}],
        }
        mock_search_cls.return_value = mock_search

        client = SerpApiClient(api_key="test_key")
        res = client.search_entity("Amazon order")
        assert res is not None
        assert res["vendor_name"] == "Amazon.com, Inc."
        assert "e-commerce" in res["description"]

    def test_enrich_file_metadata(self, tmp_path: Path) -> None:
        f = tmp_path / "receipt.pdf"
        f.write_text("Dummy receipt content")
        scanned = scan_file(f)
        scanned.ai_vendor = "Uber"

        client = SerpApiClient(api_key="test_key")
        with patch.object(
            client,
            "search_entity",
            return_value={
                "vendor_name": "Uber Technologies Inc.",
                "description": "Ride-hailing service and mobility provider",
                "link": "https://uber.com",
            },
        ):
            enriched = enrich_file_metadata(scanned, client)
            assert enriched is True
            assert "Uber Technologies Inc." in (scanned.ai_vendor or "")
            assert "web_verified" in scanned.tags


# ---------------------------------------------------------------------------
# Sentry Tracing Tests
# ---------------------------------------------------------------------------
class TestSentryTracing:
    """Tests for Sentry observability integration."""

    def test_init_sentry_none_dsn(self) -> None:
        assert init_sentry(None) is False

    def test_trace_span_context_manager_fallback(self) -> None:
        with trace_span(op="test.op", description="testing span", data={"key": "val"}) as span:
            assert span is not None

    def test_capture_exception_safe(self) -> None:
        capture_exception(RuntimeError("Test error"))


# ---------------------------------------------------------------------------
# ElevenLabs Voice Summary Tests
# ---------------------------------------------------------------------------
class TestElevenLabs:
    """Tests for ElevenLabs voice briefing generation."""

    def test_script_generation(self) -> None:
        script = generate_briefing_script(
            total_files=5,
            categories={"Receipts": 3, "Documents": 2},
        )
        assert "5 files" in script
        assert "Receipts" in script
        assert "Documents" in script

    def test_script_zero_files(self) -> None:
        script = generate_briefing_script(total_files=0, categories={})
        assert "nap" in script or "immaculate" in script

    def test_synthetic_wav_generation(self) -> None:
        wav_bytes = _generate_demo_audio_wav("Hello from slothd")
        assert len(wav_bytes) > 100
        # Check WAV header RIFF and WAVE
        assert wav_bytes[:4] == b"RIFF"
        assert wav_bytes[8:12] == b"WAVE"

    def test_client_fallback_to_synthetic(self) -> None:
        client = ElevenLabsClient(api_key=None)
        assert client.is_available() is False
        audio = client.text_to_speech("Test speech")
        assert audio[:4] == b"RIFF"
