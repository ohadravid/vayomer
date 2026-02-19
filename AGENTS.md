# Data Processing Notes

- Use `uv` for all Python commands (never call `python` directly without `uv run`).
- Prefer Taskfiles for runs:
  - root: `Taskfile.yml`
  - data pipeline: `data/Taskfile.yaml`

## Pipeline intent

- Python should enforce deterministic checks (shape, ranges, token rules, dedupe, file IO).
- LLM should handle semantic judgment (speaker/listener validity, option plausibility, bonus quality, hint choice).
- Keep prompts strict-json and retry on parse failures.
- LLM usage is mandatory in development runs for postprocessing; do not run no-LLM/skip-LLM modes.
- For quick checks, use a smaller model (for example `gemma3:4b`) instead of disabling LLM.

## Bible sources

- Source index + canonical mappings are in `data_processing/bible_sources.py`.
- Default corpus files:
  - English: `English_Collection.4921q.0.xml`
  - Hebrew: `Tanach.xml.zip`
- Bonus hint lookup uses these via `data_processing/bonus_hint_picker.py`.

## Current postprocess entrypoint

- Combined postprocess (options + bonus + hint, no hard options):
  - `data_processing/postprocess_options_with_bonus.py`
