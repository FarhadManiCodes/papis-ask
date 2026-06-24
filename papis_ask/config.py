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
        "chunk-size": 5000,
        "overlap": 250,
        # Vision LLM for multimodal enrichment (describing figures/equations/
        # tables during indexing). Must be a multimodal model; use a provider
        # prefix that is NOT openai/ when OPENAI_API_BASE points at a local
        # embedding server, or the call will be misrouted there.
        "enrichment-llm": "gemini/gemini-2.5-flash",
        "context": True,
        "excerpt": False,
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
    # Multimodal enrichment is ON by default in paper-qa (CalVer); override the
    # enrichment LLM so it doesn't fall back to the gpt-4o default.
    settings.parsing.enrichment_llm = papis.config.getstring(
        "enrichment-llm", SECTION_NAME
    )
    settings.parsing.reader_config = {
        **(settings.parsing.reader_config or {}),
        "chunk_chars": papis.config.getint("chunk-size", SECTION_NAME)
        or DEFAULTS[SECTION_NAME]["chunk-size"],
        "overlap": papis.config.getint("overlap", SECTION_NAME)
        or DEFAULTS[SECTION_NAME]["overlap"],
    }
    return settings
