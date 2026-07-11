"""Metadata provider for fetching metadata from local Papis database."""

from datetime import datetime
from typing import Optional, List, Any, Dict, ClassVar

from papis.document import Document
import papis.logging

from paperqa.types import DocDetails
from paperqa.utils import BIBTEX_MAPPING
from paperqa.clients.client_models import MetadataProvider, ClientQuery

logger = papis.logging.get_logger(__name__)

FIELDS_TO_OVERWRITE_FROM_METADATA = {
    "key",
    "docname",
    "citation",
}


class LocalDocQuery(ClientQuery):
    """Query model for local document metadata."""

    model_config = {"arbitrary_types_allowed": True}

    file_location: str
    papis_id: str
    file_last_indexed: float
    metadata_last_updated: float
    embedding_model: Optional[str] = None
    embedded_at: Optional[float] = None
    chunk_source: Optional[str] = None
    chunk_chars: Optional[int] = None
    chunk_overlap: Optional[int] = None
    fields: Optional[List[str]] = None


async def parse_papis_to_doc_details(
    doc: Document,
    file_location: str,
    file_last_indexed: float,
    metadata_last_updated: float,
    embedding_model: Optional[str] = None,
    embedded_at: Optional[float] = None,
    chunk_source: Optional[str] = None,
    chunk_chars: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
) -> DocDetails:
    """Convert Papis document metadata to DocDetails format."""

    bibtex_source = "self_generated"

    # Parse publication date
    publication_date = None
    year = doc.get("year")
    if year:
        publication_date = datetime(int(year), 1, 1)

    # Handle authors (fall back to editors if there are no authors)
    author_list = doc.get("author_list", doc.get("editor_list"))
    if author_list:
        authors = [
            f"{author.get('given', '').title()} {author.get('family', '').title()}".strip()
            for author in author_list
        ]
    else:
        authors = None

    doc_details = DocDetails(  # type: ignore[call-arg]
        bibtex_type=BIBTEX_MAPPING.get(doc.get("type") or "other", "misc"),
        authors=authors,
        publication_date=publication_date,
        year=year,
        volume=doc.get("volume"),
        issue=doc.get("issue"),
        publisher=doc.get("publisher"),
        issn=doc.get("issn"),
        pages=doc.get("pages"),
        journal=doc.get("journal"),
        url=doc.get("url"),
        title=doc.get("title"),
        doi=doc.get("doi"),
        file_location=file_location,
        other={},
    )

    # Add any additional fields to the 'other' dict. The `embedding_*` and
    # `chunk_*` entries record how this paper's stored vectors and chunk
    # boundaries were actually produced -- which model, which parser, which
    # chunk settings. Config changes to any of those invalidate what's on disk
    # while touching no file, so this stamp is the only thing that lets a later
    # run notice and rebuild instead of silently querying stale data.
    for key, value in (
        doc
        | {
            "client_source": ["papis"],
            "bibtex_source": [bibtex_source],
            "file_last_indexed": file_last_indexed,
            "metadata_last_updated": metadata_last_updated,
            "embedding_model": embedding_model,
            "embedded_at": embedded_at,
            "chunk_source": chunk_source,
            "chunk_chars": chunk_chars,
            "chunk_overlap": chunk_overlap,
        }
    ).items():
        if key not in doc_details.model_fields:
            if key in doc_details.other:
                doc_details.other[key] = [doc_details.other[key], value]
            else:
                doc_details.other[key] = value

    return doc_details


async def get_doc_details_from_papis(
    papis_id: str,
    file_location: str,
    file_last_indexed: float,
    metadata_last_updated: float,
    embedding_model: Optional[str] = None,
    embedded_at: Optional[float] = None,
    chunk_source: Optional[str] = None,
    chunk_chars: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
    fields: Optional[List[str]] = None,
    docs_by_id: Optional[Dict[str, Any]] = None,
) -> Optional[DocDetails]:
    """Get paper details from local Papis database given a document ID."""

    try:
        if not docs_by_id:
            logger.warning("No documents dictionary provided")
            return None

        doc_papis = docs_by_id.get(papis_id)
        if not doc_papis:
            logger.warning(f"Document not found for papis_id {papis_id}")
            return None

        if fields:
            filtered_doc_papis = Document(
                data={k: v for k, v in doc_papis.items() if k in fields}
            )
            return await parse_papis_to_doc_details(
                filtered_doc_papis,
                file_location,
                file_last_indexed,
                metadata_last_updated,
                embedding_model,
                embedded_at,
                chunk_source,
                chunk_chars,
                chunk_overlap,
            )

        return await parse_papis_to_doc_details(
            doc_papis,
            file_location,
            file_last_indexed,
            metadata_last_updated,
            embedding_model,
            embedded_at,
            chunk_source,
            chunk_chars,
            chunk_overlap,
        )

    except Exception as e:
        logger.error(f"Error getting Papis document {papis_id}: {str(e)}")
        return None


class PapisProvider(MetadataProvider[LocalDocQuery]):
    """Provider that fetches metadata from Papis documents."""

    # Class variable to store documents
    _docs_by_id: ClassVar[Optional[Dict[str, Any]]] = None

    @classmethod
    def configure(cls, docs_by_id: Dict[str, Any]) -> None:
        """Configure the provider with document dictionary."""
        cls._docs_by_id = docs_by_id

    async def _query(self, query: LocalDocQuery) -> Optional[DocDetails]:
        """Query the Papis database for document metadata."""
        return await get_doc_details_from_papis(
            papis_id=query.papis_id,
            file_location=query.file_location,
            fields=query.fields,
            file_last_indexed=query.file_last_indexed,
            metadata_last_updated=query.metadata_last_updated,
            embedding_model=query.embedding_model,
            embedded_at=query.embedded_at,
            chunk_source=query.chunk_source,
            chunk_chars=query.chunk_chars,
            chunk_overlap=query.chunk_overlap,
            docs_by_id=self.__class__._docs_by_id,
        )

    def query_factory(self, query: dict) -> LocalDocQuery:
        """Transform a raw query dict into a LocalDocQuery object."""
        required_fields = {"papis_id", "file_location"}
        missing_fields = required_fields - query.keys()

        if missing_fields:
            raise ValueError(
                f"Papis provider query missing required fields: {', '.join(missing_fields)}"
            )
        return LocalDocQuery(**query)
