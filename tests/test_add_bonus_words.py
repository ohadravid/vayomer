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


class _FakeHintPicker:
    def __init__(
        self,
        *,
        counts: Dict[tuple[str, str], int],
        generic: set[tuple[str, str]] | None = None,
        hintable: set[tuple[str, str]] | None = None,
    ) -> None:
        self._counts = counts
        self._generic = generic or set()
        self._hintable = hintable or set()

    def word_verse_count(self, *, lang: str, word: str) -> int:
        return int(self._counts.get((lang, word), 0))

    def is_generic_bonus_word(self, *, lang: str, word: str) -> bool:
        return (lang, word) in self._generic

    def has_hint_candidates(
        self,
        *,
        lang: str,
        bonus_word: str,
        current_quote: str,
        source: Dict,
        max_candidates: int = 1,
    ) -> bool:
        return (lang, bonus_word) in self._hintable


def test_rank_bonus_candidates_prefers_reusable_non_generic_words() -> None:
    hint_picker = _FakeHintPicker(
        counts={
            ("en", "Shiphrah"): 1,
            ("en", "midwives"): 6,
            ("en", "which"): 2500,
        },
        generic={("en", "which")},
    )

    ranked = add_bonus_words._rank_bonus_candidates(
        ["Shiphrah", "which", "midwives"],
        "en",
        hint_picker,
    )

    assert ranked[0] == "midwives"
    assert ranked[-1] == "Shiphrah"


def test_fallback_bonus_pair_prefers_candidates_with_hint_pool() -> None:
    hint_picker = _FakeHintPicker(
        counts={
            ("en", "Shiphrah"): 1,
            ("en", "women"): 120,
            ("he", "שפרה"): 1,
            ("he", "נשים"): 180,
        },
        hintable={("en", "women"), ("he", "נשים")},
    )
    item = {
        "en": {
            "quote": "And the king spoke to Shiphrah and to women.",
            "riddle": "the king spoke",
            "speaker": "the king",
            "listener": "servants",
        },
        "he": {
            "quote": "ויאמר המלך אל שפרה ואל נשים",
            "riddle": "ויאמר המלך",
            "speaker": "המלך",
            "listener": "עבדים",
        },
        "source": {
            "book_code": "EXO",
            "chapter": 1,
            "quote_verse_start": 1,
            "quote_verse_end": 1,
        },
    }

    pair, reason = add_bonus_words._fallback_bonus_pair(
        item=item,
        candidate_bonus_en=["Shiphrah", "women"],
        candidate_bonus_he=["שפרה", "נשים"],
        min_tokens=1,
        max_tokens=2,
        hint_picker=hint_picker,
    )

    assert pair == ("women", "נשים")
    assert reason == "fallback_cross_lang_aligned"


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


def test_pick_bonus_words_retries_when_llm_pick_has_no_hint_candidates(monkeypatch) -> None:
    def fake_candidates(quote: str, riddle: str, lang: str, max_candidates: int = 80, include_stopwords: bool = False) -> List[str]:
        return ["Shiphrah", "midwives"] if lang == "en" else ["שפרה", "מילדות"]

    def fake_call_llm_json(model: str, payload: Dict, max_attempts: int = 3):
        instructions = payload.get("instructions", [])
        first_line = instructions[0] if isinstance(instructions, list) and instructions else ""
        if "selecting one bonus word" in first_line:
            return {"bonus_en_idx": 0, "bonus_he_idx": 0}, {
                "calls": 1,
                "prompt_tokens": 10,
                "response_tokens": 3,
                "estimated": False,
            }
        return {"same_concept": True, "accept": True, "checks": {"specific": True, "interesting": True, "not_function_word": True}}, {
            "calls": 1,
            "prompt_tokens": 8,
            "response_tokens": 2,
            "estimated": False,
        }

    hint_picker = _FakeHintPicker(
        counts={
            ("en", "Shiphrah"): 1,
            ("en", "midwives"): 6,
            ("he", "שפרה"): 1,
            ("he", "מילדות"): 6,
        },
        hintable={("en", "midwives"), ("he", "מילדות")},
    )

    item = {
        "id": "exodus-01-15-16",
        "en": {
            "quote": "And the king spoke to Shiphrah and to midwives.",
            "riddle": "the king spoke",
            "speaker": "the king",
            "listener": "servants",
        },
        "he": {
            "quote": "ויאמר המלך אל שפרה ואל מילדות",
            "riddle": "ויאמר המלך",
            "speaker": "המלך",
            "listener": "עבדים",
        },
        "source": {
            "book_code": "EXO",
            "chapter": 1,
            "quote_verse_start": 15,
            "quote_verse_end": 16,
        },
    }

    monkeypatch.setattr(add_bonus_words, "_candidate_bonus_words", fake_candidates)
    monkeypatch.setattr(add_bonus_words, "_call_llm_json", fake_call_llm_json)

    pair, stats, retries, fail_reason = add_bonus_words._pick_bonus_words(
        model="dummy",
        item=item,
        hint_picker=hint_picker,
        max_retries=1,
        min_tokens=1,
        max_tokens=2,
    )

    assert pair == ("midwives", "מילדות")
    assert fail_reason == ""
    assert stats["calls"] == 1
    assert any("bonus_en_no_hint_candidates" in note for note in retries)
    assert retries[-1].startswith("fallback:")


def test_set_bonus_hint_writes_null_key() -> None:
    item = {"en": {}}
    changed = add_bonus_words._set_bonus_hint(item=item, lang="en", hint=None)
    assert changed is True
    assert "bonus_hint" in item["en"]
    assert item["en"]["bonus_hint"] is None
