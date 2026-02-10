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

Fix mode (applies LLM-suggested quote-span expansion for resolvable pronoun cases):

```bash
uv run python3 data_processing/postprocess_speaker_listener.py data/quotes --mode fix --out-dir data/quotes_expanded --model gemma3:27b
```

Useful flags:

- `--force` reprocess files even if audit/fix outputs already exist
- `--limit-files 50` process only first N files
- `--llm-all` run LLM audit for every item (slower, more exhaustive)
