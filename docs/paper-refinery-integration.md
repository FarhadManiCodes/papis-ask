# Integrating paper-refinery into papis-ask

This guide describes how papis-ask should consume **paper-refinery**'s output instead of
letting paper-qa parse PDFs with pypdf. It is the hand-off document for the two remaining
integration tasks; everything on the paper-refinery side is done and stable.

- **paper-refinery repo:** `~/projects/paper-refinery` (released **v0.2.0**; cloud GLM-OCR is
  the default, torch-free). v0.2.0 adds the **papis metadata channel** (§4c) — feed papis's
  info.yaml into refinery so it doesn't re-derive identity/references from OCR.
- **This is a guide, not code** — the paper-refinery-side facts are authoritative; the
  papis-ask-side code is sketched and marked where it needs verification against paper-qa.

---

## 1. What & why

paper-refinery turns a PDF into faithful, section-aware, overlapping text chunks (with
figure descriptions, page numbers, and standardized `[surname_year]` in-text citekeys).
Today papis-ask's `add_file_to_index` calls **`docs_index.aadd(file_path, ...)`**, which
hands the raw PDF to paper-qa and lets it re-parse with pypdf's blind char-window chunking —
so paper-refinery's output is never used. The integration replaces that with
**`docs_index.aadd_texts(texts, doc, ...)`**, feeding paper-qa refinery's pre-built chunks.

paper-qa's `aadd_texts` exists precisely for this ("useful if you have already chunked the
texts yourself").

## 2. The boundary contract (separation of tools)

Locked design decisions — please preserve them:

- **paper-refinery stays paper-qa-agnostic.** It never imports paper-qa; its contract is
  "PDF → faithful chunks (+ figures/citations artifacts)".
- **paper-qa is papis-ask's dependency, not refinery's.** papis-ask owns the small glue that
  converts refinery chunks into paper-qa `Text`/`Doc` objects. That glue lives *here*.
- **The seam is the chunk data** — either the returned `RefineResult.chunks` (in-process) or
  the `<pdf>.chunks.json` file. No paper-qa type ever crosses into refinery.
- **Source attribution is unchanged.** papis-ask still attributes each indexed paper by its
  papis `ref` (from `info.yaml`, via `PapisProvider`). Refinery's *in-text* `[surname_year]`
  citekeys are just text inside chunks; paper-qa does not resolve them against the library,
  and we are **not** trying to make it (the "registration" idea was shelved as valueless for
  retrieval).

## 3. Installing paper-refinery into this environment

papis (and papis-ask) run from their own environment
(`~/.local/share/uv/tools/papis/...`). paper-refinery must be importable there:

```bash
# from anywhere, into papis's environment
uv pip install --python <papis-env-python> -e ~/projects/paper-refinery
```

That's the whole install — the **default is cloud-only and torch-free**: no GPU, no
`llama-server`, no GGUF weights. OCR runs on Zhipu's GLM-OCR API (`mode="maas"`, the
default). What it needs at *runtime* instead is two API keys:

- **`ZHIPU_API_KEY`** — cloud OCR (layout + text).
- **`GOOGLE_API_KEY`** — Gemini figure descriptions + citation extraction.

paper-refinery loads these from `~/.config/paper-refinery/secrets/*.env` (one file per
service: `zai.env`, `google.env`) — a project-owned secrets dir it only ever reads. As long
as those files exist, the keys reach any process that imports paper-refinery, papis
included. (Setting the env vars directly in papis's environment also works.)

So `pask index` gains a dependency on **network access + those two keys** whenever a
*new/changed* PDF must be refined — only then; a fresh `chunks.json`/checkpoint skips it.
No GPU or local server is ever involved on the default path.

> **Optional offline OCR.** To run OCR locally instead of the cloud, install the `.[local]`
> extra (`uv pip install -e "~/projects/paper-refinery[local]"`): that pulls
> `torch`/`torchvision` + PP-DocLayout and needs `llama-server` + GLM-OCR GGUF weights and
> paths in `~/.config/paper-refinery/config.toml` with `[parse] mode = "selfhosted"`. On a
> GPU-less machine, install the CPU-only torch build first (see paper-refinery's README
> "Local (selfhosted) OCR backend"). Not needed for the default cloud path.

## 4. The paper-refinery public API

One stable entry point (added for this integration):

```python
import paper_refinery

result = paper_refinery.refine(
    pdf,                      # pathlib.Path to the PDF
    cfg=None,                 # RefineryConfig; None -> load_config() (reads ~/.config/paper-refinery)
    *,
    out=None,                 # chunks.json path; default <pdf>.chunks.json
    citations_out=None,       # citations.json path; default <pdf>.citations.json
    work_dir=None,            # reviewable/intermediate dir; default <pdf>.refinery/
    force_parse=False,        # True bypasses the OCR checkpoint and re-parses
    doi=None,                 # source paper DOI -> shorthand folded into `source` (§4c)
    source=None,              # SourceMeta bundle from info.yaml -> metadata channel (§4c)
)
# result: RefineResult
result.chunks         # list[paper_refinery.chunker.Chunk]  -- in memory
result.chunks_path    # Path to the written chunks.json
result.citations_path # Path to citations.json (may not exist if the paper had no refs)
result.work_dir       # Path to <pdf>.refinery/
```

Key behaviors:

- **It runs the full pipeline** (parse → figure-enrich → citation-verify → chunk) and
  **writes** `chunks.json` / `citations.json` / `work_dir`, exactly like the CLI.
- **It reuses a parse checkpoint.** The OCR pass — the slow stage, ~40–60 s/paper on the
  cloud API (≈10 min on the local self-hosted backend, model-load dominated) — is cached in
  `work_dir/parse_cache/`, keyed on the PDF's content hash + parse config. A repeat call on
  an unchanged PDF **skips OCR** (seconds). `force_parse=True` re-OCRs.
- **Pass `doi` when you have it** (papis does, in `info.yaml`). It enables refinery's
  citation fast-path: one bulk reference fetch instead of a throttled per-reference provider
  search — faster and better-resolved bibliographies. Without it refinery falls back to the
  OCR'd title, so omitting it only costs quality/speed on the citation stage, never
  correctness. **Recommended: always forward the papis DOI.**
- **`Chunk` objects** expose `.text`, `.page_start`, `.page_end`, `.index`, and
  `.name_for(docname)` → a paper-qa-style source label like `"brunton-2016 pages 3-4"`.

### Where should refinery write its artifacts?

By default `refine()` writes `<pdf>.chunks.json`, `<pdf>.citations.json`, and
`<pdf>.refinery/` **next to the PDF** — i.e. *inside the papis library folder*. Decide:

- **Next to the PDF (default):** artifacts are reviewable and travel with the paper;
  downside is they clutter library folders (and papis may list them as attached files).
- **In a cache dir:** pass `out=`, `citations_out=`, `work_dir=` pointing at e.g.
  `get_cache_home()/refinery/<papis_id>/...` to keep the library clean. Downside: the
  reviewable markdown is less discoverable.

Recommendation: keep them next to the PDF only if you want them reviewable in the library;
otherwise redirect to the papis cache home. Either way the checkpoint (in `work_dir`) must
be in a **stable, per-paper** location so re-indexing reuses it.

### 4b. Batch API — `refine_many` (use this for indexing many papers)

`refine()` handles one PDF. For `pask index` over a whole library, prefer **`refine_many`**,
which runs papers' pipelines concurrently and streams each result the instant it finishes.
(A single PDF gains nothing — use `refine` there.)

```python
import paper_refinery

for result in paper_refinery.refine_many(
    pdfs,                     # Sequence[pathlib.Path]
    cfg=None,                 # RefineryConfig; None -> load_config()
    *,
    dois=None,                # Sequence[str | None] aligned 1:1 to pdfs; entries may be None
    force_parse=False,        # True re-OCRs every paper (bypasses checkpoints)
    workers=4,                # papers whose full pipeline runs concurrently
    ocr_workers=2,            # papers allowed in the (rate-limited) OCR stage at once
):
    # result: RefineResult, identical shape to refine()'s return
    index(result)             # <- your aadd_texts conversion (Task 3), per paper
```

Semantics you can rely on:

- **Yields in COMPLETION order, not input order** — each paper is yielded the instant *its
  own* pipeline finishes, so you index it as soon as it's ready rather than blocking on the
  whole batch. A fast (checkpoint-hit) paper is never held behind a slow one.
- **Genuinely parallel, with OCR gated separately.** In the default cloud (maas) mode each
  paper runs its *whole* pipeline (OCR → figures ‖ citations → chunk) on a pool of `workers`.
  OCR is the one stage the cloud rate-limits, so it's held under a separate `ocr_workers`
  semaphore (default 2): at most `ocr_workers` papers hit the OCR endpoint at once, while up
  to `workers` run the network-bound stages (Gemini figures, citation providers — different
  hosts, their own limits). The moment a paper's OCR finishes it frees the slot and flows
  into its figure/citation stages while the next paper OCRs. Live-measured: `workers=4,
  ocr_workers=2` refined the 4 sample papers **~2× faster than serial with zero throttling**.
  (In `selfhosted` mode `ocr_workers` is ignored — one local `llama-server` means OCR is a
  serial queue, with each paper's network stages overlapping the next paper's OCR.)
- **Same outputs as `refine()`.** Each `RefineResult` writes the same `<pdf>.chunks.json` /
  `.citations.json` / `.refinery/` next to its PDF; `refine_many` changes *scheduling*, not
  output.
- **Checkpoint-aware.** A paper with a fresh parse checkpoint skips OCR entirely (no cloud
  call); each cache-miss spawns its own lightweight cloud client (there's no shared server to
  warm up in maas mode), so an all-cached re-index does effectively no OCR work.
- **Per-paper failure is skipped, not fatal.** A paper that fails — corrupt PDF, provider
  outage, or an OCR call the cloud never fulfilled (a rate-limit exhaustion the SDK reports
  as an *empty* parse, which refinery now catches and treats as a failure rather than writing
  a silent 0-chunk result) — is logged on the `paper_refinery` logger and omitted from the
  stream. So the yielded count may be **less than `len(pdfs)`**; track which PDFs came back if
  you need to know what was skipped.
- **Overlap with your indexing is automatic.** `refine_many`'s work runs in background
  threads, so while you `await` the `aadd_texts` conversion for one result, refinery keeps
  refining the remaining papers. Iterate the (synchronous) generator and index each result as
  it arrives; e.g. from an async loop with `await asyncio.to_thread(next, it)`, or consume it
  in a worker thread that feeds an `asyncio.Queue`.

**Tuning `ocr_workers` (matters for a large library).** The cloud OCR endpoint (z.ai)
rate-limits concurrent requests — roughly **2–3 at once** on a standard pay-as-you-go tier;
above that it returns HTTP 429. `ocr_workers=2` stays safely under it, which is the whole
reason OCR is gated apart from `workers`. Raise it only if your z.ai tier's concurrency
allows (your number is at `z.ai/manage-apikey/rate-limits`). The glmocr SDK retries a
transient 429, but sustained over-subscription exhausts the retries → that paper is skipped
(above). Note: the z.ai **coding-plan subscription (Lite/Pro/Max) does *not* cover this API**
— OCR is billed pay-as-you-go regardless, so a subscription won't raise these limits.

`dois` is the older per-paper shorthand; prefer the richer `sources` bundle (§4c), aligned to
`pdfs` (entries may be `None`).

## 4c. The metadata channel (v0.2.0) — feed papis's info.yaml into refinery

This is the payoff of the "accept complementary info, no dependency" design: papis already
knows each paper's identity and (often) its reference list; passing that in stops refinery
re-deriving it from OCR. **All optional, graceful fallback — refinery never imports papis.**

Build a `SourceMeta` dict from `info.yaml` and hand it to refinery:

```python
def source_meta(doc_papis) -> dict:            # a plain dict; paper_refinery.SourceMeta types it
    return {
        "doi": doc_papis.get("doi"),
        "title": doc_papis.get("title"),
        "year": doc_papis.get("year"),
        "authors": doc_papis.get("author_list"),   # [{"family":..., "given":...}, ...]
        "references": doc_papis.get("citations"),   # papis stores CrossRef refs here (may be absent)
    }

result = paper_refinery.refine(Path(file_path), source=source_meta(doc_papis))
# batch:  refine_many(pdfs, sources=[source_meta(d) for d in docs])
# CLI/wrapper:  refinery-batch --meta-map map.json   ({abs_pdf_path: SourceMeta}, matched by path)
```

What it buys (per §4b live results):
- **`doi`/`title`/`year`/`authors`** make source identification for the S2 bulk-references
  fast-path reliable (a messy OCR'd title can otherwise miss).
- **`references`** (papis `citations:`) are matched against the printed bibliography **locally,
  before any network call**; if they cover everything the S2 fetch is **skipped entirely**
  (zero-network resolution). Accepts papis's CrossRef shape (`article-title`/`DOI`/`author`)
  verbatim — no mapping needed on the papis side.

**Reverse direction (optional, future): enrich papis with what refinery found.** refinery
resolves references papis was missing (kalman/hyco have `citations: []`); `to_papis_citations(
result_or_json["references"])` (or the `refinery-export-citations <pdf>.citations.json` CLI)
renders the **verified** ones as a papis/CrossRef `citations:` YAML block to MERGE into
info.yaml (via papis's own update API — verified-only, dedup, opt-in). Keep this on the
papis-aware side; refinery only *emits* the data.

## 5. The chunks.json schema (the data seam)

If you prefer to read the file rather than use `result.chunks`:

```json
{
  "source_pdf": "/abs/path/to/paper.pdf",
  "docname": "paper",
  "parser": "paper-refinery",
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

- `text` is the chunk body (figure descriptions spliced in, `[surname_year]` citekeys already
  rewritten where verified; page-number markers stripped).
- `page_start`/`page_end` give the chunk's page range (either may be `null`).
- `overlap_chars`/`overlap_mode` are provenance for the soft-overlap window; you can ignore
  them for indexing.

The chunk name paper-qa should use is `"{docname} pages {start}-{end}"` (or
`"{docname} pages {n}"` for a single page, `"{docname} chunk {i}"` when no page range) —
this is exactly what `Chunk.name_for(docname)` returns, so prefer calling it over
re-implementing.

## 6. Task 3 — consume refinery chunks via `aadd_texts`

### Current code (the thing to replace)

`papis_ask/main.py::add_file_to_index` currently does (abridged):

```python
dockey = md5sum(file_path)
_, papis_id, _ = extract_doc_papis_metadata(doc_papis)
docname = await docs_index.aadd(
    file_path, dockey=dockey, docname=papis_id, citation=papis_id, settings=settings
)
# ...then update_index_metadata(...) upgrades the Doc to a DocDetails via PapisProvider
```

`aadd(file_path)` is the pypdf re-parse. Replace it with the chunk path below.

### The converter

paper-qa types (verified against the installed `paperqa/types.py`):

```python
from paperqa.types import Doc, Text   # Doc(docname, dockey, citation, ...); Text(text, name, doc, ...)
```

```python
import paper_refinery

async def add_file_to_index(file_path, doc_papis, docs_index, clients, settings):
    from paperqa.utils import md5sum

    dockey = md5sum(file_path)
    ref, papis_id, _ = extract_doc_papis_metadata(doc_papis)

    # 1. run refinery, feeding papis's known metadata (§4c) so it doesn't re-derive it from OCR
    result = paper_refinery.refine(Path(file_path), source=source_meta(doc_papis))   # reuses OCR checkpoint

    # 2. build the paper-qa Doc + Texts (dockey/docname/citation exactly as today)
    doc = Doc(docname=papis_id, dockey=dockey, citation=papis_id)
    name = ref or papis_id                      # readable source label; your choice (see note)
    texts = [Text(text=c.text, name=c.name_for(name), doc=doc) for c in result.chunks]

    # 3. hand the pre-chunked texts to paper-qa (replaces aadd(file_path))
    added = await docs_index.aadd_texts(texts, doc, settings=settings)
    if not added:
        return None   # already in the collection (dockey seen)

    # 4. metadata upgrade to DocDetails via PapisProvider -- UNCHANGED, but see note
    return await update_index_metadata(
        file_path=file_path, file_last_indexed=time.time(), dockey=dockey,
        docname=papis_id, doc_papis=doc_papis, docs_index=docs_index,
        clients=clients, settings=settings,
    )
```

### Integration points to verify (paper-qa specifics)

- **`aadd_texts` returns `bool`, not a docname** (unlike `aadd`). The current code binds
  `docname := await aadd(...)`. You now set `docname = papis_id` yourself and pass it to
  `update_index_metadata`. Confirm `update_index_metadata` is happy with an explicit
  docname and that the later DocDetails swap (`docs_index.docs[dockey] = doc_details`) still
  lines up (it re-points `text.doc` for every text with that dockey — should be fine).
- **Chunk name `docname`.** Using `ref` gives readable sources (`brunton_2016 pages 3-4`);
  `papis_id` matches the current pre-upgrade identifier. Pick one and confirm how it renders
  after the DocDetails upgrade (the upgrade may overwrite `citation`, not the per-Text
  `name`).
- **Embeddings.** `aadd_texts` computes embeddings itself when `text.embedding is None`
  (default) — you don't need to pre-embed. Pass `settings=` (and optionally
  `embedding_model=`) as the current code does for `aadd`.

### Keep the pypdf path as a fallback

Preserve the existing `aadd(file_path)` behavior behind a flag (e.g. `--no-refine`/`--raw`)
and as an automatic fallback when a PDF can't be refined (OCR backend unavailable, refine
raised). The chunks manifest is the goal, but indexing must never hard-fail because refinery
couldn't run — degrade to pypdf with a warning, mirroring refinery's own
"citations failed → warn, still write chunks" philosophy.

## 7. Task 4 — refine-on-index + flags

Make `pask index` drive refinery from the PDF, reusing papis-ask's existing staleness logic:

- **Staleness.** `determine_file_status` already compares the PDF's mtime to the index. Add:
  if a fresh `<pdf>.chunks.json` (or checkpoint) exists and is newer than the PDF, reuse it;
  if missing or older, (re)run `paper_refinery.refine(...)`. Because refinery's own OCR
  checkpoint is content-hash-keyed, calling `refine()` on an unchanged PDF is cheap (no OCR)
  — so "always call refine() and let it decide" is also acceptable and simpler.
- **`--force-refine`** — pass `force_parse=True` (or delete `work_dir/parse_cache/`) to
  re-run OCR even when a checkpoint exists.
- **`--no-refine` / `--raw`** — skip refinery, use the native pypdf `aadd` path.

Suggested precedence per file: `--no-refine` → pypdf; else `refine(pdf,
source=source_meta(doc_papis), force_parse=--force-refine)` (§4c) → `aadd_texts`.

**Indexing many papers at once:** when `pask index` processes a whole library (not a single
file), drive refinery with **`refine_many`** (§4b) rather than calling `refine` in a loop —
it overlaps each paper's network stages with the next paper's OCR and streams results as they
finish, so indexing (`aadd_texts`) of an early paper runs while later papers are still being
refined. Shape:

```python
pdfs, sources = zip(*[(p, source_meta(meta)) for p, meta in to_index])   # aligned lists (§4c)
for result in paper_refinery.refine_many(pdfs, sources=list(sources), force_parse=force_refine):
    await _index_result(result, ...)    # the §6 converter, per streamed result
```

Per-file `refine()` remains correct for the single-file `pask index <one paper>` path; use
`refine_many` only when there's a batch to pipeline.

## 8. What NOT to do

- **Don't make paper-refinery import paper-qa.** All paper-qa knowledge stays here.
- **Don't reconcile in-text citekeys with papis refs** (the shelved "registration" idea).
  paper-qa doesn't use them; it's wasted effort for retrieval.
- **Don't change how sources are attributed** — `PapisProvider` / `ref` / DocDetails flow is
  unchanged. You are only swapping *how the text chunks get in*.
- **Don't let a refine failure fail the index** — fall back to pypdf with a warning.

## 9. Validating the integration

Follow paper-refinery's project rule: verify live, not just via unit tests.

1. Pick one refined library paper; `pask index -f <query-for-it>`.
2. Confirm the index used refinery chunks: sources should carry **page-range names**
   (`… pages 3-4`) and the retrieved text should be clean (equations/figures intact), not
   pypdf glyph soup.
3. `pask "<question answerable from that paper>"` and check the answer cites the right
   `@ref` and the evidence excerpts are the refined chunks.
4. Re-index the same paper: it should **not** re-OCR (refinery checkpoint hit) and produce
   the same chunks.

## 10. Reference — current papis-ask touchpoints

- `papis_ask/main.py::add_file_to_index` — the `aadd(file_path)` call to replace.
- `papis_ask/main.py::update_index_metadata` — DocDetails upgrade via `clients["papis"]`;
  unchanged, but re-check the docname/return-value wiring (§6).
- `papis_ask/main.py::determine_file_status` — mtime staleness; extend for refine-on-index.
- `papis_ask/metadata_provider.py::PapisProvider` — source metadata from `info.yaml`;
  unchanged.
- papis config: `ref-format = {doc[author_list][0][family]}_{doc[year]}` → `smith_2020`,
  already matching refinery's minted `[surname_year]` citekeys; library at
  `~/.local/share/papis/papers`; dedup by `doi`.

---

*Authored as the hand-off from the paper-refinery side, which is complete and frozen: the
public `refine()` / `refine_many()` entry points, the parse-OCR checkpoint,
`--force-parse`/`--from chunk`, and the DOI citation fast-path are all done, tested, and
documented (see paper-refinery's own README for the same contract). Remaining work — Tasks 3
(this converter) and 4 (refine-on-index, single via `refine` + batch via `refine_many`) — is
implemented here in papis-ask. This guide is self-contained: you should not need to read the
paper-refinery source to complete the integration.*
