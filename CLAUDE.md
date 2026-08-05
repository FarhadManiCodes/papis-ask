# CLAUDE.md — papis-ask

papis-ask is a **Papis plugin** that integrates **paper-qa** to answer questions over a
Papis library: `papis ask index [query]` builds the index, `papis ask "<question>"` queries
it. paper-qa is reached through liteLLM; models are set in the papis config (`ask-llm`,
`ask-summary-llm`, `ask-embedding`). Embedding is **`gemini/gemini-embedding-2`** in the
live config — not a local ollama model, so re-embedding costs real quota and every
"should this be re-indexed?" decision is a spending decision.

Code lives in `papis_ask/`: `main.py` (commands + indexing), `metadata_provider.py`
(`PapisProvider`, source metadata from `info.yaml`), `output.py`, `config.py`,
`notes.py` (what of a reading note is worth embedding).

## Note ingestion (done)

Notes are discovered through papis' `notes:` key (never via a `.md` in `files:` — every
paper has a refinery `<stem>.md` of its full text beside it, which would index the paper
twice) and embedded like any other source, with three deliberate differences:

- **Quotes are stripped before embedding** (`papis_ask/notes.py`). Notes are captured by
  sioyek's `Alt+n` (`dotfiles/bash/sioyek-papis-note`), which writes the selected passage
  inside `<!--quote-->` fences and the page position as an HTML comment. That passage is
  already embedded from the PDF; indexing it again makes one paragraph compete with
  itself for `ask.max-sources`, so a question returns it twice and one fewer other paper.
  An unclosed fence fails **open** — over-index a passage rather than guess where a quote
  ended and silently drop the prose after it.
- **A note with no prose is not indexed at all.** `Alt+n` writes a heading and a quote
  before you type, so `indexable_prose()` reports nothing unless some line is not a
  heading. Otherwise every capture would buy a vector containing only `## p.7`.
- **Sources are marked `@<ref> (note)`** at render time (`output.source_ref`), *not* via
  `Doc.citation`: `update_index_metadata` lists `citation` in
  `fields_to_overwrite_from_metadata`, so anything written there is replaced by the papis
  title on the DocDetails upgrade. Rendering never reads `citation` anyway — both
  `format_source` and `transform_answer` build from `doc.other["ref"]`.

Notes carry `chunk_source: "note"` and are chunked by `ask.chunk-chars`/`ask.overlap`, so
they belong in the same staleness gate as pypdf papers — `determine_file_status` checks
`chunk_source in ("pypdf", "note")`. Reading `== "pypdf"` would freeze every note at
whatever chunking was configured the day it was written, with no mtime moving to show it.

## paper-refinery integration (done)

paper-qa's built-in pypdf PDF parsing is replaced by **paper-refinery**'s pre-built,
section-aware chunks (figures described, citations standardized, page numbers) whenever a
`<pdf>.chunks.json` is present and fresh. The full reference is
**`docs/paper-refinery-integration.md`** — read it first; it does not require reading the
paper-refinery source. That doc describes the design actually implemented below — not an
earlier plan; disregard any other notes that talk about Tasks 3/4 as pending or about
calling `refine()`/`refine_many()` in-process, that plan was superseded.

- **paper-refinery** (`~/projects/paper-refinery`, currently **v0.3.0**) is a separate CLI
  tool (`uv tool install ~/projects/paper-refinery` → `refinery`/`refinery-batch`/
  `refinery-export-citations`/`refinery-typeset` on `PATH`), **not a Python dependency** —
  papis-ask never imports `paper_refinery` anywhere. It is cloud-first (GLM-OCR
  `mode="maas"`, torch-free) and needs `ZHIPU_API_KEY` + `GOOGLE_API_KEY` at runtime, but
  only when *you* run `refinery`/`refinery-batch` yourself — never as a side effect of
  `pask index`.
- `main.py::add_file_to_index` (117) prefers `<pdf>.chunks.json` (read via
  `papis_ask/refinery.py`) over `docs_index.aadd(file_path)` (pypdf), calling
  `aadd_texts(texts, doc)` instead when a fresh manifest exists.
- `determine_file_status` (388) triggers re-indexing on either the PDF's mtime *or* the
  chunks.json's mtime changing. There is **no auto-refine-on-index**: a missing/stale
  manifest falls back to pypdf with a warning telling you to run `refinery`/
  `refinery-batch` yourself. `--no-refine` / `--raw` forces pypdf regardless of a valid
  manifest being present.
- **Never let a missing/failed refine fail indexing** — fall back to pypdf with a warning
  (implemented, not just a principle).

## Running / testing

It's a Papis plugin, exercised through papis itself: `papis ask index [query]`,
`papis ask "<question>"`. Secrets live in `~/.config/secrets/papis.env`; the `pask` zsh
wrapper (`~/dotfiles/zsh/functions/papis.zsh`) sources them, so from a non-interactive
shell use `zsh -c 'source ~/dotfiles/zsh/functions/papis.zsh; pask ...'`.

**Unit tests:** `uv run --extra test pytest` (uses the `test` extra already declared in
`pyproject.toml`, in a project-local `.venv`). Do **not** `uv pip install` pytest into the
papis env: `~/.local/share/uv/tools/papis` is a uv-managed *tool* env and prunes anything
not in its `uv-receipt.toml`, so side-loaded packages silently disappear.

**The plugin is installed editable**, so whatever branch is checked out here *is* the live
`papis ask`. Standing on `main`/an upstream branch means papis runs upstream's code (pickle
index, no sidecars) — always return to `personal` and verify with
`python -c "import papis_ask.refinery, papis_ask.index_store"`. Reinstall, if ever needed:
`uv tool install --force papis --with-editable ~/projects/papis-ask --with-editable ~/projects/mathunicode`
(both editables are required — `mathunicode` is not on PyPI).

**Validate live, not just via unit tests** (project rule inherited from paper-refinery):
index one paper, confirm page-range source names + clean retrieved text, re-index to confirm
the OCR checkpoint is reused. When testing *upstream* code, never point it at the real
library — use an isolated one (`papis -l /path/to/testlib ask index`), whose cache lands
beside that path rather than in `~/.cache/papis/`.

## Conventions

- **NEVER** add `Co-Authored-By` or any AI-attribution trailer to commits or PRs.
- Key touchpoints: `papis_ask/main.py` — `add_file_to_index` (117), `update_index_metadata`
  (249), `determine_file_status` (388); `papis_ask/refinery.py` — the entire
  paper-refinery seam (`chunks_json_path`, `read_refinery_chunks`, `chunk_name`);
  `papis_ask/metadata_provider.py` — `PapisProvider` (164).
- Don't reconcile refinery's in-text `[surname_year]` citekeys with papis refs (shelved —
  paper-qa doesn't use them for retrieval).
