#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Set, Tuple

from ollama import chat

HEBREW_END2END_PROMPT = [
    "You create high-quality Bible quote riddles from one chapter, using Hebrew verses first.",
    "Return strict JSON only with shape:",
    '{"items":[{"quote_verse_start":1,"quote_verse_end":2,"speaker_he":"...","listener_he":"...","riddle_he":"..."}]}',
    "Core rules:",
    "1) Output only direct-speech interactions (not pure narration).",
    "2) Keep range in same chapter and <= max_window.",
    "3) Keep only solvable interactions with one clear speaker and one clear listener.",
    "4) speaker_he/listener_he must be exact in-quote Hebrew forms from the selected range.",
    "5) If God is involved, use the fullest in-quote Hebrew title (for example: 'יְהוָה אֱלֹהִים' or 'אֲדֹנָי יְהוִה').",
    "6) riddle_he should be concise and dramatic (target 4-16 tokens) and must be an exact verbatim substring in the Hebrew quote.",
    "7) Riddle must avoid speaker/listener names, including prefixed forms like לX / בX / כX / מX / שX / וX and אל־X.",
    "8) Prefer one coherent clause, even from the middle of a verse; avoid clipped starts/ends and avoid weird whitespace/newlines.",
    "9) Skip weak or ambiguous cases. Quality over quantity.",
    "10) Never paraphrase or invent text.",
    "11) Do not add extra fields such as reason/confidence.",
]

EN_ALIGN_PROMPT = [
    "You align one Hebrew quote candidate to English using only the same verse range context.",
    "Return strict JSON only with shape:",
    '{"status":"keep|drop","reason":"...","item":{"speaker_en":"...","listener_en":"...","riddle_en":"..."}}',
    "Rules:",
    "1) Use only exact text that appears in quote_en and the provided English verses. Do not translate freely.",
    "2) speaker_en/listener_en must be concrete entities that correspond to speaker_he/listener_he and appear in quote_en.",
    "3) If God is involved, use the fullest in-quote English title (for example: 'the LORD God').",
    "4) riddle_en must be an exact substring in quote_en, concise and dramatic (target 4-16 tokens), and avoid speaker/listener names.",
    "5) Prefer an English clause that matches the same event/meaning as riddle_he.",
    "6) If not confidently alignable, return status=drop.",
]

CANDIDATE_PROMPT = [
    "Find candidate direct-speech interactions in this chapter.",
    "Return strict JSON only:",
    '{"candidates":[{"quote_verse_start":1,"quote_verse_end":2,"reason":"..."}]}',
    "Rules: range <= max_window, keep only clear speaker->listener interactions, skip weak/ambiguous cases.",
]

CANDIDATE_FINAL_PROMPT = [
    "Finalize one candidate into a quote/riddle interaction.",
    "Return strict JSON only:",
    '{"item":{"quote_verse_start":1,"quote_verse_end":2,"speaker_en":"...","listener_en":"...","speaker_he":"...","listener_he":"...","riddle_en":"...","riddle_he":"...","reason":"...","confidence":0.0}}',
    "Rules match the chapter-level generation rules (direct speech, clear entities, concise substring riddles).",
]

VALIDATE_AND_FIX_PROMPT = [
    "You are validating and fixing one generated Bible quote interaction.",
    "Decide whether to keep or drop; when keep, provide corrected fields.",
    "Return strict JSON only:",
    '{"status":"keep|drop","reason":"...","item":{"quote_verse_start":1,"quote_verse_end":2,"speaker_en":"...","listener_en":"...","speaker_he":"...","listener_he":"...","riddle_en":"...","riddle_he":"..."}}',
    "Validation rules:",
    "1) Keep only direct-speech interactions with an unambiguous speaker and listener.",
    "2) Range must be in chapter and <= max_window.",
    "3) Use exact in-quote forms for entities. If God is speaker/listener, use fullest in-quote title.",
    "4) Group entities are allowed when explicit (for example: 'children of Israel' / 'בְּנֵי יִשְׂרָאֵל').",
    "5) Riddles should be concise and dramatic (target 4-16 tokens), avoid speaker/listener names, and avoid dangling fragments.",
    "6) riddle_en/riddle_he MUST be verbatim substrings from quote_en/quote_he. Never paraphrase.",
    "7) If quote is too short or weak, prefer fixing by selecting a better clause or adjusting the verse range (still <= max_window) before dropping.",
    "8) Drop only when not confidently fixable while preserving exact substrings and clear entities.",
]


LLMStats = Dict[str, int | bool]


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


def _empty_llm_stats() -> LLMStats:
    return {
        "calls": 0,
        "prompt_tokens": 0,
        "response_tokens": 0,
        "estimated": False,
    }


def _merge_llm_stats(total: LLMStats, current: LLMStats) -> None:
    total["calls"] = int(total.get("calls", 0)) + int(current.get("calls", 0))
    total["prompt_tokens"] = int(total.get("prompt_tokens", 0)) + int(current.get("prompt_tokens", 0))
    total["response_tokens"] = int(total.get("response_tokens", 0)) + int(current.get("response_tokens", 0))
    total["estimated"] = bool(total.get("estimated", False) or current.get("estimated", False))


def _call_llm_json(model: str, payload: Dict, max_attempts: int = 3) -> Tuple[Dict, LLMStats]:
    total_prompt_tokens = 0
    total_response_tokens = 0
    estimated_calls = 0
    attempts = 0
    last_error: Optional[Exception] = None
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
            options={"temperature": 0.2, "num_predict": 512},
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
        except Exception as exc:  # noqa: PERF203
            last_error = exc
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

    # Soft-fail: return empty payload so chapter processing can continue.
    return {}, {
        "calls": attempts,
        "prompt_tokens": total_prompt_tokens,
        "response_tokens": total_response_tokens,
        "estimated": bool(estimated_calls > 0),
    }


def _coerce_items(value: object, key: str) -> List[Dict]:
    if not isinstance(value, list):
        raise ValueError(f"LLM output missing {key}[]")
    return [item for item in value if isinstance(item, dict)]


def _sanitize_int(value: object, fallback: int = 0) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return fallback


def _sanitize_str(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value.strip())


def _context_verse_map(context: List[Dict]) -> Dict[int, Dict[str, str]]:
    verse_map: Dict[int, Dict[str, str]] = {}
    for row in context:
        verse = _sanitize_int(row.get("v"), 0)
        if verse <= 0:
            continue
        verse_map[verse] = {
            "en": _sanitize_str(row.get("en")),
            "he": _sanitize_str(row.get("he")),
        }
    return verse_map


def _normalize_range(
    suggestion: Dict,
    max_window: int,
    verse_numbers: Set[int],
) -> Optional[Tuple[int, int]]:
    start = _sanitize_int(suggestion.get("quote_verse_start"), 0)
    end = _sanitize_int(suggestion.get("quote_verse_end"), 0)
    if start <= 0 or end <= 0:
        return None
    if start > end:
        start, end = end, start
    if end - start + 1 > max_window:
        return None
    for verse in range(start, end + 1):
        if verse not in verse_numbers:
            return None
    return start, end


def _range_context(verse_map: Dict[int, Dict[str, str]], start: int, end: int) -> List[Dict]:
    out: List[Dict] = []
    for verse in range(start, end + 1):
        value = verse_map.get(verse, {})
        out.append({
            "v": verse,
            "en": _sanitize_str(value.get("en")),
            "he": _sanitize_str(value.get("he")),
        })
    return out


def _range_quote(verse_map: Dict[int, Dict[str, str]], start: int, end: int, lang: str) -> str:
    pieces: List[str] = []
    for verse in range(start, end + 1):
        value = verse_map.get(verse, {})
        pieces.append(_sanitize_str(value.get(lang)))
    return _sanitize_str(" ".join(piece for piece in pieces if piece))


def _align_english_candidate(
    model: str,
    verse_map: Dict[int, Dict[str, str]],
    candidate_he: Dict,
    max_window: int,
) -> Tuple[Optional[Dict], LLMStats]:
    start = _sanitize_int(candidate_he.get("quote_verse_start"), 0)
    end = _sanitize_int(candidate_he.get("quote_verse_end"), 0)
    if start <= 0 or end <= 0:
        return None, _empty_llm_stats()

    payload = {
        "instructions": EN_ALIGN_PROMPT,
        "constraints": {
            "max_window": max_window,
            "riddle_tokens_target": "4-16",
        },
        "candidate_he": {
            "quote_verse_start": start,
            "quote_verse_end": end,
            "speaker_he": _sanitize_str(candidate_he.get("speaker_he")),
            "listener_he": _sanitize_str(candidate_he.get("listener_he")),
            "riddle_he": _sanitize_str(candidate_he.get("riddle_he")),
        },
        "range_context": _range_context(verse_map, start, end),
        "quote_he": _range_quote(verse_map, start, end, "he"),
        "quote_en": _range_quote(verse_map, start, end, "en"),
    }

    data, stats = _call_llm_json(model=model, payload=payload)

    status = str(data.get("status", "drop")).strip().lower()
    if status != "keep":
        return None, stats

    item = data.get("item", {})
    if not isinstance(item, dict):
        return None, stats

    return {
        "speaker_en": _sanitize_str(item.get("speaker_en")),
        "listener_en": _sanitize_str(item.get("listener_en")),
        "riddle_en": _sanitize_str(item.get("riddle_en")),
        "reason_en_alignment": _sanitize_str(data.get("reason")),
    }, stats


def end2end_suggestions(
    model: str,
    context: List[Dict],
    max_window: int,
    max_quotes: int,
) -> Tuple[List[Dict], LLMStats]:
    verse_map = _context_verse_map(context)
    verse_numbers = set(verse_map.keys())

    he_verses = [
        {"v": verse, "he": verse_map[verse]["he"]}
        for verse in sorted(verse_map)
    ]

    max_candidates = max(max_quotes * 2, max_quotes + 2)
    payload = {
        "instructions": HEBREW_END2END_PROMPT,
        "constraints": {
            "max_window": max_window,
            "max_quotes": max_candidates,
            "riddle_tokens_target": "4-16",
        },
        "verses_he": he_verses,
    }

    data, total_stats = _call_llm_json(model=model, payload=payload)
    he_items = _coerce_items(data.get("items", []), "items")

    out: List[Dict] = []
    seen_keys: Set[str] = set()

    for suggestion in he_items:
        normalized = _normalize_range(suggestion=suggestion, max_window=max_window, verse_numbers=verse_numbers)
        if normalized is None:
            continue
        start, end = normalized

        he_candidate = {
            "quote_verse_start": start,
            "quote_verse_end": end,
            "speaker_he": _sanitize_str(suggestion.get("speaker_he")),
            "listener_he": _sanitize_str(suggestion.get("listener_he")),
            "riddle_he": _sanitize_str(suggestion.get("riddle_he")),
            "reason": _sanitize_str(suggestion.get("reason")),
            "confidence": suggestion.get("confidence"),
        }

        align_patch, align_stats = _align_english_candidate(
            model=model,
            verse_map=verse_map,
            candidate_he=he_candidate,
            max_window=max_window,
        )
        _merge_llm_stats(total_stats, align_stats)
        if align_patch is None:
            continue

        merged = {
            "quote_verse_start": start,
            "quote_verse_end": end,
            "speaker_en": align_patch.get("speaker_en", ""),
            "listener_en": align_patch.get("listener_en", ""),
            "speaker_he": he_candidate["speaker_he"],
            "listener_he": he_candidate["listener_he"],
            "riddle_en": align_patch.get("riddle_en", ""),
            "riddle_he": he_candidate["riddle_he"],
            "reason": he_candidate["reason"] or align_patch.get("reason_en_alignment", ""),
            "confidence": he_candidate["confidence"],
        }

        dedupe_key = json.dumps(
            {
                "s": start,
                "e": end,
                "rh": merged["riddle_he"],
                "re": merged["riddle_en"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        out.append(merged)

    return out, total_stats


def candidate_suggestions(
    model: str,
    context: List[Dict],
    max_window: int,
    max_quotes: int,
) -> Tuple[List[Dict], LLMStats]:
    payload = {
        "instructions": CANDIDATE_PROMPT,
        "constraints": {
            "max_window": max_window,
            "max_quotes": max_quotes,
        },
        "verses": context,
    }
    data, stats = _call_llm_json(model=model, payload=payload)
    return _coerce_items(data.get("candidates", []), "candidates"), stats


def finalize_candidate(
    model: str,
    context: List[Dict],
    candidate: Dict,
    max_window: int,
) -> Tuple[Dict, LLMStats]:
    payload = {
        "instructions": CANDIDATE_FINAL_PROMPT,
        "constraints": {"max_window": max_window, "riddle_tokens_target": "4-16"},
        "candidate": candidate,
        "verses": context,
    }
    data, stats = _call_llm_json(model=model, payload=payload)
    item = data.get("item", {})
    if not isinstance(item, dict):
        raise ValueError("LLM output missing item{}")
    return item, stats


def validate_and_fix_item(
    model: str,
    context: List[Dict],
    suggestion: Dict,
    max_window: int,
    issues: Optional[List[str]] = None,
) -> Tuple[Dict, LLMStats]:
    payload = {
        "instructions": VALIDATE_AND_FIX_PROMPT,
        "constraints": {
            "max_window": max_window,
            "riddle_tokens_target": "4-16",
        },
        "issues_from_code_validation": issues or [],
        "candidate": suggestion,
        "verses": context,
    }
    data, stats = _call_llm_json(model=model, payload=payload)

    status = str(data.get("status", "drop")).strip().lower()
    if status not in {"keep", "drop"}:
        status = "drop"

    reason = str(data.get("reason", "")).strip()
    item = data.get("item", {})
    if not isinstance(item, dict):
        item = {}

    return {"status": status, "reason": reason, "item": item}, stats
