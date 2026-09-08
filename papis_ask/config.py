import papis.config
from papis.config import PapisConfigType
from papis.exceptions import DefaultSettingValueMissing

SECTION_NAME = "ask"

DEFAULTS: PapisConfigType = {
    SECTION_NAME: {
        "evidence-k": 10,
        "max-sources": 5,
        "answer-length": "about 200 words, but can be longer",
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


def _get_optional_bool(key: str) -> bool | None:
    """Get a boolean config value, returning None if not set."""
    try:
        return papis.config.getboolean(key, SECTION_NAME)
    except DefaultSettingValueMissing:
        return None


def create_paper_qa_settings():
    from paperqa import Settings

    settings = Settings()

    if (llm := _get_optional_string("llm")) is not None:
        settings.llm = llm
    if (summary_llm := _get_optional_string("summary-llm")) is not None:
        settings.summary_llm = summary_llm
    if (enrichment_llm := _get_optional_string("enrichment-llm")) is not None:
        settings.parsing.enrichment_llm = enrichment_llm
    if (embedding := _get_optional_string("embedding")) is not None:
        settings.embedding = embedding
    if (max_sources := papis.config.getint("max-sources", SECTION_NAME)) is not None:
        settings.answer.answer_max_sources = max_sources
    if (evidence_k := papis.config.getint("evidence-k", SECTION_NAME)) is not None:
        settings.answer.evidence_k = evidence_k
    settings.answer.answer_length = papis.config.getstring(
        "answer-length", SECTION_NAME
    )
    settings.parsing.use_doc_details = False
    if (multimodal := _get_optional_bool("multimodal")) is not None:
        settings.parsing.multimodal = multimodal
    return settings
