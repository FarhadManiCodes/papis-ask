import os
import time
from pathlib import Path
from typing import Any, Dict, Iterator, Literal, Optional, Set, Tuple

import papis.cli
import papis.config
from papis.api import get_all_documents_in_lib
import papis.logging

import click
from click_default_group import DefaultGroup
import asyncio

from papis_ask.config import SECTION_NAME, create_paper_qa_settings
from papis_ask.output import (
    to_terminal_output,
    to_json_output,
    to_markdown_output,
)

logger = papis.logging.get_logger(__name__)

settings = None

FILE_ENDINGS = (".pdf", ".txt", ".html")

FileKind = Literal["file", "note"]


def iter_indexable_files(doc_papis: Any) -> Iterator[Tuple[Path, FileKind]]:
    """Every file of a papis document that belongs in the index, with its kind.

    The single source of truth for "what does this document contribute to the
    index", used by all three places that need to agree on it: the
    still-exists-on-disk sweep and the selection loop (both in `_index_async`),
    and `index_store.load_all_from_sidecars`. They must never disagree -- when
    the loader and the indexing loops have different ideas about what exists,
    the result is phantom deletes and sidecars orphaned on disk forever.
    """
    for file_path in doc_papis.get_files():
        path = Path(file_path)
        # .lower(): a `paper.PDF` would otherwise be silently skipped here while
        # `chunks_json_path` and `add_file_to_index` (which do lowercase) treat
        # it as a PDF.
        if path.suffix.lower() in FILE_ENDINGS:
            yield path, "file"

    # Notes come from papis' own `notes:` key, deliberately *not* from `files:`
    # via a `.md` entry in FILE_ENDINGS. Every paper here has a `<stem>.md`
    # sitting beside it holding its entire extracted text (refinery's doing),
    # so admitting `.md` from `files:` would, the first time anything registered
    # those artifacts, index every paper a second time under a second docname.
    for note_path in doc_papis.get_notes():
        path = Path(note_path)
        # papis writes `notes:` into info.yaml *before* the file exists
        # (papis.notes.notes_path), so an entry can name a note nobody has
        # opened yet. Without this check it becomes a phantom that permanently
        # "needs indexing" and fails on every run.
        if path.is_file():
            yield path, "note"


def warn_on_misplaced_note(doc_papis: Any) -> None:
    """Flag a `type: note` entry whose note is in `files:` instead of `notes:`.

    Notes are discovered *only* through papis' `notes:` key, so a note written
    into `files:` is never indexed -- and it fails in the worst way available:
    no error, no warning from papis, just a query that mysteriously never finds
    what you wrote. Say so at the one moment the user is watching.

    Deliberately lives here and not in `iter_indexable_files`: that generator is
    also called by `load_all_from_sidecars` on the *query* path, so warning
    inside it would fire on every question asked, three times over.
    """
    if doc_papis.get("type") != "note" or doc_papis.get("notes"):
        return

    stray = [f for f in doc_papis.get_files() if Path(f).suffix.lower() == ".md"]
    if not stray:
        return

    name = Path(stray[0]).name
    logger.warning(
        "'%s' is type: note with %s in files: but no notes: key -- it will not "
        "be indexed. Move it to `notes: %s`.",
        doc_papis.get("ref") or doc_papis.get("papis_id"),
        name,
        name,
    )


def remove_document_from_index(docs_index: Any, dockey: str) -> Tuple[str, str]:
    """Remove a document from the index."""
    # Get the document from the index
    doc = docs_index.docs.get(dockey)

    # Get file_location if it exists
    file_location = doc.file_location
    ref = doc.other["ref"]

    # Get docname for removal
    docname = doc.docname

    # Remove document from index
    docs_index.delete(dockey=dockey)
    docs_index.deleted_dockeys.remove(dockey)
    docs_index.docnames.remove(docname)

    from papis_ask.index_store import delete_paper_sidecar

    delete_paper_sidecar(file_location)

    return file_location, ref


async def add_file_to_index(
    file_path: Path,
    doc_papis: Dict[str, Any],
    docs_index: Any,
    clients: Any,
    settings: Any,
    use_refinery: bool = True,
    kind: FileKind = "file",
) -> Optional[str]:
    """Add a file to the paperqa index.

    Prefers refinery's pre-built chunks (<pdf>.chunks.json, produced by the
    separately-run `refinery`/`refinery-batch` CLI) over paper-qa's own pypdf
    parsing; falls back to pypdf when refinery hasn't been run for this PDF,
    its chunks are stale, or `use_refinery` is False.
    """
    from paperqa.utils import md5sum
    from papis_ask.refinery import chunk_name, read_refinery_chunks

    dockey = md5sum(file_path)

    ref, papis_id, _ = extract_doc_papis_metadata(doc_papis)

    # Only papers have refined chunks. Asking for a note's chunks.json would
    # always miss, and would log the "run refinery first" warning at someone who
    # cannot act on it -- refinery does not process markdown.
    chunks_payload = (
        read_refinery_chunks(file_path) if use_refinery and kind == "file" else None
    )

    try:
        if kind == "note":
            from paperqa.readers import chunk_text, parse_text
            from paperqa.types import Doc

            from papis_ask.config import get_chunk_params
            from papis_ask.notes import indexable_prose

            parsed = parse_text(file_path)
            prose = indexable_prose(parsed.content)
            if not prose:
                # A note holding only quotes and position markers has nothing of
                # yours in it yet. Embedding the empty remainder would pay for a
                # vector that can never answer anything.
                logger.info(
                    "Note %s has no prose left after removing quotes; not indexing.",
                    file_path,
                )
                return None

            chunk_chars, chunk_overlap = get_chunk_params()
            # Distinct docname and citation: an answer must never let your own
            # speculation wear the authors' name. `(note)` is what shows up in
            # the source list.
            doc = Doc(
                docname=f"{papis_id}-note",
                dockey=dockey,
                citation=f"{ref or papis_id} (note)",
            )
            texts = chunk_text(
                parsed.model_copy(update={"content": prose}),
                doc,
                chunk_chars,
                chunk_overlap,
            )
            added = await docs_index.aadd_texts(texts, doc, settings=settings)
            # Same in-place dedupe as the refinery path below.
            docname = doc.docname if added else None
            chunk_source = "note"
        elif chunks_payload is not None:
            from paperqa.types import Doc, Text

            doc = Doc(docname=papis_id, dockey=dockey, citation=papis_id)
            name = ref or papis_id
            texts = [
                Text(
                    text=chunk["text"],
                    name=chunk_name(
                        name,
                        chunk["index"],
                        chunk.get("page_start"),
                        chunk.get("page_end"),
                    ),
                    doc=doc,
                )
                for chunk in chunks_payload["chunks"]
            ]
            added = await docs_index.aadd_texts(texts, doc, settings=settings)
            # aadd_texts mutates doc.docname in place to dedupe it (e.g. when
            # a paper has two files -- both start out named `papis_id` --
            # the second gets a unique suffix) rather than returning it, so
            # read it back off `doc` instead of assuming it's still
            # `papis_id`; using the stale, pre-dedupe name here caused two
            # DocDetails entries to end up claiming the same `docname`, which
            # then crashed `remove_document_from_index`'s `docnames.remove()`
            # the next time both got reindexed together (KeyError: the
            # shared name was already removed by the first doc's removal).
            docname = doc.docname if added else None
            chunk_source = "refinery"
        else:
            if not use_refinery or file_path.suffix.lower() != ".pdf":
                # Either the caller opted out, or this isn't a PDF -- refinery
                # only refines PDFs, so paper-qa's own parser isn't a fallback
                # here, it's the only correct path. Nothing to warn about.
                logger.debug("Parsing %s with paper-qa directly.", file_path)
            else:
                logger.warning(
                    "No refined chunks found for %s; falling back to pypdf parsing. "
                    "Run `refinery %s` (or `refinery-batch`) first to use refined chunks.",
                    file_path,
                    file_path,
                )
            docname = await docs_index.aadd(
                file_path,
                dockey=dockey,
                docname=papis_id,  # to give somewhat sensible docnames (we don't depend on it)
                citation=papis_id,  # to avoid unnecessary llm calls
                settings=settings,
            )
            chunk_source = "pypdf"

        if docname:
            from papis_ask.config import get_chunk_params, get_embedding_model

            # Record how this document was actually split. Refinery-chunked
            # papers take their boundaries from chunks.json (whose mtime we
            # already watch) and ignore chunk-chars/overlap, so those are only
            # worth stamping -- and only worth comparing later -- where the
            # settings actually decided the boundaries: pypdf and notes.
            chunk_chars, chunk_overlap = (
                (None, None) if chunk_source == "refinery" else get_chunk_params()
            )
            # One clock read: indexing this file and embedding its texts are
            # the same event, so they must not disagree on when it happened.
            now = time.time()

            if ref := await update_index_metadata(
                file_path=file_path,
                file_last_indexed=now,
                dockey=dockey,
                docname=docname,
                doc_papis=doc_papis,
                docs_index=docs_index,
                clients=clients,
                settings=settings,
                # This path just embedded the texts, so the vectors on disk
                # are by definition the currently-configured model's.
                embedding_model=get_embedding_model(),
                embedded_at=now,
                chunk_source=chunk_source,
                chunk_chars=chunk_chars,
                chunk_overlap=chunk_overlap,
            ):
                return ref
            else:
                logger.warning("Couldn't upgrade Doc to DocDetails.")
                logger.warning("Usually, this means the 'info.yaml' has faults.")

    except ValueError as e:
        if "This does not look like a text document" in str(e):
            logger.warning(f"File not recognised as text document: {file_path}")
            logger.warning("Usually, this means the file is faulty or not ocr'ed")
        else:
            # Re-raise other ValueErrors
            raise

    return None


async def update_index_metadata(
    file_path: Path,
    file_last_indexed: float,
    dockey: str,
    docname: str,
    doc_papis: Dict[str, Any],
    docs_index: Any,
    clients: Any,
    settings: Any,
    embedding_model: Optional[str] = None,
    embedded_at: Optional[float] = None,
    chunk_source: Optional[str] = None,
    chunk_chars: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
) -> Optional[str]:
    """Update metadata for a file in the paperqa index.

    `embedding_model`/`embedded_at` and the `chunk_*` fields describe the
    vectors and chunk boundaries already stored for this paper, so callers
    that are only refreshing metadata must pass the *existing* values through
    unchanged (as they already do for `file_last_indexed`) rather than the
    currently-configured ones -- a metadata refresh neither re-embeds nor
    re-chunks anything, and claiming otherwise would mark stale data current.
    """
    # Extract metadata from Papis document
    ref, papis_id, _ = extract_doc_papis_metadata(doc_papis)

    # Fetch document details from metadata client
    if doc_details := await clients["papis"].query(
        settings=settings,
        papis_id=papis_id,
        file_location=str(file_path),
        file_last_indexed=file_last_indexed,
        metadata_last_updated=time.time(),
        embedding_model=embedding_model,
        embedded_at=embedded_at,
        chunk_source=chunk_source,
        chunk_chars=chunk_chars,
        chunk_overlap=chunk_overlap,
    ):
        query_args = {
            "settings": settings,
            # we don't need the doi, title, and authors but they are needed
            # for semantic scholar search
            "fields": [
                "citation_count",
                "source_quality",
                "is_retracted",
                "doi",
                "title",
                "authors",
            ],
            **{
                key: value
                for key, value in {
                    # we can do this being sure that the fields exist as PapisProvider
                    # assigns `None` if a value doesn't exist
                    "title": doc_details["title"],
                    "doi": doc_details["doi"],
                    "authors": doc_details["authors"],
                    "journal": doc_details["journal"],
                }.items()
                if value is not None
            },
        }
        # Semantic Scholar / journal-quality enrichment is a nice-to-have on
        # top of Papis' own metadata, reached over the network without an
        # API key by default -- a rate limit (429) or any other transient
        # error here must not abort indexing for this paper (or, under a
        # whole-library --force reindex, every paper after it).
        try:
            other_details = await clients["other"].query(**query_args)
        except Exception:
            logger.warning(
                "Semantic Scholar / journal-quality lookup failed for %s; "
                "continuing with Papis metadata only.",
                ref,
                exc_info=True,
            )
            other_details = None
        if other_details:
            doc_details = other_details + doc_details
        doc_details.fields_to_overwrite_from_metadata = {
            "citation"
        }  # Restrict what can be overwritten, needed for below
        doc_details.doc_id = dockey
        doc_details.dockey = dockey
        doc_details.docname = docname
        doc_details.key = docname

        # Overwrite the Doc with a DocDetails
        docs_index.docs[dockey] = doc_details

        # Update doc reference in all Text objects that point to this document
        for text in docs_index.texts:
            if text.doc.dockey == dockey:
                text.doc = doc_details

        # Save the updated index
        save_index(docs_index)
        return ref


def get_last_modified(file_path: Path) -> float:
    """Get the last modified time of a file."""
    return os.path.getmtime(file_path)


# NOTE: no types because we'd have to globally import Docs
def get_index():
    """Load the paperqa index from disk (one JSON sidecar per paper)."""
    from papis_ask.index_store import load_all_from_sidecars

    return load_all_from_sidecars()


# NOTE: no types because we'd have to globally import Docs
def save_index(docs):
    """Save the paperqa index to disk (one JSON sidecar per paper)."""
    from papis_ask.index_store import save_all

    save_all(docs)


def extract_doc_papis_metadata(
    doc_papis,
) -> tuple[str, str, Optional[str]]:
    """Extract standard metadata from a papis document."""
    ref: str = doc_papis.get("ref") or ""
    papis_id: str = doc_papis.get("papis_id")
    # fallback ref based on papis_id
    if ref.strip() == "":
        ref = papis_id

    doi: Optional[str] = doc_papis.get("doi")

    return ref, papis_id, doi


def determine_file_status(
    file_path: Path,
    info_yaml_path: Path,
    index_files_to_dockey: Dict[str, str],
    docs_index: Any,
) -> Tuple[bool, bool]:
    """Determine if a file needs to be re-indexed or just have its metadata updated."""
    from papis_ask.config import get_chunk_params, get_embedding_model
    from papis_ask.refinery import chunks_json_path

    dockey = index_files_to_dockey.get(str(file_path))

    # If file isn't in the index, it needs indexing
    if dockey is None:
        return True, False

    doc = docs_index.docs.get(dockey)
    if doc is None:
        return True, False

    # Get timestamps
    file_last_modified = get_last_modified(file_path)
    info_yaml_last_modified = (
        get_last_modified(info_yaml_path) if info_yaml_path.exists() else 0
    )
    chunks_path = chunks_json_path(file_path)
    chunks_last_modified = (
        get_last_modified(chunks_path)
        if chunks_path is not None and chunks_path.exists()
        else 0
    )

    # Get stored timestamps
    other = getattr(doc, "other", {})
    file_last_indexed = other.get("file_last_indexed", 0)
    metadata_last_updated = other.get("metadata_last_updated", 0)

    # Check if the file itself, or refinery's pre-built chunks for it, have
    # changed since last indexing -- refinery can regenerate chunks.json
    # (e.g. re-running after an OCR cache repair) without touching the PDF's
    # own mtime at all, which would otherwise leave a stale index silently
    # out of sync with what's actually on disk.
    needs_indexing = (
        file_last_modified > file_last_indexed
        or chunks_last_modified > file_last_indexed
    )

    # Vectors are only comparable to other vectors from the same model, so a
    # change to `ask.embedding` invalidates everything embedded under the old
    # one -- nothing about the *files* changes, so no mtime check above can
    # ever catch it. Left unchecked, we'd compare the query's new-model vector
    # against the paper's old-model vectors: a dimension change blows up, and
    # a same-dimension swap silently retrieves nonsense, which is worse.
    stored_embedding_model = other.get("embedding_model")
    current_embedding_model = get_embedding_model()
    if stored_embedding_model is None:
        # Indexed before we recorded this (or by an older papis-ask). We can't
        # tell which model produced these vectors, so don't assume they're
        # wrong and silently bill the user for re-embedding the whole library;
        # say so instead and let them decide to `--force`.
        logger.debug(
            "%s has no recorded embedding model; assuming it matches %s. "
            "Re-index with --force if you've changed `ask.embedding` since.",
            file_path,
            current_embedding_model,
        )
    elif stored_embedding_model != current_embedding_model:
        logger.info(
            "%s was embedded with %s but `ask.embedding` is now %s; re-embedding.",
            file_path,
            stored_embedding_model,
            current_embedding_model,
        )
        needs_indexing = True

    # Same blind spot, for how the document was *split* rather than embedded:
    # changing `ask.chunk-chars`/`ask.overlap` alters pypdf's chunk boundaries
    # while touching no file, so no mtime check catches it either. Applies to
    # anything these settings actually split -- pypdf papers and notes.
    # Refinery-chunked papers take their boundaries from chunks.json (already
    # watched above) and ignore these settings entirely, so re-chunking them on a
    # chunk-chars change would be pure wasted spend.
    if other.get("chunk_source") in ("pypdf", "note"):
        stored_chunking = (other.get("chunk_chars"), other.get("chunk_overlap"))
        current_chunking = get_chunk_params()
        if None not in stored_chunking and stored_chunking != current_chunking:
            logger.info(
                "%s was chunked at chunk-chars/overlap %s but config is now %s; re-chunking.",
                file_path,
                stored_chunking,
                current_chunking,
            )
            needs_indexing = True

    # Check if metadata has changed since last update
    needs_metadata_update = info_yaml_last_modified > metadata_last_updated

    # If we need to re-index, we don't need to separately update metadata
    if needs_indexing:
        needs_metadata_update = False

    return needs_indexing, needs_metadata_update


@click.group("ask", cls=DefaultGroup, default="query", default_if_no_args=True)
@click.help_option("-h", "--help")
def cli():
    """Ask questions about your library."""
    pass


@cli.command("query")
@click.argument("query", type=str)
@click.help_option("--help", "-h")
@click.option(
    "--output",
    "-o",
    help="Output format.",
    type=str,
    default=lambda: papis.config.getint("output", SECTION_NAME),
)
@click.option(
    "--evidence-k",
    "-e",
    help="Number of evidence pieces to retrieve.",
    type=int,
    default=lambda: papis.config.getint("evidence-k", SECTION_NAME),
)
@click.option(
    "--max-sources",
    "-m",
    help="Maximum number of sources for an answer.",
    type=int,
    default=lambda: papis.config.getint("max-sources", SECTION_NAME),
)
@click.option(
    "--answer-length",
    "-l",
    help="Length of the answer.",
    type=str,
    default=lambda: papis.config.getstring("answer-length", SECTION_NAME),
)
@papis.cli.bool_flag(
    "--context/--no-context",
    "-c",
    help="Show context for each source.",
    default=lambda: papis.config.getboolean("context", SECTION_NAME),
)
@papis.cli.bool_flag(
    "--excerpt/--no-excerpt",
    "-x",
    help="Show context including excerpt for each source.",
    default=lambda: papis.config.getboolean("excerpt", SECTION_NAME),
)
@papis.cli.bool_flag(
    "--math/--no-math",
    help="Render LaTeX math as readable Unicode in terminal output.",
    default=lambda: papis.config.getboolean("render-math", SECTION_NAME),
)
def query_cmd(
    query: str,
    output: str,
    evidence_k: int,
    max_sources: int,
    answer_length: str,
    context: bool,
    excerpt: bool,
    math: bool,
) -> None:
    """Ask questions about your library."""
    logger.debug(
        f"Starting 'ask' with query={query}, output={output}, evidence_k={evidence_k}, max_sources={max_sources}, answer_length={answer_length}, context={context}, excerpt={excerpt}, math={math} "
    )

    asyncio.run(
        _query_async(
            query,
            output,
            evidence_k,
            max_sources,
            answer_length,
            context,
            excerpt,
            math,
        )
    )


async def _query_async(
    query: str,
    output: str,
    evidence_k: int,
    max_sources: int,
    answer_length: str,
    context: bool,
    excerpt: bool,
    math: bool,
) -> None:
    """Async implementation of query command."""
    settings = create_paper_qa_settings()
    settings.answer.answer_max_sources = max_sources
    settings.answer.evidence_k = evidence_k
    settings.answer.answer_length = answer_length

    if evidence_k <= max_sources:
        logger.error("evidence_k must be larger than max_source")
        return

    docs_index = get_index()

    if docs_index:
        answer = await docs_index.aquery(query, settings=settings)

        if output == "json":
            output = to_json_output(answer)
            print(output)
        elif output == "markdown":
            output = to_markdown_output(answer, context, excerpt)
            print(output)
        else:
            to_terminal_output(answer, context, excerpt, math)

    else:
        logger.info(
            "The index is empty. Please index some files before asking question."
        )


@cli.command("index")
@papis.cli.query_argument()
@click.option(
    "--force",
    "-f",
    help="Force regeneration of the entire index.",
    is_flag=True,
    default=False,
)
@click.option(
    "--no-refine",
    "--raw",
    "no_refine",
    help="Skip refinery's pre-built chunks (<pdf>.chunks.json) even if present; "
    "always use paper-qa's own pypdf parsing instead.",
    is_flag=True,
    default=False,
)
def index_cmd(query: Optional[str], force: bool, no_refine: bool):
    """Update the library index."""
    logger.debug(
        f"Starting 'index' with query={query}, force={force}, no_refine={no_refine}"
    )
    asyncio.run(_index_async(query, force, not no_refine))


async def _index_async(
    query: Optional[str], force: bool, use_refinery: bool = True
) -> None:
    # importing all this here rather than globally since
    # it slows down shell autocmplete otherwise
    from papis_ask.metadata_provider import PapisProvider
    from paperqa.clients import DocMetadataClient

    from paperqa.clients.semantic_scholar import SemanticScholarProvider
    from paperqa.clients.journal_quality import JournalQualityPostProcessor
    from paperqa.types import DocDetails

    settings = create_paper_qa_settings()

    docs_index = get_index()
    # Only wipe to an empty index for a true full-library rebuild (force with
    # no query, matching --force's own "regeneration of the entire index").
    # force + a query means "force-reindex just what matches", which must
    # keep the rest of the existing index intact, not silently drop it.
    if docs_index is None or (force and not query):
        from paperqa import Docs

        logger.debug("Creating new empty Docs instance")
        docs_index = Docs()

    logger.debug(f"The paper-qa index contains {len(docs_index.docs)} document(s)")

    if query:
        docs_papis = papis.cli.handle_doc_folder_or_query(query, None)
    else:
        docs_papis = get_all_documents_in_lib()

    logger.debug(f"The Papis library contains {len(docs_papis)} document(s)")

    # Configure PapisProvider with the documents dictionary
    papis_id_to_doc = {doc["papis_id"]: doc for doc in docs_papis}
    PapisProvider.configure(docs_by_id=papis_id_to_doc)

    clients = {
        "papis": DocMetadataClient(
            metadata_clients={
                PapisProvider,
                JournalQualityPostProcessor,
            }
        ),
        "other": DocMetadataClient(
            metadata_clients={
                SemanticScholarProvider,
            }
        ),
    }

    files_to_index: Set[Tuple[Path, str, FileKind]] = set()
    files_to_update_metadata: Set[Tuple[Path, str, FileKind]] = set()
    files_to_delete: Set[Path] = set()

    # Track existing files to later determine which ones to delete. This has
    # to cover the *whole* library, not just the query-scoped papis_id_to_doc:
    # a query only decides what gets indexed/updated this run, never what
    # counts as "still exists" -- otherwise `papis ask index "author:X"` would
    # make every other document look deleted and wipe it from the index.
    files_on_disk: Set[Path] = set()
    all_docs_papis = get_all_documents_in_lib() if query else docs_papis
    for doc_papis in all_docs_papis:
        warn_on_misplaced_note(doc_papis)
        for file_path, _kind in iter_indexable_files(doc_papis):
            files_on_disk.add(file_path)

    # Create a mapping of filenames to dockeys
    index_files_to_dockey: Dict[str, str] = {}
    for dockey, doc in docs_index.docs.items():
        if type(doc) is DocDetails and hasattr(doc, "file_location"):
            index_files_to_dockey[str(doc["file_location"])] = dockey

    # check the query-scoped files only
    for papis_id, doc_papis in papis_id_to_doc.items():
        info_yaml_path = Path(doc_papis.get_info_file())

        # Figure out what documents need to be indexed
        for file_path, kind in iter_indexable_files(doc_papis):
            # Skip processing if force is enabled (everything will be re-indexed)
            if force:
                files_to_index.add((file_path, papis_id, kind))
                continue

            # Use the function to determine file status
            needs_indexing, needs_metadata_update = determine_file_status(
                file_path, info_yaml_path, index_files_to_dockey, docs_index
            )

            if needs_indexing:
                logger.debug(f"File {file_path} needs to be indexed")
                files_to_index.add((file_path, papis_id, kind))
            elif needs_metadata_update:
                logger.debug(f"File {file_path} needs metadata update")
                files_to_update_metadata.add((file_path, papis_id, kind))

    logger.info(f"{len(files_to_index)} file(s) will be indexed")

    # Removing all files needing to be indexed from those that need metadata updated
    files_to_update_metadata -= files_to_index
    logger.info(
        f"{len(files_to_update_metadata)} file(s) will have their metadata updated"
    )

    # Figure out which documents need to be deleted
    files_to_delete = {
        Path(file) for file in index_files_to_dockey.keys()
    } - files_on_disk
    logger.info(f"{len(files_to_delete)} file(s) will be removed from the index")

    unchanged_files = max(
        0,
        (
            len(index_files_to_dockey)
            - len(files_to_update_metadata)
            - len(files_to_index)
            - len(files_to_delete)
        ),
    )
    logger.info(f"{unchanged_files} file(s) will remain unchanged")

    # Find files to be deleted because they don't exist on disk anymore
    dockeys_to_delete_bc_missing: list[str] = [
        index_files_to_dockey[str(file)] for file in files_to_delete
    ]

    # find files to be deleted because they changed and will be replaced with new ones
    dockeys_to_delete_bc_updated: list[str] = [
        index_files_to_dockey[str(file)]
        for file, _, _ in files_to_index
        if str(file) in index_files_to_dockey
    ]

    # Delete files that have been updated (to avoid having duplicates of same file with different hashes)
    for dockey in dockeys_to_delete_bc_updated:
        remove_document_from_index(docs_index, dockey)

    # Delete files that have been deleted
    counter = 0
    total_files = len(dockeys_to_delete_bc_missing)
    for dockey in dockeys_to_delete_bc_missing:
        counter += 1
        file_location, ref = remove_document_from_index(docs_index, dockey)
        if file_location:
            logger.info(
                "%d/%d: Removed @%s (%s)",
                counter,
                total_files,
                ref,
                file_location,
            )

    # index all new files or changed files
    counter = 0
    total_files = len(files_to_index)
    for file_path, papis_id, kind in files_to_index:
        counter += 1

        doc_papis = papis_id_to_doc[papis_id]

        if ref := await add_file_to_index(
            file_path=file_path,
            doc_papis=doc_papis,
            docs_index=docs_index,
            clients=clients,
            settings=settings,
            use_refinery=use_refinery,
            kind=kind,
        ):
            logger.info(
                "%d/%d: Indexed @%s (%s)",
                counter,
                total_files,
                ref,
                file_path.name,
            )
        else:
            logger.warning("Failed to index file: %s", file_path)

    # update metadata for papis documents that have changed
    counter = 0
    total_files = len(files_to_update_metadata)
    for file_path, papis_id, _kind in files_to_update_metadata:
        counter += 1

        doc_papis = papis_id_to_doc[papis_id]
        dockey = index_files_to_dockey.get(str(file_path))
        doc_index = docname = docs_index.docs[dockey]
        docname = doc_index.docname
        if type(doc_index) is DocDetails:
            other = docs_index.docs[dockey].other  # type: ignore (they should all be DocDetails)
            file_last_indexed = other["file_last_indexed"]
            # Carry the existing embedding/chunking stamp through untouched:
            # this path refreshes metadata only, it neither re-embeds nor
            # re-chunks.
            embedding_model = other.get("embedding_model")
            embedded_at = other.get("embedded_at")
            chunk_source = other.get("chunk_source")
            chunk_chars = other.get("chunk_chars")
            chunk_overlap = other.get("chunk_overlap")

            if not dockey:
                logger.warning(
                    "File %s is not in the index, skipping metadata update",
                    file_path,
                )
                continue
            if ref := await update_index_metadata(
                file_path=file_path,
                file_last_indexed=file_last_indexed,
                doc_papis=doc_papis,
                docs_index=docs_index,
                dockey=dockey,
                docname=docname,
                clients=clients,
                settings=settings,
                embedding_model=embedding_model,
                embedded_at=embedded_at,
                chunk_source=chunk_source,
                chunk_chars=chunk_chars,
                chunk_overlap=chunk_overlap,
            ):
                logger.info(
                    "%d/%d: Updated metadata for @%s (%s)",
                    counter,
                    total_files,
                    ref,
                    file_path.name,
                )
            else:
                logger.warning("Failed to update metadata for file: %s", file_path)
        else:
            logger.warning(f"Skipped {file_path} because it is not a DocDetails object")

    save_index(docs_index)
