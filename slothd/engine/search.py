"""Semantic search engine for slothd.

Supports two tiers:
1. High-Performance / Tiger Data: 768-dim embeddings stored in PostgreSQL + pgvector
2. Local Offline: SQLite-backed semantic index with keyword + vector matching
   so users without Docker can still experience "Where is my warranty PDF?" queries.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from slothd.engine.scanner import ScannedFile
from slothd.integrations.tiger_data import TigerDataClient

logger = logging.getLogger(__name__)


@dataclass
class SearchHit:
    """Standardized search match returned to CLI and Web Dashboard."""

    file_path: Path
    file_name: str
    category: str
    subcategory: str | None
    description: str | None
    vendor: str | None
    file_date: str | None
    similarity_score: float
    source: str = "tiger_data"  # "tiger_data" or "local_sqlite"

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": str(self.file_path),
            "file_name": self.file_name,
            "category": self.category,
            "subcategory": self.subcategory,
            "description": self.description,
            "vendor": self.vendor,
            "file_date": self.file_date,
            "similarity_score": round(self.similarity_score, 4),
            "source": self.source,
        }


def generate_embedding(
    text: str,
    *,
    ollama_host: str = "http://localhost:11434",
    embed_model: str = "nomic-embed-text",
) -> list[float]:
    """Generate a 768-dimensional embedding using Ollama nomic-embed-text.

    Falls back to a deterministic 768-dim hash-based unit vector if Ollama is
    offline or unreachable (guaranteeing tests and offline environments work).
    """
    try:
        import ollama  # type: ignore

        client = ollama.Client(host=ollama_host, timeout=0.5)
        res = client.embeddings(model=embed_model, prompt=text)
        embedding = res.get("embedding")
        if embedding and len(embedding) == 768:
            return embedding
    except Exception as e:
        logger.debug("Ollama embedding call failed (%s), using local fallback", e)

    return _fallback_deterministic_embedding(text)


def _fallback_deterministic_embedding(text: str, dim: int = 768) -> list[float]:
    """Generate a normalized pseudo-embedding from text for offline use."""
    import hashlib

    vec = [0.0] * dim
    words = text.lower().split()
    if not words:
        words = ["empty"]

    for word in words:
        h = hashlib.sha256(word.encode("utf-8")).digest()
        for i in range(0, min(len(h), 32)):
            idx = (h[i] + i * 23) % dim
            vec[idx] += float(h[i]) - 128.0

    # L2 normalize
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Compute cosine similarity between two float vectors."""
    if len(v1) != len(v2) or not v1:
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm1 * norm2)))


# --------------------------------------------------------------------------- #
#  Local SQLite Search Index                                                  #
# --------------------------------------------------------------------------- #

LOCAL_INDEX_TABLE = """
CREATE TABLE IF NOT EXISTS local_file_index (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path    TEXT UNIQUE NOT NULL,
    file_name    TEXT NOT NULL,
    category     TEXT NOT NULL,
    subcategory  TEXT,
    description  TEXT,
    vendor       TEXT,
    file_date    TEXT,
    tags         TEXT,
    embedding    TEXT, -- JSON list of floats
    indexed_at   TEXT NOT NULL
);
"""


class LocalFileIndex:
    """Lightweight SQLite-backed index for offline semantic search."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute(LOCAL_INDEX_TABLE)
        self.conn.commit()

    def index_file(
        self,
        *,
        file_path: Path,
        file_name: str,
        category: str,
        subcategory: str | None,
        description: str | None,
        vendor: str | None,
        file_date: str | None,
        tags: list[str],
        embedding: list[float],
    ) -> None:
        """Upsert file into local index."""
        from datetime import datetime

        self.conn.execute(
            """
            INSERT INTO local_file_index (
                file_path, file_name, category, subcategory, description,
                vendor, file_date, tags, embedding, indexed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(file_path) DO UPDATE SET
                file_name = excluded.file_name,
                category = excluded.category,
                subcategory = excluded.subcategory,
                description = excluded.description,
                vendor = excluded.vendor,
                file_date = excluded.file_date,
                tags = excluded.tags,
                embedding = excluded.embedding,
                indexed_at = excluded.indexed_at
            """,
            (
                str(file_path),
                file_name,
                category,
                subcategory,
                description,
                vendor,
                file_date,
                json.dumps(tags),
                json.dumps(embedding),
                datetime.now().isoformat(),
            ),
        )
        self.conn.commit()

    def search(
        self,
        query: str,
        query_embedding: list[float],
        limit: int = 5,
        min_similarity: float = 0.2,
    ) -> list[SearchHit]:
        """Search local index by vector similarity + text matching."""
        cursor = self.conn.execute(
            "SELECT file_path, file_name, category, subcategory, description, vendor, file_date, tags, embedding FROM local_file_index"
        )
        hits: list[tuple[float, SearchHit]] = []
        q_words = set(query.lower().split())

        for row in cursor.fetchall():
            (f_path, f_name, cat, subcat, desc, vend, f_date, tags_json, emb_json) = row
            tags = json.loads(tags_json) if tags_json else []
            emb = json.loads(emb_json) if emb_json else []

            # Cosine similarity
            sim = cosine_similarity(query_embedding, emb) if emb else 0.0

            # Keyword bonus
            haystack = (
                f"{f_name} {cat} {subcat or ''} {desc or ''} {vend or ''} {' '.join(tags)}".lower()
            )
            keyword_matches = sum(1 for w in q_words if w in haystack)
            if keyword_matches > 0 and q_words:
                bonus = 0.25 * (keyword_matches / len(q_words))
                sim = min(1.0, sim + bonus)

            if sim >= min_similarity:
                hit = SearchHit(
                    file_path=Path(f_path),
                    file_name=f_name,
                    category=cat,
                    subcategory=subcat,
                    description=desc,
                    vendor=vend,
                    file_date=f_date,
                    similarity_score=sim,
                    source="local_sqlite",
                )
                hits.append((sim, hit))

        hits.sort(key=lambda x: x[0], reverse=True)
        return [hit for _, hit in hits[:limit]]

    def count(self) -> int:
        cur = self.conn.execute("SELECT COUNT(*) FROM local_file_index")
        return cur.fetchone()[0]

    def close(self) -> None:
        self.conn.close()


# --------------------------------------------------------------------------- #
#  Unified Search Engine                                                      #
# --------------------------------------------------------------------------- #


class SearchEngine:
    """Unified search engine combining Tiger Data pgvector and Local SQLite."""

    def __init__(
        self,
        *,
        db_url: str | None = None,
        local_db_path: Path | None = None,
        ollama_host: str = "http://localhost:11434",
        embed_model: str = "nomic-embed-text",
    ) -> None:
        self.ollama_host = ollama_host
        self.embed_model = embed_model
        self.tiger_client = TigerDataClient(db_url) if db_url else None
        self.local_index = LocalFileIndex(
            local_db_path or (Path.home() / ".slothd" / "search_index.db")
        )

    def index_scanned_file(self, scanned_file: ScannedFile) -> None:
        """Generate embedding and index file in both Tiger Data and Local Index."""
        text_for_embed = (
            f"Filename: {scanned_file.name}\n"
            f"Category: {scanned_file.ai_category or scanned_file.basic_category}\n"
            f"Description: {scanned_file.ai_description or ''}\n"
            f"Vendor: {scanned_file.ai_vendor or ''}\n"
            f"Tags: {', '.join(scanned_file.tags)}"
        )
        vec = generate_embedding(
            text_for_embed,
            ollama_host=self.ollama_host,
            embed_model=self.embed_model,
        )

        category = scanned_file.ai_category or scanned_file.basic_category
        # Upsert local
        self.local_index.index_file(
            file_path=scanned_file.path,
            file_name=scanned_file.name,
            category=category,
            subcategory=scanned_file.ai_subcategory,
            description=scanned_file.ai_description,
            vendor=scanned_file.ai_vendor,
            file_date=scanned_file.ai_date,
            tags=scanned_file.tags,
            embedding=vec,
        )

        # Upsert Tiger Data if reachable
        if self.tiger_client and self.tiger_client.is_available():
            self.tiger_client.upsert_file_embedding(
                file_path=str(scanned_file.path),
                file_name=scanned_file.name,
                category=category,
                subcategory=scanned_file.ai_subcategory,
                description=scanned_file.ai_description,
                vendor=scanned_file.ai_vendor,
                file_date=scanned_file.ai_date,
                tags=scanned_file.tags,
                embedding=vec,
            )

    def search(
        self,
        query: str,
        limit: int = 5,
        min_similarity: float = 0.25,
    ) -> list[SearchHit]:
        """Perform semantic search across all indexed files."""
        query_vec = generate_embedding(
            query,
            ollama_host=self.ollama_host,
            embed_model=self.embed_model,
        )

        # Try Tiger Data first if available
        if self.tiger_client and self.tiger_client.is_available():
            tiger_results = self.tiger_client.search_similar(
                query_vec, limit=limit, min_similarity=min_similarity
            )
            if tiger_results:
                return [
                    SearchHit(
                        file_path=Path(r.file_path),
                        file_name=r.file_name,
                        category=r.category,
                        subcategory=r.subcategory,
                        description=r.description,
                        vendor=r.vendor,
                        file_date=r.file_date,
                        similarity_score=r.similarity,
                        source="tiger_data",
                    )
                    for r in tiger_results
                ]

        # Local fallback
        return self.local_index.search(
            query=query,
            query_embedding=query_vec,
            limit=limit,
            min_similarity=min_similarity,
        )
