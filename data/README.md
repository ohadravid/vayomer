# Data Pipeline

`data/data-proc` is the authoritative staged pipeline for Bible riddles.

It owns the full flow:

1. Bible corpus -> `data/processed/candidate_chapters/*.json`
2. candidate shards -> `data/processed/candidates.jsonl`
3. candidates -> `data/processed/generated/*.json`
4. generated quotes -> `data/processed/character_bank.json`
5. character bank + generated quotes -> `data/processed/generated_options/*.json`

Default local model for all stages: `gemma4:26b`.

## Setup

```bash
uv sync
```

## Sources

The default Bible corpus files are repo-root files:

- `English_Collection.4921q.0.xml`
- `Tanach.xml.zip`

The code uses the tandem Bible loader in `data/data-proc/src/data_proc/utils/`.

## Recommended Tasks

Build candidates:

```bash
task -t data/Taskfile.yaml candidates:build
```

Build quotes:

```bash
task -t data/Taskfile.yaml quotes:build
```

`riddles:build` is kept as an alias for `quotes:build`.

Build the options bank:

```bash
task -t data/Taskfile.yaml options:bank
```

Build options:

```bash
task -t data/Taskfile.yaml options:build
```

Build review packs:

```bash
task -t data/Taskfile.yaml candidates:eval
task -t data/Taskfile.yaml quotes:eval
task -t data/Taskfile.yaml options:eval
```

## Direct CLI

Candidates:

```bash
uv run --project data/data-proc data-proc build-candidates \
  --candidates-out data/processed/candidates.jsonl \
  --shard-dir data/processed/candidate_chapters \
  --issues-log data/processed/candidates_issues.jsonl \
  --model gemma4:26b
```

Quotes:

```bash
uv run --project data/data-proc data-proc build-quotes \
  --candidates data/processed/candidates.jsonl \
  --out-dir data/processed/generated \
  --issues-log data/processed/generated_issues.jsonl \
  --model gemma4:26b
```

Character bank:

```bash
uv run --project data/data-proc data-proc build-character-bank \
  --in-dir data/processed/generated \
  --out-file data/processed/character_bank.json \
  --model gemma4:26b
```

Options:

```bash
uv run --project data/data-proc data-proc build-options \
  --in-dir data/processed/generated \
  --bank-file data/processed/character_bank.json \
  --out-dir data/processed/generated_options \
  --issues-log data/processed/generated_options_issues.jsonl \
  --model gemma4:26b
```

Candidate eval:

```bash
uv run --project data/data-proc data-proc build-candidates-eval \
  --candidates data/processed/candidates.jsonl \
  --shard-dir data/processed/candidate_chapters \
  --out-dir data/processed/candidates_eval \
  --sample-size 24 \
  --seed 32988
```

Quote eval:

```bash
uv run --project data/data-proc data-proc build-quotes-eval \
  --candidates data/processed/candidates.jsonl \
  --out-dir data/processed/quotes_eval \
  --sample-size 24 \
  --seed 32988 \
  --model gemma4:26b
```

Options eval:

```bash
uv run --project data/data-proc data-proc build-options-eval \
  --in-dir data/processed/generated \
  --bank-file data/processed/character_bank.json \
  --out-dir data/processed/options_eval \
  --sample-size 24 \
  --seed 32988 \
  --model gemma4:26b
```

## Resume Behavior

- `build-candidates` resumes at the earliest missing chapter shard and preserves later shard files.
- `build-quotes` resumes in canonical Bible order from the earliest incomplete chapter.
- `build-options` also resumes in canonical Bible order from the earliest incomplete chapter.

Use `--no-resume` to force a fresh pass for a filtered run.

## Eval Artifacts

Each eval command writes:

- `eval_items.json`
- `review.md`

These are meant for prompt iteration and manual review, not app runtime.

## Testing

The test suite mixes:

- deterministic structural tests for ordering, resume, schema, and exact-substring mechanics
- seeded live Ollama tests for prompt-sensitive behavior

Run everything:

```bash
uv run --project data/data-proc pytest -q
```

Run the live slices only:

```bash
uv run --project data/data-proc pytest -q \
  data/data-proc/tests/test_candidates_live.py \
  data/data-proc/tests/test_live_ollama.py \
  data/data-proc/tests/test_options_live.py
```
