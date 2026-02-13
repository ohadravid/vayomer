#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from ollama import chat
from tqdm import tqdm

try:
    from data_processing import text_cleanup
except ModuleNotFoundError:
    import text_cleanup  # type: ignore[no-redef]

# Responsibility split for this pipeline:
# - Python code should enforce deterministic/mechanical guarantees only:
#   data shape, verse ranges, substring checks, token thresholds, dedupe, and file IO.
# - LLM should handle semantic judgments:
#   whether interaction quality is meaningful, whether speaker/listener are sensible,
#   and whether a listener is truly being addressed.
# - Do not hardcode semantic world-knowledge lists in Python (for example specific
#   listeners like "land"/"earth"); those decisions belong to LLM prompts + validation flow.

ROOT = Path(__file__).resolve().parents[1]

BONUS_PICK_PROMPT = [
    "You are selecting one bonus word for a bilingual Bible quote puzzle.",
    "Return strict JSON only with shape:",
    '{"bonus_en_idx":0,"bonus_he_idx":0,"reason":"..."}',
    "Rules:",
    "1) Choose ONE English word and ONE Hebrew word representing the SAME concept in this quote pair.",
    "2) Choose ONLY by index from candidate_bonus_en/candidate_bonus_he arrays.",
    "3) bonus_en must NOT appear in riddle_en; bonus_he must NOT appear in riddle_he.",
    "4) Prefer words that are interesting, important, funny, or dramatic.",
    "5) Keep it short: ideally one word in each language.",
    "6) Never paraphrase or invent words that are not in candidates.",
]

BONUS_CONCEPT_CHECK_PROMPT = [
    "You are validating whether two selected bonus words match semantically across English and Hebrew.",
    "Return strict JSON only with shape:",
    '{"same_concept":true,"reason":"..."}',
    "Rules:",
    "1) Judge in context of quote_en and quote_he.",
    "2) same_concept=true only if bonus_en and bonus_he represent the same concept/event/entity in this quote.",
    "3) If uncertain, return same_concept=false.",
]

ITEM_KEEP_PROMPT = [
    "You are validating one generated quote interaction before bonus-word generation.",
    "Return strict JSON only with shape:",
    '{"status":"keep|drop","reason":"...","checks":{"is_direct_speech":true,"speaker_solvable":true,"listener_solvable":true}}',
    "Rules:",
    "1) Keep only if this is a true direct-address interaction with a clear speaker and a clear addressed listener.",
    "2) Drop if the listener is not actually being addressed in the quote (for example narrative setup or world/state commands).",
    "3) Drop if speaker/listener are not solvable entities for the game (for example unresolved pronouns like 'him').",
    "4) If the quote is like 'And God said, Let the earth ...', drop unless listener is truly an addressed interlocutor.",
    "5) If the quote is like 'And Adam said, This is now ...', drop unless there is a clear addressed listener in the quote.",
    "6) Use semantic judgment from quote/riddle in both EN/HE; do not rely on fixed keyword lists.",
    "7) Be conservative: if unclear, drop.",
]

DIRECTION_CHECK_PROMPT = [
    "You are checking directionality for one quote interaction.",
    "Return strict JSON only with shape:",
    '{"checks":{"speaker_told_riddle_to_listener":true,"listener_told_riddle_to_speaker":false,"other_entity_told_riddle_to_listener":false},"reason":"..."}',
    "Answer these independently from quote + riddle context:",
    "1) Did speaker tell the riddle-content to listener in this interaction?",
    "2) Did listener tell the riddle-content to speaker (reverse direction)?",
    "3) Did some other entity (not the labeled speaker) tell this riddle-content to the labeled listener?",
    "Rules:",
    "4) Mark true only when clearly supported by the quote.",
    "5) If uncertain, prefer false.",
]

INTERACTION_FILTER_EXAMPLES = [
    {
        "name": "creation_command_not_dialogue",
        "expected": "drop",
        "item_en": {
            "quote": "And God said, Let the earth bring forth grass, the herb yielding seed, and the fruit tree yielding fruit after his kind, whose seed is in itself, upon the earth: and it was so.",
            "riddle": "bring forth grass, the herb yielding seed",
            "speaker": "God",
            "listener": "earth",
        },
        "note": "Creation command to world/object is not a solvable speaker->listener dialogue interaction for this game.",
    },
    {
        "name": "adam_statement_not_addressed_listener",
        "expected": "drop",
        "item_en": {
            "quote": "And Adam said, This is now bone of my bones, and flesh of my flesh: she shall be called Woman, because she was taken out of Man. Therefore shall a man leave his father and his mother, and shall cleave unto his wife: and they shall be one flesh.",
            "riddle": "This is now bone of my bones",
            "speaker": "Adam",
            "listener": "Woman",
        },
        "note": "Narrative/declarative statement without clear addressed listener should be dropped.",
    },
    {
        "name": "unsolvable_pronoun_listener",
        "expected": "drop",
        "item_en": {
            "quote": "And they that went in, went in male and female of all flesh, as God had commanded him: and the LORD shut him in.",
            "riddle": "that went in, went in male and female of all",
            "speaker": "the LORD",
            "listener": "him",
        },
        "note": "Pronoun listener is unsolvable and should be dropped.",
    },
    {
        "name": "non_speech_begat_style",
        "expected": "drop",
        "item_en": {
            "quote": "And Cush begat Nimrod: he began to be a mighty one in the earth. He was a mighty hunter before the LORD: wherefore it is said, Even as Nimrod the mighty hunter before the LORD.",
            "riddle": "he began to be a mighty one in the earth",
            "speaker": "Cush",
            "listener": "Nimrod",
        },
        "note": "Genealogical/narrative statement is not a direct addressed speech interaction.",
    },
    {
        "name": "true_dialogue",
        "expected": "keep",
        "item_en": {
            "quote": "And the LORD said unto Cain, Why art thou wroth? and why is thy countenance fallen?",
            "riddle": "Why art thou wroth? and why is thy countenance fallen?",
            "speaker": "the LORD",
            "listener": "Cain",
        },
        "note": "Clear direct-address dialogue interaction.",
    },
]

EN_STOPWORDS = {
    "the",
    "and",
    "to",
    "of",
    "in",
    "a",
    "an",
    "for",
    "with",
    "on",
    "by",
    "at",
    "from",
    "that",
    "whose",
    "this",
    "it",
    "is",
    "was",
    "be",
    "as",
    "he",
    "she",
    "they",
    "him",
    "her",
    "them",
    "his",
    "their",
    "i",
    "you",
    "we",
    "said",
    "saith",
    "saying",
    "spake",
    "answered",
}

HE_STOPWORDS = {
    "ו",
    "את",
    "אל",
    "על",
    "מן",
    "עם",
    "כי",
    "אם",
    "גם",
    "לא",
    "הוא",
    "היא",
    "הם",
    "הן",
    "אני",
    "אתה",
    "אתם",
    "אנחנו",
    "ל",
    "ב",
    "כ",
    "מ",
    "ש",
    "ויאמר",
    "ויאמרו",
    "ותאמר",
    "ותאמרו",
    "לאמר",
    "נאם",
}


@dataclass
class Stats:
    files_seen: int = 0
    files_written: int = 0
    files_skipped_existing: int = 0
    items_seen: int = 0
    items_updated: int = 0
    items_failed: int = 0
    items_skipped_existing_bonus: int = 0
    items_dropped_postprocess: int = 0
    llm_calls: int = 0
    prompt_tokens: int = 0
    response_tokens: int = 0
    estimated_calls: int = 0
    errors: int = 0


def _add_llm_stats(stats: Stats, llm_stats: Dict[str, int | bool]) -> None:
    stats.llm_calls += int(llm_stats.get("calls", 0))
    stats.prompt_tokens += int(llm_stats.get("prompt_tokens", 0))
    stats.response_tokens += int(llm_stats.get("response_tokens", 0))
    if bool(llm_stats.get("estimated", False)):
        stats.estimated_calls += 1


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


def _strip_wrapping_quotes(text: str) -> str:
    value = _sanitize_str(text)
    if not value:
        return ""
    return value.strip(' "\'“”‘’')


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
            options={"temperature": 0.2, "num_predict": 256},
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


def _chapter_filter(expr: str) -> Set[int]:
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
                lo, hi = sorted((int(a.strip()), int(b.strip())))
                for chapter in range(lo, hi + 1):
                    out.add(chapter)
            continue
        if token.isdigit():
            out.add(int(token))
    return out


def _book_match(payload: Dict, book_filter: str) -> bool:
    if not book_filter.strip():
        return True
    target = book_filter.strip().casefold()
    code = _sanitize_str(payload.get("book_code")).casefold()
    book = _sanitize_str(payload.get("book")).casefold()
    return target in {code, book}


def _iter_input_files(in_dir: Path, include_draft: bool) -> List[Path]:
    files = sorted(path for path in in_dir.glob("*.json") if path.is_file())
    if include_draft:
        return files
    return [path for path in files if not path.stem.endswith("-draft")]


def _bonus_verse_hits(raw_map: Dict[str, str], bonus: str, lang: str) -> List[int]:
    hits: List[int] = []
    bonus = _sanitize_str(bonus)
    if not bonus:
        return hits
    for key, verse_text in raw_map.items():
        try:
            verse_no = int(key)
        except ValueError:
            continue
        text = text_cleanup.clean_text(verse_text)
        if lang == "he":
            text = text_cleanup.cleanup_hebrew_quote(text)
        if bonus in text:
            hits.append(verse_no)
    return sorted(set(hits))


def _validate_lang_bonus(
    *,
    quote: str,
    riddle: str,
    candidate: str,
    lang: str,
    min_tokens: int,
    max_tokens: int,
) -> Tuple[Optional[str], str]:
    raw = _strip_wrapping_quotes(candidate)
    if not raw:
        return None, f"bonus_{lang}_empty"

    extracted = text_cleanup.extract_substring_from_quote(quote, raw, lang)
    if not extracted:
        return None, f"bonus_{lang}_not_in_quote"

    in_riddle = text_cleanup.extract_substring_from_quote(riddle, extracted, lang)
    if in_riddle:
        return None, f"bonus_{lang}_appears_in_riddle"

    tokens = text_cleanup.token_count(extracted, lang)
    if tokens < min_tokens:
        return None, f"bonus_{lang}_too_short"
    if tokens > max_tokens:
        return None, f"bonus_{lang}_too_long"

    return extracted, ""


def _validate_cross_lang_alignment(item: Dict, bonus_en: str, bonus_he: str) -> str:
    raw_source = item.get("raw_quote_source", {})
    if not isinstance(raw_source, dict):
        return ""
    raw_en = raw_source.get("en", {})
    raw_he = raw_source.get("he", {})
    if not isinstance(raw_en, dict) or not isinstance(raw_he, dict):
        return ""

    hits_en = _bonus_verse_hits(raw_en, bonus_en, "en")
    hits_he = _bonus_verse_hits(raw_he, bonus_he, "he")
    if not hits_en or not hits_he:
        return ""
    if set(hits_en).intersection(hits_he):
        return ""
    return "bonus_cross_lang_no_shared_verse"


def _candidate_bonus_words(quote: str, riddle: str, lang: str, max_candidates: int = 80) -> List[str]:
    quote = _sanitize_str(quote)
    riddle = _sanitize_str(riddle)
    if not quote:
        return []

    riddle_tokens = set(text_cleanup.tokenize_for_match(riddle, lang))
    spans = text_cleanup.tokenize_with_spans(quote, lang)
    out: List[str] = []
    seen_norm: Set[str] = set()
    stopwords = EN_STOPWORDS if lang == "en" else HE_STOPWORDS

    for token, start, end in spans:
        norm = _sanitize_str(token).casefold()
        if not norm:
            continue
        if norm in seen_norm:
            continue
        if norm in riddle_tokens:
            continue
        if norm in stopwords:
            continue
        if len(norm) <= 1:
            continue

        surface = _sanitize_str(quote[start:end])
        if not surface:
            continue

        extracted = text_cleanup.extract_substring_from_quote(quote, surface, lang)
        if not extracted:
            continue

        token_count = text_cleanup.token_count(extracted, lang)
        if token_count != 1:
            continue

        seen_norm.add(norm)
        out.append(extracted)
        if len(out) >= max_candidates:
            break

    return out


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        token = value.strip().lower()
        if token in {"true", "yes", "1"}:
            return True
        if token in {"false", "no", "0"}:
            return False
    return False


def _llm_keep_item(model: str, item: Dict, retries: int) -> Tuple[bool, str, Dict[str, int | bool]]:
    source = item.get("source", {}) if isinstance(item.get("source"), dict) else {}
    en = item.get("en", {}) if isinstance(item.get("en"), dict) else {}
    he = item.get("he", {}) if isinstance(item.get("he"), dict) else {}

    base_item = {
        "speaker_en": _sanitize_str(en.get("speaker")),
        "listener_en": _sanitize_str(en.get("listener")),
        "riddle_en": _sanitize_str(en.get("riddle")),
        "quote_en": _sanitize_str(en.get("quote")),
        "speaker_he": _sanitize_str(he.get("speaker")),
        "listener_he": _sanitize_str(he.get("listener")),
        "riddle_he": _sanitize_str(he.get("riddle")),
        "quote_he": _sanitize_str(he.get("quote")),
    }

    payload = {
        "instructions": ITEM_KEEP_PROMPT,
        "examples": INTERACTION_FILTER_EXAMPLES,
        "context": {
            "book_code": _sanitize_str(source.get("book_code")),
            "chapter": _sanitize_int(source.get("chapter"), 0),
            "item_id": _sanitize_str(item.get("id")),
        },
        "item": base_item,
    }

    data, llm_stats_1 = _call_llm_json(model=model, payload=payload, max_attempts=max(1, retries))
    status = _sanitize_str(data.get("status")).lower()
    reason = _sanitize_str(data.get("reason"))
    checks = data.get("checks", {}) if isinstance(data.get("checks"), dict) else {}
    is_direct_speech = _to_bool(checks.get("is_direct_speech"))
    speaker_solvable = _to_bool(checks.get("speaker_solvable"))
    listener_solvable = _to_bool(checks.get("listener_solvable"))

    if status not in {"keep", "drop"}:
        return False, (reason or "invalid_status"), llm_stats_1

    if status != "keep":
        return False, (reason or "llm_status_drop"), llm_stats_1

    failed_checks: List[str] = []
    if not is_direct_speech:
        failed_checks.append("not_direct_speech")
    if not speaker_solvable:
        failed_checks.append("speaker_unsolvable")
    if not listener_solvable:
        failed_checks.append("listener_unsolvable")
    if failed_checks:
        return False, ",".join(failed_checks), llm_stats_1

    direction_payload = {
        "instructions": DIRECTION_CHECK_PROMPT,
        "examples": INTERACTION_FILTER_EXAMPLES,
        "context": {
            "book_code": _sanitize_str(source.get("book_code")),
            "chapter": _sanitize_int(source.get("chapter"), 0),
            "item_id": _sanitize_str(item.get("id")),
        },
        "item": base_item,
    }
    direction_data, llm_stats_2 = _call_llm_json(
        model=model,
        payload=direction_payload,
        max_attempts=max(1, retries),
    )

    merged_stats = {
        "calls": int(llm_stats_1.get("calls", 0)) + int(llm_stats_2.get("calls", 0)),
        "prompt_tokens": int(llm_stats_1.get("prompt_tokens", 0)) + int(llm_stats_2.get("prompt_tokens", 0)),
        "response_tokens": int(llm_stats_1.get("response_tokens", 0)) + int(llm_stats_2.get("response_tokens", 0)),
        "estimated": bool(llm_stats_1.get("estimated", False) or llm_stats_2.get("estimated", False)),
    }

    direction_checks = (
        direction_data.get("checks", {}) if isinstance(direction_data.get("checks"), dict) else {}
    )
    speaker_to_listener = _to_bool(direction_checks.get("speaker_told_riddle_to_listener"))
    listener_to_speaker = _to_bool(direction_checks.get("listener_told_riddle_to_speaker"))
    other_to_listener = _to_bool(direction_checks.get("other_entity_told_riddle_to_listener"))
    direction_reason = _sanitize_str(direction_data.get("reason"))

    if not speaker_to_listener:
        return False, (direction_reason or "speaker_to_listener_false"), merged_stats
    if listener_to_speaker:
        return False, (direction_reason or "listener_to_speaker_true"), merged_stats
    if other_to_listener:
        return False, (direction_reason or "other_to_listener_true"), merged_stats

    return True, (reason or direction_reason), merged_stats


def _pick_bonus_words(
    *,
    model: str,
    item: Dict,
    max_retries: int,
    min_tokens: int,
    max_tokens: int,
) -> Tuple[Optional[Tuple[str, str]], Dict[str, int | bool], List[str], str]:
    en = item.get("en", {}) if isinstance(item.get("en"), dict) else {}
    he = item.get("he", {}) if isinstance(item.get("he"), dict) else {}

    quote_en = _sanitize_str(en.get("quote"))
    quote_he = _sanitize_str(he.get("quote"))
    riddle_en = _sanitize_str(en.get("riddle"))
    riddle_he = _sanitize_str(he.get("riddle"))
    speaker_en = _sanitize_str(en.get("speaker"))
    listener_en = _sanitize_str(en.get("listener"))
    speaker_he = _sanitize_str(he.get("speaker"))
    listener_he = _sanitize_str(he.get("listener"))

    candidate_bonus_en = _candidate_bonus_words(quote=quote_en, riddle=riddle_en, lang="en")
    candidate_bonus_he = _candidate_bonus_words(quote=quote_he, riddle=riddle_he, lang="he")

    if not candidate_bonus_en:
        return None, {"calls": 0, "prompt_tokens": 0, "response_tokens": 0, "estimated": False}, [], "bonus_en_no_candidates"
    if not candidate_bonus_he:
        return None, {"calls": 0, "prompt_tokens": 0, "response_tokens": 0, "estimated": False}, [], "bonus_he_no_candidates"

    llm_calls = 0
    llm_prompt_tokens = 0
    llm_response_tokens = 0
    llm_estimated = 0

    retry_notes: List[str] = []
    last_reason = ""

    for attempt in range(1, max_retries + 1):
        payload = {
            "instructions": BONUS_PICK_PROMPT,
            "item_id": _sanitize_str(item.get("id")),
            "constraints": {
                "bonus_tokens": f"{min_tokens}-{max_tokens}",
                "must_not_be_in_riddle": True,
                "same_concept_across_languages": True,
            },
            "quote_en": quote_en,
            "riddle_en": riddle_en,
            "candidate_bonus_en": candidate_bonus_en,
            "quote_he": quote_he,
            "riddle_he": riddle_he,
            "candidate_bonus_he": candidate_bonus_he,
            "retry_feedback": retry_notes,
        }

        data, stats = _call_llm_json(model=model, payload=payload, max_attempts=2)
        llm_calls += int(stats.get("calls", 0))
        llm_prompt_tokens += int(stats.get("prompt_tokens", 0))
        llm_response_tokens += int(stats.get("response_tokens", 0))
        if bool(stats.get("estimated", False)):
            llm_estimated += 1

        bonus_en_idx = _sanitize_int(data.get("bonus_en_idx"), -1)
        bonus_he_idx = _sanitize_int(data.get("bonus_he_idx"), -1)
        if bonus_en_idx < 0 or bonus_en_idx >= len(candidate_bonus_en):
            last_reason = "bonus_en_bad_index"
            retry_notes.append(f"attempt_{attempt}:{last_reason}")
            continue
        if bonus_he_idx < 0 or bonus_he_idx >= len(candidate_bonus_he):
            last_reason = "bonus_he_bad_index"
            retry_notes.append(f"attempt_{attempt}:{last_reason}")
            continue

        bonus_en_candidate = candidate_bonus_en[bonus_en_idx]
        bonus_he_candidate = candidate_bonus_he[bonus_he_idx]

        fixed_en, reason_en = _validate_lang_bonus(
            quote=quote_en,
            riddle=riddle_en,
            candidate=bonus_en_candidate,
            lang="en",
            min_tokens=min_tokens,
            max_tokens=max_tokens,
        )
        if not fixed_en:
            last_reason = reason_en
            retry_notes.append(f"attempt_{attempt}:{reason_en}")
            continue

        fixed_he, reason_he = _validate_lang_bonus(
            quote=quote_he,
            riddle=riddle_he,
            candidate=bonus_he_candidate,
            lang="he",
            min_tokens=min_tokens,
            max_tokens=max_tokens,
        )
        if not fixed_he:
            last_reason = reason_he
            retry_notes.append(f"attempt_{attempt}:{reason_he}")
            continue

        if text_cleanup.riddle_mentions_entities(fixed_en, speaker_en, listener_en, "en"):
            last_reason = "bonus_en_mentions_entities"
            retry_notes.append(f"attempt_{attempt}:{last_reason}")
            continue
        if text_cleanup.riddle_mentions_entities(fixed_he, speaker_he, listener_he, "he"):
            last_reason = "bonus_he_mentions_entities"
            retry_notes.append(f"attempt_{attempt}:{last_reason}")
            continue

        cross_lang_reason = _validate_cross_lang_alignment(item=item, bonus_en=fixed_en, bonus_he=fixed_he)
        if cross_lang_reason:
            last_reason = cross_lang_reason
            retry_notes.append(f"attempt_{attempt}:{cross_lang_reason}")
            continue

        concept_payload = {
            "instructions": BONUS_CONCEPT_CHECK_PROMPT,
            "quote_en": quote_en,
            "quote_he": quote_he,
            "bonus_en": fixed_en,
            "bonus_he": fixed_he,
        }
        concept_data, concept_stats = _call_llm_json(model=model, payload=concept_payload, max_attempts=2)
        llm_calls += int(concept_stats.get("calls", 0))
        llm_prompt_tokens += int(concept_stats.get("prompt_tokens", 0))
        llm_response_tokens += int(concept_stats.get("response_tokens", 0))
        if bool(concept_stats.get("estimated", False)):
            llm_estimated += 1

        if not bool(concept_data.get("same_concept")):
            last_reason = "bonus_cross_lang_not_same_concept"
            retry_notes.append(f"attempt_{attempt}:{last_reason}")
            continue

        return (fixed_en, fixed_he), {
            "calls": llm_calls,
            "prompt_tokens": llm_prompt_tokens,
            "response_tokens": llm_response_tokens,
            "estimated": bool(llm_estimated > 0),
        }, retry_notes, ""

    return None, {
        "calls": llm_calls,
        "prompt_tokens": llm_prompt_tokens,
        "response_tokens": llm_response_tokens,
        "estimated": bool(llm_estimated > 0),
    }, retry_notes, last_reason or "bonus_selection_failed"


def _normalize_item_book_and_ref(item: Dict, payload: Dict) -> bool:
    changed = False

    source = item.get("source", {}) if isinstance(item.get("source"), dict) else {}
    if not isinstance(item.get("en"), dict):
        item["en"] = {}
        changed = True
    if not isinstance(item.get("he"), dict):
        item["he"] = {}
        changed = True

    source_book_en = _sanitize_str(source.get("book"))
    source_book_he = _sanitize_str(source.get("book_he"))
    payload_book_en = _sanitize_str(payload.get("book"))
    payload_book_he = _sanitize_str(payload.get("book_he"))

    book_en = source_book_en or payload_book_en
    book_he = source_book_he or payload_book_he

    if book_en and _sanitize_str(item["en"].get("book")) != book_en:
        item["en"]["book"] = book_en
        changed = True
    if book_he and _sanitize_str(item["he"].get("book")) != book_he:
        item["he"]["book"] = book_he
        changed = True

    chapter = _sanitize_int(source.get("chapter"), _sanitize_int(payload.get("chapter"), 0))
    start = _sanitize_int(source.get("quote_verse_start"), 0)
    end = _sanitize_int(source.get("quote_verse_end"), 0)
    if chapter > 0 and start > 0 and end > 0:
        expected_ref = {"chapter": chapter, "start": start, "end": end}
        current_ref = item.get("ref")
        if not isinstance(current_ref, dict) or any(_sanitize_int(current_ref.get(k), -1) != expected_ref[k] for k in ("chapter", "start", "end")):
            item["ref"] = expected_ref
            changed = True

    return changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gemma3:27b")
    parser.add_argument("--in-dir", default="data/rebuilt_quotes")
    parser.add_argument("--out-dir", default="data/rebuilt_quotes_bonus")
    parser.add_argument("--issues-log", default="data/rebuilt_quotes_bonus_issues.jsonl")
    parser.add_argument("--book", default="", help="book filter by code or name, e.g. GEN or Genesis")
    parser.add_argument("--chapters", default="", help="chapter filter, e.g. 1-3,12,15")
    parser.add_argument("--limit-files", type=int, default=0)
    parser.add_argument("--max-retries", type=int, default=6)
    parser.add_argument("--min-bonus-tokens", type=int, default=1)
    parser.add_argument("--max-bonus-tokens", type=int, default=2)
    parser.add_argument("--item-filter-retries", type=int, default=2)
    parser.add_argument("--skip-llm-item-filter", action="store_true")
    parser.add_argument("--include-draft", action="store_true")
    parser.add_argument("--overwrite-existing-bonus", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.max_retries < 1:
        raise SystemExit("--max-retries must be >= 1")
    if args.min_bonus_tokens < 1:
        raise SystemExit("--min-bonus-tokens must be >= 1")
    if args.max_bonus_tokens < args.min_bonus_tokens:
        raise SystemExit("--max-bonus-tokens must be >= --min-bonus-tokens")
    if args.item_filter_retries < 1:
        raise SystemExit("--item-filter-retries must be >= 1")

    in_dir = (ROOT / args.in_dir).resolve()
    out_dir = (ROOT / args.out_dir).resolve()
    issues_log = (ROOT / args.issues_log).resolve()

    if not in_dir.exists() or not in_dir.is_dir():
        raise SystemExit(f"Input directory does not exist: {in_dir}")

    chapter_filter = _chapter_filter(args.chapters)
    files = _iter_input_files(in_dir=in_dir, include_draft=bool(args.include_draft))
    if args.limit_files > 0:
        files = files[: args.limit_files]

    stats = Stats()
    issue_lines: List[str] = []

    issues_log.parent.mkdir(parents=True, exist_ok=True)
    if args.force or not issues_log.exists():
        issues_log.write_text("", encoding="utf-8")

    tqdm.write(
        "Bonus queue: files={files} in_dir={in_dir} out_dir={out_dir} include_draft={include_draft} llm_item_filter={llm_item_filter}".format(
            files=len(files),
            in_dir=in_dir,
            out_dir=out_dir,
            include_draft=bool(args.include_draft),
            llm_item_filter=not bool(args.skip_llm_item_filter),
        )
    )

    for in_path in tqdm(files, desc="add-bonus", unit="file"):
        stats.files_seen += 1
        out_path = out_dir / in_path.name

        if out_path.exists() and not args.force:
            stats.files_skipped_existing += 1
            continue

        try:
            payload = json.loads(in_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: PERF203
            stats.errors += 1
            issue_lines.append(
                json.dumps(
                    {
                        "file": str(in_path),
                        "status": "error",
                        "error": f"read_failed:{exc}",
                    },
                    ensure_ascii=False,
                )
            )
            continue

        if not isinstance(payload, dict):
            stats.errors += 1
            issue_lines.append(
                json.dumps(
                    {
                        "file": str(in_path),
                        "status": "error",
                        "error": "payload_not_object",
                    },
                    ensure_ascii=False,
                )
            )
            continue

        if not _book_match(payload, args.book):
            continue
        chapter = _sanitize_int(payload.get("chapter"), 0)
        if chapter_filter and chapter not in chapter_filter:
            continue

        items = payload.get("items", [])
        if not isinstance(items, list):
            stats.errors += 1
            issue_lines.append(
                json.dumps(
                    {
                        "file": str(in_path),
                        "status": "error",
                        "error": "items_not_list",
                    },
                    ensure_ascii=False,
                )
            )
            continue

        changed = False
        filtered_items: List[Dict] = []
        seen_ids: Set[str] = set()

        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                stats.items_dropped_postprocess += 1
                issue_lines.append(
                    json.dumps(
                        {
                            "file": str(in_path),
                            "idx": idx,
                            "status": "drop_postprocess",
                            "reason": "item_not_object",
                        },
                        ensure_ascii=False,
                    )
                )
                changed = True
                continue

            item_id = _sanitize_str(item.get("id"))
            if item_id and item_id in seen_ids:
                stats.items_dropped_postprocess += 1
                issue_lines.append(
                    json.dumps(
                        {
                            "file": str(in_path),
                            "idx": idx,
                            "id": item_id,
                            "status": "drop_postprocess",
                            "reason": "duplicate_id",
                        },
                        ensure_ascii=False,
                    )
                )
                changed = True
                continue
            if item_id:
                seen_ids.add(item_id)

            if not args.skip_llm_item_filter:
                keep, reason, filter_stats = _llm_keep_item(
                    model=args.model,
                    item=item,
                    retries=args.item_filter_retries,
                )
                _add_llm_stats(stats, filter_stats)
                if not keep:
                    stats.items_dropped_postprocess += 1
                    issue_lines.append(
                        json.dumps(
                            {
                                "file": str(in_path),
                                "idx": idx,
                                "id": item_id,
                                "status": "drop_postprocess",
                                "reason": f"llm_interaction_drop:{reason or 'drop'}",
                            },
                            ensure_ascii=False,
                        )
                    )
                    changed = True
                    continue

            filtered_items.append(item)

        payload["items"] = filtered_items

        for idx, item in enumerate(filtered_items):
            stats.items_seen += 1

            if _normalize_item_book_and_ref(item=item, payload=payload):
                changed = True

            en = item.get("en", {}) if isinstance(item.get("en"), dict) else {}
            he = item.get("he", {}) if isinstance(item.get("he"), dict) else {}
            existing_bonus_en = _sanitize_str(en.get("bonus"))
            existing_bonus_he = _sanitize_str(he.get("bonus"))
            if existing_bonus_en and existing_bonus_he and not args.overwrite_existing_bonus:
                stats.items_skipped_existing_bonus += 1
                continue

            pair, llm_stats, retries, fail_reason = _pick_bonus_words(
                model=args.model,
                item=item,
                max_retries=args.max_retries,
                min_tokens=args.min_bonus_tokens,
                max_tokens=args.max_bonus_tokens,
            )
            _add_llm_stats(stats, llm_stats)

            if pair is None:
                stats.items_failed += 1
                issue_lines.append(
                    json.dumps(
                        {
                            "file": str(in_path),
                            "idx": idx,
                            "id": _sanitize_str(item.get("id")),
                            "status": "failed_bonus",
                            "reason": fail_reason,
                            "retries": retries,
                        },
                        ensure_ascii=False,
                    )
                )
                continue

            bonus_en, bonus_he = pair
            if not isinstance(item.get("en"), dict):
                item["en"] = {}
            if not isinstance(item.get("he"), dict):
                item["he"] = {}
            item["en"]["bonus"] = bonus_en
            item["he"]["bonus"] = bonus_he

            if "meta" not in item or not isinstance(item.get("meta"), dict):
                item["meta"] = {}
            item["meta"]["bonus_source"] = "llm"
            item["meta"]["bonus_retries"] = len(retries)

            changed = True
            stats.items_updated += 1

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if changed:
            stats.files_written += 1

    if issue_lines:
        with issues_log.open("a", encoding="utf-8") as handle:
            for line in issue_lines:
                handle.write(line + "\n")

    tqdm.write(
        "Done: files_seen={files_seen}, files_written={files_written}, files_skipped_existing={files_skipped_existing}, "
        "items_seen={items_seen}, items_updated={items_updated}, items_skipped_existing_bonus={items_skipped_existing_bonus}, "
        "items_failed={items_failed}, items_dropped_postprocess={items_dropped_postprocess}, llm_calls={llm_calls}, "
        "prompt_tokens={prompt_tokens}, response_tokens={response_tokens}, estimated_calls={estimated_calls}, "
        "errors={errors}, out_dir={out_dir}, issues_log={issues_log}".format(
            files_seen=stats.files_seen,
            files_written=stats.files_written,
            files_skipped_existing=stats.files_skipped_existing,
            items_seen=stats.items_seen,
            items_updated=stats.items_updated,
            items_skipped_existing_bonus=stats.items_skipped_existing_bonus,
            items_failed=stats.items_failed,
            items_dropped_postprocess=stats.items_dropped_postprocess,
            llm_calls=stats.llm_calls,
            prompt_tokens=stats.prompt_tokens,
            response_tokens=stats.response_tokens,
            estimated_calls=stats.estimated_calls,
            errors=stats.errors,
            out_dir=out_dir,
            issues_log=issues_log,
        )
    )

    return 1 if stats.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
