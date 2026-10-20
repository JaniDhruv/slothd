"""Tests for the semantic search engine (Tiger Data pgvector + Local SQLite)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from slothd.engine.scanner import scan_file
from slothd.engine.search import (
    LocalFileIndex,
    SearchEngine,
    _fallback_deterministic_embedding,
    cosine_similarity,
    generate_embedding,
)


class TestEmbeddingGeneration:
    """Tests for vector embedding generation and fallbacks."""

    def test_fallback_deterministic_embedding_dim(self) -> None:
        """Deterministic fallback produces 768-dim unit vector."""
        vec = _fallback_deterministic_embedding("Amazon receipt for headphones")
        assert len(vec) == 768
        # Verify L2 norm is approximately 1.0
        norm = sum(x * x for x in vec) ** 0.5
        assert pytest.approx(norm, 0.01) == 1.0

    def test_deterministic_embedding_consistency(self) -> None:
        """Same input text produces identical vectors."""
        v1 = _fallback_deterministic_embedding("Tax Return 2026")
        v2 = _fallback_deterministic_embedding("Tax Return 2026")
        assert v1 == v2

    def test_different_inputs_produce_different_vectors(self) -> None:
        """Different inputs produce distinct vectors."""
        v1 = _fallback_deterministic_embedding("Receipt for coffee")
        v2 = _fallback_deterministic_embedding("Python programming tutorial")
        assert v1 != v2

    @patch("ollama.Client")
    def test_generate_embedding_with_ollama(self, mock_client_cls) -> None:
        """When Ollama is online, calls client.embeddings."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.embeddings.return_value = {"embedding": [0.1] * 768}

        emb = generate_embedding("sample text")
        assert len(emb) == 768
        assert emb[0] == 0.1


class TestCosineSimilarity:
    """Tests for cosine_similarity calculation."""

    def test_identical_vectors(self) -> None:
        v = [0.5, 0.5, 0.5, 0.5]
        assert pytest.approx(cosine_similarity(v, v), 0.001) == 1.0

    def test_orthogonal_vectors(self) -> None:
        v1 = [1.0, 0.0]
        v2 = [0.0, 1.0]
        assert pytest.approx(cosine_similarity(v1, v2), 0.001) == 0.0

    def test_empty_vectors(self) -> None:
        assert cosine_similarity([], []) == 0.0


class TestLocalFileIndex:
    """Tests for SQLite-backed local file index."""

    def test_index_and_search(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test_search.db"
        index = LocalFileIndex(db_path)

        f_path = tmp_path / "warranty.pdf"
        f_path.write_text("dummy warranty content")
        vec = _fallback_deterministic_embedding("Amazon warranty document for laptop")

        index.index_file(
            file_path=f_path,
            file_name="warranty.pdf",
            category="Documents",
            subcategory="Warranty",
            description="Laptop warranty from Amazon",
            vendor="Amazon",
            file_date="2026-10-15",
            tags=["warranty", "amazon", "laptop"],
            embedding=vec,
        )

        assert index.count() == 1

        # Search with matching query
        query_vec = _fallback_deterministic_embedding("Amazon laptop warranty")
        hits = index.search("Amazon warranty", query_vec, limit=5, min_similarity=0.1)

        assert len(hits) == 1
        assert hits[0].file_name == "warranty.pdf"
        assert hits[0].vendor == "Amazon"
        assert hits[0].source == "local_sqlite"
        assert hits[0].similarity_score > 0.3

        index.close()


class TestSearchEngine:
    """Tests for unified SearchEngine."""

    def test_engine_indexes_and_searches(self, tmp_path: Path) -> None:
        db_path = tmp_path / "search.db"
        engine = SearchEngine(local_db_path=db_path)

        f = tmp_path / "flight_ticket.pdf"
        f.write_text("Flight to SFO")
        scanned = scan_file(f)
        scanned.ai_category = "Travel"
        scanned.ai_subcategory = "Flight"
        scanned.ai_vendor = "United Airlines"
        scanned.ai_description = "Flight ticket to SFO"
        scanned.tags = ["flight", "travel", "ticket"]

        engine.index_scanned_file(scanned)

        hits = engine.search("United Airlines flight ticket", limit=3, min_similarity=0.1)
        assert len(hits) >= 1
        assert hits[0].file_name == "flight_ticket.pdf"
        assert hits[0].category == "Travel"

        engine.local_index.close()
