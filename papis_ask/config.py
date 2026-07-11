import papis.config
from papis.config import PapisConfigType
from papis.exceptions import DefaultSettingValueMissing

SECTION_NAME = "ask"

DEFAULTS: PapisConfigType = {
    SECTION_NAME: {
        "evidence-k": 10,
        "max-sources": 5,
        "answer-length": "about 200 words, but can be longer",
        # Chunking in characters (defaults match paper-qa). Changing either
        # requires a full re-index: `papis ask index -f`.
        "chunk-chars": 5000,
        "overlap": 250,
        "context": True,
        "excerpt": False,
        "render-math": False,
        "output": "terminal",
    }
}


papis.config.register_default_settings(DEFAULTS)


def _get_optional_string(key: str) -> str | None:
    """Get a string config value, returning None if not set."""
    try:
        return papis.config.getstring(key, SECTION_NAME)
    except DefaultSettingValueMissing:
        return None


def get_embedding_model() -> str | None:
    """The embedding model the index is currently configured to use.

    Stamped into each paper's index entry when it's embedded, so a later run
    can tell whether the vectors on disk were produced by the model we'd query
    with today -- see `determine_file_status`.
    """
    return _get_optional_string("embedding")


def create_paper_qa_settings():
    from paperqa import Settings

    settings = Settings()

    settings.llm = _get_optional_string("llm")
    settings.summary_llm = _get_optional_string("summary-llm")
    settings.embedding = _get_optional_string("embedding")
    # OpenAI-compatible local embedding servers (e.g. llama.cpp) return HTTP 500
    # on the `encoding_format: null` that LiteLLM sends by default. Force a valid
    # value for openai/ embeddings (harmless elsewhere, so scoped to that prefix).
    if settings.embedding and settings.embedding.startswith("openai/"):
        settings.embedding_config = {"kwargs": {"encoding_format": "float"}}
    settings.answer.answer_max_sources = papis.config.getint(
        "max-sources", SECTION_NAME
    )
    settings.answer.evidence_k = papis.config.getint("evidence-k", SECTION_NAME)
    settings.answer.answer_length = papis.config.getstring(
        "answer-length", SECTION_NAME
    )
    settings.parsing.use_doc_details = False
    # paper-refinery already does figure/table enrichment on its own path;
    # paper-qa's own multimodal enrichment (ON by default, gpt-4o) would
    # otherwise run during the pypdf fallback path and misroute into whatever
    # OPENAI_API_BASE points at (e.g. a local embedding-only server).
    settings.parsing.multimodal = False
    settings.parsing.reader_config = {
        **settings.parsing.reader_config,
        "chunk_chars": papis.config.getint("chunk-chars", SECTION_NAME),
        "overlap": papis.config.getint("overlap", SECTION_NAME),
    }
    return settings
