"""Citation and page rendering in answers."""

from types import SimpleNamespace

import pytest

from papis_ask.output import context_pages, format_source, transform_answer


def make_context(name, ref="Kalman_1960", text="", summary="", chunk_source=None):
    other = {"ref": ref, "papis_id": "abc123"}
    if chunk_source is not None:
        other["chunk_source"] = chunk_source
    doc = SimpleNamespace(
        other=other,
        # The bibliographic page range from info.yaml. Deliberately set to
        # something that is NOT the chunk's location: nothing should read it.
        pages="35--45",
        file_location="/lib/kalman-1960/paper.pdf",
    )
    return SimpleNamespace(
        text=SimpleNamespace(name=name, doc=doc, text=text),
        context=summary,
        score=5,
    )


class TestContextPages:
    """The page cited must be where the *chunk* is, not where the article is.

    Regression: every output path used to print `doc.pages` -- the journal page
    range from info.yaml -- so all 22 chunks of a paper cited the same "35-45",
    and papers with no `pages:` field rendered a literal "p. None".
    """

    def test_single_page(self):
        assert context_pages(make_context("Kalman_1960 pages 6")) == "6"

    def test_page_range(self):
        assert context_pages(make_context("Raissi_2017 pages 19-22")) == "19-22"

    def test_chunk_without_pages(self):
        """paper-qa's own parser names chunks "... chunk 1" -- no page info."""
        assert context_pages(make_context("abc123 chunk 1")) is None

    def test_missing_name(self):
        assert context_pages(make_context("")) is None

    def test_never_falls_back_to_the_bibliographic_range(self):
        ctx = make_context("abc123 chunk 1")
        assert ctx.text.doc.pages == "35--45"  # available...
        assert context_pages(ctx) is None  # ...and deliberately not used


class TestFormatSource:
    def test_with_pages(self):
        assert (
            format_source(make_context("Kalman_1960 pages 6")) == "@Kalman_1960, p. 6"
        )

    def test_without_pages_omits_the_page_reference(self):
        """Rather than printing "p. None"."""
        assert format_source(make_context("abc123 chunk 1")) == "@Kalman_1960"

    def test_falls_back_to_papis_id_when_there_is_no_ref(self):
        ctx = make_context("abc123 chunk 1")
        ctx.text.doc.other = {"papis_id": "abc123"}
        assert format_source(ctx) == "@abc123"


class TestTransformAnswer:
    def make_answer(self, text, contexts):
        return SimpleNamespace(answer=text, question="q", contexts=contexts)

    def test_rewrites_a_real_citation_to_the_papis_ref(self):
        ctx = make_context("abc123 pages 6")
        answer = transform_answer(
            self.make_answer("The filter is recursive (abc123 pages 6).", [ctx])
        )
        assert "[@Kalman_1960, p. 6]" in answer.answer

    @pytest.mark.parametrize(
        "math",
        [
            "the term u_syn(x) dominates",
            "at step (k+1) the estimate converges",
            "we define f(x) = 0",
        ],
    )
    def test_leaves_ordinary_parenthesised_maths_alone(self, math):
        """Regression: the citation regex matched any (...) and rewrote it,
        turning "u_syn(x)" into a bogus "[@x]" citation marker."""
        ctx = make_context("abc123 pages 6")
        answer = transform_answer(self.make_answer(math, [ctx]))
        assert answer.answer == math


class TestNoteSourcesAreMarked:
    """Your own thinking must never be cited as if the authors had said it.

    Caught only by live validation: `Doc.citation` was being set to
    "<ref> (note)" at index time, but `update_index_metadata` lists `citation` in
    `fields_to_overwrite_from_metadata`, so the DocDetails upgrade replaced it
    with the papis title and the marker vanished. Nothing in the unit suite
    looked at `citation`, and rendering never read it in the first place.
    """

    def test_note_source_is_marked(self):
        ctx = make_context("abc123-note chunk 1", chunk_source="note")
        assert format_source(ctx) == "@Kalman_1960 (note)"

    def test_paper_source_is_not_marked(self):
        ctx = make_context("Kalman_1960 chunk 1 pages 6-7", chunk_source="refinery")
        assert format_source(ctx) == "@Kalman_1960, p. 6-7"

    def test_a_chunk_with_no_chunk_source_is_not_marked(self):
        """Entries indexed before chunk_source was stamped must still render."""
        assert format_source(make_context("Kalman_1960 chunk 1")) == "@Kalman_1960"

    def test_inline_citation_from_a_note_is_marked(self):
        answer = SimpleNamespace(
            answer="The whiteness assumption fails here (abc123-note).",
            contexts=[make_context("abc123-note chunk 1", chunk_source="note")],
        )
        assert "[@Kalman_1960 (note)]" in transform_answer(answer).answer

    def test_inline_citation_from_a_paper_is_unchanged(self):
        answer = SimpleNamespace(
            answer="The covariance propagates (Kalman_1960 pages 6-7).",
            contexts=[
                make_context("Kalman_1960 chunk 1 pages 6-7", chunk_source="refinery")
            ],
        )
        assert "[@Kalman_1960, p. 6-7]" in transform_answer(answer).answer
