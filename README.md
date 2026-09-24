# Papis-ask

This plugin for [Papis](https://github.com/papis/papis) integrates [paper-qa](https://github.com/Future-House/paper-qa) to allow you to use LLMs to ask questions about your library. Use it to search for documents or have it explain things to you. You can set it up to use a variety of local and online models. It is inspired by [isaksamsten](https://github.com/isaksamsten)'s excellent work on [papisqa](https://github.com/isaksamsten/papisqa).

Papis-ask is under active development. Expect bugs and changes.

## Installation

### Using pipx

Install papis (if not already installed):

```bash
$ pipx install papis
```

Then inject `papis-ask`:

```bash
$ pipx inject papis git+https://github.com/jghauser/papis-ask
```

### Using Nix Flake

Nix users can use the flake to create an overlay for Papis that includes Papis-ask.

<details>
  <summary>Nix configuration example</summary>

```nix
{
  description = "Papis-ask installation example";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";

    papis-ask = {
      url = "github:jghauser/papis-ask"; # Replace with actual repository
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, papis-ask, ... }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs {
        inherit system;
        overlays = [
          (final: prev: {
            papis = prev.papis.overrideAttrs (oldAttrs: {
              propagatedBuildInputs = (oldAttrs.propagatedBuildInputs or []) ++ [
                papis-ask.packages.${system}.default
              ];
            });
          })
        ];
      };
    in {
      # NixOS system configuration
      nixosConfigurations.mySystem = nixpkgs.lib.nixosSystem {
        inherit system;
        modules = [
          ({ pkgs, ... }: {
            environment.systemPackages = [
              pkgs.papis
            ];
          })
        ];
      };
    };
}
```

</details>

## Configuration

Paper-qa (and hence Papis-ask) uses [liteLLM](https://github.com/BerriAI/litellm) for model access, which supports various local and remote LLM providers. You'll need to set up your models and API keys following the [liteLLM documentation](https://docs.litellm.ai/docs).

Configure the following settings in your Papis configuration file:

```
ask-llm = "your-preferred-llm-model"
ask-summary-llm = "your-preferred-summary-llm-model"
ask-embedding = "your-preferred-embedding-model"
ask-enrichment-llm = "your-preferred-enrichment-llm-model"
```

The enrichment LLM will be used to process images. This can be turned off with the following setting:

```
ask-multimodal = False
```

Additionally, you can set the defaults for the plugin's arguments. See the section on commands below for further information on what these do.

```
ask-evidence-k = 10
ask-max-sources = 5
ask-answer-length = "about 200 words, but can be longer"
ask-context = True
ask-excerpt = False
```

## Preparation

Papis-ask assumes various things about the state of your library: it assumes that your pdf files contain text and that metadata is complete and correct. There are various scripts in the `contrib` folder that can help you making sure the library is in a good state. Create backups and use at your own risk.

You might want to use the `ocrpdf.py` script to fix all PDFs that are missing embedded texts or whose embedded text is garbage. The script inspects the text of every page, and OCRs the files it classifies as broken (with backups under `ocr_backups/`). Use `--dry-run` to only report problematic PDFs without modifying them. Do check the results -- by comparing the backups with the newly created PDFs -- as PDFs can be broken in old sorts of unique ways that the scripts may not handle correctly.

To compare models before changing `[ask] llm` or `summary-llm`, `contrib/eval_questions.py` answers the fixed question set in `contrib/eval_questions.json` with two papis configs against the same index, saves both sets of answers, and summarises evidence scores and cited pages per question. It makes paid calls; judging faithfulness still means reading the answers against the cited pages.

The `editor-author-list.py` and `fix-months.sh` scripts help fix the metadata in your `info.yaml` files. The first creates `author_list` and `editor_list` fields from `author` and `editor` fields, respectively. The second converts the `month` fields to an integer. Additionally, I suggest to use `papis doctor` to make sure the library doesn't contain any errors. Files will be indexed even if metadata is missing or false, but such mistakes might impact response quality.

## Commands

### Indexing your library

Before querying, you need to index your library:

```bash
$ papis ask index
```

Note that this can take a long time if you're indexing your whole library. Progress is checkpointed every 25 documents and saved when the command exits (including on Ctrl-C), so it's possible to interrupt the command and continue later.

You can also index specific documents. In this personal fork, unmatched documents
remain indexed, including when using `--force` with a query. Entries removed from
the Papis library are still pruned:

```bash
$ papis ask index "author:einstein"
```

Use the `--force` or `-f` flag to regenerate the entire index:

```bash
$ papis ask index --force
```

### Querying your library

Ask questions about your library:

```bash
$ papis ask "What is the relationship between X and Y?"
```

Control the output format and level of detail:

```bash
$ papis ask "My question" --context/no-context    # Show context for each source (default: True)
$ papis ask "My question" --excerpt/no-excerpt    # Show context with excerpts (default: False)
$ papis ask "My question" --output markdown       # Output format, one of terminal/markdown/json (default: terminal)
$ papis ask "My question" --answer-length short   # Length of answer (default: "about 200 words, but can be longer")
$ papis ask "My question" --evidence-k 20         # Retrieve 20 pieces of evidence (default: 10)
$ papis ask "My question" --max-sources 10        # Use up to 10 sources in the answer (default: 5)
```

Restrict an answer to part of the library with `--scope`/`-s`, which takes any
papis query, including `AND` (also implied between terms), `OR`, `NOT` and
parentheses. Values match as unanchored, case-insensitive regexes, so `tags:steer`
matches `llm-steering` and `ref:^X$` is exact. Repeating `-s` is the same as
joining the queries with `OR`:

```bash
$ papis ask "What is the costate?" -s "tags:control-theory"
$ papis ask "My question" -s "tags:llm-steering OR tags:agent-safety"
$ papis ask "My question" -s "tags:book AND NOT tags:cpp"
$ papis ask "My question" -s "author:zuazua year:2026"
```

Scoping reuses the stored embeddings of the matching documents (including their
notes), so it adds no embedding cost. Matching documents that are not indexed
yet are skipped; if none are indexed, the command stops and says so.

## Troubleshooting

### Papis library cache

Make sure your papis library's cache is up-to-date. Run `papis cache reset` when in doubt.

### Semantic Scholar

Papis-ask queries Semantic Scholar for some metadata. This service is quite strictly rate-limited. Getting your own API key can help, though unfortunately there seems to be a long waitlist. Otherwise, rerunning the command is the only option at the moment.

## Personal fork additions

This branch keeps upstream's atomic pickle storage, float32 embeddings, checkpointing,
and enrichment configuration. See [the personal branch notes](docs/upstream-rebuild.md)
for storage, compatibility, and development details.

Answers distinguish personal-note evidence from publication excerpts. Under
`[ask]`, `evidence-score-cutoff = 3` excludes weak summaries from the answer
model (valid range 0–10; lower it to admit more marginal evidence). Retrieved
summaries remain inspectable, but the References list contains only sources
actually cited by the answer, with duplicate source/page entries collapsed.

Grouped citations and `chunk N` note references are formatted as Papis refs.
Terminal/Markdown summaries hide the model's trailing score because it is already
displayed separately; JSON also exposes it as a separate field. JSON answer text
remains the original PaperQA answer, retaining LaTeX and its original references.

HTML indexing removes explicitly marked navigation, forms and site landmarks;
it does not guess from arbitrary CSS classes or drop scientific sidebars. This
applies to newly indexed/reindexed HTML only. Existing indexes are not silently
rebuilt when installing these query/output changes.

- Fresh `paper.chunks.json` manifests supply refinery's prebuilt chunks; see
  [the refinery integration](docs/paper-refinery-integration.md). Missing or stale
  manifests fall back to PaperQA parsing. `index --no-refine` (alias `--raw`) skips
  manifests; use `--force` to replace already-indexed chunks.
- `ask-chunk-chars = 5000` and `ask-overlap = 250` control PaperQA parsing and personal
  notes, in characters. Refinery manifests already define their own boundaries and
  ignore these settings. Size must be positive and overlap must be smaller than size.
- Notes registered under Papis's `notes:` field are indexed after removing fenced
  quotes and HTML comments. Markdown under `files:` is ignored. Note citations are
  labeled `(note)` in terminal and Markdown output.
- `--math` / `--no-math` and `ask-render-math` control terminal math rendering through
  the sibling `mathunicode` project. Markdown and JSON retain LaTeX.
- Evidence references use chunk page information when available. Unknown pages are
  omitted in terminal/Markdown and represented as `null` in JSON, rather than using
  the article's bibliographic page range.
- Indexing detects changes to the embedding model, refinery manifest, and applicable
  chunk settings. Known mismatches trigger re-embedding, which may cost API quota.
  Older entries without settings stamps are not rebuilt on a guess.

Upstream leaves multimodal enrichment enabled by default. For this refinery-based
workflow, set `multimodal = False` under `[ask]` (equivalently `ask-multimodal = False`
under `[settings]`) to disable PaperQA's separate image enrichment during fallback
parsing. This is a user configuration choice, not a hardcoded override.

The personal dependency `mathunicode` must be available. In the normal sibling
checkout layout, `uv` uses `../mathunicode`; an isolated worktree can use the existing
project Python environment directly for tests.

## Screenshots

![2025-03-16T19:37:19,390782526+01:00](https://github.com/user-attachments/assets/6ff8e847-b0ca-45e0-a3f2-066d92b7f674)
