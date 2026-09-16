# Personal papis-ask development

This fork layers refinery ingestion, personal notes, character chunk settings,
terminal math, evidence page reporting, and indexing protections on upstream.
Read `docs/upstream-rebuild.md` for the branch/storage transition and
`docs/paper-refinery-integration.md` for the ingestion contract.

## Runtime and tests

- `papis-ask` is an editable dependency of the uv-managed `papis` tool. The checkout
  at `/home/farhad/projects/papis-ask` is the live code. Use a separate worktree to
  test alternate branches without changing the active installation.
- Reuse the project's `.venv`; do not install tests into the uv tool environment.
  From a worktree, run `/home/farhad/projects/papis-ask/.venv/bin/python -m pytest`.
  Running `python -m pytest` from the worktree ensures its code takes precedence
  over the editable install. `LITELLM_LOCAL_MODEL_COST_MAP=True` prevents the
  optional remote pricing-map fetch during offline checks.
- Tests use synthetic documents and model doubles. Check the actual CLI indexing
  path, pickle reload, repeat indexing, and retrieval without making model calls.
- The `pask` wrapper refines missing/stale PDFs before indexing. Avoid it during
  storage tests; use the plugin directly with an isolated library.
- The live embedding model is configured under `[ask]`. Re-embedding can consume
  paid quota. Do not use a whole-library forced rebuild for routine validation.
- Set `[ask] multimodal = False` for the personal refinery workflow. The code
  deliberately retains upstream's configurable multimodal/enrichment handling.
- `mathunicode` is a sibling local project, not a PyPI dependency. Both editables
  must be retained if reinstalling the papis tool:
  `uv tool install --force papis --with-editable /home/farhad/projects/papis-ask --with-editable /home/farhad/projects/mathunicode`.

## Storage and invariants

- Use upstream's pickle index, atomic replacement, float32 embeddings, and
  checkpoints. Do not restore runtime per-paper JSON persistence.
- Never point the old sidecar branch at the new active pickle: its automatic
  reverse migration could replace sidecar backups.
- Scoped indexing updates selected papers while preserving unmatched papers.
  Existence checks cover the full library. Full-library force rebuilds remain
  available; scoped force rebuilds keep unrelated entries.
- Preserve upstream's error handling for metadata services and missing author
  fields, plus the last-document check when deleting a shared docname.
- Refinery belongs only at the JSON manifest boundary. Do not import it or launch
  it from the plugin. Notes use Papis's `notes:` field, never arbitrary `.md` files.
- Config-change detection remains personal; do not silently change its rebuild
  policy while updating unrelated features.

## History

Keep personal features in focused commits above upstream. The citation-recognition
fix is separately proposed in upstream PR #3. No other upstream publication is
implied by local personal-branch work.

Never add `Co-Authored-By` or AI-attribution trailers to commits or PRs.
