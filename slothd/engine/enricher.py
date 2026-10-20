"""Metadata enricher — web grounding via SerpApi when opted into.

Keeps slothd air-gapped by default; only runs when --enrich-online is passed.
"""

from __future__ import annotations

import logging

from slothd.engine.scanner import ScannedFile
from slothd.integrations.serpapi_client import SerpApiClient

logger = logging.getLogger(__name__)


def enrich_file_metadata(
    scanned_file: ScannedFile,
    serpapi_client: SerpApiClient,
) -> bool:
    """Enrich a ScannedFile's vendor and description with SerpApi web grounding.

    Args:
        scanned_file: File to enrich.
        serpapi_client: Configured SerpApiClient instance.

    Returns:
        True if enriched, False otherwise.
    """
    if not serpapi_client.is_available():
        return False

    # Determine best search term
    search_term = None
    if scanned_file.ai_vendor:
        search_term = f"{scanned_file.ai_vendor} official site customer service"
    elif scanned_file.ai_subcategory and scanned_file.ai_subcategory not in ("Unknown", "Other"):
        search_term = f"{scanned_file.ai_subcategory} {scanned_file.name}"
    else:
        search_term = scanned_file.name.replace("_", " ").replace("-", " ")

    data = serpapi_client.search_entity(search_term)
    if not data:
        return False

    if data.get("vendor_name"):
        scanned_file.ai_vendor = data["vendor_name"]

    if data.get("description"):
        current_desc = scanned_file.ai_description or ""
        scanned_file.ai_description = (
            f"{current_desc} (Verified via web: {data['description'][:120]}...)".strip()
        )

    if data.get("link"):
        scanned_file.tags.append("web_verified")

    logger.info("Enriched %s via SerpApi: %s", scanned_file.name, scanned_file.ai_vendor)
    return True
