#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Tuple

from ollama import chat

END2END_PROMPT = [
    "You create high-quality Bible quote riddles from one chapter containing English and Hebrew verses.",
    "Return strict JSON only with shape:",
    '{"items":[{"quote_verse_start":1,"quote_verse_end":2,"speaker_en":"...","listener_en":"...","speaker_he":"...","listener_he":"...","riddle_en":"...","riddle_he":"...","reason":"...","confidence":0.0}]}',
    "Core rules:",
    "1) Output only direct-speech interactions (not pure narration).",
    "2) Keep range in same chapter and <= max_window.",
    "3) Keep only solvable interactions with one clear speaker and one clear listener.",
    "4) Use exact in-quote forms for entities. If God is involved, use the fullest in-quote title in each language.",
    "5) riddle_en and riddle_he should be concise and dramatic (prefer 4-14 tokens), and each must be a verbatim substring in its language quote.",
    "6) Riddles should avoid speaker/listener names, including prefixed Hebrew forms like ל/ב/כ/מ/ש/ו + name, or אל־name.",
    "7) If a case is weak/ambiguous, skip it. Quality over quantity.",
    "8) NEVER paraphrase verse text. Do not invent words. Do not add explanatory text.",
    "9) Avoid weird whitespace/newlines and avoid clipped fragments.",
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
    "4) Riddles should be concise (prefer 4-14 tokens), dramatic, and not include speaker/listener names.",
    "5) riddle_en/riddle_he MUST be verbatim substrings from candidate quote_en/quote_he. Never paraphrase.",
    "6) If you cannot keep exact substrings and exact in-quote entities, return status=drop.",
    "7) Riddles must look like natural quote clauses, not narration fragments.",
    "8) If not confidently fixable, return status=drop.",
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


def _call_llm_json(model: str, payload: Dict, max_attempts: int = 3) -> Tuple[Dict, LLMStats]:
    total_prompt_tokens = 0
    total_response_tokens = 0
    estimated_calls = 0
    attempts = 0
    last_error: Optional[Exception] = None

    for attempt in range(1, max_attempts + 1):
        prompt = dict(payload)
        if attempt > 1:
            prompt["strict_json_retry"] = (
                "Previous output was invalid JSON. Return strict JSON only, parsable by json.loads."
            )

        response = chat(
            model=model,
            messages=[{"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}],
        )
        attempts += 1
        content = response["message"]["content"].strip()

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

    raise ValueError(f"LLM JSON parse failed after {attempts} attempts: {last_error}")


def _coerce_items(value: object, key: str) -> List[Dict]:
    if not isinstance(value, list):
        raise ValueError(f"LLM output missing {key}[]")
    return [item for item in value if isinstance(item, dict)]


def end2end_suggestions(
    model: str,
    context: List[Dict],
    max_window: int,
    max_quotes: int,
) -> Tuple[List[Dict], LLMStats]:
    payload = {
        "instructions": END2END_PROMPT,
        "constraints": {
            "max_window": max_window,
            "max_quotes": max_quotes,
            "riddle_tokens_target": "4-14",
        },
        "verses": context,
    }
    data, stats = _call_llm_json(model=model, payload=payload)
    return _coerce_items(data.get("items", []), "items"), stats


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
        "constraints": {"max_window": max_window, "riddle_tokens_target": "4-14"},
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
            "riddle_tokens_target": "4-14",
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
