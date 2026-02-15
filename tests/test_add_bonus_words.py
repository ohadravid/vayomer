from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_processing import add_bonus_words


def _sample_item() -> Dict:
    return {
        "id": "sample-01-01-01",
        "en": {
            "quote": "And he said unto the midwife, Help this woman now.",
            "riddle": "And he said unto",
            "speaker": "he",
            "listener": "this woman",
        },
        "he": {
            "quote": "ויאמר אל המילדת עזרי לאשה הזאת כעת",
            "riddle": "ויאמר אל",
            "speaker": "הוא",
            "listener": "האשה הזאת",
        },
    }


def test_pick_bonus_words_fallback_when_llm_bad_index(monkeypatch) -> None:
    def fake_candidates(quote: str, riddle: str, lang: str, max_candidates: int = 80, include_stopwords: bool = False) -> List[str]:
        return ["midwife"] if lang == "en" else ["המילדת"]

    def fake_call_llm_json(model: str, payload: Dict, max_attempts: int = 3):
        return {"bonus_en_idx": 999, "bonus_he_idx": 999}, {
            "calls": 1,
            "prompt_tokens": 10,
            "response_tokens": 3,
            "estimated": False,
        }

    monkeypatch.setattr(add_bonus_words, "_candidate_bonus_words", fake_candidates)
    monkeypatch.setattr(add_bonus_words, "_call_llm_json", fake_call_llm_json)

    pair, stats, retries, fail_reason = add_bonus_words._pick_bonus_words(
        model="dummy",
        item=_sample_item(),
        hint_picker=None,
        max_retries=2,
        min_tokens=1,
        max_tokens=2,
    )

    assert pair == ("midwife", "המילדת")
    assert fail_reason == ""
    assert retries and retries[-1].startswith("fallback:")
    assert stats["calls"] == 2


def test_pick_bonus_words_fallback_after_concept_reject(monkeypatch) -> None:
    calls = {"n": 0}

    def fake_candidates(quote: str, riddle: str, lang: str, max_candidates: int = 80, include_stopwords: bool = False) -> List[str]:
        return ["midwife"] if lang == "en" else ["המילדת"]

    def fake_call_llm_json(model: str, payload: Dict, max_attempts: int = 3):
        calls["n"] += 1
        instructions = payload.get("instructions", [])
        first_line = instructions[0] if isinstance(instructions, list) and instructions else ""
        if "selecting one bonus word" in first_line:
            return {"bonus_en_idx": 0, "bonus_he_idx": 0}, {
                "calls": 1,
                "prompt_tokens": 10,
                "response_tokens": 3,
                "estimated": False,
            }
        if "validating whether two selected bonus words match semantically" in first_line:
            return {"same_concept": False, "reason": "reject"}, {
                "calls": 1,
                "prompt_tokens": 8,
                "response_tokens": 2,
                "estimated": False,
            }
        return {"accept": False, "reason": "reject", "checks": {}}, {
            "calls": 1,
            "prompt_tokens": 8,
            "response_tokens": 2,
            "estimated": False,
        }

    monkeypatch.setattr(add_bonus_words, "_candidate_bonus_words", fake_candidates)
    monkeypatch.setattr(add_bonus_words, "_call_llm_json", fake_call_llm_json)

    pair, stats, retries, fail_reason = add_bonus_words._pick_bonus_words(
        model="dummy",
        item=_sample_item(),
        hint_picker=None,
        max_retries=1,
        min_tokens=1,
        max_tokens=2,
    )

    assert pair == ("midwife", "המילדת")
    assert fail_reason == ""
    assert retries and retries[-1].startswith("fallback:")
    assert stats["calls"] >= 2
    assert calls["n"] >= 2


def test_set_bonus_hint_writes_null_key() -> None:
    item = {"en": {}}
    changed = add_bonus_words._set_bonus_hint(item=item, lang="en", hint=None)
    assert changed is True
    assert "bonus_hint" in item["en"]
    assert item["en"]["bonus_hint"] is None
