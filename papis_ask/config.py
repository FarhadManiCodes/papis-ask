import papis.config
from papis.config import PapisConfigType

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


def create_paper_qa_settings():
    from paperqa import Settings

    settings = Settings()

    settings.llm = papis.config.getstring("llm", SECTION_NAME)
    settings.summary_llm = papis.config.getstring("summary-llm", SECTION_NAME)
    settings.embedding = papis.config.getstring("embedding", SECTION_NAME)
    # OpenAI-compatible local embedding servers (e.g. llama.cpp) return HTTP 500
    # on the `encoding_format: null` that LiteLLM sends by default. Force a valid
    # value for openai/ embeddings (harmless elsewhere, so scoped to that prefix).
    if settings.embedding.startswith("openai/"):
        settings.embedding_config = {"kwargs": {"encoding_format": "float"}}
    settings.answer.answer_max_sources = (
        papis.config.getint("max-sources", SECTION_NAME)
        or DEFAULTS[SECTION_NAME]["max-sources"]  # TODO: redundancy
    )
    settings.answer.evidence_k = (
        papis.config.getint("evidence-k", SECTION_NAME)
        or DEFAULTS[SECTION_NAME]["evidence-k"]  # TODO: redundancy
    )
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
