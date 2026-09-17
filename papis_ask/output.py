import re
import json
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.table import Table


_CHUNK_PAGES_RE = re.compile(r"\bpages\s+(\d+(?:-\d+)?)\s*$")


def context_pages(context: Any) -> str | None:
    """Where in the document this specific chunk came from, e.g. "3" or "3-5".

    Read off the chunk's own name (refinery stamps a page range into it via
    `chunk_name`), NOT from `doc.pages` -- that's the bibliographic field from
    info.yaml, i.e. where the *article* sits in its journal. Using it here
    printed the same page range on every chunk of a paper, told you nothing
    about where the evidence actually was, and rendered "p. None" for the many
    papers with no `pages:` in info.yaml.

    None when the chunk has no page information at all (some parsers provide only
    chunk numbers, and HTML has no pages to begin with), in which
    case callers omit the page reference rather than inventing one.
    """
    match = _CHUNK_PAGES_RE.search(context.text.name or "")
    return match.group(1) if match else None


def source_ref(doc: Any) -> str:
    """The ref to display for a chunk, marked when it came from your own note.

    The marker cannot live on `Doc.citation`: `update_index_metadata` sets
    `fields_to_overwrite_from_metadata = {"citation"}`, so anything put there is
    replaced by the papis title during the DocDetails upgrade. Rendering is the
    only place the distinction survives -- and it has to survive somewhere,
    because an answer that cites your speculation exactly like the authors'
    claims is worse than one that cannot see your notes at all.
    """
    ref = doc.other.get("ref", doc.other.get("papis_id"))
    if doc.other.get("chunk_source") == "note":
        return f"{ref} (note)"
    return ref


def format_source(context: Any) -> str:
    """Render a chunk's citation: `@ref, p. 3`, or `@ref` when it has no pages."""
    ref = source_ref(context.text.doc)
    pages = context_pages(context)
    return f"@{ref}, p. {pages}" if pages else f"@{ref}"


def to_latex_math(text: str) -> str:
    return (
        text.replace(r"\(", "$")
        .replace(r"\)", "$")
        .replace(r"\[", "$$")
        .replace(r"\]", "$$")
    )


def summary_text(context: Any) -> str:
    """Hide the plain-text scoring trailer, not numbers inside the evidence."""
    text = context.context
    # The plain-text prompt requests a final score. Require a blank separator
    # (or an explicit label), so a final equation/value on one line is safe.
    score = re.escape(str(context.score))
    return re.sub(
        rf"(?:\n[ \t]*\n[ \t]*{score}|\n[ \t]*Score:\s*{score})[ \t\r\n]*$",
        "",
        text,
        flags=re.IGNORECASE,
    )


def unique_references(contexts: Any) -> list[Any]:
    """Deduplicate the bibliography only; keep all evidence excerpts available."""
    seen = set()
    result = []
    for context in contexts:
        key = (format_source(context), str(context.text.doc.file_location))
        if key not in seen:
            seen.add(key)
            result.append(context)
    return result


def cited_references(answer: Any) -> list[Any]:
    """Use PaperQA's original citation IDs, before they become display labels."""
    if hasattr(answer, "raw_answer"):
        from paperqa.utils import get_citation_ids

        cited_ids = set(get_citation_ids(answer.raw_answer))
        return unique_references(c for c in answer.contexts if c.id in cited_ids)
    # Support callers constructing a simple answer without PaperQA's raw form.
    return unique_references(answer.contexts)


def transform_answer(answer: Any) -> Any:
    """Transform the answer to format references correctly using Papis references."""
    # Convert to latex math
    answer.answer = to_latex_math(answer.answer)

    # Create a mapping of document names to references
    papis_id_to_ref = {}

    # First pass: collect all document names and their references and convert to latex math
    for context in answer.contexts:
        context.context = to_latex_math(context.context)
        if context.text.name:
            papis_id_to_ref[context.text.name.split()[0]] = source_ref(context.text.doc)

    if not papis_id_to_ref:
        return answer
    names = "|".join(
        re.escape(n) for n in sorted(papis_id_to_ref, key=len, reverse=True)
    )
    page_range = r"\d+(?:[-–]\d+)?"
    item = re.compile(
        rf"(?P<name>{names})(?P<chunk>\s+chunk\s+\d+)?"
        rf"(?:\s+pages\s+(?P<pages>{page_range}(?:\s*,\s*{page_range})*))?"
    )
    known_chunks = {c.text.name: c for c in answer.contexts}

    def replace_citation(match):
        body = match.group(1).strip()
        if not body:
            return match.group(0)
        position = 0
        references = []
        while position < len(body):
            citation = item.match(body, position)
            if citation is None:
                return match.group(0)
            name, pages = citation.group("name", "pages")
            if citation.group("chunk"):
                chunk = known_chunks.get(citation.group(0))
                if chunk is None:
                    return match.group(0)
                pages = context_pages(chunk)
            ref = f"@{papis_id_to_ref[name]}"
            if pages:
                ref += f", p. {pages}"
            references.append(ref)
            position = citation.end()
            if position < len(body):
                separator = re.match(r"\s*[,;]\s*", body[position:])
                if separator is None:
                    return match.group(0)
                position += separator.end()
                if position == len(body):
                    return match.group(0)
        return "[" + "; ".join(dict.fromkeys(references)) + "]"

    # Convert only fully recognized groups. Mixed prose/unknown identifiers are
    # left intact, preserving the ordinary-parentheses guarantee of PR #3.
    answer.answer = re.sub(r"\(([^()]*)\)", replace_citation, answer.answer)

    return answer


def to_terminal_output(
    answer: Any,
    context: bool,
    excerpt: bool,
    math: bool = False,
) -> None:
    """Format and print the answer with optional context and excerpts."""
    answer = transform_answer(answer)
    console = Console()

    # Format question
    question_md = Text(answer.question)
    console.print(
        Panel(
            question_md,
            title=Text("Question", style="magenta bold"),
            border_style="bright_black",
        )
    )

    # Create a Text object for the answer. LaTeX -> Unicode is terminal-only
    # (never applied to markdown/json output, which keep real LaTeX source
    # for downstream tools that render it themselves).
    if math:
        from mathunicode import convert_math_spans

        answer.answer = convert_math_spans(answer.answer)
    answer_text = Text(answer.answer)

    # Define a regex pattern for citations like [@XYZ]
    citation_pattern = r"\[@[^\]]+\]"

    # Highlight all matches in blue
    answer_text.highlight_regex(citation_pattern, style="blue")

    # Display in panel
    console.print(
        Panel(
            answer_text,
            title=Text("Answer", style="green bold"),
            border_style="bright_black",
        )
    )

    # Create references with colored names
    references = []
    for answer_context in cited_references(answer):
        filename = Path(answer_context.text.doc.file_location).name
        reference_line = Text("- ")
        reference_line.append(format_source(answer_context), style="blue")
        reference_line.append(f" ({filename})")
        references.append(reference_line)

    from rich.console import Group

    references_group = Group(*(references or [Text("No cited sources.")]))
    console.print(
        Panel(
            references_group,
            title=Text("References", style="yellow bold"),
            border_style="bright_black",
        )
    )

    # Format context if requested
    if context or excerpt:
        if math:
            from mathunicode import convert_math_spans
        for answer_context in answer.contexts:
            # Format summary
            summary = summary_text(answer_context)
            excerpt_text = to_latex_math(answer_context.text.text)
            if math:
                summary = convert_math_spans(summary)
                excerpt_text = convert_math_spans(excerpt_text)
            summary_table = Table(show_header=False, box=None)
            summary_table.add_row(Text("Summary:", style="bold"), Text(summary))
            summary_table.add_row(
                Text("Score:", style="bold"), Text(str(answer_context.score))
            )
            if excerpt:
                summary_table.add_row(
                    Text("Excerpt:", style="bold"), Text(excerpt_text)
                )

            # Print context
            filename = Path(answer_context.text.doc.file_location).name
            title = Text()
            title.append(format_source(answer_context), style="blue bold")
            title.append(f" ({filename})", style="white")
            console.print(
                Panel(
                    summary_table,
                    title=Text("\n") + title,  # Add newline before the title
                    border_style="bright_black",
                )
            )


def to_json_output(answer: Any) -> str:
    """Convert the answer object to a JSON-serializable dictionary."""
    output = {
        "question": answer.question,
        "answer": answer.answer,
        "references": [
            {
                "papis_id": context.text.doc.other.get("papis_id"),
                "pages": context_pages(context),
            }
            for context in cited_references(answer)
        ],
        "contexts": [
            {
                "papis_id": context.text.doc.other.get("papis_id"),
                "pages": context_pages(context),
                "summary": summary_text(context),
                "score": context.score,
                "excerpt": context.text.text,
            }
            for context in answer.contexts
        ],
    }
    return json.dumps(output, indent=2)


def to_markdown_output(
    answer: Any,
    context: bool = False,
    excerpt: bool = False,
) -> str:
    """Format the answer as a well-formatted markdown document."""
    answer = transform_answer(answer)

    markdown = []

    # Question section
    markdown.append("# Question\n")
    markdown.append(answer.question + "\n")

    # Answer section
    markdown.append("# Answer\n")

    # Process answer text to adjust heading levels
    answer_text = answer.answer
    lines = answer_text.split("\n")

    # First, determine if we need to adjust heading levels
    min_heading_level = float("inf")
    for line in lines:
        if line.strip().startswith("#"):
            # Count the number of # symbols at the start
            level = 0
            for char in line.strip():
                if char == "#":
                    level += 1
                else:
                    break
            min_heading_level = min(min_heading_level, level)

    # If the minimum heading level is 1, shift all headings
    if min_heading_level == 1:
        adjusted_lines = []
        for line in lines:
            if line.strip().startswith("#"):
                adjusted_lines.append("#" + line)  # Add one # to increase heading level
            else:
                adjusted_lines.append(line)
        answer_text = "\n".join(adjusted_lines)

    markdown.append(answer_text + "\n")

    # References section
    markdown.append("## References\n")
    for answer_context in cited_references(answer):
        filename = Path(answer_context.text.doc.file_location).name
        markdown.append(f"- [{format_source(answer_context)}] ({filename})")

    # Context section (only if requested)
    if context or excerpt:
        markdown.append("\n# Context\n")

        for answer_context in answer.contexts:
            # Context metadata
            filename = Path(answer_context.text.doc.file_location).name
            markdown.append(f"## {format_source(answer_context)} ({filename})\n")

            # Summary
            markdown.append(to_latex_math(summary_text(answer_context)) + "\n")

            # Score
            markdown.append(f"**Score:** {answer_context.score}\n")

            # Excerpt (only if requested)
            if excerpt:
                markdown.append("### Excerpt\n")
                markdown.append(answer_context.text.text + "\n")

    return "\n".join(markdown)
