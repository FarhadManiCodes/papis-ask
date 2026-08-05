"""Reduce a reading note to the part worth embedding.

A note captured by sioyek's `Alt+n` (`dotfiles/bash/sioyek-papis-note`)
interleaves three kinds of content: your own prose, verbatim quotes from the
paper, and position markers. Only the prose belongs in the index.

The quotes must go because the paper's own text is *already* embedded from the
PDF. Indexing it a second time from a note makes the same passage compete with
itself for the `ask.max-sources` budget, so a question can come back with two
copies of one paragraph and one fewer other paper -- a silent loss of recall
that looks like the index simply not knowing things.
"""

import re

# The fence and everything between it, plus the trailing newline so removing a
# block leaves no hole. Non-greedy: two quotes in one note are two matches.
_QUOTE_BLOCK = re.compile(
    r"[ \t]*<!--\s*quote\s*-->.*?<!--\s*/quote\s*-->[ \t]*\n?",
    re.DOTALL,
)

# Whatever comments remain: the `<!--sioyek page=... -->` position markers, and
# anything you write that is meant to be invisible when the note is rendered.
_COMMENT = re.compile(r"[ \t]*<!--.*?-->[ \t]*\n?", re.DOTALL)

# Removing blocks tends to leave runs of blank lines behind.
_BLANK_RUN = re.compile(r"\n{3,}")

# `## p.7 - 2026-08-05`, the heading Alt+n writes before you have typed anything.
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s")


def strip_note_markup(text: str) -> str:
    """Return only the prose of a note, with quotes and HTML comments removed.

    An *unclosed* `<!--quote-->` fence -- easy to create by hand-editing a note
    -- deliberately fails open: `_QUOTE_BLOCK` cannot match it, so `_COMMENT`
    strips the dangling fence and the text under it stays. That over-indexes one
    passage, which costs a little retrieval budget. Failing closed would mean
    guessing where the quote ended and silently dropping the prose after it,
    which costs your actual thinking.
    """
    out = _QUOTE_BLOCK.sub("", text)
    out = _COMMENT.sub("", out)
    out = _BLANK_RUN.sub("\n\n", out)
    return out.strip()


def indexable_prose(text: str) -> str:
    """The part of a note worth embedding, or `""` when there is none.

    Headings are kept when the note has prose -- `## p.7` tells a retrieved chunk
    which page it came from, which is context worth having in an answer. But a
    note that is *only* headings has nothing in it yet: `Alt+n` writes the
    heading and the quote before you type, so this is the state every capture
    passes through. Embedding it would buy a vector whose entire content is a
    page number, and it would do so on every capture.
    """
    prose = strip_note_markup(text)
    if not any(line.strip() and not _HEADING.match(line) for line in prose.splitlines()):
        return ""
    return prose
