"""Query-time provenance; never changes stored chunks or their embeddings."""

from papis_ask.output import summary_text


async def serialize_evidence(settings, contexts, question, pre_str):
    annotated = []
    for context in contexts:
        is_note = getattr(context.text.doc, "other", {}).get("chunk_source") == "note"
        source_type = "personal_note" if is_note else "publication_excerpt"
        annotated.append(
            context.model_copy(
                update={
                    "context": (
                        f'<source_metadata type="{source_type}" />\n'
                        "<summary_of_this_source>\n"
                        + summary_text(context)
                        + "\n</summary_of_this_source>"
                    ),
                }
            )
        )
    # Delegate ordering, score filtering, citation keys and source limits to
    # PaperQA, avoiding a fork of its context serializer.
    defaults = settings.model_copy(update={"custom_context_serializer": None})
    return await defaults.context_serializer(annotated, question, pre_str)
