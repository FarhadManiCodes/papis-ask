"""The seam between papis-ask and paper-refinery.

Not a test of refinery -- refinery has its own suite, and this package never
imports it. What's tested here is the part papis-ask actually owns: locating a
paper's manifest, deciding when to trust it, and the chunk-name round trip
between the names we write onto paper-qa Texts and the pages we later read back
off them for citations.
"""

import json
import os
from types import SimpleNamespace

import pytest

from papis_ask.output import context_pages
from papis_ask.refinery import chunk_name, chunks_json_path, read_refinery_chunks


@pytest.fixture
def pdf(tmp_path):
    p = tmp_path / "paper.pdf"
    p.write_bytes(b"%PDF-1.4")
    return p


def write_manifest(pdf, chunks):
    """Write a chunks.json next to `pdf`, newer than it (as refinery would)."""
    path = chunks_json_path(pdf)
    path.write_text(json.dumps({"chunks": chunks}))
    return path


class TestLocatingTheManifest:
    """Which file's chunks belong to which document."""

    def test_pdf_maps_to_its_manifest(self, tmp_path):
        assert chunks_json_path(tmp_path / "paper.pdf").name == "paper.chunks.json"

    def test_uppercase_extension_still_recognised(self, tmp_path):
        assert chunks_json_path(tmp_path / "paper.PDF").name == "paper.chunks.json"

    @pytest.mark.parametrize("name", ["paper.html", "paper.txt"])
    def test_non_pdf_has_no_manifest(self, tmp_path, name):
        """Refinery only refines PDFs, and names the manifest after the stem.

        Regression: this used to be a bare `with_suffix()`, which *replaces* the
        extension -- so a papis entry holding both `paper.pdf` and `paper.html`
        had both resolve to the same `paper.chunks.json`.
        """
        assert chunks_json_path(tmp_path / name) is None

    def test_html_never_picks_up_a_sibling_pdfs_chunks(self, tmp_path, pdf):
        """The regression above, end to end.

        This is what actually happened to mastrone-2021: the HTML was indexed
        with the PDF's refined chunks, its own content never parsed, and the same
        text sat in the index twice under two docnames.
        """
        write_manifest(pdf, [{"text": "content of the PDF", "index": 0}])
        html = tmp_path / "paper.html"
        html.write_text("<html>entirely different content</html>")

        assert read_refinery_chunks(html) is None


class TestWhenToTrustTheManifest:
    """papis-ask's own fallback rules: anything suspect means use paper-qa."""

    def test_well_formed_manifest_is_used(self, pdf):
        write_manifest(pdf, [{"text": "hello", "index": 0}])
        payload = read_refinery_chunks(pdf)
        assert payload["chunks"][0]["text"] == "hello"

    def test_missing_manifest_falls_back(self, pdf):
        assert read_refinery_chunks(pdf) is None

    def test_manifest_older_than_the_pdf_is_stale(self, pdf):
        """The PDF was replaced after it was refined, so the chunks describe
        content that is no longer there."""
        manifest = write_manifest(pdf, [{"text": "hello", "index": 0}])
        os.utime(manifest, (1, 1))
        assert read_refinery_chunks(pdf) is None

    def test_malformed_manifest_falls_back(self, pdf):
        chunks_json_path(pdf).write_text("{not json")
        assert read_refinery_chunks(pdf) is None

    def test_empty_manifest_falls_back(self, pdf):
        write_manifest(pdf, [])
        assert read_refinery_chunks(pdf) is None


class TestChunkNameRoundTrip:
    """chunk_name() writes the name onto a Text; context_pages() reads it back
    to cite a page. Nothing else parses these names, so the only thing that has
    to hold is that the two agree -- if they ever drift, citations silently lose
    their page numbers (which is exactly how "p. None" reached the output)."""

    def as_context(self, name):
        return SimpleNamespace(text=SimpleNamespace(name=name))

    @pytest.mark.parametrize(
        "page_start,page_end,expected",
        [
            (3, 5, "3-5"),
            (3, 3, "3"),
            (1, 1, "1"),
            (19, 22, "19-22"),
        ],
    )
    def test_pages_survive_the_round_trip(self, page_start, page_end, expected):
        name = chunk_name("Kalman_1960", 0, page_start, page_end)
        assert context_pages(self.as_context(name)) == expected

    def test_a_chunk_with_no_pages_round_trips_to_no_pages(self):
        """Refinery couldn't attribute a page (or paper-qa parsed it), so there
        is nothing to cite -- and we must not invent one."""
        name = chunk_name("Kalman_1960", 7, None, None)
        assert context_pages(self.as_context(name)) is None
