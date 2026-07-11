"""What counts as "this paper needs re-indexing".

The expensive question in the whole package: say no when you should have said
yes and the index silently serves stale or incomparable vectors; say yes when
you shouldn't and the user pays to re-embed their library.

Every case here is a config change that touches *no file on disk*, which is
precisely why none of them can be caught by an mtime check.
"""

import json
import os
from types import SimpleNamespace

import pytest

import papis_ask.config as config
from papis_ask.main import determine_file_status
from papis_ask.refinery import chunks_json_path

MODEL = "gemini/gemini-embedding-2"
CHUNKING = (5000, 250)


@pytest.fixture(autouse=True)
def current_config(monkeypatch):
    """Pin the "currently configured" model and chunking; tests vary these."""
    monkeypatch.setattr(config, "get_embedding_model", lambda: MODEL)
    monkeypatch.setattr(config, "get_chunk_params", lambda: CHUNKING)


@pytest.fixture
def paper(tmp_path):
    """A PDF, its info.yaml, and a refinery manifest -- all older than the index."""
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    info = tmp_path / "info.yaml"
    info.write_text("ref: Kalman_1960\n")
    chunks_json_path(pdf).write_text(
        json.dumps({"chunks": [{"text": "x", "index": 0}]})
    )

    # Index entry recorded well after every file was written.
    indexed_at = pdf.stat().st_mtime + 1000
    return SimpleNamespace(pdf=pdf, info=info, indexed_at=indexed_at)


def status(paper, **other):
    """Run determine_file_status against an index entry stamped with `other`."""
    stamp = {
        "file_last_indexed": paper.indexed_at,
        "metadata_last_updated": paper.indexed_at,
        "embedding_model": MODEL,
        "chunk_source": "refinery",
        "chunk_chars": None,
        "chunk_overlap": None,
    }
    stamp.update(other)
    doc = SimpleNamespace(other=stamp)
    docs_index = SimpleNamespace(docs={"KEY": doc})
    return determine_file_status(
        paper.pdf, paper.info, {str(paper.pdf): "KEY"}, docs_index
    )


class TestNothingChanged:
    def test_a_current_paper_is_left_alone(self, paper):
        assert status(paper) == (False, False)


class TestFilesChanged:
    def test_a_modified_pdf_is_reindexed(self, paper):
        assert status(paper, file_last_indexed=0) == (True, False)

    def test_regenerated_chunks_are_reindexed(self, paper):
        """Refinery can rewrite chunks.json (e.g. re-running after an OCR cache
        repair) without touching the PDF's mtime at all."""
        newer = paper.indexed_at + 100
        os.utime(chunks_json_path(paper.pdf), (newer, newer))
        assert status(paper) == (True, False)

    def test_edited_info_yaml_updates_metadata_without_reembedding(self, paper):
        assert status(paper, metadata_last_updated=0) == (False, True)

    def test_reindexing_subsumes_the_metadata_update(self, paper):
        """No point refreshing metadata separately when the whole doc is about
        to be rebuilt anyway."""
        assert status(paper, file_last_indexed=0, metadata_last_updated=0) == (
            True,
            False,
        )


class TestEmbeddingModelChanged:
    """Vectors are only comparable to vectors from the same model."""

    def test_a_different_model_forces_a_reembed(self, paper):
        assert status(paper, embedding_model="ollama/nomic-embed-text")[0] is True

    def test_an_unstamped_paper_is_not_reembedded_on_a_guess(self, paper):
        """Indexed before papis-ask recorded the model. We cannot tell what
        produced these vectors -- and assuming the worst would silently bill the
        user for re-embedding their whole library."""
        assert status(paper, embedding_model=None) == (False, False)


class TestChunkingChanged:
    """chunk-chars/overlap change how a document is *split*, but only on the
    paper-qa parsing path."""

    def test_pypdf_document_is_rechunked(self, paper):
        assert (
            status(paper, chunk_source="pypdf", chunk_chars=3000, chunk_overlap=250)[0]
            is True
        )

    def test_refinery_document_is_not_rechunked(self, paper):
        """Refinery-chunked papers take their boundaries from chunks.json and
        ignore these settings entirely, so re-embedding them on a chunk-chars
        change would be pure wasted spend."""
        assert status(paper, chunk_source="refinery") == (False, False)

    def test_matching_chunk_params_are_left_alone(self, paper):
        assert status(
            paper, chunk_source="pypdf", chunk_chars=5000, chunk_overlap=250
        ) == (False, False)

    def test_an_unstamped_pypdf_paper_is_not_rechunked_on_a_guess(self, paper):
        assert status(
            paper, chunk_source="pypdf", chunk_chars=None, chunk_overlap=None
        ) == (False, False)


class TestNotInTheIndex:
    def test_an_unknown_file_needs_indexing(self, paper):
        docs_index = SimpleNamespace(docs={})
        assert determine_file_status(paper.pdf, paper.info, {}, docs_index) == (
            True,
            False,
        )

    def test_a_dangling_dockey_needs_indexing(self, paper):
        """Mapped to a dockey the index doesn't actually hold."""
        docs_index = SimpleNamespace(docs={})
        assert determine_file_status(
            paper.pdf, paper.info, {str(paper.pdf): "GONE"}, docs_index
        ) == (True, False)
