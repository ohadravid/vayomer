#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from ollama import chat
from tqdm import tqdm

try:
    from data_processing import bible_sources, bible_tandem
except ModuleNotFoundError:
    import bible_sources  # type: ignore[no-redef]
    import bible_tandem  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[1]

EN_PRONOUNS = {
    "he",
    "she",
    "they",
    "them",
    "him",
    "her",
    "you",
    "thou",
    "thee",
    "ye",
    "me",
    "i",
    "we",
    "us",
    "my",
    "our",
    "his",
    "their",
    "hers",
    "himself",
    "herself",
    "themselves",
}

HE_PRONOUNS = {
    "הוא",
    "היא",
    "הם",
    "הן",
    "להם",
    "להן",
    "לו",
    "לה",
    "אתה",
    "את",
    "אתם",
    "אתן",
    "אני",
    "אנחנו",
}

EN_GROUP_ENTITY_TOKENS = {
    "people",
    "men",
    "man",
    "women",
    "woman",
    "inhabitants",
    "children",
    "sons",
    "daughters",
    "kings",
    "king",
    "princes",
    "priests",
    "priest",
    "servants",
    "servant",
    "house",
    "nation",
    "tribe",
    "tribes",
    "elders",
}
EN_CONNECTOR_TOKENS = {
    "the",
    "of",
    "and",
    "unto",
    "to",
    "son",
    "daughter",
    "his",
    "her",
    "their",
    "my",
    "thy",
    "your",
    "our",
}
EN_LOCATION_TOKENS = {"israel", "judah", "jerusalem", "egypt", "zion", "babylon"}

HE_GROUP_ENTITY_BASE_TOKENS = {
    "עם",
    "איש",
    "אנשים",
    "יושב",
    "יושבי",
    "בני",
    "מלך",
    "מלכי",
    "כהן",
    "כהנים",
    "עבד",
    "עבדים",
    "בית",
    "זקן",
    "זקנים",
    "נשיא",
    "נשיאים",
}
HE_CONNECTOR_BASE_TOKENS = {"ו", "בן", "בת", "בני", "בית", "של"}
HE_LOCATION_BASE_TOKENS = {"יהודה", "ירושלם", "ירושלים", "ישראל", "מצרים", "ציון", "בבל"}
EN_SPEECH_MARKERS = {"said", "saith", "saying", "spake", "speak", "answered", "commanded", "called"}
HE_SPEECH_BASE_MARKERS = {"אמר", "דבר", "לאמר", "נאם"}

END2END_PROMPT = [
    "You are creating high-quality Bible quote riddles from one chapter.",
    "Output only solvable direct-speech interactions with clear speaker and listener.",
    "Return strict JSON only with shape:",
    '{"items":[{"quote_verse_start":1,"quote_verse_end":2,"speaker_en":"...","listener_en":"...","speaker_he":"...","listener_he":"...","riddle_en":"...","riddle_he":"...","reason":"...","confidence":0.0}]}',
    "Rules:",
    "1) quote_verse_end - quote_verse_start + 1 MUST be <= 5 and same chapter.",
    "2) Keep only interactions with one unambiguous speaker and one unambiguous listener.",
    "2b) Skip weak/unclear cases (reported-speech chains, unclear listener, broad crowd listeners) rather than forcing.",
    "3) speaker and listener should both appear in the full quote text whenever possible.",
    "3b) Use exact in-quote forms for names/titles (e.g. Abram vs Abraham, LORD vs God when relevant).",
    "3c) For God titles, choose the fullest in-quote form in each language.",
    "4) riddle must be a verbatim substring in each language and MUST NOT include speaker/listener names (including prefixed Hebrew forms like ל/ב/כ/מ/ש/ו + name, or אל־name).",
    "5) prefer dramatic/interesting, concise riddles (roughly 4-14 tokens), ideally one coherent clause.",
    "5b) avoid clipped riddles starting/ending with dangling particles (e.g. and/of/that or את/אל/כי/אשר).",
    "6) avoid weird whitespace/newlines.",
    "7) if a candidate is weak or ambiguous, skip it instead of forcing it.",
]

CANDIDATE_PROMPT = [
    "Find candidate direct speech interactions in this chapter.",
    "Return strict JSON only: {'candidates':[{'quote_verse_start':1,'quote_verse_end':2,'reason':'...'}]}",
    "Rules: max window is 5 verses, include only candidates with clear speaker->listener interaction, skip weak/ambiguous crowd-address cases.",
]

CANDIDATE_FINAL_PROMPT = [
    "Finalize one candidate quote/riddle pair from this verse range.",
    "Return strict JSON only with shape:",
    '{"item":{"quote_verse_start":1,"quote_verse_end":2,"speaker_en":"...","listener_en":"...","speaker_he":"...","listener_he":"...","riddle_en":"...","riddle_he":"...","reason":"...","confidence":0.0}}',
    "Rules: keep one clear speaker+listener pair, use fullest in-quote God title, and keep riddles concise (4-14 tokens), dramatic, and not clipped.",
]

REPAIR_PROMPT = [
    "You are repairing one generated Bible quote record after validation failures.",
    "Return strict JSON only with shape:",
    '{"item":{"quote_verse_start":1,"quote_verse_end":2,"speaker_en":"...","listener_en":"...","speaker_he":"...","listener_he":"...","riddle_en":"...","riddle_he":"...","reason":"...","confidence":0.0}}',
    "Rules:",
    "1) keep range in same chapter and <=5 verses.",
    "2) fix ambiguity in speaker/listener and skip crowd-style unclear listeners.",
    "3) keep riddle concise and dramatic (4-14 tokens), avoid clipped dangling start/end tokens.",
    "4) exclude speaker/listener names (including prefixed Hebrew forms).",
    "5) riddle must be exact substring of full quote in each language.",
]


@dataclass
class ValidationConfig:
    max_window: int = 5
    min_quote_tokens: int = 12
    min_riddle_tokens: int = 4
    max_riddle_tokens: int = 14
    min_context_tokens: int = 6


@dataclass
class Stats:
    files: int = 0
    chapters: int = 0
    suggestions: int = 0
    kept_items: int = 0
    dropped_items: int = 0
    repaired_items: int = 0
    llm_calls: int = 0
    prompt_tokens: int = 0
    response_tokens: int = 0
    estimated_calls: int = 0
    skipped_existing: int = 0
    errors: int = 0


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


def _sanitize_int(value: object, fallback: int = 0) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return fallback


def _sanitize_str(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return bible_tandem.clean_text(value)


def _strip_wrapping_quotes(text: str) -> str:
    value = _sanitize_str(text)
    if not value:
        return ""
    return value.strip(" \"'“”‘’")


def _is_suspicious_en(name: str) -> bool:
    value = _sanitize_str(name).casefold()
    if not value:
        return True
    if value in EN_PRONOUNS:
        return True
    if value.startswith(("he ", "she ", "they ", "them ", "him ", "her ", "you ", "thou ", "thee ", "ye ")):
        return True
    if " said " in value or value.startswith("said "):
        return True
    if value in {"someone", "somebody", "person", "narrator", "voice"}:
        return True
    return False


def _is_suspicious_he(name: str) -> bool:
    value = _sanitize_str(name)
    if not value:
        return True
    if value.startswith(("־", "-")) or value.endswith(("־", "-")):
        return True
    if value in HE_PRONOUNS:
        return True
    if "ויאמר" in value or "וַיֹּאמֶר" in value:
        return True
    if value in {"סיפור", "קריין", "מספר"}:
        return True
    tokens = bible_tandem.tokenize_for_match(value, "he")
    if tokens and _hebrew_base_token(tokens[0]) in {"כה", "נאם", "אמר"}:
        return True
    return False


def _hebrew_base_token(token: str) -> str:
    base = token
    for _ in range(2):
        if len(base) <= 2:
            break
        if base[0] not in bible_tandem.HEBREW_PREFIX_CHARS:
            break
        base = base[1:]
    return base


def _is_group_like_en(name: str) -> bool:
    tokens = bible_tandem.tokenize_for_match(_sanitize_str(name), "en")
    if not tokens:
        return True
    core = [tok for tok in tokens if tok not in EN_CONNECTOR_TOKENS]
    if not core:
        return True
    if len(core) == 1 and core[0] in EN_LOCATION_TOKENS:
        return True
    group_hits = [tok for tok in core if tok in EN_GROUP_ENTITY_TOKENS]
    if not group_hits:
        return False
    non_group = [tok for tok in core if tok not in EN_GROUP_ENTITY_TOKENS and tok not in EN_LOCATION_TOKENS]
    if not non_group:
        return True
    return len(core) >= 3 and len(group_hits) >= 1


def _is_group_like_he(name: str) -> bool:
    raw_tokens = bible_tandem.tokenize_for_match(_sanitize_str(name), "he")
    if not raw_tokens:
        return True
    base_tokens = [_hebrew_base_token(tok) for tok in raw_tokens]
    core = [tok for tok in base_tokens if tok not in HE_CONNECTOR_BASE_TOKENS]
    if not core:
        return True
    if len(core) == 1 and core[0] in HE_LOCATION_BASE_TOKENS:
        return True
    group_hits = [tok for tok in core if tok in HE_GROUP_ENTITY_BASE_TOKENS]
    if not group_hits:
        return False
    non_group = [tok for tok in core if tok not in HE_GROUP_ENTITY_BASE_TOKENS and tok not in HE_LOCATION_BASE_TOKENS]
    if not non_group:
        return True
    return len(core) >= 3 and len(group_hits) >= 1


def _riddle_verse_hits(raw_map: Dict[str, str], riddle: str, lang: str) -> List[int]:
    hits: List[int] = []
    if not riddle:
        return hits
    for key, verse_text in raw_map.items():
        try:
            verse_no = int(key)
        except ValueError:
            continue
        text = bible_tandem.clean_text(verse_text)
        if lang == "he":
            text = bible_tandem.cleanup_hebrew_quote(text)
        if riddle in text:
            hits.append(verse_no)
    return sorted(set(hits))


def _clean_verse_for_lang(text: str, lang: str) -> str:
    cleaned = bible_tandem.clean_text(text)
    if lang == "he":
        return bible_tandem.cleanup_hebrew_quote(cleaned)
    return cleaned


def _verse_speech_marker_positions(text: str, lang: str) -> List[int]:
    if not text:
        return []
    if lang == "en":
        out: List[int] = []
        for m in re.finditer(r"\b(said|saith|saying|spake|speak|answered|commanded|called)\b", text, re.IGNORECASE):
            out.append(m.start())
        return sorted(out)

    out_he: List[int] = []
    for tok, start, _ in bible_tandem.tokenize_with_spans(text, "he"):
        base = _hebrew_base_token(tok)
        if tok in {"ויאמר", "ויאמרו", "ותאמר", "ותאמרו", "וידבר", "לאמר", "נאם"}:
            out_he.append(start)
            continue
        if base in HE_SPEECH_BASE_MARKERS:
            out_he.append(start)
    return sorted(set(out_he))


def _riddle_in_direct_speech_context(raw_map: Dict[str, str], riddle: str, lang: str) -> bool:
    hits = _riddle_verse_hits(raw_map=raw_map, riddle=riddle, lang=lang)
    if not hits:
        return False

    cleaned_by_verse: Dict[int, str] = {}
    for key, verse_text in raw_map.items():
        try:
            verse_no = int(key)
        except ValueError:
            continue
        cleaned_by_verse[verse_no] = _clean_verse_for_lang(str(verse_text), lang)

    for verse_no in hits:
        verse_text = cleaned_by_verse.get(verse_no, "")
        if not verse_text:
            continue
        marker_positions = _verse_speech_marker_positions(verse_text, lang)
        riddle_pos = verse_text.find(riddle)
        if marker_positions and riddle_pos >= min(marker_positions):
            return True
        if marker_positions and riddle_pos == -1:
            # If text normalization mismatch hides exact index, still accept same-verse marker.
            return True

        # Allow one-verse continuation when speech starts in the immediately previous verse.
        prev_text = cleaned_by_verse.get(verse_no - 1, "")
        if prev_text and _verse_speech_marker_positions(prev_text, lang):
            return True

    return False


def _stabilize_single_verse_riddle(
    raw_map: Dict[str, str],
    full_quote: str,
    riddle: str,
    speaker: str,
    listener: str,
    lang: str,
    cfg: ValidationConfig,
) -> str:
    hits = _riddle_verse_hits(raw_map, riddle, lang)
    if len(hits) == 1:
        return riddle

    best_candidate = ""
    for verse_no in sorted(raw_map.keys(), key=lambda x: int(x) if str(x).isdigit() else 10**9):
        verse_text = bible_tandem.clean_text(str(raw_map.get(verse_no, "")))
        if lang == "he":
            verse_text = bible_tandem.cleanup_hebrew_quote(verse_text)
        if not verse_text:
            continue

        candidate = bible_tandem.fallback_riddle_from_quote(
            quote=verse_text,
            speaker=speaker,
            listener=listener,
            lang=lang,
            min_tokens=cfg.min_riddle_tokens,
            max_tokens=cfg.max_riddle_tokens,
        )
        if not candidate:
            continue
        if candidate not in full_quote:
            continue
        if bible_tandem.has_dangling_edges(candidate, lang):
            continue
        if bible_tandem.riddle_mentions_entities(candidate, speaker, listener, lang):
            continue
        best_candidate = candidate
        break

    return best_candidate or riddle


def _chapter_filename(book_code: str, chapter: int) -> str:
    slug = bible_sources.BOOK_CODE_TO_EN.get(book_code, book_code).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return f"{slug}-{chapter:03d}.json"


def _build_item_id(book_code: str, chapter: int, start: int, end: int) -> str:
    slug = bible_sources.BOOK_CODE_TO_EN.get(book_code, book_code).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return f"{slug}-{chapter:02d}-{start:02d}-{end:02d}"


def _call_llm_json(model: str, payload: Dict) -> Tuple[Dict, Dict[str, int | bool]]:
    total_prompt_tokens = 0
    total_response_tokens = 0
    estimated_calls = 0
    attempts = 0
    last_error: Optional[Exception] = None

    for attempt in range(1, 4):
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


def _chapter_context(tandem: bible_tandem.TandemBible, book_code: str, chapter: int) -> List[Dict]:
    return [
        {"v": verse.verse, "en": verse.en_raw, "he": verse.he_raw}
        for verse in tandem.iter_verses(book_code, chapter)
    ]


def _end2end_suggestions(
    model: str,
    context: List[Dict],
    max_window: int,
    max_quotes: int,
) -> Tuple[List[Dict], Dict[str, int | bool]]:
    payload = {
        "instructions": END2END_PROMPT,
        "constraints": {
            "max_window": max_window,
            "max_quotes": max_quotes,
        },
        "verses": context,
    }
    data, stats = _call_llm_json(model=model, payload=payload)
    items = data.get("items", [])
    if not isinstance(items, list):
        raise ValueError("LLM output missing items[]")
    return items, stats


def _candidate_suggestions(
    model: str,
    context: List[Dict],
    max_window: int,
    max_quotes: int,
) -> Tuple[List[Dict], Dict[str, int | bool]]:
    payload = {
        "instructions": CANDIDATE_PROMPT,
        "constraints": {
            "max_window": max_window,
            "max_quotes": max_quotes,
        },
        "verses": context,
    }
    data, stats = _call_llm_json(model=model, payload=payload)
    candidates = data.get("candidates", [])
    if not isinstance(candidates, list):
        raise ValueError("LLM output missing candidates[]")
    return candidates, stats


def _finalize_candidate(
    model: str,
    context: List[Dict],
    candidate: Dict,
) -> Tuple[Dict, Dict[str, int | bool]]:
    payload = {
        "instructions": CANDIDATE_FINAL_PROMPT,
        "candidate": candidate,
        "verses": context,
    }
    data, stats = _call_llm_json(model=model, payload=payload)
    item = data.get("item", {})
    if not isinstance(item, dict):
        raise ValueError("LLM output missing item{}")
    return item, stats


def _repair_item(
    model: str,
    context: List[Dict],
    item: Dict,
    issues: List[str],
    max_window: int,
) -> Tuple[Optional[Dict], Dict[str, int | bool]]:
    payload = {
        "instructions": REPAIR_PROMPT,
        "constraints": {"max_window": max_window},
        "issues": issues,
        "current_item": item,
        "verses": context,
    }
    data, stats = _call_llm_json(model=model, payload=payload)
    repaired = data.get("item")
    if not isinstance(repaired, dict):
        return None, stats
    return repaired, stats


def _coerce_item_from_suggestion(
    tandem: bible_tandem.TandemBible,
    book_code: str,
    chapter: int,
    suggestion: Dict,
    cfg: ValidationConfig,
) -> Tuple[Optional[Dict], str]:
    start = _sanitize_int(suggestion.get("quote_verse_start"), 0)
    end = _sanitize_int(suggestion.get("quote_verse_end"), 0)
    if start <= 0 or end <= 0:
        return None, "bad_range"
    if start > end:
        start, end = end, start
    if end - start + 1 > cfg.max_window:
        return None, "range_too_wide"

    range_quote = tandem.collect_range(book_code=book_code, chapter=chapter, start=start, end=end)
    if range_quote.missing:
        return None, "missing_source_verses"
    if not range_quote.en_quote or not range_quote.he_quote:
        return None, "empty_quote"

    speaker_en = _strip_wrapping_quotes(suggestion.get("speaker_en"))
    listener_en = _strip_wrapping_quotes(suggestion.get("listener_en"))
    speaker_he = _strip_wrapping_quotes(suggestion.get("speaker_he"))
    listener_he = _strip_wrapping_quotes(suggestion.get("listener_he"))
    riddle_en = _strip_wrapping_quotes(suggestion.get("riddle_en"))
    riddle_he = _strip_wrapping_quotes(suggestion.get("riddle_he"))

    speaker_en = bible_tandem.align_entity_to_quote(speaker_en, range_quote.en_quote, "en")
    listener_en = bible_tandem.align_entity_to_quote(listener_en, range_quote.en_quote, "en")
    speaker_he = bible_tandem.align_entity_to_quote(speaker_he, range_quote.he_quote, "he")
    listener_he = bible_tandem.align_entity_to_quote(listener_he, range_quote.he_quote, "he")

    riddle_en = bible_tandem.extract_substring_from_quote(range_quote.en_quote, riddle_en, "en") or riddle_en
    riddle_he = bible_tandem.extract_substring_from_quote(range_quote.he_quote, riddle_he, "he") or riddle_he

    riddle_en_tokens = bible_tandem.tokenize_for_match(riddle_en, "en")
    quote_en_tokens = bible_tandem.tokenize_for_match(range_quote.en_quote, "en")
    riddle_en_ratio = (len(riddle_en_tokens) / len(quote_en_tokens)) if quote_en_tokens else 0.0
    if (
        not riddle_en
        or riddle_en not in range_quote.en_quote
        or bible_tandem.riddle_mentions_entities(riddle_en, speaker_en, listener_en, "en")
        or len(bible_tandem.tokenize_for_match(riddle_en, "en")) > cfg.max_riddle_tokens
        or bible_tandem.has_dangling_edges(riddle_en, "en")
        or riddle_en_ratio > 0.72
    ):
        riddle_en = (
            bible_tandem.fallback_riddle_from_quote(
                quote=range_quote.en_quote,
                speaker=speaker_en,
                listener=listener_en,
                lang="en",
                min_tokens=cfg.min_riddle_tokens,
                max_tokens=cfg.max_riddle_tokens,
            )
            or riddle_en
        )
    raw_en = range_quote.raw_quote_source.get("en", {})
    if isinstance(raw_en, dict):
        riddle_en = _stabilize_single_verse_riddle(
            raw_map=raw_en,
            full_quote=range_quote.en_quote,
            riddle=riddle_en,
            speaker=speaker_en,
            listener=listener_en,
            lang="en",
            cfg=cfg,
        )

    riddle_he_tokens = bible_tandem.tokenize_for_match(riddle_he, "he")
    quote_he_tokens = bible_tandem.tokenize_for_match(range_quote.he_quote, "he")
    riddle_he_ratio = (len(riddle_he_tokens) / len(quote_he_tokens)) if quote_he_tokens else 0.0
    if (
        not riddle_he
        or riddle_he not in range_quote.he_quote
        or bible_tandem.riddle_mentions_entities(riddle_he, speaker_he, listener_he, "he")
        or len(bible_tandem.tokenize_for_match(riddle_he, "he")) > cfg.max_riddle_tokens
        or bible_tandem.has_dangling_edges(riddle_he, "he")
        or riddle_he_ratio > 0.72
    ):
        riddle_he = (
            bible_tandem.fallback_riddle_from_quote(
                quote=range_quote.he_quote,
                speaker=speaker_he,
                listener=listener_he,
                lang="he",
                min_tokens=cfg.min_riddle_tokens,
                max_tokens=cfg.max_riddle_tokens,
            )
            or riddle_he
        )
    raw_he = range_quote.raw_quote_source.get("he", {})
    if isinstance(raw_he, dict):
        riddle_he = _stabilize_single_verse_riddle(
            raw_map=raw_he,
            full_quote=range_quote.he_quote,
            riddle=riddle_he,
            speaker=speaker_he,
            listener=listener_he,
            lang="he",
            cfg=cfg,
        )

    item = {
        "id": _build_item_id(book_code=book_code, chapter=chapter, start=start, end=end),
        "source": {
            "book_code": book_code,
            "book": bible_sources.BOOK_CODE_TO_EN.get(book_code, book_code),
            "book_he": bible_sources.BOOK_CODE_TO_HE.get(book_code, ""),
            "chapter": chapter,
            "quote_verse_start": start,
            "quote_verse_end": end,
        },
        "en": {
            "quote": range_quote.en_quote,
            "riddle": _sanitize_str(riddle_en),
            "speaker": _sanitize_str(speaker_en),
            "listener": _sanitize_str(listener_en),
        },
        "he": {
            "quote": range_quote.he_quote,
            "riddle": _sanitize_str(riddle_he),
            "speaker": _sanitize_str(speaker_he),
            "listener": _sanitize_str(listener_he),
        },
        "raw_quote_source": range_quote.raw_quote_source,
        "meta": {
            "reason": _sanitize_str(suggestion.get("reason")),
            "confidence": suggestion.get("confidence"),
        },
    }
    return item, ""


def _validate_item(item: Dict, cfg: ValidationConfig) -> List[str]:
    issues: List[str] = []

    source = item.get("source", {})
    start = _sanitize_int(source.get("quote_verse_start"), 0)
    end = _sanitize_int(source.get("quote_verse_end"), 0)
    if start <= 0 or end <= 0 or end < start:
        issues.append("bad_range")
    elif end - start + 1 > cfg.max_window:
        issues.append("range_too_wide")

    en = item.get("en", {})
    he = item.get("he", {})
    quote_en = _sanitize_str(en.get("quote"))
    quote_he = _sanitize_str(he.get("quote"))
    riddle_en = _sanitize_str(en.get("riddle"))
    riddle_he = _sanitize_str(he.get("riddle"))
    speaker_en = _sanitize_str(en.get("speaker"))
    listener_en = _sanitize_str(en.get("listener"))
    speaker_he = _sanitize_str(he.get("speaker"))
    listener_he = _sanitize_str(he.get("listener"))
    if (
        bible_tandem.tokenize_for_match(speaker_en, "en")
        and bible_tandem.tokenize_for_match(speaker_en, "en") == bible_tandem.tokenize_for_match(listener_en, "en")
    ):
        issues.append("speaker_listener_same_en")
    if (
        bible_tandem.tokenize_for_match(speaker_he, "he")
        and bible_tandem.tokenize_for_match(speaker_he, "he") == bible_tandem.tokenize_for_match(listener_he, "he")
    ):
        issues.append("speaker_listener_same_he")

    if any("\n" in x or "\t" in x for x in [quote_en, quote_he, riddle_en, riddle_he]):
        issues.append("weird_whitespace")

    quote_tokens_en = bible_tandem.tokenize_for_match(quote_en, "en")
    quote_tokens_he = bible_tandem.tokenize_for_match(quote_he, "he")
    riddle_tokens_en = bible_tandem.tokenize_for_match(riddle_en, "en")
    riddle_tokens_he = bible_tandem.tokenize_for_match(riddle_he, "he")

    if len(quote_tokens_en) < cfg.min_quote_tokens:
        issues.append("quote_en_too_short")
    if len(quote_tokens_he) < cfg.min_quote_tokens:
        issues.append("quote_he_too_short")

    for lang, tokens in (("en", riddle_tokens_en), ("he", riddle_tokens_he)):
        if len(tokens) < cfg.min_riddle_tokens:
            issues.append(f"riddle_{lang}_too_short")
        if len(tokens) > cfg.max_riddle_tokens:
            issues.append(f"riddle_{lang}_too_long")

    if riddle_en not in quote_en:
        issues.append("riddle_en_not_substring")
    if riddle_he not in quote_he:
        issues.append("riddle_he_not_substring")
    if bible_tandem.has_dangling_edges(riddle_en, "en"):
        issues.append("riddle_en_dangling_edges")
    if bible_tandem.has_dangling_edges(riddle_he, "he"):
        issues.append("riddle_he_dangling_edges")
    if quote_tokens_en and len(riddle_tokens_en) / len(quote_tokens_en) > 0.72:
        issues.append("riddle_en_too_much_of_quote")
    if quote_tokens_he and len(riddle_tokens_he) / len(quote_tokens_he) > 0.72:
        issues.append("riddle_he_too_much_of_quote")
    if len(quote_tokens_en) - len(riddle_tokens_en) < cfg.min_context_tokens:
        issues.append("quote_en_context_too_short")
    if len(quote_tokens_he) - len(riddle_tokens_he) < cfg.min_context_tokens:
        issues.append("quote_he_context_too_short")

    if _is_suspicious_en(speaker_en) or _is_suspicious_en(listener_en):
        issues.append("bad_english_entities")
    if _is_suspicious_he(speaker_he) or _is_suspicious_he(listener_he):
        issues.append("bad_hebrew_entities")
    if _is_group_like_en(listener_en):
        issues.append("listener_en_ambiguous_group")
    if _is_group_like_he(listener_he):
        issues.append("listener_he_ambiguous_group")

    if not bible_tandem.entity_in_quote(speaker_en, quote_en, "en"):
        issues.append("speaker_en_not_in_quote")
    if not bible_tandem.entity_in_quote(speaker_he, quote_he, "he"):
        issues.append("speaker_he_not_in_quote")
    if not bible_tandem.entity_in_quote(listener_en, quote_en, "en"):
        issues.append("listener_en_not_in_quote")
    if not bible_tandem.entity_in_quote(listener_he, quote_he, "he"):
        issues.append("listener_he_not_in_quote")

    if bible_tandem.riddle_mentions_entities(riddle_en, speaker_en, listener_en, "en"):
        issues.append("riddle_en_mentions_entities")
    if bible_tandem.riddle_mentions_entities(riddle_he, speaker_he, listener_he, "he"):
        issues.append("riddle_he_mentions_entities")

    raw_source = item.get("raw_quote_source", {})
    raw_en = raw_source.get("en", {}) if isinstance(raw_source, dict) else {}
    raw_he = raw_source.get("he", {}) if isinstance(raw_source, dict) else {}
    hits_en = _riddle_verse_hits(raw_en if isinstance(raw_en, dict) else {}, riddle_en, "en")
    hits_he = _riddle_verse_hits(raw_he if isinstance(raw_he, dict) else {}, riddle_he, "he")
    if len(hits_en) != 1:
        issues.append("riddle_en_not_single_verse")
    if len(hits_he) != 1:
        issues.append("riddle_he_not_single_verse")
    if len(hits_en) == 1 and len(hits_he) == 1 and hits_en[0] != hits_he[0]:
        issues.append("riddle_cross_lang_misaligned")

    if isinstance(raw_en, dict) and not _riddle_in_direct_speech_context(raw_en, riddle_en, "en"):
        issues.append("riddle_en_not_direct_speech")
    if isinstance(raw_he, dict) and not _riddle_in_direct_speech_context(raw_he, riddle_he, "he"):
        issues.append("riddle_he_not_direct_speech")

    return sorted(set(issues))


def _parse_chapter_filter(expr: str) -> Set[int]:
    out: Set[int] = set()
    if not expr.strip():
        return out
    for part in expr.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            a, b = token.split("-", 1)
            if a.strip().isdigit() and b.strip().isdigit():
                start = int(a.strip())
                end = int(b.strip())
                lo, hi = sorted((start, end))
                for ch in range(lo, hi + 1):
                    out.add(ch)
            continue
        if token.isdigit():
            out.add(int(token))
    return out


def _process_chapter(
    tandem: bible_tandem.TandemBible,
    book_code: str,
    chapter: int,
    out_path: Path,
    audit_path: Path,
    issues_log_path: Path,
    model: str,
    mode: str,
    cfg: ValidationConfig,
    max_quotes_per_chapter: int,
    repair_tries: int,
) -> Stats:
    stats = Stats(files=1, chapters=1)
    context = _chapter_context(tandem=tandem, book_code=book_code, chapter=chapter)
    if not context:
        payload = {
            "book_code": book_code,
            "book": bible_sources.BOOK_CODE_TO_EN.get(book_code, book_code),
            "book_he": bible_sources.BOOK_CODE_TO_HE.get(book_code, ""),
            "chapter": chapter,
            "items": [],
        }
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(json.dumps({"results": [], "items_total": 0}, ensure_ascii=False, indent=2), encoding="utf-8")
        return stats

    suggestions: List[Dict] = []
    if mode == "end2end":
        raw_suggestions, call_stats = _end2end_suggestions(
            model=model,
            context=context,
            max_window=cfg.max_window,
            max_quotes=max_quotes_per_chapter,
        )
        stats.llm_calls += int(call_stats["calls"])
        stats.prompt_tokens += int(call_stats["prompt_tokens"])
        stats.response_tokens += int(call_stats["response_tokens"])
        if bool(call_stats["estimated"]):
            stats.estimated_calls += 1
        suggestions = [s for s in raw_suggestions if isinstance(s, dict)]
    else:
        candidates, call_stats = _candidate_suggestions(
            model=model,
            context=context,
            max_window=cfg.max_window,
            max_quotes=max_quotes_per_chapter * 2,
        )
        stats.llm_calls += int(call_stats["calls"])
        stats.prompt_tokens += int(call_stats["prompt_tokens"])
        stats.response_tokens += int(call_stats["response_tokens"])
        if bool(call_stats["estimated"]):
            stats.estimated_calls += 1
        for cand in candidates:
            if not isinstance(cand, dict):
                continue
            finalized, cand_stats = _finalize_candidate(model=model, context=context, candidate=cand)
            stats.llm_calls += int(cand_stats["calls"])
            stats.prompt_tokens += int(cand_stats["prompt_tokens"])
            stats.response_tokens += int(cand_stats["response_tokens"])
            if bool(cand_stats["estimated"]):
                stats.estimated_calls += 1
            suggestions.append(finalized)

    stats.suggestions += len(suggestions)
    audit_results: List[Dict] = []
    kept_items: List[Dict] = []
    issue_lines: List[str] = []
    seen_keys: Set[str] = set()

    for suggestion in suggestions:
        item, fail_reason = _coerce_item_from_suggestion(
            tandem=tandem,
            book_code=book_code,
            chapter=chapter,
            suggestion=suggestion,
            cfg=cfg,
        )
        if item is None:
            stats.dropped_items += 1
            audit_results.append(
                {
                    "action": "drop",
                    "drop_reason": fail_reason,
                    "suggestion": suggestion,
                }
            )
            issue_lines.append(
                json.dumps(
                    {
                        "book_code": book_code,
                        "chapter": chapter,
                        "status": "drop",
                        "drop_reason": fail_reason,
                        "suggestion": suggestion,
                    },
                    ensure_ascii=False,
                )
            )
            continue

        issues = _validate_item(item=item, cfg=cfg)
        repaired = False
        for _ in range(repair_tries):
            if not issues:
                break
            repaired_suggestion, repair_stats = _repair_item(
                model=model,
                context=context,
                item=item,
                issues=issues,
                max_window=cfg.max_window,
            )
            stats.llm_calls += int(repair_stats["calls"])
            stats.prompt_tokens += int(repair_stats["prompt_tokens"])
            stats.response_tokens += int(repair_stats["response_tokens"])
            if bool(repair_stats["estimated"]):
                stats.estimated_calls += 1
            if not repaired_suggestion:
                break
            rebuilt, fail_reason = _coerce_item_from_suggestion(
                tandem=tandem,
                book_code=book_code,
                chapter=chapter,
                suggestion=repaired_suggestion,
                cfg=cfg,
            )
            if rebuilt is None:
                issues = [fail_reason]
                break
            item = rebuilt
            issues = _validate_item(item=item, cfg=cfg)
            repaired = True

        if issues:
            stats.dropped_items += 1
            audit_results.append(
                {
                    "id": item.get("id"),
                    "action": "drop",
                    "drop_reason": ",".join(issues),
                    "issues": issues,
                    "item": item,
                }
            )
            issue_lines.append(
                json.dumps(
                    {
                        "book_code": book_code,
                        "chapter": chapter,
                        "id": item.get("id"),
                        "status": "drop",
                        "issues": issues,
                        "item": item,
                    },
                    ensure_ascii=False,
                )
            )
            continue

        dedupe_key = json.dumps(
            {
                "s": item["source"]["quote_verse_start"],
                "e": item["source"]["quote_verse_end"],
                "re": item["en"]["riddle"].casefold(),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)

        if repaired:
            stats.repaired_items += 1
        stats.kept_items += 1
        kept_items.append(item)
        audit_results.append(
            {
                "id": item.get("id"),
                "action": "keep_repaired" if repaired else "keep",
                "issues": [],
            }
        )
        if len(kept_items) >= max_quotes_per_chapter:
            break

    out_payload = {
        "book_code": book_code,
        "book": bible_sources.BOOK_CODE_TO_EN.get(book_code, book_code),
        "book_he": bible_sources.BOOK_CODE_TO_HE.get(book_code, ""),
        "chapter": chapter,
        "mode": mode,
        "items": kept_items,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    audit_payload = {
        "book_code": book_code,
        "book": bible_sources.BOOK_CODE_TO_EN.get(book_code, book_code),
        "chapter": chapter,
        "items_total": len(suggestions),
        "kept_items": len(kept_items),
        "dropped_items": len(suggestions) - len(kept_items),
        "results": audit_results,
    }
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(audit_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if issue_lines:
        issues_log_path.parent.mkdir(parents=True, exist_ok=True)
        with issues_log_path.open("a", encoding="utf-8") as handle:
            for line in issue_lines:
                handle.write(line + "\n")

    return stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gemma3:27b")
    parser.add_argument("--mode", choices=["end2end", "candidates"], default="end2end")
    parser.add_argument("--book", default="", help="book filter by code or name, e.g. GEN or Genesis")
    parser.add_argument("--chapters", default="", help="chapter filter, e.g. 1-3,12,15")
    parser.add_argument("--limit-chapters", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0, help="alias for --limit-chapters")
    parser.add_argument("--max-window", type=int, default=5)
    parser.add_argument("--max-quotes-per-chapter", type=int, default=4)
    parser.add_argument("--min-quote-tokens", type=int, default=12)
    parser.add_argument("--min-riddle-tokens", type=int, default=4)
    parser.add_argument("--max-riddle-tokens", type=int, default=14)
    parser.add_argument("--min-context-tokens", type=int, default=6)
    parser.add_argument("--repair-tries", type=int, default=2)
    parser.add_argument("--out-dir", default="data/rebuilt_quotes")
    parser.add_argument("--audit-dir", default="data/rebuilt_quotes_audit")
    parser.add_argument("--issues-log", default="data/rebuilt_quotes_issues.jsonl")
    parser.add_argument("--english-xml", default=bible_sources.DEFAULT_ENGLISH_COLLECTION)
    parser.add_argument("--hebrew-zip", default=bible_sources.DEFAULT_HEBREW_ZIP)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.max_window < 1 or args.max_window > 5:
        raise SystemExit("--max-window must be between 1 and 5")
    if args.max_riddle_tokens < args.min_riddle_tokens:
        raise SystemExit("--max-riddle-tokens must be >= --min-riddle-tokens")
    if args.min_context_tokens < 0:
        raise SystemExit("--min-context-tokens must be >= 0")

    english_xml = (ROOT / args.english_xml).resolve()
    hebrew_zip = (ROOT / args.hebrew_zip).resolve()
    out_dir = (ROOT / args.out_dir).resolve()
    audit_dir = (ROOT / args.audit_dir).resolve()
    issues_log = (ROOT / args.issues_log).resolve()

    tqdm.write(f"Loading tandem Bible: en={english_xml} he={hebrew_zip}")
    tandem = bible_tandem.TandemBible.load(english_xml=english_xml, hebrew_zip=hebrew_zip)

    chapter_filter = _parse_chapter_filter(args.chapters)
    chapters: List[Tuple[str, int]] = []
    for code, chapter in tandem.iter_chapters(book_filter=args.book):
        if chapter_filter and chapter not in chapter_filter:
            continue
        chapters.append((code, chapter))
    limit_chapters = args.limit_chapters or args.limit
    if limit_chapters:
        chapters = chapters[: limit_chapters]

    queue: List[Tuple[str, int, Path, Path]] = []
    skipped_existing = 0
    for code, chapter in chapters:
        filename = _chapter_filename(book_code=code, chapter=chapter)
        out_path = out_dir / filename
        audit_path = audit_dir / filename
        if not args.force and out_path.exists() and audit_path.exists():
            skipped_existing += 1
            continue
        queue.append((code, chapter, out_path, audit_path))

    if args.force or not issues_log.exists():
        issues_log.parent.mkdir(parents=True, exist_ok=True)
        issues_log.write_text("", encoding="utf-8")

    tqdm.write(
        f"Rebuild queue: total={len(chapters)} pending={len(queue)} skipped_existing={skipped_existing} "
        f"mode={args.mode}"
    )
    if not queue:
        return 0

    cfg = ValidationConfig(
        max_window=args.max_window,
        min_quote_tokens=args.min_quote_tokens,
        min_riddle_tokens=args.min_riddle_tokens,
        max_riddle_tokens=args.max_riddle_tokens,
        min_context_tokens=args.min_context_tokens,
    )

    total = Stats(skipped_existing=skipped_existing)
    for code, chapter, out_path, audit_path in tqdm(queue, desc=f"rebuild-{args.mode}", unit="chap"):
        try:
            stats = _process_chapter(
                tandem=tandem,
                book_code=code,
                chapter=chapter,
                out_path=out_path,
                audit_path=audit_path,
                issues_log_path=issues_log,
                model=args.model,
                mode=args.mode,
                cfg=cfg,
                max_quotes_per_chapter=args.max_quotes_per_chapter,
                repair_tries=max(0, args.repair_tries),
            )
        except Exception as exc:
            total.errors += 1
            tqdm.write(f"ERROR {code} {chapter}: {exc}")
            continue

        total.files += stats.files
        total.chapters += stats.chapters
        total.suggestions += stats.suggestions
        total.kept_items += stats.kept_items
        total.dropped_items += stats.dropped_items
        total.repaired_items += stats.repaired_items
        total.llm_calls += stats.llm_calls
        total.prompt_tokens += stats.prompt_tokens
        total.response_tokens += stats.response_tokens
        total.estimated_calls += stats.estimated_calls

    tqdm.write(
        "Done: chapters={chapters}, suggestions={suggestions}, kept_items={kept}, dropped_items={dropped}, "
        "repaired_items={repaired}, llm_calls={llm_calls}, prompt_tokens={prompt_tokens}, "
        "response_tokens={response_tokens}, estimated_calls={estimated_calls}, skipped_existing={skipped}, "
        "errors={errors}, out_dir={out_dir}, audit_dir={audit_dir}, issues_log={issues_log}".format(
            chapters=total.chapters,
            suggestions=total.suggestions,
            kept=total.kept_items,
            dropped=total.dropped_items,
            repaired=total.repaired_items,
            llm_calls=total.llm_calls,
            prompt_tokens=total.prompt_tokens,
            response_tokens=total.response_tokens,
            estimated_calls=total.estimated_calls,
            skipped=total.skipped_existing,
            errors=total.errors,
            out_dir=out_dir,
            audit_dir=audit_dir,
            issues_log=issues_log,
        )
    )
    return 1 if total.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
