"""What a papis document contributes to the index.

The single source of truth for three call sites that must agree -- the
still-exists-on-disk sweep, the selection loop, and the sidecar loader. When
they disagree, the loader and the indexing loops have different ideas about
what exists, and the result is phantom deletes and sidecars orphaned on disk
forever.
"""

from pathlib import Path
from types import SimpleNamespace

from papis_ask.main import iter_indexable_files, warn_on_misplaced_note


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


def test_note_is_yielded_as_kind_note(tmp_path):
    """A paper-bound note rides alongside its paper, on the `notes:` axis."""
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    note = tmp_path / "notes.md"
    note.write_text("> quote\n[@Kalman_1960, p. 3]\n")

    doc = papis_doc(files=[str(pdf)], notes=[str(note)])
    assert set(iter_indexable_files(doc)) == {(pdf, "file"), (note, "note")}


def test_standalone_note_has_no_files(tmp_path):
    """A standalone note is an entry with a note and nothing else."""
    note = tmp_path / "note.md"
    note.write_text("An idea worth keeping.\n")

    doc = papis_doc(notes=[str(note)], type="note", ref="adjoint-vs-forward")
    assert set(iter_indexable_files(doc)) == {(note, "note")}


def test_note_named_but_never_created_is_skipped(tmp_path):
    """papis writes the `notes:` key before the file exists -- don't be fooled.

    `papis.notes.notes_path()` does `doc["notes"] = ...; save_doc(doc)` and only
    *then* (in `notes_path_ensured`) creates the file. So `papis edit --notes`
    that's cancelled at the editor, or any interruption in between, leaves an
    entry naming a note that isn't there. Yield it and it becomes a phantom:
    permanently "needs indexing", failing on every single run.
    """
    doc = papis_doc(notes=[str(tmp_path / "notes.md")])
    assert list(iter_indexable_files(doc)) == []


def test_warns_when_note_is_in_files_instead_of_notes(tmp_path, caplog):
    """`files: [note.md]` on a note entry indexes nothing, silently.

    Only `notes:` is discovered, so this shape is invisible -- and invisible
    without an error, which is exactly the failure that has you re-reading the
    source wondering why a query finds nothing.
    """
    doc = papis_doc(files=["/lib/note.md"], type="note", ref="adjoint-vs-forward")
    warn_on_misplaced_note(doc)

    assert "adjoint-vs-forward" in caplog.text
    assert "note.md" in caplog.text
    assert "notes:" in caplog.text


def test_no_warning_for_a_correctly_shaped_note():
    doc = papis_doc(notes=["/lib/note.md"], type="note", ref="ok")
    warn_on_misplaced_note(doc)


def test_no_warning_for_a_paper_with_md_artifacts(caplog):
    """A paper's refinery `<stem>.md` is not a misplaced note -- stay quiet.

    Every paper has one. Warning here would fire on the whole library, every
    run, about files that are working exactly as intended.
    """
    doc = papis_doc(
        files=["/lib/paper.pdf", "/lib/paper.md"], type="article", ref="Kalman_1960"
    )
    warn_on_misplaced_note(doc)

    assert caplog.text == ""
