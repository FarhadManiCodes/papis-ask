"""Consume paper-refinery's <pdf>.chunks.json hand-off.

papis-ask never imports paper_refinery: refinery runs as its own tool
(`refinery` / `refinery-batch`, installed separately), and this module just
reads the JSON manifest it leaves next to the PDF. See
docs/paper-refinery-integration.md for the full contract.
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional

import papis.logging

logger = papis.logging.get_logger(__name__)


def chunks_json_path(file_path: Path) -> Path:
    """Path to the chunks manifest refinery writes next to a PDF."""
    return file_path.with_suffix(".chunks.json")


def chunk_name(
    docname: str,
    index: int,
    page_start: Optional[int],
    page_end: Optional[int],
) -> str:
    """Mirror paper_refinery.chunker.Chunk.name_for() without importing it."""
    if page_start is None:
        return f"{docname} chunk {index}"
    if page_start == page_end:
        return f"{docname} pages {page_start}"
    return f"{docname} pages {page_start}-{page_end}"


def read_refinery_chunks(file_path: Path) -> Optional[Dict[str, Any]]:
    """Read <pdf>.chunks.json if present, fresh, and well-formed.

    Returns None (with a warning logged) if the manifest is missing, older
    than the PDF, or malformed, so callers can fall back to pypdf parsing.
    """
    chunks_path = chunks_json_path(file_path)
    if not chunks_path.exists():
        return None

    if chunks_path.stat().st_mtime < file_path.stat().st_mtime:
        logger.warning(
            "Refined chunks for %s are older than the PDF; ignoring stale %s. "
            "Run `refinery %s` (or `refinery-batch`) to refresh it.",
            file_path,
            chunks_path,
            file_path,
        )
        return None

    try:
        with open(chunks_path) as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Failed to read %s: %s", chunks_path, e)
        return None

    if not payload.get("chunks"):
        logger.warning("%s has no chunks; ignoring", chunks_path)
        return None

    return payload
