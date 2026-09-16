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

# The chunks.json envelope version this module understands (paper-refinery's own
# MANIFEST_SCHEMA_VERSION, cli.py). Bumped there whenever the on-disk shape changes
# incompatibly -- checked here so an unrecognized *explicit* future version falls back
# to pypdf cleanly (same as a missing/stale manifest) instead of a downstream
# KeyError/TypeError from reading fields that no longer mean what this code assumes. A
# manifest with no schema_version at all predates the field (paper-refinery < v0.2.0)
# and is trusted, not rejected -- see read_refinery_chunks.
SUPPORTED_SCHEMA_VERSION = 1


def chunks_json_path(file_path: Path) -> Optional[Path]:
    """Path to the chunks manifest refinery writes next to a PDF.

    None for anything that isn't a PDF: refinery only refines PDFs, and its
    manifest is named after the *stem* (`paper.pdf` -> `paper.chunks.json`).
    A papis entry holding both `paper.pdf` and `paper.html` would otherwise
    have `with_suffix()` map both files onto the PDF's one manifest, so the
    HTML would silently get indexed with the PDF's chunks -- its own content
    never parsed, and the same text embedded twice under two docnames.
    """
    if file_path.suffix.lower() != ".pdf":
        return None
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
    """Read <pdf>.chunks.json if present, fresh, schema-compatible, and well-formed.

    Returns None (with a warning logged) if the manifest is missing, older than the
    PDF, an explicitly unrecognized schema version, or malformed, so callers can fall
    back to pypdf parsing. A manifest with no schema_version at all (predates the
    field) is trusted, not rejected.
    """
    chunks_path = chunks_json_path(file_path)
    if chunks_path is None or not chunks_path.exists():
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

    # A missing field is trusted, not rejected: it means this manifest predates the
    # field's introduction (paper-refinery < v0.2.0), back when the on-disk shape was
    # exactly what version 1 is -- confirmed live against paper-refinery's own
    # pre-versioning sample manifests, which are otherwise perfectly readable. Only an
    # *explicit* different version is untrusted: that's the actual signal a future
    # incompatible release would set.
    schema_version = payload.get("schema_version")
    if schema_version is not None and schema_version != SUPPORTED_SCHEMA_VERSION:
        logger.warning(
            "%s has schema_version %r, but this papis-ask understands only %d; "
            "ignoring and falling back to pypdf. Upgrade papis-ask, or re-run "
            "`refinery %s` with a compatible paper-refinery version.",
            chunks_path,
            schema_version,
            SUPPORTED_SCHEMA_VERSION,
            file_path,
        )
        return None

    if not payload.get("chunks"):
        logger.warning("%s has no chunks; ignoring", chunks_path)
        return None

    return payload
