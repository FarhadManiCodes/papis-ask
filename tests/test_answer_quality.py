from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from papis_ask.output import (
    transform_answer,
    summary_text,
    unique_references,
    cited_references,
    to_markdown_output,
)
from papis_ask.main import cli


def answer(text):
    contexts = []
    for name, ref, source in [
        ("abc pages 1", "PaperA", "refinery"),
        ("def pages 2", "PaperB", "refinery"),
        ("abc-note chunk 1", "PaperA", "note"),
    ]:
        contexts.append(
            NS(
                context="Evidence\n\n7",
                score=7,
                text=NS(
                    name=name,
                    text="Excerpt",
                    doc=NS(
                        other={"ref": ref, "chunk_source": source},
                        file_location=f"/library/{ref}-{source}.pdf",
                    ),
                ),
            )
        )
    return NS(answer=text, contexts=contexts, question="Question")


@pytest.mark.parametrize(
    "source,expected",
    [
        ("(abc pages 1, def pages 2)", "[@PaperA, p. 1; @PaperB, p. 2]"),
        ("(abc pages 1, abc pages 2)", "[@PaperA, p. 1; @PaperA, p. 2]"),
        ("(abc, def)", "[@PaperA; @PaperB]"),
        ("(abc pages 1, 2; def pages 2)", "[@PaperA, p. 1, 2; @PaperB, p. 2]"),
        ("(abc-note chunk 1)", "[@PaperA (note)]"),
        ("(abc-note chunk 1, abc pages 1)", "[@PaperA (note); @PaperA, p. 1]"),
        ("(abc, abc)", "[@PaperA]"),
    ],
)
def test_grouped_and_note_citations(source, expected):
    assert transform_answer(answer(source)).answer == expected


@pytest.mark.parametrize(
    "source",
    [
        "f(x) at (k+1)",
        "()",
        "(abc pages prose)",
        "(abc, unknown)",
        "(abc and some prose)",
        "(abc-note chunk 99)",
        "(abc,)",
    ],
)
def test_never_partially_rewrites_unrecognized_groups(source):
    assert transform_answer(answer(source)).answer == source


def test_only_scoring_trailers_are_hidden():
    context = answer("").contexts[0]
    assert summary_text(context) == "Evidence"
    for text in ["The score is 7", "Final value:\n7", "Evidence\n\n8", "$x =\n7$"]:
        context.context = text
        assert summary_text(context) == text


def test_reference_dedup_does_not_hide_evidence_or_notes():
    value = answer("Answer")
    value.contexts.append(deepcopy(value.contexts[0]))
    assert len(unique_references(value.contexts)) == 3
    output = to_markdown_output(value, context=True)
    assert output.count("- [@PaperA, p. 1]") == 1
    assert output.count("## @PaperA, p. 1") == 2
    assert "- [@PaperA (note)]" in output
    assert "Evidence\n\n7" not in output


def test_reference_list_only_contains_cited_evidence():
    value = answer("Answer")
    for i, context in enumerate(value.contexts):
        context.id = f"pqac-0000000{i}"
    value.raw_answer = "Claim (pqac-00000002)."
    assert cited_references(value) == [value.contexts[2]]
    assert len(value.contexts) == 3
    value.raw_answer = "I cannot answer."
    assert cited_references(value) == []


@pytest.mark.parametrize(
    "args",
    [
        ["--evidence-k", "2", "--max-sources", "4"],
        ["--evidence-k", "4", "--max-sources", "4"],
        ["--evidence-k", "0"],
        ["--max-sources", "-1"],
        ["--output", "jsno"],
    ],
)
def test_invalid_cli_options_fail_before_api(args):
    with patch("papis_ask.main._query_async", new_callable=AsyncMock) as query:
        result = CliRunner().invoke(cli, ["query", "Question", *args])
    assert result.exit_code == 2, result.output
    query.assert_not_called()


@pytest.mark.asyncio
async def test_provenance_and_cutoff_use_real_serializer_without_mutation():
    from paperqa import Settings
    from paperqa.types import Context, Text
    from paperqa.types import DocDetails
    from papis_ask.evidence import serialize_evidence

    settings = Settings()
    settings.answer.evidence_relevance_score_cutoff = 3
    settings.custom_context_serializer = serialize_evidence
    contexts = []
    for name, kind, score in [
        ("note", "note", 7),
        ("paper", "refinery", 8),
        ("low", "refinery", 1),
    ]:
        doc = DocDetails(
            docname=name, citation=name, dockey=name, other={"chunk_source": kind}
        )
        contexts.append(
            Context(
                text=Text(text="Source", name=name, doc=doc),
                context=f"{name} evidence\n\n{score}",
                score=score,
            )
        )
    before = [c.model_dump() for c in contexts]
    result = await settings.context_serializer(contexts, "Question", None)
    assert '<source_metadata type="personal_note" />' in result
    assert '<source_metadata type="publication_excerpt" />' in result
    assert "<summary_of_this_source>\nnote evidence\n</summary_of_this_source>" in result
    assert "low evidence" not in result
    assert contexts[0].id in result and contexts[1].id in result
    assert contexts[2].id not in result
    assert "note evidence\n\n7" not in result
    assert [c.model_dump() for c in contexts] == before


@pytest.mark.asyncio
async def test_low_relevance_only_does_not_call_answer_model():
    from paperqa import Docs, Settings
    from paperqa.types import Context, Doc, Text, PQASession
    from papis_ask.evidence import serialize_evidence

    settings = Settings()
    settings.custom_context_serializer = serialize_evidence
    settings.answer.evidence_relevance_score_cutoff = 3
    doc = Doc(docname="paper", citation="Paper", dockey="paper")
    context = Context(
        context="Unrelated evidence\n\n1",
        score=1,
        text=Text(text="Source", name="paper", doc=doc),
    )
    session = PQASession(question="Unsupported question", contexts=[context])
    model = NS(call_single=AsyncMock(side_effect=AssertionError("No evidence")))
    result = await Docs(docs={doc.dockey: doc}).aquery(
        session,
        settings=settings,
        llm_model=model,
        summary_llm_model=model,
        embedding_model=object(),
    )
    assert "insufficient information" in result.answer
    model.call_single.assert_not_called()
