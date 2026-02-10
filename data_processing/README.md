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
