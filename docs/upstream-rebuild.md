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
