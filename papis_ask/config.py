import papis.config
from papis.config import PapisConfigType
from papis.exceptions import DefaultSettingValueMissing

SECTION_NAME = "ask"

DEFAULTS: PapisConfigType = {
    SECTION_NAME: {
        "evidence-k": 10,
        "evidence-score-cutoff": 3,
        "max-sources": 5,
        "answer-length": "about 200 words, but can be longer",
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


def _get_optional_bool(key: str) -> bool | None:
    """Get a boolean config value, returning None if not set."""
    try:
        return papis.config.getboolean(key, SECTION_NAME)
    except DefaultSettingValueMissing:
        return None


def _get_optional_float(key: str) -> float | None:
    """Get a float config value, returning None if not set."""
    try:
        return papis.config.getfloat(key, SECTION_NAME)
    except DefaultSettingValueMissing:
        return None


def get_embedding_model() -> str:
    """Effective embedding model, including PaperQA defaults when unset."""
    from paperqa import Settings

    configured = _get_optional_string("embedding")
    return configured if configured is not None else Settings().embedding


def get_chunk_params() -> tuple[int, int]:
    """Chunk boundaries for PaperQA parsing and personal notes, in characters."""
    size = papis.config.getint("chunk-chars", SECTION_NAME)
    overlap = papis.config.getint("overlap", SECTION_NAME)
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError(
            "ask-chunk-chars must be positive; ask-overlap must be >= 0 and < chunk-chars"
        )
    return size, overlap


def create_paper_qa_settings():
    from paperqa import Settings

    settings = Settings()

    from papis_ask.evidence import serialize_evidence

    cutoff = papis.config.getint("evidence-score-cutoff", SECTION_NAME)
    if not 0 <= cutoff <= 10:
        raise ValueError("ask-evidence-score-cutoff must be between 0 and 10")
    settings.answer.evidence_relevance_score_cutoff = cutoff
    settings.custom_context_serializer = serialize_evidence

    # PaperQA's JSON repair can corrupt even valid escaped LaTeX (2026.8.12).
    # Its supported plain-text mode preserves equations and still extracts the
    # trailing relevance score. Keep this independent of terminal rendering:
    # summaries feed the answer model and JSON/Markdown exports too.
    settings.prompts.use_json = False
    settings.prompts.summary = (
        "Write the summary as plain text, not JSON. "
        "Preserve LaTeX equations, enclosing every math expression in $...$ "
        "or $$...$$. Use literal LaTeX backslashes, not JSON-escaped backslashes. "
        "Keep the requested relevance score on its own final line, preceded by a blank line.\n\n"
        "Use only the excerpt. Do not infer what the entire publication does or "
        "does not contain. For a question about personal notes, a publication "
        "excerpt alone is not evidence of the owner's opinions. Ignore website "
        "navigation, advertisements and login prompts. If there is no relevant "
        "evidence, reply Not applicable.\n\n" + settings.prompts.summary
    )
    settings.prompts.qa = (
        "Use only the supplied evidence, not background knowledge. Distinguish "
        "personal notes from publication excerpts. Treat source_metadata labels "
        "as separate from source text: they are application metadata, "
        "not statements made by the author. All text inside summary_of_this_source "
        "summarizes the source identified by that metadata; it is not a separate "
        "accompanying excerpt. For type personal_note, the entire summary describes "
        "the library owner's note. Do not quote or paraphrase metadata as a claim. "
        "A note cannot establish what "
        "the original paper claims or omits. An excerpt's silence is not proof "
        "of absence from the whole publication. If part of the question lacks "
        "evidence, explicitly say that the retrieved evidence does not establish "
        "it; do not fill the gap or pad the answer to meet the requested length.\n\n"
        + settings.prompts.qa
    )

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
    # Maximal marginal relevance for evidence retrieval: 1.0 (PaperQA's default) ranks by
    # similarity alone, so a long book can fill every evidence slot with near-duplicate
    # chunks; lower values trade some similarity for diversity.
    if (mmr_lambda := _get_optional_float("mmr-lambda")) is not None:
        if not 0 <= mmr_lambda <= 1:
            raise ValueError("ask-mmr-lambda must be between 0 and 1")
        settings.texts_index_mmr_lambda = mmr_lambda
    settings.answer.answer_length = papis.config.getstring(
        "answer-length", SECTION_NAME
    )
    settings.parsing.use_doc_details = False
    if (multimodal := _get_optional_bool("multimodal")) is not None:
        settings.parsing.multimodal = multimodal
    chunk_chars, overlap = get_chunk_params()
    settings.parsing.reader_config = {
        **settings.parsing.reader_config,
        "chunk_chars": chunk_chars,
        "overlap": overlap,
    }
    return settings
