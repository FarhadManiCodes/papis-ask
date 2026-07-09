# CLAUDE.md — papis-ask

papis-ask is a **Papis plugin** that integrates **paper-qa** to answer questions over a
Papis library: `papis ask index [query]` builds the index, `papis ask "<question>"` queries
it. paper-qa is reached through liteLLM; models are set in the papis config (`ask-llm`,
`ask-summary-llm`, `ask-embedding` — the last is typically `ollama/nomic-embed-text`, local).

Code lives in `papis_ask/`: `main.py` (commands + indexing), `metadata_provider.py`
(`PapisProvider`, source metadata from `info.yaml`), `output.py`, `config.py`.

## Current work: ingest paper-refinery chunks instead of pypdf

The active task is replacing paper-qa's built-in pypdf PDF parsing with **paper-refinery**'s
pre-built, section-aware chunks (figures described, citations standardized, page numbers).
The full, self-contained hand-off guide is **`docs/paper-refinery-integration.md`** — read it
first; it does not require reading the paper-refinery source.

- **paper-refinery** (`~/projects/paper-refinery`, released **v0.1.0**) is DONE and frozen. It
  turns a PDF into chunks via `paper_refinery.refine()` / `refine_many()` and is deliberately
  **paper-qa-agnostic** — so **all paper-qa glue lives here, in papis-ask.** It is cloud-first
  (GLM-OCR `mode="maas"`, torch-free) and needs `ZHIPU_API_KEY` + `GOOGLE_API_KEY` at runtime.
- **Task 3** — `main.py::add_file_to_index` (line 52): swap the `docs_index.aadd(file_path)`
  call (line 68, pypdf) for `aadd_texts(texts, doc)` built from `refine(pdf, doi=…).chunks`.
- **Task 4** — refine-on-index: staleness in `determine_file_status` (line 256);
  `--force-refine` / `--no-refine` flags; batch path via `refine_many`.
- **Never let a refine failure fail indexing** — fall back to pypdf with a warning.

## Running / testing

It's a Papis plugin, exercised through papis itself (`papis` at `~/.local/bin/papis`):
`papis ask index [query]`, `papis ask "<question>"`. For the integration, paper-refinery must
be importable in the papis environment — not yet installed; per the guide §3:
`uv pip install --python <papis-env-python> -e ~/projects/paper-refinery` (torch-free cloud
default). **Validate live, not just via unit tests** (project rule inherited from
paper-refinery): index one paper, confirm page-range source names + clean retrieved text,
re-index to confirm the OCR checkpoint is reused.

## Conventions

- **NEVER** add `Co-Authored-By` or any AI-attribution trailer to commits or PRs.
- Key touchpoints: `papis_ask/main.py` — `add_file_to_index` (52), `update_index_metadata`
  (102), `determine_file_status` (256); `papis_ask/metadata_provider.py` — `PapisProvider`
  (137).
- Don't reconcile refinery's in-text `[surname_year]` citekeys with papis refs (shelved —
  paper-qa doesn't use them for retrieval).
