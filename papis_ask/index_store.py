"""Per-paper JSON sidecar persistence for the paper-qa index.

Replaces the old single pickle file (~/.cache/papis/<lib>.qa) with one small
`<pdf-stem>.embeddings.json` file per paper, living next to the PDF -- a
sibling to paper-refinery's own `<pdf-stem>.chunks.json` (same idea, a
different owner/file). The old pickle was a single point of total failure:
`save_index()` did a plain non-atomic overwrite of the *entire* library's
index on every call (once per indexed/updated paper, plus once more at the
end of every run), so any crash mid-write corrupted everyone's embeddings,
not just whichever paper was being processed. Splitting by paper means a bad
write can only ever affect that one paper, and each write is itself done via
temp-file + atomic rename so even that single file can't be left half-written.
"""

import json
import os
from pathlib import Path
from typing import Any, List, Optional, Tuple

import papis.logging

logger = papis.logging.get_logger(__name__)


def embeddings_json_path(file_location: Any) -> Path:
    """Path to the embeddings sidecar this module writes next to a paper's file.

    Appends rather than replacing the suffix: a paper can have multiple files
    of different types sharing one stem (e.g. both a .pdf and a .html version),
    and .with_suffix() would map them to the same filename, silently clobbering
    one with the other. (chunks_json_path does replace the suffix, because
    that's refinery's own naming convention -- which is exactly why it now
    returns None for non-PDFs rather than handing the .html the .pdf's chunks.)
    """
    return Path(str(file_location) + ".embeddings.json")


def write_paper_sidecar(doc: Any, texts: List[Any]) -> bool:
    """Atomically write one paper's Doc + Texts to its sidecar file.

    Returns False (with a warning logged) if the doc has no file_location to
    derive a sidecar path from, or if the write fails.
    """
    if not doc.file_location:
        logger.warning(
            "Doc %s has no file_location; cannot write embeddings sidecar",
            doc.docname,
        )
        return False

    path = embeddings_json_path(doc.file_location)
    payload = {
        "doc": doc.model_dump(mode="json"),
        # Exclude the nested `doc` field on each Text: it's the same object
        # repeated for every chunk, stored once at the top level instead.
        "texts": [t.model_dump(mode="json", exclude={"doc"}) for t in texts],
    }

    # Embeddings dominate file size (thousands of floats per chunk) and
    # aren't meant to be human-read, so skip refinery chunks.json's
    # pretty-printing convention here -- compact JSON keeps writes/reads fast.
    tmp_path = path.with_name(path.name + ".tmp")
    try:
        with open(tmp_path, "w") as f:
            json.dump(payload, f)
        os.replace(tmp_path, path)
    except OSError as e:
        logger.error("Failed to write sidecar %s: %s", path, e)
        return False

    # Read-only between writes: rename/unlink only need write permission on
    # the *directory* (unaffected by this), but a naive `open(path, "w")` by
    # some unrelated tool does check the file's own permission bits and will
    # fail loudly instead of silently truncating our data.
    try:
        path.chmod(0o444)
    except OSError as e:
        logger.warning("Failed to make sidecar %s read-only: %s", path, e)

    return True


def read_paper_sidecar(path: Path) -> Optional[Tuple[Any, List[Any]]]:
    """Read one paper's sidecar file back into (DocDetails, [Text, ...]).

    Returns None (with an error logged) if the file is missing, malformed, or
    fails pydantic validation.
    """
    from pydantic import ValidationError
    from paperqa.types import DocDetails, Text

    if not path.exists():
        return None

    try:
        with open(path) as f:
            payload = json.load(f)
        doc = DocDetails.model_validate(payload["doc"])
        texts = [
            Text.model_validate({**text_dict, "doc": doc})
            for text_dict in payload["texts"]
        ]
    except (OSError, json.JSONDecodeError, KeyError, ValidationError) as e:
        logger.error("Failed to read sidecar %s: %s", path, e)
        return None

    return doc, texts


def _migrate_legacy_text_fields(docs: Any) -> int:
    """Patch old pickled Text objects to add fields introduced since they
    were saved. Pickle bypasses pydantic validation entirely (it restores
    an object's __dict__ directly), so an old Text may be missing attributes
    a newer paper-qa version added -- this is the same shim papis-ask's old
    `_migrate_index()` used. Only needed for this one-time pickle read: JSON
    `model_validate()` fills in defaults for missing fields on every future
    load, so no equivalent is needed once sidecar files are the source of
    truth.
    """
    from paperqa.types import Text as TextType

    missing_fields: dict[str, object] = {
        name: field.get_default(call_default_factory=True)
        for name, field in TextType.model_fields.items()
        if not field.is_required() and field.default_factory is not None
    }
    if not missing_fields:
        return 0

    migrated = 0
    for text in docs.texts:
        for field_name, default_value in missing_fields.items():
            if not hasattr(text, field_name):
                object.__setattr__(text, field_name, default_value)
                migrated += 1
    return migrated


def _legacy_pickle_file() -> Path:
    from papis.config import get_lib
    from papis.utils import get_cache_home

    return Path(get_cache_home()) / "{}.qa".format(get_lib().name)


def _migrate_pickle_if_present() -> None:
    """One-time split of the legacy pickle index into per-paper sidecar
    files, so already-embedded papers never need re-embedding. Idempotent:
    renames the old file to `.bak` on success, so later calls find nothing
    to migrate.
    """
    import pickle

    old_file = _legacy_pickle_file()
    if not old_file.exists():
        return

    try:
        with open(old_file, "rb") as f:
            old_docs = pickle.load(f)
    except (OSError, pickle.PickleError) as e:
        logger.error("Failed to read legacy index for migration: %s", e)
        return

    _migrate_legacy_text_fields(old_docs)

    migrated = 0
    for dockey, doc in old_docs.docs.items():
        texts = [t for t in old_docs.texts if t.doc.dockey == dockey]
        if write_paper_sidecar(doc, texts):
            migrated += 1

    backup = old_file.with_name(old_file.name + ".bak")
    old_file.rename(backup)
    logger.info(
        "Migrated %d paper(s) from the legacy pickle index to per-paper "
        "sidecar files; old index backed up to %s",
        migrated,
        backup,
    )


def load_all_from_sidecars() -> Optional[Any]:
    """Assemble an in-memory Docs from every paper's sidecar file.

    Returns None if nothing has ever been indexed (mirrors the old
    get_index()'s None-if-no-pickle-file-yet behavior), so callers that check
    `if docs_index:` keep working unchanged.
    """
    from paperqa import Docs
    from papis.api import get_all_documents_in_lib
    from papis_ask.main import FILE_ENDINGS

    _migrate_pickle_if_present()

    docs_by_key: dict[Any, Any] = {}
    texts: List[Any] = []
    docnames: set[str] = set()

    for doc_papis in get_all_documents_in_lib():
        for file_path in doc_papis.get_files():
            file_path = Path(file_path)
            if file_path.suffix not in FILE_ENDINGS:
                continue

            result = read_paper_sidecar(embeddings_json_path(file_path))
            if result is None:
                continue

            doc, paper_texts = result
            docs_by_key[doc.dockey] = doc
            texts.extend(paper_texts)
            docnames.add(doc.docname)

    if not docs_by_key:
        return None

    return Docs(docs=docs_by_key, texts=texts, docnames=docnames)


def save_all(docs: Any) -> None:
    """Write every paper currently in `docs` to its own sidecar file."""
    for dockey, doc in docs.docs.items():
        paper_texts = [t for t in docs.texts if t.doc.dockey == dockey]
        write_paper_sidecar(doc, paper_texts)


def delete_paper_sidecar(file_location: Any) -> None:
    """Remove one paper's sidecar file, if present."""
    if not file_location:
        return
    path = embeddings_json_path(file_location)
    try:
        path.unlink(missing_ok=True)
    except OSError as e:
        logger.error("Failed to delete sidecar %s: %s", path, e)
