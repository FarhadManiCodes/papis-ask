"""Scoped asking: `papis ask query --scope QUERY` answers from a library subset."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import click
import pytest
from click.testing import CliRunner
from paperqa import Docs, Settings
from paperqa.types import DocDetails, Text

from papis_ask import main


def document(key, path):
    doc = DocDetails(
        docname=key,
        dockey=key,
        citation=key,
        file_location=str(path),
        other={"ref": key},
    )
    doc.dockey = key
    return doc


class Paper(dict):
    def __init__(self, papis_id, files, notes=()):
        super().__init__(papis_id=papis_id, ref=papis_id)
        self._files, self._notes = files, notes

    def get_files(self):
        return [str(f) for f in self._files]

    def get_notes(self):
        return [str(n) for n in self._notes]


@pytest.fixture
def indexed(tmp_path):
    """Three papers; A also has a note indexed as its own document."""
    paths = {k: tmp_path / f"{k}.pdf" for k in "ABC"}
    note = tmp_path / "A-notes.md"
    note.write_text("my note")
    docs = {k: document(k, p) for k, p in paths.items()}
    docs["A-note"] = document("A-note", note)
    texts = [
        Text(text=f"chunk {key}", name=f"{key} p1", doc=doc, embedding=[1.0, float(i)])
        for i, (key, doc) in enumerate(docs.items())
    ]
    index = Docs(docs=docs, docnames=set(docs), texts=texts)
    papers = {
        "A": Paper("A", [paths["A"]], [note]),
        "B": Paper("B", [paths["B"]]),
        "C": Paper("C", [paths["C"]]),
    }
    return index, papers, paths, note


def test_scope_index_keeps_only_matching_docs_and_texts(indexed):
    index, _, paths, note = indexed
    scoped = main.scope_index(index, {paths["A"], note, paths["C"]})

    assert set(scoped.docs) == {"A", "A-note", "C"}
    assert {t.doc.dockey for t in scoped.texts} == {"A", "A-note", "C"}
    # Same Doc objects, so docnames (and citations) are exactly the index's own.
    assert all(scoped.docs[k] is index.docs[k] for k in scoped.docs)
    assert scoped.docnames == {index.docs[k].docname for k in ("A", "A-note", "C")}
    # The full index is untouched.
    assert len(index.docs) == 4 and len(index.texts) == 4


@pytest.mark.asyncio
async def test_scoped_vector_store_reuses_stored_embeddings(indexed):
    index, _, paths, _ = indexed
    scoped = main.scope_index(index, {paths["B"]})
    model = AsyncMock()

    await scoped._build_texts_index(embedding_model=model)

    model.embed_documents.assert_not_called()
    assert len(scoped.texts_index) == 1


def test_resolve_scope_files_unions_queries_and_includes_notes(indexed, monkeypatch):
    _, papers, paths, note = indexed
    results = {"tags:x": [papers["A"], papers["B"]], "tags:y": [papers["B"]]}
    monkeypatch.setattr(
        "papis.api.get_documents_in_lib", lambda search: results.get(search, [])
    )

    files, n_matched = main.resolve_scope_files(("tags:x", "tags:y"))

    assert n_matched == 2
    assert files == {paths["A"], note, paths["B"]}


@pytest.fixture
def query_env(indexed, monkeypatch):
    index, papers, _, _ = indexed
    monkeypatch.setattr(main, "get_index", lambda: index)
    monkeypatch.setattr(main, "create_paper_qa_settings", lambda: Settings())
    monkeypatch.setattr(main, "to_terminal_output", lambda *a: None)
    seen = []

    async def aquery(self, query, settings):
        seen.append(set(self.docs))
        return object()

    monkeypatch.setattr(Docs, "aquery", aquery)

    def use_library(results):
        monkeypatch.setattr(
            "papis.api.get_documents_in_lib",
            lambda search: [papers[k] for k in results.get(search, "")],
        )

    return seen, use_library


async def ask(scopes):
    await main._query_async("Q", "terminal", 10, 5, "short", False, False, False, scopes)


@pytest.mark.asyncio
async def test_query_without_scope_uses_whole_index(query_env):
    seen, _ = query_env
    await ask(())
    assert seen == [{"A", "A-note", "B", "C"}]


@pytest.mark.asyncio
async def test_query_with_scope_answers_from_subset(query_env):
    seen, use_library = query_env
    use_library({"tags:x": "A", "tags:y": "C"})
    await ask(("tags:x", "tags:y"))
    assert seen == [{"A", "A-note", "C"}]


@pytest.mark.asyncio
async def test_scope_matching_no_documents_is_a_usage_error(query_env):
    seen, use_library = query_env
    use_library({})
    with pytest.raises(click.UsageError, match="No documents"):
        await ask(("tags:none",))
    assert seen == []


@pytest.mark.asyncio
async def test_scope_matching_only_unindexed_documents_fails(query_env, tmp_path):
    seen, _ = query_env
    unindexed = Paper("D", [tmp_path / "D.pdf"])
    with patch("papis.api.get_documents_in_lib", lambda search: [unindexed]):
        with pytest.raises(click.ClickException, match="none of them is indexed"):
            await ask(("ref:D",))
    assert seen == []


def test_cli_passes_repeated_scopes():
    with patch("papis_ask.main._query_async", new_callable=AsyncMock) as query:
        result = CliRunner().invoke(
            main.cli, ["query", "Q", "-s", "tags:a", "--scope", "tags:b"]
        )
    assert result.exit_code == 0, result.output
    assert query.call_args.args[-1] == ("tags:a", "tags:b")


def test_scope_paths_compare_as_strings(indexed):
    """Index file_location is stored as str; library files arrive as Path."""
    index, _, paths, _ = indexed
    scoped = main.scope_index(index, {Path(str(paths["B"]))})
    assert set(scoped.docs) == {"B"}
