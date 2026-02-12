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
- `data_processing/create_quotes.py`: LLM generation + LLM semantic validation/fixing prompts.
- `data_processing/rebuild.py`: file iteration, queueing, output/audit writing, and strict code-side validations.

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
- `--repair-tries 2` LLM repair attempts after validation failures
- `--min-quote-tokens 12` / `--max-riddle-tokens 14` quality thresholds
- `--min-context-tokens 6` require enough non-riddle context in the full quote
- `--limit 10` process only the first N pending chapters (alias for `--limit-chapters`)
- `--force` reprocess existing chapter outputs
