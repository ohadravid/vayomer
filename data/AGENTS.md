This model uses a local Ollama instance that is always available.

```
from ollama import chat
```

Use `tqdm` for progress bars.

Use `uv` to run, and always use correct imports like `from data_processing import bible_tandem, text_cleanup`.

Use `click` for argparsing.

Use `pytest` for tests.

# Responsibility split for this pipeline:

- Python code should enforce deterministic/mechanical guarantees only:
  data shape, verse ranges, substring checks, token thresholds, dedupe, and file IO.
- LLM should handle semantic judgments:
  whether interaction quality is meaningful, whether speaker/listener are sensible,
  and whether a listener is truly being addressed.
- Do not hardcode semantic world-knowledge lists in Python (for example specific
  listeners like "land"/"earth"); those decisions belong to LLM prompts + validation flow.