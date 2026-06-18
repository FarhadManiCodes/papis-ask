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


def create_paper_qa_settings():
    from paperqa import Settings

    settings = Settings()

    settings.llm = _get_optional_string("llm")
    settings.summary_llm = _get_optional_string("summary-llm")
    settings.embedding = _get_optional_string("embedding")
    settings.answer.answer_max_sources = papis.config.getint(
        "max-sources", SECTION_NAME
    )
    settings.answer.evidence_k = papis.config.getint("evidence-k", SECTION_NAME)
    settings.answer.answer_length = papis.config.getstring(
        "answer-length", SECTION_NAME
    )
    settings.parsing.use_doc_details = False
    return settings
