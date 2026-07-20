# paper-refinery integration

This describes how papis-ask consumes **paper-refinery**'s output instead of letting
paper-qa parse PDFs with pypdf. **Status: implemented and in use.** This doc describes the
actual current design, not a plan — it replaces an earlier hand-off draft that sketched a
different (in-process, Python-API) integration; that approach was **not** what got built.

- **paper-refinery repo:** `~/projects/paper-refinery`, currently **v0.3.0**; cloud GLM-OCR
  is the default (torch-free, no GPU). Installed as its own standalone tool (`uv tool
  install ~/projects/paper-refinery`), giving `refinery` / `refinery-batch` /
  `refinery-export-citations` / `refinery-typeset` on `PATH`.
- **paper-refinery is a separate CLI tool, not a Python dependency of papis-ask.**
  papis-ask does not `import paper_refinery` anywhere — see §2.

---

## 1. What & why

paper-refinery turns a PDF into faithful, section-aware, overlapping text chunks (with
figure descriptions, page numbers, and standardized `[surname_year]` in-text citekeys).
papis-ask's `add_file_to_index` prefers these pre-built chunks (`<pdf>.chunks.json`) over
letting paper-qa re-parse the PDF itself with pypdf's blind char-window chunking, via
**`docs_index.aadd_texts(texts, doc, ...)`** instead of `docs_index.aadd(file_path, ...)`.

## 2. The boundary contract (separation of tools)

Locked design decisions:

- **paper-refinery stays paper-qa-agnostic.** It never imports paper-qa; its contract is
  "PDF → faithful chunks (+ figures/citations artifacts)", produced by running the
  `refinery` / `refinery-batch` CLI as its own process.
- **papis-ask never imports `paper_refinery`, either.** The only coupling is the on-disk
  `<pdf>.chunks.json` file (`papis_ask/refinery.py` reads it) — no Python API call, no
  subprocess invocation of `refinery` from within papis-ask. Refining a PDF is a step the
  *user* (or their own automation) runs separately, before `pask index`.
- **paper-qa is papis-ask's dependency, not refinery's.** papis-ask owns the glue that
  converts refinery's chunk JSON into paper-qa `Text`/`Doc` objects
  (`add_file_to_index` in `papis_ask/main.py`).
- **The seam is `<pdf>.chunks.json`.** No paper-qa type ever crosses into refinery; no
  refinery type ever crosses into paper-qa except as plain chunk text.
- **Source attribution is unchanged.** papis-ask still attributes each indexed paper by its
  papis `ref` (from `info.yaml`, via `PapisProvider`). Refinery's *in-text* `[surname_year]`
  citekeys are just text inside chunks; paper-qa does not resolve them against the library
  (the "registration" idea was shelved as valueless for retrieval).
- **Never let a missing/stale/failed refine block indexing.** Fall back to pypdf with a
  warning — this is implemented (§6), not just a principle.

## 3. Installing paper-refinery

paper-refinery is installed as its own global tool, independent of papis-ask's own
environment:

```bash
uv tool install ~/projects/paper-refinery
# -> refinery, refinery-batch, refinery-export-citations, refinery-typeset on PATH
```

Re-run this (`--force` to reinstall over an existing tool install) after pulling
paper-refinery changes — a `uv tool install` snapshot does **not** track the source
directory live, unlike an editable `pip install -e`. Confirm the live version:

```bash
uv tool list | grep -A1 paper-refinery
```

The **default is cloud-only and torch-free**: no GPU, no `llama-server`, no GGUF weights.
OCR runs on Zhipu's GLM-OCR API (`mode="maas"`, the default). At *runtime* it needs two API
keys:

- **`ZHIPU_API_KEY`** — cloud OCR (layout + text).
- **`GOOGLE_API_KEY`** — Gemini figure descriptions + citation extraction (and, optionally,
  `refinery-typeset --clean-toc`'s heading classification).

paper-refinery loads these from `~/.config/paper-refinery/secrets/*.env` (one file per
service: `zai.env`, `google.env`) — a project-owned secrets dir it only ever reads.

> **Optional offline OCR.** To run OCR locally instead of the cloud, install the `.[local]`
> extra (`uv pip install -e "~/projects/paper-refinery[local]"` into a venv you drive
> yourself — the local extra pulls `torch`/`torchvision` + PP-DocLayout and needs
> `llama-server` + GLM-OCR GGUF weights, with paths in
> `~/.config/paper-refinery/config.toml` (`[parse] mode = "selfhosted"`). Not needed for the
> default cloud path; see paper-refinery's own README for details.

## 4. Refining papers (a manual step, not automated by papis-ask)

There's no "refine-on-index" in papis-ask (§7 explains why that was deliberately not
built). Refine PDFs yourself, before indexing:

```bash
# one paper
refinery path/to/paper.pdf

# a whole library, refined concurrently
refinery-batch $(papis list --file)
```

Each run writes `<pdf>.chunks.json` (+ `.citations.json`, `.refinery/`) next to the PDF. A
repeat run on an unchanged PDF reuses its OCR checkpoint (`work_dir/parse_cache/`) and
costs no OCR. See paper-refinery's own README for `refine()`/`refine_many()`'s full Python
API, `--doi`/`--meta-map` (the papis-metadata channel — feed `info.yaml`'s DOI/title/refs
into refinery so it doesn't re-derive paper identity from OCR alone), and
`refinery-batch --workers`/`--ocr-workers` tuning — none of that is wired into papis-ask
directly; it's there if *you* want to script your own refine step around it (e.g. a
pre-commit hook, a `papis add` post-hook, a cron job over the library).

`refinery-typeset` (PDF/.md → a clean, reflowed reading-copy PDF with a table of contents)
is unrelated to indexing — a separate output for humans, not part of the chunks.json seam.

## 5. The chunks.json schema (the data seam)

```json
{
  "schema_version": 1,
  "parser": "paper-refinery",
  "source_pdf": "/abs/path/to/paper.pdf",
  "docname": "paper",
  "chunks": [
    {
      "index": 0,
      "text": "…chunk text with page markers stripped…",
      "page_start": 3,
      "page_end": 4,
      "overlap_chars": 512,
      "overlap_mode": "SENT"
    }
  ]
}
```

- `text` is the chunk body (figure descriptions spliced in, `[surname_year]` citekeys
  rewritten where verified, footnote content kept and clearly labeled, page-number markers
  stripped).
- `page_start`/`page_end` give the chunk's page range (either may be `null`).
- `overlap_chars`/`overlap_mode` are provenance for the soft-overlap window; ignored for
  indexing.
- `schema_version` **is checked** — `read_refinery_chunks` falls back to pypdf if it's an
  explicit, unrecognized value (`SUPPORTED_SCHEMA_VERSION` in `papis_ask/refinery.py`,
  currently `1`), same as a missing/stale/malformed manifest. A manifest with the field
  *absent entirely* is trusted, not rejected — it predates the field's introduction
  (paper-refinery < v0.2.0), and every real pre-versioning manifest is otherwise perfectly
  readable; rejecting those would silently regress an existing library's older refined
  papers back to pypdf quality for no actual incompatibility.

The chunk name paper-qa uses is `"{docname} pages {start}-{end}"` (or
`"{docname} pages {n}"` for a single page, `"{docname} chunk {i}"` when no page range) —
`papis_ask/refinery.py::chunk_name` mirrors `paper_refinery.chunker.Chunk.name_for()`
without importing it (per §2, no import at all).

## 6. How papis-ask consumes it (implemented)

`papis_ask/refinery.py` — the only file that knows about refinery's on-disk contract:

- `chunks_json_path(file_path)` — `<pdf>.chunks.json`, or `None` for a non-PDF.
- `read_refinery_chunks(file_path)` — returns the parsed payload, or `None` (with a logged
  warning) if the manifest is missing, **older than the PDF**, malformed, or has no chunks.
- `chunk_name(...)` — mirrors `Chunk.name_for()`.

`papis_ask/main.py::add_file_to_index` (abridged):

```python
from papis_ask.refinery import chunk_name, read_refinery_chunks

chunks_payload = read_refinery_chunks(file_path) if use_refinery else None

if chunks_payload is not None:
    doc = Doc(docname=papis_id, dockey=dockey, citation=papis_id)
    texts = [
        Text(text=c["text"], name=chunk_name(name, c["index"], c.get("page_start"), c.get("page_end")), doc=doc)
        for c in chunks_payload["chunks"]
    ]
    added = await docs_index.aadd_texts(texts, doc, settings=settings)
    docname = doc.docname if added else None   # aadd_texts mutates doc.docname to dedupe; read it back, don't assume papis_id survived
else:
    # refinery opted out, chunks missing/stale, or not a PDF -- pypdf, unchanged
    if use_refinery and file_path.suffix.lower() == ".pdf":
        logger.warning("No refined chunks for %s; falling back to pypdf. Run `refinery %s` first.", file_path, file_path)
    docname = await docs_index.aadd(file_path, dockey=dockey, docname=papis_id, citation=papis_id, settings=settings)
```

Then, same as before either way: `update_index_metadata` upgrades the `Doc` to a
`DocDetails` via `PapisProvider`, additionally now stamping `chunk_source`
(`"refinery"`/`"pypdf"`) + (for the pypdf path only) `chunk_chars`/`chunk_overlap`, so
`determine_file_status` (§7) can tell what produced the current chunks and whether that's
gone stale.

**CLI control:** `pask index --no-refine` (alias `--raw`) forces the pypdf path for the
whole run, ignoring any chunks.json present — useful for A/B-checking retrieval quality or
working around a bad refine.

## 7. Staleness detection (implemented; simpler than the original "refine-on-index" plan)

The originally-sketched plan (an earlier draft of this doc) had papis-ask call
`paper_refinery.refine()` itself when chunks were missing or stale, with a `--force-refine`
flag driving `force_parse=True`. **That was not built.** What's implemented instead,
`determine_file_status` in `papis_ask/main.py`:

- Re-indexing triggers when the **PDF's mtime** *or* **`<pdf>.chunks.json`'s mtime**
  exceeds the recorded `file_last_indexed` — so re-running `refinery <pdf>` (e.g. after an
  OCR-cache repair) without touching the PDF itself is still detected.
- An embedding-model change (`ask.embedding` differs from what's recorded) forces
  re-indexing regardless of file mtimes, since no mtime check can catch a config-only
  change.
- A chunk-params change (`ask.chunk-chars`/`ask.overlap`) forces re-chunking **only** for
  papers on the pypdf path (`chunk_source == "pypdf"`) — refinery-chunked papers ignore
  those settings entirely, so re-chunking them on a config change would be wasted spend.
- There is **no automatic OCR trigger**. If chunks are missing or stale, `pask index` falls
  back to pypdf with a warning (§6) rather than calling refinery for you. Refining is
  always a step you (or your own automation) run first — this keeps `pask index` free of
  refinery's runtime dependencies (network, `ZHIPU_API_KEY`/`GOOGLE_API_KEY`, OCR latency)
  by construction, and keeps papis-ask itself refinery-import-free (§2).

If you want auto-refine-on-index, build it as your own wrapper around `refinery-batch`
(or `paper_refinery.refine_many()`, §4) run before `pask index` — not inside papis-ask.

## 8. What NOT to do

- **Don't make paper-refinery import paper-qa.**
- **Don't make papis-ask import `paper_refinery`.** The file-based seam (§2) is the
  deliberate, settled design — reintroducing an in-process call would couple papis-ask to
  refinery's runtime dependencies (network, API keys, OCR latency) inside `pask index`.
- **Don't reconcile in-text citekeys with papis refs** (the shelved "registration" idea).
  paper-qa doesn't use them; it's wasted effort for retrieval.
- **Don't change how sources are attributed** — `PapisProvider` / `ref` / DocDetails flow is
  unchanged.
- **Don't let a refine failure, or its absence, fail the index** — fall back to pypdf with a
  warning (implemented).

## 9. Validating the integration

1. Refine a paper: `refinery path/to/paper.pdf` (writes `<pdf>.chunks.json` next to it).
2. `pask index -f <query-for-it>`.
3. Confirm the index used refinery chunks: sources should carry **page-range names**
   (`… pages 3-4`) and the retrieved text should be clean (equations/figures intact), not
   pypdf glyph soup. `doc.other["chunk_source"]` should read `"refinery"`.
4. `pask "<question answerable from that paper>"` and check the answer cites the right
   `@ref` and the evidence excerpts are the refined chunks.
5. Re-index the same paper: it should **not** re-OCR (refinery's own checkpoint hit) and
   `pask index` should skip it (no chunks.json mtime change, no PDF mtime change).
6. `pask index --no-refine -f <query-for-it>` and confirm it falls back to pypdf even with
   a valid chunks.json present.

## 10. Reference — touchpoints

- `papis_ask/refinery.py` — the entire refinery seam: `chunks_json_path`,
  `read_refinery_chunks`, `chunk_name`. The only file that knows refinery's on-disk shape.
- `papis_ask/main.py::add_file_to_index` — prefers refinery chunks via `aadd_texts`, falls
  back to `aadd(file_path)` (pypdf).
- `papis_ask/main.py::update_index_metadata` — DocDetails upgrade via `clients["papis"]`;
  now also stamps `chunk_source`/`chunk_chars`/`chunk_overlap`.
- `papis_ask/main.py::determine_file_status` — staleness (§7).
- `papis_ask/main.py::index_cmd` — `--no-refine`/`--raw` CLI flag.
- `papis_ask/metadata_provider.py::PapisProvider` — source metadata from `info.yaml`;
  unrelated to refinery.
- `tests/test_refinery_integration.py` — manifest-locating, staleness, and chunk-naming
  tests for the `papis_ask/refinery.py` seam.
- papis config: `ref-format = {doc[author_list][0][family]}_{doc[year]}` → `smith_2020`,
  matching refinery's minted `[surname_year]` citekeys; library at
  `~/.local/share/papis/papers`; dedup by `doi`.
