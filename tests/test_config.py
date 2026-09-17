"""Personal chunk settings layer on top of upstream's model configuration."""

import pytest

from papis_ask import config


@pytest.fixture
def options(monkeypatch):
    values = {
        "chunk-chars": 5000,
        "overlap": 250,
        "max-sources": 5,
        "evidence-k": 10,
        "evidence-score-cutoff": 3,
    }
    monkeypatch.setattr(config.papis.config, "getint", lambda key, section: values[key])
    monkeypatch.setattr(
        config.papis.config, "getstring", lambda *args: "about 200 words"
    )
    monkeypatch.setattr(config, "_get_optional_string", lambda key: None)
    monkeypatch.setattr(config, "_get_optional_bool", lambda key: None)
    return values


def test_chunk_defaults(options):
    assert config.get_chunk_params() == (5000, 250)


@pytest.mark.parametrize("cutoff", [0, 3, 10])
def test_evidence_cutoff_is_configurable(options, cutoff):
    options["evidence-score-cutoff"] = cutoff
    assert (
        config.create_paper_qa_settings().answer.evidence_relevance_score_cutoff
        == cutoff
    )


@pytest.mark.parametrize("cutoff", [-1, 11])
def test_rejects_invalid_evidence_cutoff(options, cutoff):
    options["evidence-score-cutoff"] = cutoff
    with pytest.raises(ValueError, match="evidence-score-cutoff"):
        config.create_paper_qa_settings()


def test_summary_prompt_preserves_math_without_changing_models(options):
    from paperqa import Settings

    settings = config.create_paper_qa_settings()
    defaults = Settings()
    assert settings.prompts.use_json is False
    assert settings.prompts.summary.endswith(defaults.prompts.summary)
    assert "$...$" in settings.prompts.summary
    assert "not JSON-escaped" in settings.prompts.summary
    assert settings.summary_llm == defaults.summary_llm
    assert settings.prompts.qa.endswith(defaults.prompts.qa)
    # Formatting must not interpret equation braces as new prompt variables.
    settings.prompts.summary.format(
        citation="Example",
        text="Excerpt",
        question="Question",
        summary_length="100 words",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "summary,score",
    [
        (r"Green's theorem: $\oint_C a_1 ds = \iint_A a_{2,1} dA$." + "\n9", 9),
        (
            r"The divergence is $\nabla \cdot \mathbf{a}$; "
            r"use $\frac{\partial g}{\partial x}$." + "\n8",
            8,
        ),
        ("No equations are needed for this evidence.\n7", 7),
        ("Not applicable", 0),
    ],
)
async def test_real_evidence_path_preserves_summary_and_scores(
    options, monkeypatch, summary, score
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from lmi import LLMResult
    from paperqa import Docs
    from paperqa.types import Doc, Text
    import paperqa.docs

    settings = config.create_paper_qa_settings()
    settings.answer.evidence_retrieval = False
    doc = Doc(docname="example", citation="Example", dockey="example")
    text = Text(text="Evidence", name="example pages 1", doc=doc)
    docs = Docs(docs={doc.dockey: doc}, texts=[text])
    model = SimpleNamespace(
        call_single=AsyncMock(
            return_value=LLMResult(model="test", date="", text=summary)
        )
    )

    def reject_json(*args, **kwargs):
        pytest.fail("The summary must not pass through PaperQA's JSON repair")

    monkeypatch.setattr(paperqa.docs, "llm_parse_json", reject_json)
    session = await docs.aget_evidence(
        "Question", settings=settings, summary_llm_model=model, embedding_model=object()
    )
    model.call_single.assert_awaited_once()
    if score:
        assert len(session.contexts) == 1
        assert session.contexts[0].context == summary
        assert session.contexts[0].score == score
    else:
        assert session.contexts == []


def test_chunk_override_keeps_upstream_model_controls(options, monkeypatch):
    options.update({"chunk-chars": 2000, "overlap": 100})
    monkeypatch.setattr(config, "_get_optional_bool", lambda key: False)
    monkeypatch.setattr(
        config,
        "_get_optional_string",
        lambda key: "custom-vision" if key == "enrichment-llm" else None,
    )
    settings = config.create_paper_qa_settings()
    assert settings.parsing.reader_config["chunk_chars"] == 2000
    assert settings.parsing.reader_config["overlap"] == 100
    assert settings.parsing.multimodal is False
    assert settings.parsing.enrichment_llm == "custom-vision"


@pytest.mark.parametrize(
    "size,overlap", [(0, 0), (-1, 0), (100, -1), (100, 100), (100, 101)]
)
def test_rejects_nonprogressing_chunk_windows(options, size, overlap):
    options.update({"chunk-chars": size, "overlap": overlap})
    with pytest.raises(ValueError, match="ask-chunk-chars"):
        config.get_chunk_params()
