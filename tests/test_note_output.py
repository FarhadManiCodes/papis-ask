from types import SimpleNamespace

from papis_ask.output import source_ref, transform_answer


def test_note_source_marker_survives_metadata_citation_replacement():
    doc = SimpleNamespace(
        other={"ref": "Paper", "chunk_source": "note"}, citation="Paper title"
    )
    context = SimpleNamespace(
        context="Summary", text=SimpleNamespace(name="id-note chunk 1", doc=doc)
    )
    answer = SimpleNamespace(answer="Observation (id-note).", contexts=[context])
    assert source_ref(doc) == "Paper (note)"
    assert transform_answer(answer).answer == "Observation [@Paper (note)]."
