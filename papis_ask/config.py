import papis.config
from papis.config import PapisConfigType

SECTION_NAME = "ask"

DEFAULTS: PapisConfigType = {
    SECTION_NAME: {
        "evidence-k": 10,
        "max-sources": 5,
        "answer-length": "about 200 words, but can be longer",
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
    return settings
