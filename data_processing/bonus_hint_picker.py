#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from ollama import chat

try:
    from data_processing import bible_tandem, text_cleanup
except ModuleNotFoundError:
    import bible_tandem  # type: ignore[no-redef]
    import text_cleanup  # type: ignore[no-redef]

HINT_PICK_PROMPT = [
    "You are choosing one bonus hint quote for a Bible puzzle word.",
    "Return strict JSON only with shape:",
    '{"status":"pick|none","hint_idx":0,"reason":"..."}',
    "Rules:",
    "1) Pick exactly one candidate index from candidates, or status=none if no candidate is suitable.",
    "2) The chosen quote must be different from current_quote.",
    "3) Prefer the most interesting / important / funny / dramatic usage of bonus_word.",
    "4) Keep decisions grounded only in provided candidates and current quote.",
]


@dataclass(frozen=True)
class VerseIndexEntry:
    book_code: str
    book_en: str
    book_he: str
    chapter: int
    verse: int
    quote_en: str
    quote_he: str
    en_tokens: frozenset[str]
    he_tokens: frozenset[str]


def _sanitize_str(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return text_cleanup.clean_text(value)


def _sanitize_int(value: object, fallback: int = 0) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return fallback


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return len(re.findall(r"\S+", text))


def _parse_json_payload(content: str) -> Dict:
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"(\{.*\})", content, re.S)
        if not match:
            raise
        data = json.loads(match.group(1))
    if not isinstance(data, dict):
        raise ValueError("LLM output is not an object")
    return data


def _call_llm_json(model: str, payload: Dict, max_attempts: int = 3) -> Tuple[Dict, Dict[str, int | bool]]:
    total_prompt_tokens = 0
    total_response_tokens = 0
    estimated_calls = 0
    attempts = 0
    last_content = ""

    for attempt in range(1, max_attempts + 1):
        prompt = dict(payload)
        if attempt > 1:
            prompt["strict_json_retry"] = (
                "Previous output was invalid JSON. Return strict JSON only, parsable by json.loads."
            )

        response = chat(
            model=model,
            messages=[{"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}],
            format="json",
            options={"temperature": 0.2, "num_predict": 192},
        )
        attempts += 1
        content = response["message"]["content"].strip()
        last_content = content

        prompt_tokens = response.get("prompt_eval_count")
        response_tokens = response.get("eval_count")
        if prompt_tokens is None or response_tokens is None:
            estimated_calls += 1
            prompt_tokens = _estimate_tokens(json.dumps(prompt, ensure_ascii=False))
            response_tokens = _estimate_tokens(content)

        total_prompt_tokens += int(prompt_tokens)
        total_response_tokens += int(response_tokens)

        try:
            data = _parse_json_payload(content)
            return data, {
                "calls": attempts,
                "prompt_tokens": total_prompt_tokens,
                "response_tokens": total_response_tokens,
                "estimated": bool(estimated_calls > 0),
            }
        except Exception:
            continue

    repaired = ""
    if last_content:
        repaired = re.sub(r",(\s*[}\]])", r"\1", last_content)
    if repaired:
        try:
            data = _parse_json_payload(repaired)
            return data, {
                "calls": attempts,
                "prompt_tokens": total_prompt_tokens,
                "response_tokens": total_response_tokens,
                "estimated": bool(estimated_calls > 0),
            }
        except Exception:
            pass

    return {}, {
        "calls": attempts,
        "prompt_tokens": total_prompt_tokens,
        "response_tokens": total_response_tokens,
        "estimated": bool(estimated_calls > 0),
    }


def _source_bounds(source: Dict) -> Tuple[str, int, int, int]:
    if not isinstance(source, dict):
        return "", 0, 0, 0
    return (
        _sanitize_str(source.get("book_code")),
        _sanitize_int(source.get("chapter"), 0),
        _sanitize_int(source.get("quote_verse_start"), 0),
        _sanitize_int(source.get("quote_verse_end"), 0),
    )


def _merge_llm_stats(a: Dict[str, int | bool], b: Dict[str, int | bool]) -> Dict[str, int | bool]:
    return {
        "calls": int(a.get("calls", 0)) + int(b.get("calls", 0)),
        "prompt_tokens": int(a.get("prompt_tokens", 0)) + int(b.get("prompt_tokens", 0)),
        "response_tokens": int(a.get("response_tokens", 0)) + int(b.get("response_tokens", 0)),
        "estimated": bool(a.get("estimated", False) or b.get("estimated", False)),
    }


class BonusHintPicker:
    def __init__(self, entries: List[VerseIndexEntry]) -> None:
        self._entries = entries
        self._total_verses = len(entries)
        en_counts: Dict[str, int] = {}
        he_counts: Dict[str, int] = {}
        for entry in entries:
            for token in entry.en_tokens:
                en_counts[token] = en_counts.get(token, 0) + 1
            for token in entry.he_tokens:
                he_counts[token] = he_counts.get(token, 0) + 1
        self._en_token_verse_count = en_counts
        self._he_token_verse_count = he_counts

    @classmethod
    def load(cls, english_xml: Path, hebrew_zip: Path) -> "BonusHintPicker":
        tandem = bible_tandem.TandemBible.load(english_xml=english_xml, hebrew_zip=hebrew_zip)
        entries: List[VerseIndexEntry] = []

        for book_code, chapter in tandem.iter_chapters():
            for verse in tandem.iter_verses(book_code, chapter):
                quote_en = text_cleanup.clean_text(verse.en_raw)
                quote_he = text_cleanup.clean_text(verse.he_clean)
                if not quote_en or not quote_he:
                    continue
                entries.append(
                    VerseIndexEntry(
                        book_code=verse.book_code,
                        book_en=verse.book_en,
                        book_he=verse.book_he,
                        chapter=verse.chapter,
                        verse=verse.verse,
                        quote_en=quote_en,
                        quote_he=quote_he,
                        en_tokens=frozenset(text_cleanup.tokenize_for_match(quote_en, "en")),
                        he_tokens=frozenset(text_cleanup.tokenize_for_match(quote_he, "he")),
                    )
                )
        return cls(entries=entries)

    def is_generic_bonus_word(
        self,
        *,
        lang: str,
        word: str,
        max_ratio: float = 0.008,
        min_verse_count: int = 120,
    ) -> bool:
        if self._total_verses <= 0:
            return False
        tokens = set(text_cleanup.tokenize_for_match(_sanitize_str(word), lang))
        if not tokens:
            return False
        counts = self._en_token_verse_count if lang == "en" else self._he_token_verse_count
        for token in tokens:
            token_count = int(counts.get(token, 0))
            if token_count < max(1, min_verse_count):
                continue
            if (token_count / float(self._total_verses)) >= max_ratio:
                return True
        return False

    def word_verse_count(self, *, lang: str, word: str) -> int:
        tokens = set(text_cleanup.tokenize_for_match(_sanitize_str(word), lang))
        if not tokens:
            return 0
        counts = self._en_token_verse_count if lang == "en" else self._he_token_verse_count
        return max(int(counts.get(token, 0)) for token in tokens)

    def _collect_candidates(
        self,
        *,
        lang: str,
        bonus_word: str,
        current_quote: str,
        source: Dict,
        max_candidates: int,
    ) -> List[VerseIndexEntry]:
        cleaned_word = _sanitize_str(bonus_word)
        if not cleaned_word:
            return []
        query_tokens = text_cleanup.tokenize_for_match(cleaned_word, lang)
        if not query_tokens:
            return []

        query_token_set: Set[str] = set(query_tokens)
        source_code, source_chapter, source_start, source_end = _source_bounds(source)
        cleaned_current_quote = _sanitize_str(current_quote)
        candidates: List[VerseIndexEntry] = []

        for entry in self._entries:
            if (
                source_code
                and entry.book_code == source_code
                and source_chapter > 0
                and entry.chapter == source_chapter
                and source_start > 0
                and source_end > 0
                and source_start <= entry.verse <= source_end
            ):
                continue

            verse_quote = entry.quote_en if lang == "en" else entry.quote_he
            if cleaned_current_quote and verse_quote == cleaned_current_quote:
                continue

            token_set = entry.en_tokens if lang == "en" else entry.he_tokens
            if not query_token_set.issubset(token_set):
                continue

            if not text_cleanup.extract_substring_from_quote(verse_quote, cleaned_word, lang):
                continue

            candidates.append(entry)
            if len(candidates) >= max_candidates:
                break

        return candidates

    def _pick_with_llm(
        self,
        *,
        model: str,
        lang: str,
        bonus_word: str,
        current_quote: str,
        candidates: List[VerseIndexEntry],
        max_retries: int,
    ) -> Tuple[Optional[VerseIndexEntry], Dict[str, int | bool], str]:
        if not candidates:
            return None, {"calls": 0, "prompt_tokens": 0, "response_tokens": 0, "estimated": False}, "no_candidates"

        llm_total = {"calls": 0, "prompt_tokens": 0, "response_tokens": 0, "estimated": False}
        retry_feedback: List[str] = []
        last_reason = ""

        payload_candidates: List[Dict] = []
        for idx, entry in enumerate(candidates):
            quote = entry.quote_en if lang == "en" else entry.quote_he
            book = entry.book_en if lang == "en" else entry.book_he
            payload_candidates.append(
                {
                    "idx": idx,
                    "quote": quote,
                    "source": {
                        "book": book,
                        "chapter": entry.chapter,
                        "start": entry.verse,
                        "end": entry.verse,
                    },
                }
            )

        for attempt in range(1, max_retries + 1):
            payload = {
                "instructions": HINT_PICK_PROMPT,
                "lang": lang,
                "bonus_word": _sanitize_str(bonus_word),
                "current_quote": _sanitize_str(current_quote),
                "retry_feedback": retry_feedback,
                "candidates": payload_candidates,
            }
            data, stats = _call_llm_json(model=model, payload=payload, max_attempts=2)
            llm_total = _merge_llm_stats(llm_total, stats)

            status = _sanitize_str(data.get("status")).lower()
            reason = _sanitize_str(data.get("reason"))
            if status == "none":
                return None, llm_total, reason or "llm_none"

            hint_idx = _sanitize_int(data.get("hint_idx"), -1)
            if hint_idx < 0 or hint_idx >= len(candidates):
                last_reason = "hint_bad_index"
                retry_feedback.append(f"attempt_{attempt}:{last_reason}")
                continue

            selected = candidates[hint_idx]
            selected_quote = selected.quote_en if lang == "en" else selected.quote_he
            if not text_cleanup.extract_substring_from_quote(selected_quote, _sanitize_str(bonus_word), lang):
                last_reason = "hint_word_not_in_quote"
                retry_feedback.append(f"attempt_{attempt}:{last_reason}")
                continue

            return selected, llm_total, ""

        return None, llm_total, last_reason or "hint_selection_failed"

    def pick_hint(
        self,
        *,
        model: str,
        lang: str,
        bonus_word: str,
        current_quote: str,
        source: Dict,
        max_candidates: int = 10,
        max_retries: int = 3,
    ) -> Tuple[Optional[Dict], Dict[str, int | bool], str]:
        candidates = self._collect_candidates(
            lang=lang,
            bonus_word=bonus_word,
            current_quote=current_quote,
            source=source,
            max_candidates=max(1, max_candidates),
        )

        selected, llm_stats, reason = self._pick_with_llm(
            model=model,
            lang=lang,
            bonus_word=bonus_word,
            current_quote=current_quote,
            candidates=candidates,
            max_retries=max(1, max_retries),
        )
        if selected is None:
            return None, llm_stats, reason

        if lang == "en":
            quote = selected.quote_en
            book = selected.book_en
        else:
            quote = selected.quote_he
            book = selected.book_he

        hint = {
            "quote": quote,
            "source": {
                "book": book,
                "chapter": selected.chapter,
                "start": selected.verse,
                "end": selected.verse,
            },
        }
        return hint, llm_stats, ""
