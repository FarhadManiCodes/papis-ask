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


def test_a_note_and_its_paper_with_the_same_ref_stay_apart():
    # the label is one token ("Kalman_1960-note"): transform_answer keys by first word
    note_doc = SimpleNamespace(
        other={"ref": "Kalman_1960", "chunk_source": "note"}, citation="t"
    )
    paper_doc = SimpleNamespace(
        other={"ref": "Kalman_1960", "chunk_source": "refinery"}, citation="t"
    )
    note = SimpleNamespace(
        context="n", text=SimpleNamespace(name="Kalman_1960-note", doc=note_doc)
    )
    paper = SimpleNamespace(
        context="p", text=SimpleNamespace(name="Kalman_1960 pages 5", doc=paper_doc)
    )
    for contexts in ([note, paper], [paper, note]):
        answer = SimpleNamespace(
            answer="Stable (Kalman_1960 pages 5). Diverges (Kalman_1960-note).",
            contexts=contexts,
        )
        out = transform_answer(answer).answer
        assert "[@Kalman_1960, p. 5]" in out and "[@Kalman_1960 (note)]" in out
