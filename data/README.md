# Data Pipeline README

This folder contains generated artifacts for the Bible quote pipeline.

## Main Output Folders

- `data/rebuilt_quotes`: rebuilt EN/HE quote+riddle items from `data_processing/rebuild.py`.
- `data/rebuilt_quotes_audit`: per-chapter rebuild audit output.
- `data/rebuilt_quotes_bonus`: rebuilt quotes after bonus-word pass.
- `data/rebuilt_quotes_options`: per-chapter `*-options.json` files with item-level `options` + `hard_difficulty_options`.
- `data/rebuilt_quotes_bonus_issues.jsonl`: issues from bonus/hint post-processing.

## End-to-End Flow

1. Rebuild base quotes:

```bash
uv run python3 data_processing/rebuild.py --model gemma3:27b --mode end2end --out-dir data/rebuilt_quotes --audit-dir data/rebuilt_quotes_audit
```

2. Add bonus + bonus_hint:

```bash
uv run python3 data_processing/add_bonus_words.py --model gemma3:4b --in-dir data/rebuilt_quotes --out-dir data/rebuilt_quotes_bonus
```

Higher-quality variant (recommended for final outputs):

```bash
uv run python3 data_processing/add_bonus_words.py --model gemma3:4b --bonus-model gemma3:27b --hint-model gemma3:27b --in-dir data/rebuilt_quotes --out-dir data/rebuilt_quotes_bonus
```

### Bonus Hint Behavior

- `en.bonus_hint` and `he.bonus_hint` are selected independently from each language's `bonus` word.
- Candidate hint quotes are searched across the full Bible (default limit: 10 per language).
- The LLM picks one candidate quote + source (`book/chapter/start/end`).
- If no suitable different quote exists, `bonus_hint` is written as `null`.
- Bonus picks are also filtered by Bible-wide token frequency to reduce generic/common words.

## Important Note About Existing Files

If you generated `data/rebuilt_quotes_bonus` before the hint feature landed, those files will not have `bonus_hint`.
Re-run the bonus pass to backfill:

```bash
uv run python3 data_processing/add_bonus_words.py --model gemma3:4b --in-dir data/rebuilt_quotes --out-dir data/rebuilt_quotes_bonus --force
```

## Model + Runtime Notes (Observed On 2026-02-15)

Machine-local observations from current workspace runs:

- `gemma3:4b`:
  - Fastest/stablest for long batches.
  - `add_bonus_words` on `EXO 1-10` with retries set to 1 took about 6 minutes.
- `gemma3:27b`:
  - Better quality potential, but some calls can stall on long runs in this workflow.
  - Use for rebuild if needed; for bonus/hints prefer smaller model unless you can monitor.
- `gpt-oss:20b`:
  - Available locally; expected to be between `4b` and `27b` in speed/cost.
  - Not benchmarked in this session.

For reliable unattended runs, start with `gemma3:4b`, then re-run difficult subsets with a larger model only if needed.

## Taskfile Shortcuts

From repo root:

```bash
task data:rebuild:gen-smoke
task data:rebuild:full
task data:bonus:exo1-10
task data:bonus:full
task data:bonus:stats
```
