"""Exercise personal selection against upstream's Docs and persistence."""

import pickle
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest
from paperqa import Docs, Settings
from paperqa.types import DocDetails, Text

from papis_ask import main


def document(key, path):
    doc = DocDetails(
        docname=key, dockey=key, citation=key, file_location=str(path),
        other={"ref": key, "file_last_indexed": 100, "metadata_last_updated": 100},
    )
    # As in update_index_metadata, apply identity after DocDetails validation.
    doc.docname = key
    return doc


@pytest.fixture
def library(tmp_path, monkeypatch):
    class Paper(dict):
        def get_files(self):
            return [str(tmp_path / (self["papis_id"] + ".txt"))]

        def get_notes(self):
            return []

        def get_info_file(self):
            return str(tmp_path / "info.yaml")

    papers = [Paper(papis_id=k, ref=k) for k in "ABC"]
    docs = {}
    for paper in papers:
        path = tmp_path / (paper["papis_id"] + ".txt")
        path.write_text("Content for " + paper["papis_id"])
        docs[paper["papis_id"]] = document(paper["papis_id"], path)
    index = Docs(docs=docs, docnames=set(docs))
    saved = []
    monkeypatch.setattr(main, "get_index", lambda: index)
    monkeypatch.setattr(main, "save_index", lambda value: saved.append(pickle.loads(pickle.dumps(value))))
    monkeypatch.setattr(main, "get_all_documents_in_lib", lambda: papers)
    monkeypatch.setattr(main.papis.cli, "handle_doc_folder_or_query", lambda *a: papers[:1])
    monkeypatch.setattr(main, "determine_file_status", lambda *a: (False, False))
    monkeypatch.setattr(main, "create_paper_qa_settings", lambda: Settings())

    async def add(file_path, doc_papis, docs_index, **kwargs):
        key = doc_papis["papis_id"]
        docs_index.docs[key] = document(key, file_path)
        docs_index.docnames.add(key)
        return key

    add_mock = AsyncMock(side_effect=add)
    monkeypatch.setattr(main, "add_file_to_index", add_mock)
    return SimpleNamespace(papers=papers, index=index, saved=saved, add=add_mock)


@pytest.mark.asyncio
@pytest.mark.parametrize("force", [False, True])
async def test_scoped_index_keeps_unmatched_papers(library, force):
    await main._index_async("A", force)
    assert set(library.saved[-1].docs) == set("ABC")
    assert library.add.await_count == int(force)


@pytest.mark.asyncio
async def test_full_force_rebuilds_all_papers(library):
    await main._index_async(None, True)
    assert set(library.saved[-1].docs) == set("ABC")
    assert library.add.await_count == 3


@pytest.mark.asyncio
async def test_scoped_index_removes_actually_missing_library_entries(library):
    library.papers.pop()
    await main._index_async("A", False)
    assert set(library.saved[-1].docs) == set("AB")


@pytest.mark.asyncio
async def test_exit_saves_progress_on_interruption(library):
    library.add.side_effect = KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        await main._index_async("A", True)
    assert len(library.saved) == 1
    assert set(library.saved[-1].docs) == set("BC")


def test_checkpoint_cadence(library):
    for count in range(1, 51):
        main.checkpoint_index(library.index, count)
    assert len(library.saved) == 2


def test_shared_docname_is_removed_only_after_last_document(tmp_path):
    a, b = document("A", tmp_path / "a"), document("B", tmp_path / "b")
    b.docname = a.docname
    index = Docs(docs={"A": a, "B": b}, docnames={"A"})
    main.remove_document_from_index(index, "A")
    assert index.docnames == {"A"}
    main.remove_document_from_index(index, "B")
    assert not index.docnames


def test_pickle_round_trip_uses_float32_and_retains_metadata(tmp_path, monkeypatch):
    target = tmp_path / "index.qa"
    monkeypatch.setattr(main, "get_index_file", lambda: target)
    doc = document("A", tmp_path / "a")
    doc.other.update(embedding_model="model-a", chunk_source="refinery")
    chunk = Text(text="Evidence", name="A pages 6", doc=doc, embedding=[0.1, 0.2])
    main.save_index(Docs(docs={"A": doc}, docnames={"A"}, texts=[chunk]))
    loaded = main.get_index()
    assert loaded.texts[0].embedding.dtype == np.float32
    np.testing.assert_allclose(loaded.texts[0].embedding, [0.1, 0.2])
    assert loaded.docs["A"].other["embedding_model"] == "model-a"
    assert loaded.docs["A"].other["chunk_source"] == "refinery"


def test_failed_atomic_replace_preserves_previous_pickle(tmp_path, monkeypatch):
    target = tmp_path / "index.qa"
    monkeypatch.setattr(main, "get_index_file", lambda: target)
    main.save_index(Docs())
    previous = target.read_bytes()

    def fail(*args):
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(main.os, "replace", fail)
    with pytest.raises(OSError):
        main.save_index(Docs())
    assert target.read_bytes() == previous
    assert not target.with_name("index.qa.tmp").exists()
