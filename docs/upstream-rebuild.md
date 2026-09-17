# Personal branch rebuild

The September 2026 rebuild starts at upstream `b51f349`, includes citation fix
`b338e53` (upstream PR #3), then adds personal features in focused commits.
`backup/personal-before-upstream-2026-09-16` preserves the previous branch at
`3da3e26`.

## Decisions

- Keep chunk configuration personal and small; refinery itself ignores it.
- Keep refinery, notes, math rendering, evidence page formatting, scoped-index
  protection, and embedding/chunk-setting invalidation personal.
- Adopt upstream's atomic pickle writes, float32 vectors, periodic checkpointing,
  metadata-service error handling, duplicate-name deletion guard, author handling,
  multimodal controls, OCR tools, and dependency updates.
- Remove the local OpenAI embedding-format workaround and hardcoded multimodal
  override. Configure `[ask] multimodal = False` for the refinery workflow.
- Defer upstream issues/PRs about scoped indexing and page reporting. No new
  publication beyond the existing citation fix is part of this rebuild.

## Index storage

The personal branch uses upstream's pickle index directly. New indexes are
built through normal indexing and embedding, which can incur API charges.
No sidecar-conversion utility is maintained in this branch.

For the live `papers` library, upstream's target is
`~/.cache/papis/papers.qa`. Keep the existing `.qa.bak` and all JSON sidecars as
rollback material. Activate the rebuilt code when installing this index. Do not
run the previous personal branch while the new active `.qa` exists: the old
branch automatically migrates pickles back into sidecars. For rollback, first
move the new pickle aside, then return to the backup branch. Its sidecars reflect
the state before this migration; later indexing work would need reconciliation.

## Verification on the existing index

An isolated migration of the current library preserved 16 documents and 1,081
chunks. All document metadata and chunk text matched the old loader. Float32
rounding introduced at most `7.45e-9` absolute vector error. Ten offline PaperQA
retrieval probes using stored vectors returned identical ordered top-10 results.
These validate retrieval consistency; they are not a cloud answer-quality test.

The original validation suite passed both with the project environment (PaperQA 2026.3.18)
and with the live Papis dependency set (PaperQA 2026.8.12, Papis 0.16.1). The latter
borrows only the test tooling from the project environment, without installing
packages into the uv tool environment. Retrieval consistency also passes with
the live dependency versions.

After the rebuild, both environments were refreshed to current compatible stable
dependencies. Python 3.13 is selected by `.python-version` because LiteLLM's
installed distribution requires Python <3.14. Latest PaperQA on PyPI at validation
time was 2026.8.12. Package versions are not capped to that release; future updates
use `uv sync --extra test --upgrade` and `uv tool upgrade papis --python 3.13`,
followed by the tests and `uv pip check`. The Python baseline is >=3.12 to match
the personal mathunicode dependency. A passing test suite alone does not override
dependency compatibility metadata.

Final validation uses Python 3.13.15, PaperQA 2026.8.12, and Papis 0.16.1 in both
environments. All 105 tests pass in each environment; `uv pip check` reports no
incompatible packages. The live pickle and the original sidecars also pass the
same content/vector/retrieval comparison under this final dependency set.

The editable checkout was initially activated on `personal-next`, and the live
`~/.cache/papis/papers.qa` contains the verified migration. The `[ask]` setting
`multimodal = False` was added to the symlinked Papis config in the dotfiles repo.
At that point the old `personal` branch, named backup branch, sidecars, and `.qa.bak` remained.
At initial activation, the personal rebuild had not yet been pushed. Only the
citation fix is proposed upstream.

Measured in separate processes using the same environment and data, over five
loads after imports (warm filesystem cache):

| Measurement | JSON sidecars | Float32 pickle |
| --- | ---: | ---: |
| Storage | 50.3 MB | 18.0 MB |
| Median load | 0.790 s | 0.010 s |
| Peak process RSS | 396 MiB | 258 MiB |

The old implementation rewrote all sidecars after each document. Upstream saves
after every 25 processed files and on exit. Both load the whole library into RAM.
Sidecars could support incremental writes and per-paper recovery, but the old
implementation did not provide incremental writes. The pickle is the simpler,
smaller and faster choice for this measured workload, with less upstream divergence.

## Summary math follow-up (`fix/summary-math`)

Live validation found that PaperQA 2026.8.12's `llm_parse_json` repair corrupts
already-valid JSON containing LaTeX backslashes. For example, a correctly encoded
`$\nabla \cdot \mathbf{a}$` no longer round-trips. Some generated summaries also
omit math delimiters, which the terminal's span-only converter needs.

Use PaperQA's supported `prompts.use_json = False` summary mode, keeping its
existing summary instructions and relevance-score extraction. A short prefix
asks for plain text, literal LaTeX backslashes, and `$...$` / `$$...$$` delimiters.
This bypasses the defective parser without patching PaperQA or changing models.
The native plain-text path retains the final scoring line; the output layer now
hides blank-separated or labelled score trailers and displays the score separately.
Delimiter compliance remains
model-dependent; the renderer does not guess equations from arbitrary prose.

This setting controls the internal evidence-summary format, not `--output json`:
JSON and Markdown exports still preserve LaTeX. Terminal Unicode conversion stays
optional. No reindexing, data migration, dependency reinstall, or model upgrade is
required. Revisit this workaround once PaperQA fixes its parser; reverting the
mode must include tests for exact LaTeX round-tripping.

Regression coverage runs the real PaperQA evidence path with a synthetic model,
checking equations, relevance scores and irrelevant-evidence filtering. Output
tests cover terminal conversion, `--no-math`, and LaTeX-preserving exports.
Before the migration-only tests were retired, all 114 tests passed in both the
project and live Papis environments. A live Aris
query using the unchanged summary model produced four summaries with intact
LaTeX; replaying each through the terminal converter left no raw commands or
math delimiters. This is formatting validation, not a model-quality benchmark.
A second live question rendered summary equations directly in the terminal; the
answer model timed out twice before succeeding on retry.

## Promotion to `personal` (2026-09-17)

The rebuilt branch plus the summary-math fix replaces the old local `personal`
branch. The live editable checkout now uses `personal`; the old history remains
at `backup/personal-before-upstream-2026-09-16`. `personal-next` remains as the
pre-summary-fix checkpoint. The rebuilt `personal` is also published to the fork;
upstream and its citation PR remain separate.

The one-time migration commit was subsequently removed from `personal` history,
including its helper and six dedicated tests. The current 108-test suite passes
in both the project and live Papis environments. Runtime code and the existing
index are unchanged; no re-embedding is needed for this history cleanup.

## Answer-quality follow-up

Grouped citations and exact `chunk N` citations now resolve to Papis references,
including `(note)` labels. A group containing unknown identifiers or prose is
left intact rather than partially rewritten. Bibliographies use PaperQA's raw
citation IDs to list only cited sources and deduplicate identical source/pages;
all retrieved context summaries remain available for inspection.

The answer model receives explicit note/publication provenance on copies of
contexts, without changing stored text, embeddings, or citation IDs. Application
source metadata is kept outside the tagged summary text: a live smoke test showed
that prose labels could otherwise be mistaken for a separate note or author claim.
The prompt explicitly identifies the labels as application metadata. Upstream
still handles ordering and source limits. `evidence-score-cutoff` defaults to 3
(configurable 0–10), excluding weak evidence from synthesis. With no qualifying
evidence, PaperQA declines without calling the answer model. Stricter prompts
discourage unsupported background and whole-publication claims based on notes
or excerpts. This reduces the observed failures, not a guarantee of correctness.

Invalid output formats, nonpositive counts, and evidence/source count conflicts
now fail with CLI usage errors before any model call. HTML cleaning is limited
to explicitly marked site chrome and applies only on future indexing/reindexing.
The existing live index has not been modified by this follow-up.

Validation: 144 tests pass in the project and live-tool dependency environments.
Four live questions covered math, cross-paper synthesis, personal notes and an
unsupported premise (about 6–21 seconds, no API errors). Grouped and note citations
rendered correctly; the note answer explicitly declined to infer the original
paper's contents, and the unsupported question stopped at insufficient evidence.
The index checksum was unchanged. Model output remains probabilistic; these are
focused regression checks, not a general factual-accuracy benchmark.
