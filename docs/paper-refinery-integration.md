# Refinery and personal notes

Papis-ask consumes `paper.chunks.json` beside `paper.pdf`. Refinery owns the
manifest and its chunk boundaries; papis-ask owns embedding, metadata and retrieval.
There is no Python dependency on refinery and no refinery subprocess in the plugin.

## Refinery input

Only PDFs are eligible. A same-stem HTML file must never consume the PDF manifest.
The manifest must be readable, nonempty, and at least as new as its PDF. Explicit
schema versions other than `1` are rejected; an absent version is accepted for old
manifests. A missing, stale or invalid manifest falls back to PaperQA with a warning.

Each chunk provides `index`, `text`, and optional `page_start` / `page_end`.
Papis-ask constructs PaperQA `Text` objects and calls `aadd_texts()`. It retains the
docname assigned by PaperQA after deduplication. PDF page locations are encoded in
chunk names for retrieval and personal reference formatting.

`papis ask index --no-refine` (alias `--raw`) bypasses the manifest reader. Add
`--force` to replace existing chunks; the flag alone does not invalidate the index.

The machine's `pask` shell wrapper is a separate layer: it refines PDFs with missing
or stale manifests before invoking the plugin. Its `--no-refine` / `--raw` option
suppresses that step. For controlled tests, invoke the plugin directly rather than
the wrapper. Do not run refinery just to test index storage: OCR and enrichment can
make paid requests.

## Notes and fallback chunking

Notes are discovered through `notes:`, not Markdown entries under `files:`. This
avoids indexing refinery's generated Markdown as a duplicate of the paper. Notes
which have not been created are skipped; `type: note` entries with misplaced
Markdown files get a warning.

Quote blocks delimited by `<!--quote-->` / `<!--/quote-->` and other HTML comments
are stripped. An unclosed quote fence preserves its text. Notes consisting only
of headings or quotes are not embedded. Prose is chunked using the same character
size and overlap settings as PaperQA fallback parsing. Refinery chunk boundaries
are never changed by these settings.

## Persistence and invalidation

Both ingestion paths produce ordinary PaperQA `Docs`, saved by upstream's atomic
float32 pickle writer. There is no runtime embeddings-sidecar reader or writer.
Existing pickle indexes are loaded directly; new indexes are built by embedding
the library through the normal indexing command.

Metadata records `embedding_model`, `embedded_at`, `chunk_source`, `chunk_chars`,
and `chunk_overlap`. Metadata-only refreshes preserve these stamps. The model
identifier includes PaperQA's default when the setting is unset.

Indexing detects source-file and manifest mtime changes, embedding-model changes,
and chunk-setting changes for fallback documents and notes. Refinery chunks ignore
character-window changes. Unknown historical stamps do not force re-embedding.
Known changes still rebuild automatically, matching the old personal behavior;
changing this spending policy is deferred.

Source references remain Papis refs. Note sources are marked `(note)` at rendering
time because metadata replacement can overwrite `Doc.citation`. Chunk locations
are PDF page positions, which may differ from printed journal page numbers. No
page is invented for text-only chunks. JSON page fields may be `null`.
