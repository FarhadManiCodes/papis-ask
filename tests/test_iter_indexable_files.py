"""What a papis document contributes to the index.

The single source of truth for three call sites that must agree -- the
still-exists-on-disk sweep, the selection loop, and the sidecar loader. When
they disagree, the loader and the indexing loops have different ideas about
what exists, and the result is phantom deletes and sidecars orphaned on disk
forever.
"""

from pathlib import Path
from types import SimpleNamespace

from papis_ask.main import iter_indexable_files


def papis_doc(files=(), notes=(), **fields):
    """A papis document exposing just the two accessors discovery walks."""
    return SimpleNamespace(
        get_files=lambda: list(files),
        get_notes=lambda: list(notes),
        get=lambda key, default=None: fields.get(key, default),
    )


def test_yields_indexable_files_as_kind_file():
    doc = papis_doc(files=["/lib/paper.pdf", "/lib/paper.html", "/lib/notes.txt"])
    assert set(iter_indexable_files(doc)) == {
        (Path("/lib/paper.pdf"), "file"),
        (Path("/lib/paper.html"), "file"),
        (Path("/lib/notes.txt"), "file"),
    }


def test_skips_unindexable_extensions():
    doc = papis_doc(files=["/lib/paper.pdf", "/lib/paper.djvu", "/lib/scan.jpg"])
    assert set(iter_indexable_files(doc)) == {(Path("/lib/paper.pdf"), "file")}


def test_uppercase_extension_is_indexed():
    """`paper.PDF` was silently skipped while the rest of the pipeline took it.

    The suffix check here was case-sensitive, but `chunks_json_path` and
    `add_file_to_index` both lowercase before deciding it's a PDF -- so an
    uppercase file was invisible to discovery yet perfectly indexable had it
    ever arrived.
    """
    doc = papis_doc(files=["/lib/paper.PDF"])
    assert set(iter_indexable_files(doc)) == {(Path("/lib/paper.PDF"), "file")}


def test_md_in_files_is_never_yielded():
    """The refinery-artifact landmine: `.md` must never enter FILE_ENDINGS.

    Every paper in the library has a `<stem>.md` sitting beside it holding its
    full extracted text (plus `.refinery/references.md`, `refinery.md`). None
    are in `files:` today, so they're invisible -- but admit `.md` here and the
    day anything registers them (a `papis addto`, a doctor fix) every paper's
    entire text gets indexed a second time: duplicate content under a second
    docname, double the embedding spend, and retrieval polluted with exact
    duplicates of every paper.

    Notes are discovered from `notes:` instead, which no artifact can occupy.
    """
    doc = papis_doc(
        files=[
            "/lib/paper.pdf",
            "/lib/a-new-approach-to-linear-filtering-and-p.md",
            "/lib/paper.refinery/references.md",
        ]
    )
    assert set(iter_indexable_files(doc)) == {(Path("/lib/paper.pdf"), "file")}


def test_no_files_yields_nothing():
    """An entry with nothing indexable must yield nothing -- not raise.

    `--prune` keys off this: a zero-yield document is treated as "don't touch",
    never as "every sidecar here is orphaned".
    """
    assert list(iter_indexable_files(papis_doc())) == []
