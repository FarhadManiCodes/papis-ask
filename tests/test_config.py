"""Personal chunk settings layer on top of upstream's model configuration."""

import pytest

from papis_ask import config


@pytest.fixture
def options(monkeypatch):
    values = {"chunk-chars": 5000, "overlap": 250, "max-sources": 5, "evidence-k": 10}
    monkeypatch.setattr(config.papis.config, "getint", lambda key, section: values[key])
    monkeypatch.setattr(
        config.papis.config, "getstring", lambda *args: "about 200 words"
    )
    monkeypatch.setattr(config, "_get_optional_string", lambda key: None)
    monkeypatch.setattr(config, "_get_optional_bool", lambda key: None)
    return values


def test_chunk_defaults(options):
    assert config.get_chunk_params() == (5000, 250)


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
