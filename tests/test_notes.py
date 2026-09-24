"""What survives from a reading note into the index.

The quote fences exist so that a passage already embedded from the PDF is not
embedded a second time from a note about it. If stripping regresses, nothing
breaks loudly -- questions just start returning the same paragraph twice under
two names, quietly spending the `max-sources` budget. These tests are the only
thing that would notice.
"""

from papis_ask.notes import indexable_prose, strip_note_markup


def test_strips_quote_block_and_keeps_prose():
    note = """## p.7 — 2026-08-05
<!--sioyek page=6 label=7 offset_y=3412.8-->

<!--quote-->
> the residual is bounded by the
> discrete inf-sup constant
<!--/quote-->

this is the assumption that breaks for a non-conforming mesh
"""
    out = strip_note_markup(note)
    assert "this is the assumption that breaks for a non-conforming mesh" in out
    assert "inf-sup" not in out
    assert "sioyek" not in out
    assert "<!--" not in out


def test_strips_every_quote_block_not_just_the_first():
    note = """<!--quote-->
> first passage
<!--/quote-->
thought one
<!--quote-->
> second passage
<!--/quote-->
thought two
"""
    out = strip_note_markup(note)
    assert "first passage" not in out
    assert "second passage" not in out
    assert "thought one" in out
    assert "thought two" in out


def test_uncommented_capture_is_not_indexable():
    """The state every Alt+n capture passes through before you type anything.

    Heading plus quote and nothing else: `strip_note_markup` still leaves the
    heading (it is real text), but there is no thought here to embed, so
    `indexable_prose` reports nothing and the caller skips the file.
    """
    note = """## p.3
<!--sioyek page=2 label=3 offset_y=100.0-->

<!--quote-->
> nothing but someone else's words
<!--/quote-->
"""
    assert strip_note_markup(note) == "## p.3"
    assert indexable_prose(note) == ""


def test_headings_are_kept_once_there_is_prose():
    """`## p.7` tells a retrieved chunk which page it came from -- worth keeping."""
    note = "## p.7\n\nthe bound is only valid for conforming meshes\n"
    out = indexable_prose(note)
    assert out.startswith("## p.7")
    assert "conforming meshes" in out


def test_unclosed_fence_fails_open():
    """Losing the prose would be worse than over-indexing one passage."""
    note = """<!--quote-->
> a quote whose closing fence got deleted

my thought that must not disappear
"""
    out = strip_note_markup(note)
    assert "my thought that must not disappear" in out
    assert "<!--" not in out


def test_tolerates_whitespace_in_the_fences():
    note = "<!-- quote -->\n> passage\n<!-- /quote -->\nmy point\n"
    out = strip_note_markup(note)
    assert out == "my point"


def test_blank_line_runs_collapse():
    note = "para one\n\n<!--quote-->\n> x\n<!--/quote-->\n\npara two\n"
    assert strip_note_markup(note) == "para one\n\npara two"


def test_ordinary_blockquote_is_kept():
    """Only fenced quotes are source text; a bare '>' may be your own emphasis."""
    note = "> my own emphasised line\n\nand a thought\n"
    out = strip_note_markup(note)
    assert "my own emphasised line" in out


# ---------------------------------------------------------------------------
# note chunk labels
# ---------------------------------------------------------------------------


def _note_index():
    from paperqa import Docs
    from paperqa.types import DocDetails, Text

    doc = DocDetails(
        docname="x",
        dockey="n1",
        citation="c",
        other={"chunk_source": "note", "ref": "Kalman_1960"},
    )
    doc.docname = "6daaa-note"
    doc.dockey = "n1"
    paper = DocDetails(
        docname="y",
        dockey="p1",
        citation="c",
        other={"chunk_source": "refinery", "ref": "Kalman_1960"},
    )
    texts = [Text(text="t", name=f"{doc.docname} chunk {i}", doc=doc) for i in (1, 2)]
    # DocDetails recomputes docname on assignment; names use whatever it holds
    texts.append(Text(text="p", name="Kalman_1960 pages 5", doc=paper))
    return Docs(docs={"n1": doc, "p1": paper}, texts=texts)


def test_note_chunks_are_labelled_with_the_papers_ref():
    from papis_ask import main

    index = _note_index()
    docname_before = index.docs["n1"].docname
    assert main._relabel_indexed_notes(index) == 2
    assert [t.name for t in index.texts] == [
        "Kalman_1960 note chunk 1",
        "Kalman_1960 note chunk 2",
        "Kalman_1960 pages 5",
    ]
    assert index.docs["n1"].docname == docname_before  # identity untouched
    assert main._relabel_indexed_notes(index) == 0  # idempotent


def test_migration_reports_a_relabel_so_the_index_is_saved():
    from papis_ask import main

    assert main._migrate_index(_note_index()) is True
