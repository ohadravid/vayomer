#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from ollama import chat
from tqdm import tqdm

try:
    from data_processing import bible_sources
except ModuleNotFoundError:
    import bible_sources  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[1]

STATUS_OK = "ok"
STATUS_FIX = "fix"
STATUS_DROP = "drop"

HEBREW_CANTILLATION_RE = re.compile(r"[\u0591-\u05AF]")
HEBREW_ALL_MARKS_RE = re.compile(r"[\u0591-\u05C7]")
SPACE_RE = re.compile(r"\s+")
TOKEN_RE = re.compile(r"[a-z0-9\u05D0-\u05EA]+")
HEBREW_PREFIX_CHARS = set("ולבכמשה")
HEBREW_PREFIX_WORDS = {"אל", "ואל"}

GOD_NAME_CANDIDATES_EN: List[List[str]] = [
    ["the", "lord", "god"],
    ["lord", "god"],
    ["the", "lord"],
    ["lord"],
    ["god"],
]

GOD_NAME_CANDIDATES_HE: List[List[str]] = [
    ["אדני", "יהוה"],
    ["יהוה", "אלהים"],
    ["יהוה"],
    ["אדני"],
    ["אלהים"],
]

EN_REPORTING_STARTS = {
    "and",
    "then",
    "he",
    "she",
    "they",
    "said",
    "saith",
    "saying",
}

HE_REPORTING_STARTS = {
    "ויאמר",
    "ויאמרו",
    "ותאמר",
    "ותאמרו",
    "לאמר",
    "נאם",
}

EN_QUESTION_STARTS = {"what", "why", "how", "where", "who", "whence", "when", "whither"}
HE_QUESTION_STARTS = {"מה", "למה", "מדוע", "מי", "מתי", "איך", "האם"}

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
    "הוּא",
    "הִיא",
    "הֵם",
    "הֶם",
    "הֵן",
    "הֶן",
    "אַתָּה",
    "אַתְּ",
    "אַתֶּם",
    "אַתֶּן",
    "אֲנִי",
    "אֲנַחְנוּ",
    "לוֹ",
    "לָהּ",
    "לָהֶם",
    "לָהֶן",
    "אֵלָיו",
    "אֵלַי",
    "אֲלֵיהֶם",
    "אֲלֵיהֶן",
}

FINAL_PROMPT = [
    "You are finalizing Bible quote metadata.",
    "For each item return a status, corrected speaker/listener, and a quote verse range.",
    "Rules:",
    "1) Keep quote range in the same chapter and at most 3 verses.",
    "2) Use concrete normalized names/entities for speaker/listener (not pronouns, not 'a man', not reporting clauses).",
    "3) The speaker name must appear explicitly in the selected quote text in both languages.",
    "3b) Speaker is the entity saying the quoted words; listener is the addressed entity.",
    "3c) If God is speaker/listener, output the fullest in-quote name form (e.g., 'the LORD God', 'אֲדֹנָי יְהוִה', 'יְהוָה אֱלֹהִים').",
    "4) Prefer preserving current range when already valid.",
    "5) Return a short riddle substring for each language that is an exact direct substring of the selected quote text.",
    "5b) Riddle must exclude speaker/listener names, including Hebrew prefixed forms (e.g., לX, בX, אל-X).",
    "5bb) Target roughly 6-14 tokens for the riddle unless the verse cannot support it cleanly.",
    "5c) Prefer one coherent sentence/clause and avoid chaining long multi-clause riddles when a concise clause works.",
    "6) status=ok when current data is already valid; status=fix when changing names/range/riddle; status=drop only when not confidently fixable after trying up to 3-verse expansion.",
    "7) Most items should be fixable. Use drop sparingly.",
    "Return strict JSON only in this shape:",
    '{"results":[{"idx":0,"status":"ok|fix|drop","reason":"...","quote_verse_start":1,"quote_verse_end":1,"speaker_en":"...","listener_en":"...","speaker_he":"...","listener_he":"...","riddle_en":"...","riddle_he":"..."}]}',
]


@dataclass
class Stats:
    files: int = 0
    items: int = 0
    llm_calls: int = 0
    prompt_tokens: int = 0
    response_tokens: int = 0
    estimated_calls: int = 0
    ok: int = 0
    fix: int = 0
    drop: int = 0
    kept_items: int = 0
    dropped_items: int = 0
    fixed_items: int = 0
    skipped_existing: int = 0
    errors: int = 0


def _iter_inputs(path: Path) -> Iterable[Path]:
    if path.is_dir():
        yield from sorted(path.glob("*.json"))
    else:
        yield path


def _clean_text(text: str) -> str:
    return SPACE_RE.sub(" ", text or "").strip()


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


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return len(re.findall(r"\S+", text))


def _sanitize_status(value: object) -> str:
    if isinstance(value, str):
        status = value.strip().lower()
        if status in {STATUS_OK, STATUS_FIX, STATUS_DROP}:
            return status
    return STATUS_DROP


def _sanitize_int(value: object, fallback: int) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return fallback


def _sanitize_name(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return _clean_text(value)


def _norm_en(text: str) -> str:
    return _clean_text(text).casefold()


def _norm_he(text: str) -> str:
    return _clean_text(text)


def _is_suspicious_en(name: str) -> bool:
    value = _norm_en(name)
    if not value:
        return True
    if value in EN_PRONOUNS:
        return True
    if value.startswith(("he ", "she ", "they ", "them ", "him ", "her ", "you ", "thou ", "thee ", "ye ")):
        return True
    if " said " in value or value.startswith("said "):
        return True
    if value == "the god":
        return True
    return False


def _is_suspicious_he(name: str) -> bool:
    value = _norm_he(name)
    if not value:
        return True
    if value in HE_PRONOUNS:
        return True
    if "וַיֹּאמֶר" in value or "ויאמר" in value:
        return True
    return False


def _cleanup_hebrew_quote(text: str) -> str:
    text = _clean_text((text or "").replace("\u034F", ""))
    text = HEBREW_CANTILLATION_RE.sub("", text)
    text = text.replace("׃", "")
    text = text.replace("׀", "")
    text = re.sub(r"\s*־\s*", "־", text)
    return _clean_text(text)


def _normalized_char(ch: str, lang: str) -> str:
    if lang == "he":
        if ch in {"-", "־"}:
            return " "
        if HEBREW_ALL_MARKS_RE.match(ch):
            return ""
        if ch == "\u034F":
            return ""
        if "\u05D0" <= ch <= "\u05EA":
            return ch
        if ch.isalnum():
            return ch.lower()
        return " "
    if ch.isalnum():
        return ch.lower()
    return " "


def _normalized_with_index(text: str, lang: str) -> Tuple[str, List[int]]:
    out_chars: List[str] = []
    out_indices: List[int] = []
    prev_space = True

    for idx, ch in enumerate(text):
        norm = _normalized_char(ch, lang)
        if not norm:
            continue
        if norm == " ":
            if prev_space:
                continue
            out_chars.append(" ")
            out_indices.append(idx)
            prev_space = True
            continue
        out_chars.append(norm)
        out_indices.append(idx)
        prev_space = False

    while out_chars and out_chars[0] == " ":
        out_chars.pop(0)
        out_indices.pop(0)
    while out_chars and out_chars[-1] == " ":
        out_chars.pop()
        out_indices.pop()

    return "".join(out_chars), out_indices


def _tokenize_with_spans(text: str, lang: str) -> List[Tuple[str, int, int]]:
    normalized, indices = _normalized_with_index(text, lang)
    if not normalized:
        return []

    tokens: List[Tuple[str, int, int]] = []
    for match in TOKEN_RE.finditer(normalized):
        start, end = match.span()
        if start >= len(indices) or end - 1 >= len(indices):
            continue
        orig_start = indices[start]
        orig_end = indices[end - 1] + 1
        tokens.append((match.group(), orig_start, orig_end))
    return tokens


def _tokenize_for_match(text: str, lang: str) -> List[str]:
    normalized, _ = _normalized_with_index(text, lang)
    if not normalized:
        return []
    return [match.group() for match in TOKEN_RE.finditer(normalized)]


def _find_subsequence(haystack: List[str], needle: List[str]) -> Optional[int]:
    if not haystack or not needle or len(needle) > len(haystack):
        return None
    limit = len(haystack) - len(needle) + 1
    for idx in range(limit):
        if haystack[idx : idx + len(needle)] == needle:
            return idx
    return None


def _token_match_with_prefix(token: str, entity_token: str, lang: str, allow_prefix: bool) -> bool:
    if token == entity_token:
        return True
    if lang != "he" or not allow_prefix:
        return False
    if not token.endswith(entity_token):
        return False
    prefix = token[: len(token) - len(entity_token)]
    if not prefix:
        return True
    if prefix in HEBREW_PREFIX_WORDS:
        return True
    return all(ch in HEBREW_PREFIX_CHARS for ch in prefix)


def _find_entity_subsequence(haystack: List[str], needle: List[str], lang: str) -> Optional[int]:
    if not haystack or not needle or len(needle) > len(haystack):
        return None
    limit = len(haystack) - len(needle) + 1
    for idx in range(limit):
        ok = True
        for j, entity_token in enumerate(needle):
            token = haystack[idx + j]
            allow_prefix = lang == "he" and j == 0
            if not _token_match_with_prefix(token, entity_token, lang=lang, allow_prefix=allow_prefix):
                ok = False
                break
        if ok:
            return idx
    return None


def _extract_token_sequence_from_quote(quote: str, seq_tokens: List[str], lang: str) -> Optional[str]:
    if not quote or not seq_tokens:
        return None
    spans = _tokenize_with_spans(quote, lang)
    if not spans:
        return None
    quote_tokens = [tok for tok, _, _ in spans]
    idx = _find_subsequence(quote_tokens, seq_tokens)
    if idx is None:
        return None
    start = spans[idx][1]
    end = spans[idx + len(seq_tokens) - 1][2]
    if lang == "he":
        while start > 0 and HEBREW_ALL_MARKS_RE.match(quote[start - 1]):
            start -= 1
        while end < len(quote) and HEBREW_ALL_MARKS_RE.match(quote[end]):
            end += 1
    return _clean_text(quote[start:end])


def _is_god_like_entity(entity: str, lang: str) -> bool:
    tokens = _tokenize_for_match(entity, lang)
    if not tokens:
        return False
    if lang == "en":
        return any(tok in {"lord", "god"} for tok in tokens)
    return any(tok in {"יהוה", "אלהים", "אדני"} for tok in tokens)


def _best_god_name_in_quote(quote: str, lang: str) -> Optional[str]:
    candidates = GOD_NAME_CANDIDATES_EN if lang == "en" else GOD_NAME_CANDIDATES_HE
    for seq in candidates:
        match = _extract_token_sequence_from_quote(quote, seq, lang)
        if match:
            return match
    return None


def _riddle_mentions_entities(riddle: str, speaker: str, listener: str, lang: str) -> bool:
    riddle_tokens = _tokenize_for_match(riddle, lang)
    if not riddle_tokens:
        return False
    speaker_tokens = _tokenize_for_match(speaker, lang)
    listener_tokens = _tokenize_for_match(listener, lang)
    if speaker_tokens and _find_entity_subsequence(riddle_tokens, speaker_tokens, lang) is not None:
        return True
    if listener_tokens and _find_entity_subsequence(riddle_tokens, listener_tokens, lang) is not None:
        return True
    speaker_god = _is_god_like_entity(speaker, lang)
    listener_god = _is_god_like_entity(listener, lang)
    if speaker_god or listener_god:
        if lang == "en":
            if any(tok in {"lord", "god"} for tok in riddle_tokens):
                return True
        else:
            if any(tok in {"יהוה", "אלהים", "אדני"} for tok in riddle_tokens):
                return True
    return False


def _riddle_needs_refine(riddle: str, lang: str) -> bool:
    tokens = _tokenize_for_match(riddle, lang)
    if not tokens:
        return False
    if len(tokens) > 14:
        return True
    first = tokens[0]
    if lang == "en":
        if first in EN_REPORTING_STARTS:
            return True
        if tokens.count("why") >= 2:
            return True
    else:
        if first in HE_REPORTING_STARTS:
            return True
        if tokens.count("למה") >= 2:
            return True
    return False


def _extract_substring_from_quote(quote: str, text: str, lang: str) -> Optional[str]:
    if not quote or not text:
        return None

    candidates = [text]
    if lang == "en":
        stripped = re.sub(r"^(?:the|a|an|o|ye)\s+", "", text, flags=re.I).strip()
        if stripped and stripped != text:
            candidates.append(stripped)

    quote_tokens = _tokenize_with_spans(quote, lang)
    if not quote_tokens:
        return None
    quote_only_tokens = [tok for tok, _, _ in quote_tokens]

    for candidate in candidates:
        if candidate in quote:
            return candidate

        text_tokens = _tokenize_for_match(candidate, lang)
        if not text_tokens:
            continue

        idx = _find_subsequence(quote_only_tokens, text_tokens)
        if idx is None:
            continue

        start = quote_tokens[idx][1]
        end = quote_tokens[idx + len(text_tokens) - 1][2]
        if lang == "he":
            while start > 0 and HEBREW_ALL_MARKS_RE.match(quote[start - 1]):
                start -= 1
            while end < len(quote) and HEBREW_ALL_MARKS_RE.match(quote[end]):
                end += 1
        return _clean_text(quote[start:end])

    return None


def _fallback_riddle_from_quote(
    quote: str,
    speaker: str,
    listener: str,
    lang: str,
    min_tokens: int = 4,
    max_tokens: int = 12,
) -> Optional[str]:
    spans = _tokenize_with_spans(quote, lang)
    if not spans:
        return None

    tokens = [token for token, _, _ in spans]
    if not tokens:
        return None

    speaker_tokens = _tokenize_for_match(speaker, lang)
    listener_tokens = _tokenize_for_match(listener, lang)
    speaker_god = _is_god_like_entity(speaker, lang)
    listener_god = _is_god_like_entity(listener, lang)

    def _window_has_entities(window_tokens: List[str]) -> bool:
        if speaker_tokens and _find_entity_subsequence(window_tokens, speaker_tokens, lang) is not None:
            return True
        if listener_tokens and _find_entity_subsequence(window_tokens, listener_tokens, lang) is not None:
            return True
        if speaker_god or listener_god:
            if lang == "en":
                if any(tok in {"lord", "god"} for tok in window_tokens):
                    return True
            else:
                if any(tok in {"יהוה", "אלהים", "אדני"} for tok in window_tokens):
                    return True
        return False

    n = len(spans)
    lo = min(min_tokens, n)
    hi = min(max_tokens, n)

    for size in range(hi, lo - 1, -1):
        starts = list(range(0, n - size + 1))
        if lang == "en":
            starts.sort(key=lambda s: (0 if tokens[s] in EN_QUESTION_STARTS else 1, s))
        else:
            starts.sort(key=lambda s: (0 if tokens[s] in HE_QUESTION_STARTS else 1, s))

        for start in starts:
            end = start + size
            window_tokens = tokens[start:end]
            first = window_tokens[0]
            if lang == "en" and first in EN_REPORTING_STARTS:
                continue
            if lang == "he" and first in HE_REPORTING_STARTS:
                continue
            if _window_has_entities(window_tokens):
                continue
            orig_start = spans[start][1]
            orig_end = spans[end - 1][2]
            candidate = _clean_text(quote[orig_start:orig_end])
            if candidate:
                return candidate

    start = max(0, (n - hi) // 2)
    end = start + hi
    candidate = _clean_text(quote[spans[start][1] : spans[end - 1][2]])
    return candidate or None


def _entity_in_quote(entity: str, quote: str, lang: str) -> bool:
    if not entity or not quote:
        return False
    if entity in quote:
        return True
    quote_tokens = _tokenize_for_match(quote, lang)
    entity_tokens = _tokenize_for_match(entity, lang)
    if not quote_tokens or not entity_tokens:
        return False
    return _find_entity_subsequence(quote_tokens, entity_tokens, lang) is not None


def _get_ref_range(item: Dict) -> Tuple[Optional[str], Optional[int], Optional[int], Optional[int]]:
    source = item.get("source", {})
    ref_start = source.get("ref_start")
    ref_end = source.get("ref_end")
    if not isinstance(ref_start, str) or not isinstance(ref_end, str):
        return None, None, None, None
    try:
        book_s, chapter_s, verse_s = bible_sources.parse_reference(ref_start)
        book_e, chapter_e, verse_e = bible_sources.parse_reference(ref_end)
    except ValueError:
        return None, None, None, None
    if book_s != book_e or chapter_s != chapter_e:
        return None, None, None, None
    return book_s, chapter_s, min(verse_s, verse_e), max(verse_s, verse_e)


def _chapter_context(
    code: str,
    chapter: int,
    english_map: bible_sources.VerseMap,
    hebrew_map: bible_sources.VerseMap,
) -> List[Dict]:
    verse_nums = sorted(
        {
            verse
            for (v_code, v_chapter, verse), text in english_map.items()
            if v_code == code and v_chapter == chapter and text and hebrew_map.get((v_code, v_chapter, verse))
        }
    )
    return [
        {
            "v": verse,
            "en": english_map[(code, chapter, verse)],
            "he": hebrew_map[(code, chapter, verse)],
        }
        for verse in verse_nums
    ]


def _build_input(item: Dict, idx: int, start: int, end: int) -> Dict:
    return {
        "idx": idx,
        "id": item.get("id"),
        "quote_verse_start": start,
        "quote_verse_end": end,
        "speaker_en": item.get("en", {}).get("speaker"),
        "listener_en": item.get("en", {}).get("listener"),
        "speaker_he": item.get("he", {}).get("speaker"),
        "listener_he": item.get("he", {}).get("listener"),
        "riddle_en": item.get("en", {}).get("riddle"),
        "riddle_he": item.get("he", {}).get("riddle"),
        "quote_en": item.get("en", {}).get("quote"),
        "quote_he": item.get("he", {}).get("quote"),
    }


def _call_llm_for_items(
    model: str,
    context: List[Dict],
    inputs: List[Dict],
) -> Tuple[List[Dict], Dict[str, int | bool]]:
    base_prompt = {
        "context_verses": context,
        "items": inputs,
        "instructions": FINAL_PROMPT,
    }

    total_prompt_tokens = 0
    total_response_tokens = 0
    estimated_calls = 0
    attempts = 0
    last_error: Optional[Exception] = None

    for attempt in range(1, 4):
        prompt = dict(base_prompt)
        if attempt > 1:
            prompt["strict_json_retry"] = (
                "Previous output was invalid. Return strict JSON only, parsable with json.loads."
            )

        response = chat(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": json.dumps(prompt, ensure_ascii=False),
                }
            ],
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
            payload = _parse_json_payload(content)
            results = payload.get("results", [])
            if not isinstance(results, list):
                raise ValueError("LLM output missing results list")
            return results, {
                "prompt_tokens": total_prompt_tokens,
                "response_tokens": total_response_tokens,
                "estimated": bool(estimated_calls > 0),
                "calls": attempts,
            }
        except Exception as exc:  # noqa: PERF203
            last_error = exc
            continue

    raise ValueError(f"LLM JSON parse failed after {attempts} attempts: {last_error}")


def _apply_candidate(
    item: Dict,
    suggestion: Dict,
    english_map: bible_sources.VerseMap,
    hebrew_map: bible_sources.VerseMap,
) -> Tuple[bool, Dict, str]:
    book, chapter, cur_start, cur_end = _get_ref_range(item)
    if not book or chapter is None or cur_start is None or cur_end is None:
        return False, item, "bad_reference"

    start = _sanitize_int(suggestion.get("quote_verse_start"), cur_start)
    end = _sanitize_int(suggestion.get("quote_verse_end"), cur_end)
    if start <= 0 or end <= 0:
        return False, item, "bad_range"
    if start > end:
        start, end = end, start
    if end - start + 1 > 3:
        return False, item, "range_too_long"

    code = bible_sources.BOOK_NAME_TO_CODE.get(book)
    if not code:
        return False, item, "unknown_book"

    quote_en, quote_he_raw, missing = bible_sources.collect_range_text(
        code=code,
        chapter=chapter,
        start=start,
        end=end,
        english_map=english_map,
        hebrew_map=hebrew_map,
    )
    if missing or not quote_en or not quote_he_raw:
        return False, item, "missing_source_verses"

    quote_he = _cleanup_hebrew_quote(quote_he_raw)
    if not quote_he:
        return False, item, "empty_hebrew_quote"

    new_item = json.loads(json.dumps(item, ensure_ascii=False))
    en = dict(new_item.get("en", {}))
    he = dict(new_item.get("he", {}))
    source = dict(new_item.get("source", {}))

    speaker_en = _sanitize_name(suggestion.get("speaker_en")) or _sanitize_name(en.get("speaker"))
    listener_en = _sanitize_name(suggestion.get("listener_en")) or _sanitize_name(en.get("listener"))
    speaker_he = _sanitize_name(suggestion.get("speaker_he")) or _sanitize_name(he.get("speaker"))
    listener_he = _sanitize_name(suggestion.get("listener_he")) or _sanitize_name(he.get("listener"))

    speaker_en_aligned = _extract_substring_from_quote(quote_en, speaker_en, "en")
    speaker_he_aligned = _extract_substring_from_quote(quote_he, speaker_he, "he")
    listener_en_aligned = _extract_substring_from_quote(quote_en, listener_en, "en")
    listener_he_aligned = _extract_substring_from_quote(quote_he, listener_he, "he")

    if speaker_en_aligned:
        speaker_en = speaker_en_aligned
    if speaker_he_aligned:
        speaker_he = speaker_he_aligned
    if listener_en_aligned:
        listener_en = listener_en_aligned
    if listener_he_aligned:
        listener_he = listener_he_aligned

    if _is_god_like_entity(speaker_en, "en"):
        best = _best_god_name_in_quote(quote_en, "en")
        if best:
            speaker_en = best
    if _is_god_like_entity(listener_en, "en"):
        best = _best_god_name_in_quote(quote_en, "en")
        if best:
            listener_en = best
    if _is_god_like_entity(speaker_he, "he"):
        best = _best_god_name_in_quote(quote_he, "he")
        if best:
            speaker_he = best
    if _is_god_like_entity(listener_he, "he"):
        best = _best_god_name_in_quote(quote_he, "he")
        if best:
            listener_he = best

    speaker_in_en = _entity_in_quote(speaker_en, quote_en, "en")
    speaker_in_he = _entity_in_quote(speaker_he, quote_he, "he")
    if not speaker_in_en or not speaker_in_he:
        listener_in_en = _entity_in_quote(listener_en, quote_en, "en")
        listener_in_he = _entity_in_quote(listener_he, quote_he, "he")
        if listener_in_en and listener_in_he:
            speaker_en, listener_en = listener_en, speaker_en
            speaker_he, listener_he = listener_he, speaker_he
            if _is_god_like_entity(speaker_en, "en"):
                best = _best_god_name_in_quote(quote_en, "en")
                if best:
                    speaker_en = best
            if _is_god_like_entity(listener_en, "en"):
                best = _best_god_name_in_quote(quote_en, "en")
                if best:
                    listener_en = best
            if _is_god_like_entity(speaker_he, "he"):
                best = _best_god_name_in_quote(quote_he, "he")
                if best:
                    speaker_he = best
            if _is_god_like_entity(listener_he, "he"):
                best = _best_god_name_in_quote(quote_he, "he")
                if best:
                    listener_he = best
            speaker_in_en = _entity_in_quote(speaker_en, quote_en, "en")
            speaker_in_he = _entity_in_quote(speaker_he, quote_he, "he")

    if _is_suspicious_en(speaker_en) or _is_suspicious_en(listener_en):
        return False, item, "bad_english_entities"
    if _is_suspicious_he(speaker_he) or _is_suspicious_he(listener_he):
        return False, item, "bad_hebrew_entities"

    if not speaker_in_en:
        return False, item, "speaker_en_not_in_quote"
    if not speaker_in_he:
        return False, item, "speaker_he_not_in_quote"

    riddle_en_input = _sanitize_name(suggestion.get("riddle_en")) or _sanitize_name(en.get("riddle"))
    riddle_he_input = _sanitize_name(suggestion.get("riddle_he")) or _sanitize_name(he.get("riddle"))
    riddle_en = _extract_substring_from_quote(quote_en, riddle_en_input, "en")
    riddle_he = _extract_substring_from_quote(quote_he, riddle_he_input, "he")
    if (
        not riddle_en
        or _riddle_mentions_entities(riddle_en, speaker_en, listener_en, "en")
        or _riddle_needs_refine(riddle_en, "en")
    ):
        riddle_en = _fallback_riddle_from_quote(
            quote=quote_en,
            speaker=speaker_en,
            listener=listener_en,
            lang="en",
        )
    if (
        not riddle_he
        or _riddle_mentions_entities(riddle_he, speaker_he, listener_he, "he")
        or _riddle_needs_refine(riddle_he, "he")
    ):
        riddle_he = _fallback_riddle_from_quote(
            quote=quote_he,
            speaker=speaker_he,
            listener=listener_he,
            lang="he",
        )
    if not riddle_en:
        return False, item, "riddle_en_not_substring"
    if not riddle_he:
        return False, item, "riddle_he_not_substring"
    if _riddle_mentions_entities(riddle_en, speaker_en, listener_en, "en"):
        return False, item, "riddle_en_mentions_entities"
    if _riddle_mentions_entities(riddle_he, speaker_he, listener_he, "he"):
        return False, item, "riddle_he_mentions_entities"

    en["quote"] = quote_en
    en["riddle"] = riddle_en
    en["speaker"] = speaker_en
    en["listener"] = listener_en
    en["book"] = book

    he["quote"] = quote_he
    he["riddle"] = riddle_he
    he["speaker"] = speaker_he
    he["listener"] = listener_he
    he["book"] = bible_sources.BOOK_CODE_TO_HE.get(code, he.get("book", ""))

    source["ref_start"] = f"{book} {chapter}:{start}"
    source["ref_end"] = f"{book} {chapter}:{end}"
    source["line_start"] = start
    source["line_end"] = end

    new_item["en"] = en
    new_item["he"] = he
    new_item["source"] = source
    return True, new_item, ""


def _build_result(raw: Dict, fallback_item: Dict, idx: int) -> Dict:
    _, _, start, end = _get_ref_range(fallback_item)
    return {
        "idx": idx,
        "id": fallback_item.get("id"),
        "status": _sanitize_status(raw.get("status")),
        "reason": _sanitize_name(raw.get("reason")),
        "quote_verse_start": raw.get("quote_verse_start", start),
        "quote_verse_end": raw.get("quote_verse_end", end),
        "speaker_en": _sanitize_name(raw.get("speaker_en")),
        "listener_en": _sanitize_name(raw.get("listener_en")),
        "speaker_he": _sanitize_name(raw.get("speaker_he")),
        "listener_he": _sanitize_name(raw.get("listener_he")),
        "riddle_en": _sanitize_name(raw.get("riddle_en")),
        "riddle_he": _sanitize_name(raw.get("riddle_he")),
    }


def _build_fallback_suggestions(item: Dict) -> List[Dict]:
    _, _, start, end = _get_ref_range(item)
    if start is None or end is None:
        return []

    en = item.get("en", {})
    he = item.get("he", {})
    base = {
        "speaker_en": _sanitize_name(en.get("speaker")),
        "listener_en": _sanitize_name(en.get("listener")),
        "speaker_he": _sanitize_name(he.get("speaker")),
        "listener_he": _sanitize_name(he.get("listener")),
        "riddle_en": _sanitize_name(en.get("riddle")),
        "riddle_he": _sanitize_name(he.get("riddle")),
    }

    windows: List[Tuple[int, int]] = []
    span = end - start + 1
    if span <= 3:
        windows.append((start, end))
    else:
        for size in (3, 2, 1):
            limit = end - size + 1
            for s in range(start, limit + 1):
                windows.append((s, s + size - 1))

    out: List[Dict] = []
    for s, e in windows:
        suggestion = dict(base)
        suggestion["quote_verse_start"] = s
        suggestion["quote_verse_end"] = e
        out.append(suggestion)
    return out


def _process_file(
    path: Path,
    out_path: Path,
    audit_path: Path,
    issue_log_path: Path,
    model: str,
    english_map: bible_sources.VerseMap,
    hebrew_map: bible_sources.VerseMap,
) -> Stats:
    data = json.loads(path.read_text(encoding="utf-8"))
    items: List[Dict] = data.get("items", [])
    stats = Stats(files=1, items=len(items))

    if not items:
        audit_payload = {"file": str(path), "items_total": 0, "results": []}
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(json.dumps(audit_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return stats

    by_chapter: Dict[Tuple[str, int], List[Tuple[int, Dict]]] = {}
    results_by_idx: Dict[int, Dict] = {}

    for idx, item in enumerate(items):
        book, chapter, start, end = _get_ref_range(item)
        if not book or chapter is None or start is None or end is None:
            results_by_idx[idx] = {
                "idx": idx,
                "id": item.get("id"),
                "status": STATUS_DROP,
                "reason": "bad_or_missing_reference",
            }
            continue
        by_chapter.setdefault((book, chapter), []).append((idx, item))

    for (book, chapter), chapter_items in by_chapter.items():
        code = bible_sources.BOOK_NAME_TO_CODE.get(book)
        if not code:
            for idx, item in chapter_items:
                results_by_idx[idx] = {
                    "idx": idx,
                    "id": item.get("id"),
                    "status": STATUS_DROP,
                    "reason": f"unknown_book:{book}",
                }
            continue

        context = _chapter_context(code, chapter, english_map, hebrew_map)
        inputs: List[Dict] = []
        for idx, item in chapter_items:
            _, _, start, end = _get_ref_range(item)
            assert start is not None and end is not None
            inputs.append(_build_input(item=item, idx=idx, start=start, end=end))

        llm_results, call_stats = _call_llm_for_items(model=model, context=context, inputs=inputs)
        stats.llm_calls += int(call_stats.get("calls", 1))
        stats.prompt_tokens += int(call_stats["prompt_tokens"])
        stats.response_tokens += int(call_stats["response_tokens"])
        if bool(call_stats["estimated"]):
            stats.estimated_calls += 1

        for raw in llm_results:
            idx = _sanitize_int(raw.get("idx"), -1)
            if idx < 0 or idx >= len(items):
                continue
            results_by_idx[idx] = _build_result(raw=raw, fallback_item=items[idx], idx=idx)

    for idx, item in enumerate(items):
        if idx not in results_by_idx:
            results_by_idx[idx] = {
                "idx": idx,
                "id": item.get("id"),
                "status": STATUS_DROP,
                "reason": "missing_llm_result",
            }

    kept_items: List[Dict] = []
    audit_results: List[Dict] = []
    issue_lines: List[str] = []

    for idx, item in enumerate(items):
        result = results_by_idx[idx]
        status = _sanitize_status(result.get("status"))
        reason = _sanitize_name(result.get("reason"))

        if status == STATUS_OK:
            stats.ok += 1
        elif status == STATUS_FIX:
            stats.fix += 1
        else:
            stats.drop += 1

        kept = False
        action = "drop"
        action_reason = reason or "status_drop"
        fixed = False
        kept_from = ""
        applied_item: Optional[Dict] = None

        attempts: List[Tuple[str, Dict]] = [("llm", result)]
        llm_key = json.dumps(result, sort_keys=True, ensure_ascii=False)
        seen = {llm_key}
        for fallback in _build_fallback_suggestions(item):
            key = json.dumps(fallback, sort_keys=True, ensure_ascii=False)
            if key in seen:
                continue
            seen.add(key)
            attempts.append(("fallback", fallback))

        failure_reason = ""
        for source_kind, suggestion in attempts:
            applied, candidate_item, failure_reason = _apply_candidate(
                item=item,
                suggestion=suggestion,
                english_map=english_map,
                hebrew_map=hebrew_map,
            )
            if applied:
                applied_item = candidate_item
                kept = True
                kept_from = source_kind
                break

        if kept and applied_item is not None:
            kept_items.append(applied_item)
            action = "keep"
            action_reason = ""
            fixed = json.dumps(applied_item, ensure_ascii=False, sort_keys=True) != json.dumps(
                item, ensure_ascii=False, sort_keys=True
            )
        else:
            action_reason = failure_reason or action_reason

        if kept:
            if kept_from == "fallback":
                action = "keep_fallback"
            else:
                action = "keep"

        if kept:
            stats.kept_items += 1
            if fixed:
                stats.fixed_items += 1
        else:
            stats.dropped_items += 1
            issue_lines.append(
                json.dumps(
                    {
                        "file": str(path),
                        "id": item.get("id"),
                        "status": status,
                        "reason": reason,
                        "drop_reason": action_reason,
                        "suggested": result,
                    },
                    ensure_ascii=False,
                )
            )

        audit_results.append(
            {
                "idx": idx,
                "id": item.get("id"),
                "status": status,
                "reason": reason,
                "action": action,
                "drop_reason": action_reason,
                "suggested": result,
            }
        )

    if issue_lines:
        issue_log_path.parent.mkdir(parents=True, exist_ok=True)
        with issue_log_path.open("a", encoding="utf-8") as handle:
            for line in issue_lines:
                handle.write(line + "\n")

    out_payload = dict(data)
    out_payload["items"] = kept_items
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    audit_payload = {
        "file": str(path),
        "items_total": len(items),
        "ok": stats.ok,
        "fix": stats.fix,
        "drop": stats.drop,
        "kept_items": stats.kept_items,
        "dropped_items": stats.dropped_items,
        "fixed_items": stats.fixed_items,
        "results": audit_results,
    }
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(audit_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", default="data/quotes", help="input quote JSON file or directory")
    parser.add_argument("--model", default="gemma3:27b")
    parser.add_argument("--out-dir", default="data/final_quotes")
    parser.add_argument("--audit-dir", default="data/final_quote_audit")
    parser.add_argument("--issues-log", default="data/final_quote_issues.jsonl")
    parser.add_argument("--english-xml", default=bible_sources.DEFAULT_ENGLISH_COLLECTION)
    parser.add_argument("--hebrew-zip", default=bible_sources.DEFAULT_HEBREW_ZIP)
    parser.add_argument("--limit", type=int, default=0, help="max pending files to process (0 = all)")
    parser.add_argument("--force", action="store_true", help="reprocess files even if outputs already exist")
    args = parser.parse_args()

    target = (ROOT / args.path).resolve()
    out_dir = (ROOT / args.out_dir).resolve()
    audit_dir = (ROOT / args.audit_dir).resolve()
    issues_log = (ROOT / args.issues_log).resolve()
    english_xml = (ROOT / args.english_xml).resolve()
    hebrew_zip = (ROOT / args.hebrew_zip).resolve()

    tqdm.write(f"Loading English verses: {english_xml}")
    english_map = bible_sources.load_english_verse_map(english_xml)
    tqdm.write(f"Loading Hebrew verses: {hebrew_zip}")
    hebrew_map = bible_sources.load_tanach_zip_verse_map(hebrew_zip)

    paths = list(_iter_inputs(target))
    queue: List[Path] = []
    skipped_existing = 0
    for path in paths:
        out_path = out_dir / path.name
        audit_path = audit_dir / path.name
        exists = out_path.exists() and audit_path.exists()
        if exists and not args.force:
            skipped_existing += 1
            continue
        queue.append(path)

    if args.limit:
        queue = queue[: args.limit]

    if args.force or not issues_log.exists():
        issues_log.parent.mkdir(parents=True, exist_ok=True)
        issues_log.write_text("", encoding="utf-8")

    tqdm.write(
        f"Finalize queue: total={len(paths)} pending={len(queue)} skipped_existing={skipped_existing} "
        f"limit={args.limit or 'all'}"
    )
    if not queue:
        return 0

    total = Stats(skipped_existing=skipped_existing)
    for path in tqdm(queue, desc="finalize-quotes", unit="file"):
        out_path = out_dir / path.name
        audit_path = audit_dir / path.name
        try:
            stats = _process_file(
                path=path,
                out_path=out_path,
                audit_path=audit_path,
                issue_log_path=issues_log,
                model=args.model,
                english_map=english_map,
                hebrew_map=hebrew_map,
            )
        except Exception as exc:
            total.errors += 1
            tqdm.write(f"ERROR {path}: {exc}")
            continue

        total.files += stats.files
        total.items += stats.items
        total.llm_calls += stats.llm_calls
        total.prompt_tokens += stats.prompt_tokens
        total.response_tokens += stats.response_tokens
        total.estimated_calls += stats.estimated_calls
        total.ok += stats.ok
        total.fix += stats.fix
        total.drop += stats.drop
        total.kept_items += stats.kept_items
        total.dropped_items += stats.dropped_items
        total.fixed_items += stats.fixed_items

    tqdm.write(
        "Done: files={files}, items={items}, ok={ok}, fix={fix}, drop={drop}, kept_items={kept}, "
        "dropped_items={dropped}, fixed_items={fixed}, llm_calls={llm_calls}, "
        "prompt_tokens={prompt_tokens}, response_tokens={response_tokens}, estimated_calls={estimated}, "
        "skipped_existing={skipped_existing}, errors={errors}, out_dir={out_dir}, audit_dir={audit_dir}, "
        "issues_log={issues_log}".format(
            files=total.files,
            items=total.items,
            ok=total.ok,
            fix=total.fix,
            drop=total.drop,
            kept=total.kept_items,
            dropped=total.dropped_items,
            fixed=total.fixed_items,
            llm_calls=total.llm_calls,
            prompt_tokens=total.prompt_tokens,
            response_tokens=total.response_tokens,
            estimated=total.estimated_calls,
            skipped_existing=total.skipped_existing,
            errors=total.errors,
            out_dir=out_dir,
            audit_dir=audit_dir,
            issues_log=issues_log,
        )
    )
    return 1 if total.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
