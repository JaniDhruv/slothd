"""SerpApi web search integration for slothd.

Enables optional web grounding (`--enrich-online`) to verify vendor info,
flight details, product warranty pages, and store metadata without compromising
the default air-gapped posture.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class SerpApiClient:
    """Client for querying SerpApi for entity grounding."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key

    def is_available(self) -> bool:
        return bool(self.api_key)

    def search_entity(self, query: str) -> dict[str, Any] | None:
        """Search Google via SerpApi for knowledge graph or organic snippet info."""
        if not self.api_key:
            logger.debug("SerpApi key not configured; skipping web grounding.")
            return None

        try:
            from serpapi import GoogleSearch

            params = {
                "q": query,
                "api_key": self.api_key,
                "num": 3,
                "engine": "google",
            }
            search = GoogleSearch(params)
            results = search.get_dict()

            knowledge_graph = results.get("knowledge_graph", {})
            title = knowledge_graph.get("title")
            description = knowledge_graph.get("description")

            organic = results.get("organic_results", [])
            top_snippet = organic[0].get("snippet") if organic else None
            top_title = organic[0].get("title") if organic else None

            return {
                "query": query,
                "vendor_name": title or top_title,
                "description": description or top_snippet,
                "link": organic[0].get("link") if organic else None,
            }
        except Exception as e:
            logger.warning("SerpApi search error for '%s': %s", query, e)
            return None
