"""CLI indexing and retrieval through real PaperQA, with offline model doubles."""

import asyncio
import json
from unittest.mock import AsyncMock

import numpy as np
from click.testing import CliRunner
from paperqa import Settings

from papis_ask import config, main
from papis_ask.metadata_provider import parse_papis_to_doc_details


def test_refinery_notes_reindex_and_retrieval(tmp_path, tmp_config, monkeypatch):
    class Embeddings:
        calls = 0

        def set_mode(self, mode):
            pass

        async def embed_documents(self, texts):
            self.calls += 1
            return [[float(len(text)), 1.0, 2.0] for text in texts]

    class Paper(dict):
        def get_files(self):
            return [str(pdf)]

        def get_notes(self):
            return [str(note)]

        def get_info_file(self):
            return str(info)

    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"Synthetic PDF: refinery supplies the text")
    manifest = pdf.with_suffix(".chunks.json")
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "chunks": [
                    {
                        "index": 0,
                        "text": "The refined evidence.",
                        "page_start": 6,
                        "page_end": 6,
                    }
                ],
            }
        )
    )
    note = tmp_path / "notes.md"
    note.write_text(
        "<!--quote-->Duplicate passage<!--/quote-->\nMy interpretation of the evidence.\n"
    )
    info = tmp_path / "info.yaml"
    info.write_text("papis_id: A\nref: Paper\n")
    paper = Paper(
        papis_id="A",
        ref="Paper",
        title="A paper",
        notes="notes.md",
        author_list=[{"given": None, "family": "Author"}],
    )
    embeddings = Embeddings()
    settings = Settings()
    settings.parsing.multimodal = False
    settings.parsing.use_doc_details = False
    monkeypatch.setattr(Settings, "get_embedding_model", lambda self: embeddings)
    monkeypatch.setattr(main, "create_paper_qa_settings", lambda: settings)
    monkeypatch.setattr(config, "get_embedding_model", lambda: settings.embedding)
    monkeypatch.setattr(config, "get_chunk_params", lambda: (5000, 250))
    monkeypatch.setattr(main, "get_index_file", lambda: tmp_path / "papers.qa")
    monkeypatch.setattr(main, "get_all_documents_in_lib", lambda: [paper])
    monkeypatch.setattr(
        main.papis.cli, "handle_doc_folder_or_query", lambda *args: [paper]
    )

    async def metadata_query(**kwargs):
        return await parse_papis_to_doc_details(
            paper,
            **{k: v for k, v in kwargs.items() if k not in ("settings", "papis_id")},
        )

    import paperqa.clients

    clients = iter(
        [
            type("Local", (), {"query": staticmethod(metadata_query)})(),
            type(
                "Remote", (), {"query": AsyncMock(side_effect=RuntimeError("offline"))}
            )(),
        ]
    )
    monkeypatch.setattr(
        paperqa.clients, "DocMetadataClient", lambda **kwargs: next(clients)
    )
    runner = CliRunner()
    result = runner.invoke(main.cli, ["index"])
    if result.exception:
        raise result.exception
    assert result.exit_code == 0, result.output + repr(result.exception)
    docs = main.get_index()
    assert len(docs.docs) == 2
    assert {d.other["chunk_source"] for d in docs.docs.values()} == {"refinery", "note"}
    assert all(d.authors == ["Author"] for d in docs.docs.values())
    assert all(t.embedding.dtype == np.float32 for t in docs.texts)
    assert any(t.name.endswith("pages 6") for t in docs.texts)
    assert "Duplicate passage" not in " ".join(t.text for t in docs.texts)
    assert any("My interpretation" in t.text for t in docs.texts)
    assert not list(tmp_path.glob("*.embeddings.json"))

    calls = embeddings.calls
    clients = iter([object(), object()])
    result = runner.invoke(main.cli, ["index"])
    assert result.exit_code == 0, result.output + repr(result.exception)
    assert embeddings.calls == calls

    matches = asyncio.run(
        docs.retrieve_texts(
            "evidence", k=2, settings=settings, embedding_model=embeddings
        )
    )
    assert {t.doc.other["chunk_source"] for t in matches} == {"refinery", "note"}
