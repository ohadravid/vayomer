from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_processing import postprocess_hard_options


def _candidate(
    *,
    label: str,
    quote: str,
    lang: str = "en",
    item_id: str = "item-x",
) -> postprocess_hard_options.Candidate:
    return postprocess_hard_options.Candidate(
        label=label,
        label_norm=postprocess_hard_options._normalize_label(label, lang),
        quote=quote,
        riddle="sample riddle",
        item_id=item_id,
        book="Genesis",
        chapter=1,
        verse_start=1,
        verse_end=1,
        label_tokens=tuple(postprocess_hard_options.text_cleanup.tokenize_for_match(label, lang)),
        quote_tokens=tuple(postprocess_hard_options.text_cleanup.tokenize_for_match(quote, lang)),
    )


def test_select_options_for_field_uses_llm_and_fallback(monkeypatch) -> None:
    calls: List[Tuple[str, Dict]] = []

    def fake_call_llm_json(model: str, payload: Dict, max_attempts: int = 3):
        calls.append((model, payload))
        instructions = payload.get("instructions", [])
        first_line = instructions[0] if isinstance(instructions, list) and instructions else ""

        if "selecting multiple-choice distractor options" in first_line:
            # Return only partial picks so fallback must fill.
            return {"regular_add": [0], "hard_add": [1]}, {
                "calls": 1,
                "prompt_tokens": 10,
                "response_tokens": 4,
                "estimated": False,
            }

        # Validation keeps everything.
        return {"drop_regular": [], "drop_hard": []}, {
            "calls": 1,
            "prompt_tokens": 8,
            "response_tokens": 3,
            "estimated": False,
        }

    monkeypatch.setattr(postprocess_hard_options, "_call_llm_json", fake_call_llm_json)

    candidates = [
        _candidate(label="Jacob", quote="And Jacob said unto Joseph, I am thy father."),
        _candidate(label="Joseph", quote="And Joseph said unto Jacob, Hear me now."),
        _candidate(label="Isaac", quote="And Isaac said unto Abraham, My father."),
        _candidate(label="Abraham", quote="And Abraham said unto Sarah, Say now."),
        _candidate(label="Pharaoh", quote="And Pharaoh said unto Moses, Go now."),
        _candidate(label="Moses", quote="And Moses said unto Pharaoh, Let my people go."),
    ]

    regular, hard, stats, notes = postprocess_hard_options._select_options_for_field(
        model="dummy-model",
        skip_llm=False,
        lang="en",
        field="speaker",
        item_id="genesis-01-01-01",
        answer="the LORD",
        target_quote="And the LORD said unto Abram, Get thee out.",
        target_riddle="Get thee out",
        candidates=candidates,
        option_count=4,
        sample_size=6,
        max_rounds=1,
        llm_retries=1,
    )

    assert len(regular) == 4
    assert len(hard) == 4
    assert "the LORD" not in regular
    assert "the LORD" not in hard
    assert stats["calls"] == 2
    assert calls
    assert isinstance(notes, list)


def test_build_output_item_shapes_fields_with_skip_llm() -> None:
    pools = {
        ("en", "speaker"): [
            _candidate(label="Jacob", quote="Jacob said unto Joseph."),
            _candidate(label="Joseph", quote="Joseph said unto Jacob."),
            _candidate(label="Isaac", quote="Isaac said unto Abraham."),
            _candidate(label="Abraham", quote="Abraham said unto Sarah."),
            _candidate(label="Moses", quote="Moses said unto Pharaoh."),
        ],
        ("en", "listener"): [
            _candidate(label="Jacob", quote="And Joseph said unto Jacob."),
            _candidate(label="Joseph", quote="And Jacob said unto Joseph."),
            _candidate(label="Sarah", quote="And Abraham said unto Sarah."),
            _candidate(label="Pharaoh", quote="And Moses said unto Pharaoh."),
            _candidate(label="Aaron", quote="And Moses said unto Aaron."),
        ],
        ("he", "speaker"): [
            _candidate(lang="he", label="יעקב", quote="ויאמר יעקב אל יוסף"),
            _candidate(lang="he", label="יוסף", quote="ויאמר יוסף אל יעקב"),
            _candidate(lang="he", label="יצחק", quote="ויאמר יצחק אל אברהם"),
            _candidate(lang="he", label="אברהם", quote="ויאמר אברהם אל שרה"),
            _candidate(lang="he", label="משה", quote="ויאמר משה אל פרעה"),
        ],
        ("he", "listener"): [
            _candidate(lang="he", label="יעקב", quote="ויאמר יוסף אל יעקב"),
            _candidate(lang="he", label="יוסף", quote="ויאמר יעקב אל יוסף"),
            _candidate(lang="he", label="שרה", quote="ויאמר אברהם אל שרה"),
            _candidate(lang="he", label="פרעה", quote="ויאמר משה אל פרעה"),
            _candidate(lang="he", label="אהרן", quote="ויאמר משה אל אהרן"),
        ],
    }

    item = {
        "id": "genesis-12-01-01",
        "en": {
            "quote": "And the LORD said unto Abram, Get thee out.",
            "riddle": "Get thee out",
            "speaker": "the LORD",
            "listener": "Abram",
        },
        "he": {
            "quote": "ויאמר יהוה אל אברם לך לך",
            "riddle": "לך לך",
            "speaker": "יהוה",
            "listener": "אברם",
        },
    }

    out_item, stats, issues = postprocess_hard_options._build_output_item(
        item=item,
        pools=pools,
        model="dummy-model",
        skip_llm=True,
        option_count=4,
        sample_size=4,
        max_rounds=0,
        llm_retries=1,
    )

    assert out_item["id"] == "genesis-12-01-01"
    for lang in ("en", "he"):
        assert "options" in out_item[lang]
        assert "hard_difficulty_options" in out_item[lang]
        assert len(out_item[lang]["options"]["speaker"]) == 4
        assert len(out_item[lang]["options"]["listener"]) == 4
        assert len(out_item[lang]["hard_difficulty_options"]["speaker"]) == 4
        assert len(out_item[lang]["hard_difficulty_options"]["listener"]) == 4

    assert stats["calls"] == 0
    assert isinstance(issues, list)

