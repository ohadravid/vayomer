# Data Processing

Python pipeline for Bible quote generation and postprocessing using only local Bible sources in this repo:

- `English_Collection.4921q.0.xml`
- `Tanach.xml.zip`

## Setup

```bash
uv sync
```

## 1) Preprocess (chapter -> quote candidates)

Resume-safe by default (skips existing outputs in `data/quote_candidates`):

```bash
uv run python3 data_processing/preprocess_quotes.py --model gemma3:27b
```

Useful flags:

- `--force` reprocess existing chapter outputs
- `--book GEN` or `--book "Genesis"` filter to one book
- `--limit 10` process only the first N chapters

## 2) Postprocess (cleanup + verification)

Resume-safe by default (skips files that already exist in `data/checked_quotes`):

```bash
uv run python3 data_processing/postprocess_quotes.py data/quotes
```

Useful flags:

- `--force` reprocess checked outputs
- `--log-minor` include minor differences in the JSONL log
- `--limit-files 20` process only first N files

## 3) Postprocess speaker/listener audit (LLM)

Report-only mode first (recommended):

```bash
uv run python3 data_processing/postprocess_speaker_listener.py data/quotes --mode report --model gemma3:27b
```

This checks whether speaker/listener values are concrete entities (not pronouns like `them`) and logs findings.

Fix mode writes back into `data/quotes` by default and enforces:

- speaker/listener must be concrete (not pronouns/reporting clauses),
- quote span must be at most 3 verses,
- `riddle` must be a direct substring of `quote` in both English and Hebrew,
- unresolved/unfixable items are dropped.

```bash
uv run python3 data_processing/postprocess_speaker_listener.py data/quotes --mode fix --model gemma3:27b
```

Useful flags:

- `--force` reprocess files even if audit/fix outputs already exist
- `--limit-files 50` process only first N files
- `--llm-all` run LLM audit for every item (slower, more exhaustive)

## 4) Finalize quotes (source-locked + speaker/listener + riddle substring)

Writes final outputs to `data/final_quotes` and audit records to `data/final_quote_audit`.

```bash
uv run python3 data_processing/finalize_quotes.py data/quotes --model gemma3:27b --limit 10
```

Run repeatedly with `--limit 10` to process the next pending files (resume-safe by default).

Useful flags:

- `--force` reprocess files already written to `data/final_quotes`
- `--out-dir data/final_quotes` set a different final output folder
- `--audit-dir data/final_quote_audit` set a different audit output folder

## 5) Rebuild Quotes End-to-End (chapter -> final riddles)

This flow is now split by responsibility:

- `data_processing/bible_sources.py` + `data_processing/bible_tandem.py`: load Bible sources and iterate EN/HE in tandem.
- `data_processing/text_cleanup.py`: mechanical text normalization/cleanup (cantillation stripping, tokenization, substring alignment).
- `data_processing/create_quotes.py`: LLM generation + LLM semantic validation/fixing prompts (Hebrew-first generation, then English alignment).
- `data_processing/rebuild.py`: file iteration, queueing, output/audit writing, strict code-side validations, and mechanical speech-marker candidate fallback.

`rebuild.py` reprocesses the Bible chapter-by-chapter (without reading existing `data/quotes`),
keeps raw source verses in each output item, and asks the LLM for final quote+riddle metadata.

Default mode is `end2end` (single LLM pass per chapter + LLM validator). A `candidates` mode is also available.

```bash
uv run python3 data_processing/rebuild.py --model gemma3:27b --book GEN --chapters 1-5 --mode end2end
```

Compatibility wrapper (same behavior):

```bash
uv run python3 data_processing/rebuild_quotes_end2end.py --model gemma3:27b --book GEN --chapters 1-5 --mode end2end
```

Outputs:

- `data/rebuilt_quotes/*.json` chapter outputs with final items and `raw_quote_source`
- `data/rebuilt_quotes/*-draft.json` chapter inspection files with:
  - `verses` side-by-side EN/HE verse text
  - `candidates` full candidate decision trace (`keep`/`drop`/`skip_*` + reasons/issues)
- `data/rebuilt_quotes_audit/*.json` per-chapter keep/drop audit
- `data/rebuilt_quotes_issues.jsonl` dropped-item details

Useful flags:

- `--max-window 5` max quote verse window (hard-capped to 5)
- `--max-quotes-per-chapter 4` cap output items per chapter
- `--repair-tries 3` LLM repair attempts after validation failures
- `--min-quote-tokens 10` / `--max-riddle-tokens 16` quality thresholds
- `--min-context-tokens 4` require enough non-riddle context in the full quote
- `--require-single-verse-riddle` enforce that each riddle appears in exactly one source verse
- `--limit 10` process only the first N pending chapters (alias for `--limit-chapters`)
- `--force` reprocess existing chapter outputs

## 6) Add bonus words to rebuilt quotes (LLM post-pass)

Adds `en.bonus` + `he.bonus` to each item from rebuilt outputs and writes updated files to a new folder.
Also adds `en.bonus_hint` + `he.bonus_hint`:
- each hint is a different quote containing the selected bonus word,
- candidates are searched across the full Bible (up to 10 per language by default),
- the LLM chooses the most interesting candidate quote,
- if no other quote is found, `bonus_hint` is set to `null`.

It also normalizes item metadata to include:
- `en.book` + `he.book`
- `ref: { "chapter": N, "start": S, "end": E }` (derived from `source`)

```bash
uv run python3 data_processing/add_bonus_words.py --model gemma3:27b --in-dir data/rebuilt_quotes --out-dir data/rebuilt_quotes_bonus
```

Validation is code-side after each LLM pick:

- bonus must be an exact substring in the full quote (EN/HE),
- bonus must not appear in the riddle (EN/HE),
- bonus is rejected if it is too common across the full Bible corpus (generic-frequency guard),
- retry is automatic on invalid picks.
- hint picks are validated to ensure the bonus word appears in the selected hint quote.
- LLM interaction post-filter is applied before bonus generation:
  - filter decisions are made by the LLM (example-driven), including unsolvable pronouns and not-addressed-listener cases,
  - drop items that are not true direct-address speaker->listener interactions,
  - drop items where speaker/listener are not solvable entities,
  - run direction checks (`speaker->listener`, reverse `listener->speaker`, and `other->listener`) and drop inconsistent cases,
  - drop duplicate items that share the same `id`.

Useful flags:

- `--max-retries 6` retries per item when bonus validation fails
- `--min-bonus-tokens 1 --max-bonus-tokens 2` bonus word length bounds
- `--bonus-model gemma3:27b` use a stronger model for bonus word quality (falls back to `--model`)
- `--hint-model gemma3:27b` use a stronger model for hint quote selection (falls back to `--model`)
- `--item-filter-model gemma3:4b` optionally use a faster model just for interaction filtering
- `--hint-max-candidates 10` max other-quote candidates per language before LLM hint selection
- `--hint-retries 3` retries for LLM hint index selection
- `--item-filter-retries 2` retries for LLM interaction keep/drop filter
- `--skip-llm-item-filter` disable LLM interaction filtering
- `--include-draft` process `*-draft.json` files too
- `--overwrite-existing-bonus` replace existing `bonus` values
- `--english-xml English_Collection.4921q.0.xml --hebrew-zip Tanach.xml.zip` override Bible sources used for hint search
- `--book GEN --chapters 1-5` process only selected chapters
- `--force` overwrite already-written files in the output folder

## 7) Build item-level regular + hard option pools (LLM post-pass)

Generates per-item multiple-choice distractor pools for both difficulty levels:

- `en.options` / `he.options` (normal difficulty)
- `en.hard_difficulty_options` / `he.hard_difficulty_options` (hard difficulty)

This script:

- scans non-draft `data/rebuilt_quotes/*.json`,
- builds global candidate pools for speaker/listener in EN+HE, each candidate paired with its full quote,
- iteratively samples candidates for each item and asks the LLM to select regular/hard distractors,
- runs an LLM validation pass to drop weak picks,
- fills missing slots with deterministic Python fallback ranking,
- writes per-chapter outputs to `data/rebuilt_quotes_options/*-options.json`, preserving top-level chapter metadata.

```bash
uv run python3 data_processing/postprocess_hard_options.py --model gemma3:4b --in-dir data/rebuilt_quotes --out-dir data/rebuilt_quotes_options
```

Useful flags:

- `--sample-size 10` candidates per LLM sampling round
- `--max-rounds 6` max LLM rounds per item/field/lang
- `--option-count 4` target count per bucket (`options` and `hard_difficulty_options`)
- `--skip-llm` use deterministic fallback ranking only (fast smoke checks)
- `--book GEN --chapters 1-5` process only selected chapters
- `--force` overwrite already-written output files
