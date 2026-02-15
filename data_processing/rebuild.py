#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from tqdm import tqdm

try:
    from data_processing import bible_sources, bible_tandem, create_quotes, text_cleanup
except ModuleNotFoundError:
    import bible_sources  # type: ignore[no-redef]
    import bible_tandem  # type: ignore[no-redef]
    import create_quotes  # type: ignore[no-redef]
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
HE_SPEECH_MARKERS = ("ויאמר", "ותאמר", "ויאמרו", "לאמר", "נאם")
EN_SPEECH_MARKERS = (" said", " saying", " saith", " spake", " answered")


@dataclass
class ValidationConfig:
    max_window: int = 5
    min_quote_tokens: int = 10
    min_riddle_tokens: int = 4
    max_riddle_tokens: int = 16
    min_context_tokens: int = 4
    require_single_verse_riddle: bool = False


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


def _add_llm_stats(
    total: Stats,
    llm_stats: Dict[str, int | bool],
    *,
    progress: bool = False,
    label: str = "",
) -> None:
    calls = int(llm_stats.get("calls", 0))
    prompt_tokens = int(llm_stats.get("prompt_tokens", 0))
    response_tokens = int(llm_stats.get("response_tokens", 0))
    estimated = bool(llm_stats.get("estimated", False))

    total.llm_calls += calls
    total.prompt_tokens += prompt_tokens
    total.response_tokens += response_tokens
    if estimated:
        total.estimated_calls += 1
    if progress and calls > 0:
        scope = f" {label}" if label else ""
        est_marker = " estimated" if estimated else ""
        tqdm.write(
            "[llm{scope}] +calls={calls} +prompt={prompt} +response={response}{est} | "
            "totals calls={total_calls} prompt={total_prompt} response={total_response}".format(
                scope=scope,
                calls=calls,
                prompt=prompt_tokens,
                response=response_tokens,
                est=est_marker,
                total_calls=total.llm_calls,
                total_prompt=total.prompt_tokens,
                total_response=total.response_tokens,
            )
        )


def _sanitize_int(value: object, fallback: int = 0) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return fallback


def _sanitize_str(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return text_cleanup.clean_text(value)


def _strip_wrapping_quotes(text: str) -> str:
    value = _sanitize_str(text)
    if not value:
        return ""
    return value.strip(" \"'“”‘’")


def _chapter_filename(book_code: str, chapter: int) -> str:
    slug = bible_sources.BOOK_CODE_TO_EN.get(book_code, book_code).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return f"{slug}-{chapter:03d}.json"


def _chapter_draft_path(out_path: Path) -> Path:
    return out_path.with_name(f"{out_path.stem}-draft.json")


def _build_item_id(book_code: str, chapter: int, start: int, end: int) -> str:
    slug = bible_sources.BOOK_CODE_TO_EN.get(book_code, book_code).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return f"{slug}-{chapter:02d}-{start:02d}-{end:02d}"


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
                lo, hi = sorted((int(a.strip()), int(b.strip())))
                for chapter in range(lo, hi + 1):
                    out.add(chapter)
            continue
        if token.isdigit():
            out.add(int(token))
    return out


def _chapter_context(
    tandem: bible_tandem.TandemBible,
    book_code: str,
    chapter: int,
    first_k_verses: int = 0,
) -> List[Dict]:
    limit = max(0, first_k_verses)
    out: List[Dict] = []
    for verse in tandem.iter_verses(book_code, chapter):
        if limit and verse.verse > limit:
            break
        out.append(
            {
                "v": verse.verse,
                "en": verse.en_raw,
                "he": verse.he_clean,
                "en_raw": verse.en_raw,
                "he_raw": verse.he_raw,
            }
        )
    return out


def _focused_context(context: List[Dict], start: int, end: int, pad: int) -> List[Dict]:
    if start <= 0 or end <= 0 or not context:
        return context
    if start > end:
        start, end = end, start

    verses = sorted(
        {
            _sanitize_int(entry.get("v"), 0)
            for entry in context
            if _sanitize_int(entry.get("v"), 0) > 0
        }
    )
    if not verses:
        return context

    min_verse = verses[0]
    max_verse = verses[-1]
    lo = max(min_verse, start - max(0, pad))
    hi = min(max_verse, end + max(0, pad))
    focused = [
        entry
        for entry in context
        if lo <= _sanitize_int(entry.get("v"), 0) <= hi
    ]
    return focused or context


def _looks_like_speech(entry: Dict) -> bool:
    en = _sanitize_str(entry.get("en")).casefold()
    he = _sanitize_str(entry.get("he"))
    if any(marker in he for marker in HE_SPEECH_MARKERS):
        return True
    if any(marker in f" {en}" for marker in EN_SPEECH_MARKERS):
        return True
    return False


def _mechanical_candidates(context: List[Dict], max_window: int, max_candidates: int) -> List[Dict]:
    verse_map = {
        _sanitize_int(entry.get("v"), 0): entry
        for entry in context
        if _sanitize_int(entry.get("v"), 0) > 0
    }
    verse_numbers = sorted(verse_map)
    verse_index = {verse: idx for idx, verse in enumerate(verse_numbers)}
    candidates: List[Dict] = []
    seen: Set[str] = set()
    scan_window = max(1, max_window)
    miss_jump = max(1, scan_window - 1)

    idx = 0
    while idx < len(verse_numbers):
        start_verse = verse_numbers[idx]

        # Build a contiguous scan window up to max_window verses.
        window: List[int] = [start_verse]
        next_idx = idx + 1
        while next_idx < len(verse_numbers) and len(window) < scan_window:
            prev = window[-1]
            cur = verse_numbers[next_idx]
            if cur != prev + 1:
                break
            window.append(cur)
            next_idx += 1

        hit_start = 0
        hit_end = 0
        for verse in window:
            entry = verse_map.get(verse, {})
            if not _looks_like_speech(entry):
                continue
            hit_start = verse
            hit_end = verse
            hit_idx = verse_index[verse]
            while hit_idx + 1 < len(verse_numbers):
                cur = verse_numbers[hit_idx]
                nxt = verse_numbers[hit_idx + 1]
                if nxt != cur + 1:
                    break
                if nxt - hit_start + 1 > scan_window:
                    break
                hit_idx += 1
                hit_end = verse_numbers[hit_idx]
            break

        if hit_start <= 0:
            idx += miss_jump
            continue

        key = f"{hit_start}-{hit_end}"
        if key not in seen:
            seen.add(key)
            candidates.append(
                {
                    "quote_verse_start": hit_start,
                    "quote_verse_end": hit_end,
                    "reason": "mechanical_speech_marker",
                }
            )
            if len(candidates) >= max_candidates:
                return candidates

        idx = verse_index.get(hit_end, idx) + 1
    return candidates


def _verses_side_by_side(context: List[Dict]) -> Dict[str, Dict[str, str]]:
    verses: Dict[str, Dict[str, str]] = {}
    for entry in context:
        verse_no = _sanitize_int(entry.get("v"), 0)
        if verse_no <= 0:
            continue
        verses[str(verse_no)] = {
            "en": _sanitize_str(entry.get("en_raw") or entry.get("en")),
            "he": _sanitize_str(entry.get("he_raw") or entry.get("he")),
        }
    return verses


def _riddle_verse_hits(raw_map: Dict[str, str], riddle: str, lang: str) -> List[int]:
    hits: List[int] = []
    riddle = _sanitize_str(riddle)
    if not riddle:
        return hits
    for key, verse_text in raw_map.items():
        try:
            verse_no = int(key)
        except ValueError:
            continue
        text = text_cleanup.clean_text(verse_text)
        if lang == "he":
            text = text_cleanup.cleanup_hebrew_quote(text)
        if riddle in text:
            hits.append(verse_no)
    return sorted(set(hits))


def _extract_field(suggestion: Dict, flat_key: str, section: str, section_key: str) -> str:
    value = suggestion.get(flat_key)
    if isinstance(value, str):
        return _strip_wrapping_quotes(value)
    nested = suggestion.get(section)
    if isinstance(nested, dict):
        nested_value = nested.get(section_key)
        if isinstance(nested_value, str):
            return _strip_wrapping_quotes(nested_value)
    return ""


def _extract_range(suggestion: Dict) -> Tuple[int, int]:
    start = _sanitize_int(suggestion.get("quote_verse_start"), 0)
    end = _sanitize_int(suggestion.get("quote_verse_end"), 0)
    if start and end:
        return start, end

    source = suggestion.get("source")
    if isinstance(source, dict):
        start = _sanitize_int(source.get("quote_verse_start"), 0)
        end = _sanitize_int(source.get("quote_verse_end"), 0)
    return start, end


def _coerce_item_from_suggestion(
    tandem: bible_tandem.TandemBible,
    book_code: str,
    chapter: int,
    suggestion: Dict,
    cfg: ValidationConfig,
) -> Tuple[Optional[Dict], str]:
    start, end = _extract_range(suggestion)
    if start <= 0 or end <= 0:
        return None, "bad_range"
    if start > end:
        start, end = end, start
    if end - start + 1 > cfg.max_window:
        end = start + cfg.max_window - 1

    range_quote = tandem.collect_range(book_code=book_code, chapter=chapter, start=start, end=end)
    if range_quote.missing:
        return None, "missing_source_verses"
    if not range_quote.en_quote or not range_quote.he_quote:
        return None, "empty_quote"

    speaker_en = _extract_field(suggestion, "speaker_en", "en", "speaker")
    listener_en = _extract_field(suggestion, "listener_en", "en", "listener")
    speaker_he = _extract_field(suggestion, "speaker_he", "he", "speaker")
    listener_he = _extract_field(suggestion, "listener_he", "he", "listener")
    riddle_en = _extract_field(suggestion, "riddle_en", "en", "riddle")
    riddle_he = _extract_field(suggestion, "riddle_he", "he", "riddle")

    speaker_en = text_cleanup.align_entity_to_quote(speaker_en, range_quote.en_quote, "en")
    listener_en = text_cleanup.align_entity_to_quote(listener_en, range_quote.en_quote, "en")
    speaker_he = text_cleanup.align_entity_to_quote(speaker_he, range_quote.he_quote, "he")
    listener_he = text_cleanup.align_entity_to_quote(listener_he, range_quote.he_quote, "he")

    extracted_en = text_cleanup.extract_substring_from_quote(range_quote.en_quote, riddle_en, "en")
    extracted_he = text_cleanup.extract_substring_from_quote(range_quote.he_quote, riddle_he, "he")
    if extracted_en:
        riddle_en = extracted_en
    if extracted_he:
        riddle_he = extracted_he

    if (
        not riddle_en
        or not text_cleanup.extract_substring_from_quote(range_quote.en_quote, riddle_en, "en")
        or text_cleanup.riddle_mentions_entities(riddle_en, speaker_en, listener_en, "en")
    ):
        fallback_en = text_cleanup.suggest_riddle_from_quote(
            quote=range_quote.en_quote,
            speaker=speaker_en,
            listener=listener_en,
            lang="en",
            min_tokens=cfg.min_riddle_tokens,
            max_tokens=cfg.max_riddle_tokens,
        )
        if fallback_en:
            riddle_en = fallback_en

    if (
        not riddle_he
        or not text_cleanup.extract_substring_from_quote(range_quote.he_quote, riddle_he, "he")
        or text_cleanup.riddle_mentions_entities(riddle_he, speaker_he, listener_he, "he")
    ):
        fallback_he = text_cleanup.suggest_riddle_from_quote(
            quote=range_quote.he_quote,
            speaker=speaker_he,
            listener=listener_he,
            lang="he",
            min_tokens=cfg.min_riddle_tokens,
            max_tokens=cfg.max_riddle_tokens,
        )
        if fallback_he:
            riddle_he = fallback_he

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


def _item_to_suggestion(item: Dict) -> Dict:
    source = item.get("source", {})
    en = item.get("en", {})
    he = item.get("he", {})
    return {
        "quote_verse_start": _sanitize_int(source.get("quote_verse_start"), 0),
        "quote_verse_end": _sanitize_int(source.get("quote_verse_end"), 0),
        "speaker_en": _sanitize_str(en.get("speaker")),
        "listener_en": _sanitize_str(en.get("listener")),
        "speaker_he": _sanitize_str(he.get("speaker")),
        "listener_he": _sanitize_str(he.get("listener")),
        "riddle_en": _sanitize_str(en.get("riddle")),
        "riddle_he": _sanitize_str(he.get("riddle")),
        "quote_en": _sanitize_str(en.get("quote")),
        "quote_he": _sanitize_str(he.get("quote")),
        "raw_quote_source": item.get("raw_quote_source", {}),
        "reason": _sanitize_str(item.get("meta", {}).get("reason")),
        "confidence": item.get("meta", {}).get("confidence"),
    }


def _merge_suggestion(base: Dict, patch: Dict) -> Dict:
    merged = dict(base)
    for key in (
        "quote_verse_start",
        "quote_verse_end",
        "speaker_en",
        "listener_en",
        "speaker_he",
        "listener_he",
        "riddle_en",
        "riddle_he",
        "reason",
        "confidence",
    ):
        value = patch.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        merged[key] = value
    return merged


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

    if text_cleanup.has_weird_whitespace(quote_en, quote_he, riddle_en, riddle_he):
        issues.append("weird_whitespace")

    quote_en_tokens = text_cleanup.token_count(quote_en, "en")
    quote_he_tokens = text_cleanup.token_count(quote_he, "he")
    riddle_en_tokens = text_cleanup.token_count(riddle_en, "en")
    riddle_he_tokens = text_cleanup.token_count(riddle_he, "he")

    if quote_en_tokens < cfg.min_quote_tokens:
        issues.append("quote_en_too_short")
    if quote_he_tokens < cfg.min_quote_tokens:
        issues.append("quote_he_too_short")

    if riddle_en_tokens < cfg.min_riddle_tokens:
        issues.append("riddle_en_too_short")
    if riddle_he_tokens < cfg.min_riddle_tokens:
        issues.append("riddle_he_too_short")
    if riddle_en_tokens > cfg.max_riddle_tokens:
        issues.append("riddle_en_too_long")
    if riddle_he_tokens > cfg.max_riddle_tokens:
        issues.append("riddle_he_too_long")

    if quote_en_tokens - riddle_en_tokens < cfg.min_context_tokens:
        issues.append("quote_en_context_too_short")
    if quote_he_tokens - riddle_he_tokens < cfg.min_context_tokens:
        issues.append("quote_he_context_too_short")

    if not riddle_en or riddle_en not in quote_en:
        issues.append("riddle_en_not_substring")
    if not riddle_he or riddle_he not in quote_he:
        issues.append("riddle_he_not_substring")

    if not speaker_en or not listener_en or not speaker_he or not listener_he:
        issues.append("missing_entities")

    if text_cleanup.tokenize_for_match(speaker_en, "en") == text_cleanup.tokenize_for_match(listener_en, "en"):
        issues.append("speaker_listener_same_en")
    if text_cleanup.tokenize_for_match(speaker_he, "he") == text_cleanup.tokenize_for_match(listener_he, "he"):
        issues.append("speaker_listener_same_he")

    if not text_cleanup.entity_in_quote(speaker_en, quote_en, "en"):
        issues.append("speaker_en_not_in_quote")
    if not text_cleanup.entity_in_quote(listener_en, quote_en, "en"):
        issues.append("listener_en_not_in_quote")
    if not text_cleanup.entity_in_quote(speaker_he, quote_he, "he"):
        issues.append("speaker_he_not_in_quote")
    if not text_cleanup.entity_in_quote(listener_he, quote_he, "he"):
        issues.append("listener_he_not_in_quote")

    if text_cleanup.riddle_mentions_entities(riddle_en, speaker_en, listener_en, "en"):
        issues.append("riddle_en_mentions_entities")
    if text_cleanup.riddle_mentions_entities(riddle_he, speaker_he, listener_he, "he"):
        issues.append("riddle_he_mentions_entities")

    raw_source = item.get("raw_quote_source", {})
    raw_en = raw_source.get("en", {}) if isinstance(raw_source, dict) else {}
    raw_he = raw_source.get("he", {}) if isinstance(raw_source, dict) else {}

    hits_en = _riddle_verse_hits(raw_en if isinstance(raw_en, dict) else {}, riddle_en, "en")
    hits_he = _riddle_verse_hits(raw_he if isinstance(raw_he, dict) else {}, riddle_he, "he")

    if cfg.require_single_verse_riddle:
        if len(hits_en) != 1:
            issues.append("riddle_en_not_single_verse")
        if len(hits_he) != 1:
            issues.append("riddle_he_not_single_verse")
        if len(hits_en) == 1 and len(hits_he) == 1 and hits_en[0] != hits_he[0]:
            issues.append("riddle_cross_lang_misaligned")

    return sorted(set(issues))


def _process_chapter(
    tandem: bible_tandem.TandemBible,
    book_code: str,
    chapter: int,
    out_path: Path,
    audit_path: Path,
    draft_path: Path,
    issues_log_path: Path,
    model: str,
    mode: str,
    cfg: ValidationConfig,
    max_quotes_per_chapter: int,
    repair_tries: int,
    first_k_verses: int = 0,
    llm_progress: bool = False,
) -> Stats:
    stats = Stats(files=1, chapters=1)
    context = _chapter_context(
        tandem=tandem,
        book_code=book_code,
        chapter=chapter,
        first_k_verses=first_k_verses,
    )

    def add_llm(llm_stats: Dict[str, int | bool], stage: str) -> None:
        _add_llm_stats(
            stats,
            llm_stats,
            progress=llm_progress,
            label=f"{book_code} {chapter} {stage}",
        )

    if not context:
        payload = {
            "book_code": book_code,
            "book": bible_sources.BOOK_CODE_TO_EN.get(book_code, book_code),
            "book_he": bible_sources.BOOK_CODE_TO_HE.get(book_code, ""),
            "chapter": chapter,
            "first_k_verses": first_k_verses,
            "items": [],
        }
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(json.dumps({"results": [], "items_total": 0}, ensure_ascii=False, indent=2), encoding="utf-8")
        draft_path.parent.mkdir(parents=True, exist_ok=True)
        draft_path.write_text(
            json.dumps(
                {
                    "book_code": book_code,
                    "book": bible_sources.BOOK_CODE_TO_EN.get(book_code, book_code),
                    "book_he": bible_sources.BOOK_CODE_TO_HE.get(book_code, ""),
                    "chapter": chapter,
                    "mode": mode,
                    "first_k_verses": first_k_verses,
                    "items": [],
                    "verses": {},
                    "candidates": [],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return stats

    suggestions: List[Dict] = []
    if mode == "end2end":
        target_pool = max(max_quotes_per_chapter * 2, max_quotes_per_chapter + 1)
        seen_candidate_ranges: Set[str] = set()
        raw_suggestions, llm_stats = create_quotes.end2end_suggestions(
            model=model,
            context=context,
            max_window=cfg.max_window,
            max_quotes=max_quotes_per_chapter,
        )
        add_llm(llm_stats, "end2end_suggestions")
        suggestions = raw_suggestions
        for suggestion in suggestions:
            start, end = _extract_range(suggestion)
            if start > 0 and end > 0:
                seen_candidate_ranges.add(f"{start}-{end}")
        if len(suggestions) < target_pool:
            mechanical_candidates = _mechanical_candidates(
                context=context,
                max_window=cfg.max_window,
                max_candidates=target_pool * 2,
            )
            for candidate in mechanical_candidates:
                start, end = _extract_range(candidate)
                if start > 0 and end > 0:
                    range_key = f"{start}-{end}"
                    if range_key in seen_candidate_ranges:
                        continue
                    seen_candidate_ranges.add(range_key)
                finalize_context = _focused_context(
                    context=context,
                    start=start,
                    end=end,
                    pad=cfg.max_window,
                )
                finalized, fin_stats = create_quotes.finalize_candidate(
                    model=model,
                    context=finalize_context,
                    candidate=candidate,
                    max_window=cfg.max_window,
                )
                add_llm(fin_stats, "finalize_mechanical")
                suggestions.append(finalized)
                f_start, f_end = _extract_range(finalized)
                if f_start > 0 and f_end > 0:
                    seen_candidate_ranges.add(f"{f_start}-{f_end}")
                if len(suggestions) >= target_pool:
                    break

        if len(suggestions) < target_pool:
            candidates, cand_stats = create_quotes.candidate_suggestions(
                model=model,
                context=context,
                max_window=cfg.max_window,
                max_quotes=target_pool * 2,
            )
            add_llm(cand_stats, "candidate_suggestions")
            for candidate in candidates:
                start, end = _extract_range(candidate)
                if start > 0 and end > 0:
                    range_key = f"{start}-{end}"
                    if range_key in seen_candidate_ranges:
                        continue
                    seen_candidate_ranges.add(range_key)
                finalize_context = _focused_context(
                    context=context,
                    start=start,
                    end=end,
                    pad=cfg.max_window,
                )
                finalized, fin_stats = create_quotes.finalize_candidate(
                    model=model,
                    context=finalize_context,
                    candidate=candidate,
                    max_window=cfg.max_window,
                )
                add_llm(fin_stats, "finalize_candidate")
                suggestions.append(finalized)
                f_start, f_end = _extract_range(finalized)
                if f_start > 0 and f_end > 0:
                    seen_candidate_ranges.add(f"{f_start}-{f_end}")
                if len(suggestions) >= target_pool:
                    break
    else:
        target_pool = max_quotes_per_chapter * 2
        candidates, llm_stats = create_quotes.candidate_suggestions(
            model=model,
            context=context,
            max_window=cfg.max_window,
            max_quotes=max_quotes_per_chapter * 2,
        )
        add_llm(llm_stats, "candidate_suggestions")
        seen_candidate_ranges: Set[str] = set()
        for candidate in candidates:
            start, end = _extract_range(candidate)
            if start > 0 and end > 0:
                range_key = f"{start}-{end}"
                if range_key in seen_candidate_ranges:
                    continue
                seen_candidate_ranges.add(range_key)
            finalize_context = _focused_context(
                context=context,
                start=start,
                end=end,
                pad=cfg.max_window,
            )
            finalized, fin_stats = create_quotes.finalize_candidate(
                model=model,
                context=finalize_context,
                candidate=candidate,
                max_window=cfg.max_window,
            )
            add_llm(fin_stats, "finalize_candidate")
            suggestions.append(finalized)
            if len(suggestions) >= target_pool:
                break

    if mode == "end2end" and suggestions:
        max_pool = max(max_quotes_per_chapter * 3, max_quotes_per_chapter + 2)
        suggestions = sorted(
            suggestions,
            key=lambda s: (
                _sanitize_int(s.get("quote_verse_end"), 0) - _sanitize_int(s.get("quote_verse_start"), 0),
                _sanitize_int(s.get("quote_verse_start"), 9999),
                _sanitize_int(s.get("quote_verse_end"), 9999),
            ),
        )[:max_pool]

    stats.suggestions += len(suggestions)

    kept_items: List[Dict] = []
    audit_results: List[Dict] = []
    candidate_records: List[Dict] = []
    issue_lines: List[str] = []
    seen_keys: Set[str] = set()

    for idx, suggestion in enumerate(suggestions):
        record: Dict = {"idx": idx, "suggestion": suggestion}
        candidate_records.append(record)

        if not isinstance(suggestion, dict):
            stats.dropped_items += 1
            record["action"] = "drop_invalid_suggestion"
            record["drop_reason"] = "invalid_suggestion_type"
            continue

        item, fail_reason = _coerce_item_from_suggestion(
            tandem=tandem,
            book_code=book_code,
            chapter=chapter,
            suggestion=suggestion,
            cfg=cfg,
        )
        if item is None:
            stats.dropped_items += 1
            record["action"] = "drop_coerce"
            record["drop_reason"] = fail_reason
            audit_results.append({"action": "drop", "drop_reason": fail_reason, "suggestion": suggestion})
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
        record["item"] = item

        # LLM validation/fixing: semantic quality decisions live here.
        initial_input = _item_to_suggestion(item)
        source = item.get("source", {})
        validate_context = _focused_context(
            context=context,
            start=_sanitize_int(source.get("quote_verse_start"), 0),
            end=_sanitize_int(source.get("quote_verse_end"), 0),
            pad=cfg.max_window,
        )
        decision, decision_stats = create_quotes.validate_and_fix_item(
            model=model,
            context=validate_context,
            suggestion=initial_input,
            max_window=cfg.max_window,
            issues=[],
        )
        add_llm(decision_stats, "validate_initial")
        initial_semantic_issue = ""
        record["llm_initial"] = {
            "status": decision.get("status"),
            "reason": _sanitize_str(decision.get("reason")),
        }
        if decision["status"] == "drop":
            reason = _sanitize_str(decision.get("reason")) or "llm_semantic_drop"
            initial_semantic_issue = f"llm_semantic_drop:{reason}"
            record["llm_initial_drop"] = reason
        else:
            patch = decision.get("item") if isinstance(decision.get("item"), dict) else {}
            fixed_suggestion = _merge_suggestion(initial_input, patch)
            rebuilt, fail_reason = _coerce_item_from_suggestion(
                tandem=tandem,
                book_code=book_code,
                chapter=chapter,
                suggestion=fixed_suggestion,
                cfg=cfg,
            )
            if rebuilt is None:
                stats.dropped_items += 1
                record["action"] = "drop_coerce_after_llm"
                record["drop_reason"] = fail_reason
                audit_results.append({"action": "drop", "drop_reason": fail_reason, "suggestion": fixed_suggestion})
                issue_lines.append(
                    json.dumps(
                        {
                            "book_code": book_code,
                            "chapter": chapter,
                            "status": "drop",
                            "drop_reason": fail_reason,
                            "suggestion": fixed_suggestion,
                        },
                        ensure_ascii=False,
                    )
                )
                continue
            item = rebuilt
            record["item"] = item

        issues = _validate_item(item=item, cfg=cfg)
        if initial_semantic_issue:
            issues = sorted(set(issues + [initial_semantic_issue]))
        record["validation_issues_initial"] = list(issues)
        repaired = False
        repair_attempts: List[Dict] = []

        for _ in range(max(0, repair_tries)):
            if not issues:
                break

            fix_input = _item_to_suggestion(item)
            source = item.get("source", {})
            validate_context = _focused_context(
                context=context,
                start=_sanitize_int(source.get("quote_verse_start"), 0),
                end=_sanitize_int(source.get("quote_verse_end"), 0),
                pad=cfg.max_window,
            )
            decision, fix_stats = create_quotes.validate_and_fix_item(
                model=model,
                context=validate_context,
                suggestion=fix_input,
                max_window=cfg.max_window,
                issues=issues,
            )
            add_llm(fix_stats, "validate_repair")
            attempt_record: Dict = {
                "issues_in": list(issues),
                "status": decision.get("status"),
                "reason": _sanitize_str(decision.get("reason")),
            }

            if decision["status"] == "drop":
                attempt_record["result"] = "drop"
                repair_attempts.append(attempt_record)
                break

            fixed_patch = decision.get("item") if isinstance(decision.get("item"), dict) else {}
            fixed_suggestion = _merge_suggestion(fix_input, fixed_patch)
            rebuilt, fail_reason = _coerce_item_from_suggestion(
                tandem=tandem,
                book_code=book_code,
                chapter=chapter,
                suggestion=fixed_suggestion,
                cfg=cfg,
            )
            if rebuilt is None:
                issues = [fail_reason]
                attempt_record["result"] = "coerce_fail"
                attempt_record["coerce_fail_reason"] = fail_reason
                repair_attempts.append(attempt_record)
                break

            item = rebuilt
            record["item"] = item
            issues = _validate_item(item=item, cfg=cfg)
            attempt_record["result"] = "updated"
            attempt_record["issues_out"] = list(issues)
            repair_attempts.append(attempt_record)
            repaired = True

        if repair_attempts:
            record["repair_attempts"] = repair_attempts

        if issues:
            stats.dropped_items += 1
            record["action"] = "drop_validation"
            record["issues"] = list(issues)
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
            record["action"] = "skip_dedupe"
            record["item_id"] = item.get("id")
            continue
        seen_keys.add(dedupe_key)

        if len(kept_items) >= max_quotes_per_chapter:
            record["action"] = "skip_quota"
            record["item_id"] = item.get("id")
            record["reason"] = f"max_quotes_per_chapter={max_quotes_per_chapter}"
            continue

        if repaired:
            stats.repaired_items += 1
        stats.kept_items += 1
        kept_items.append(item)
        record["action"] = "keep_repaired" if repaired else "keep"
        record["item_id"] = item.get("id")
        audit_results.append(
            {
                "id": item.get("id"),
                "action": "keep_repaired" if repaired else "keep",
                "issues": [],
            }
        )

    kept_items = sorted(
        kept_items,
        key=lambda item: (
            _sanitize_int(item.get("source", {}).get("quote_verse_start"), 9999),
            _sanitize_int(item.get("source", {}).get("quote_verse_end"), 9999),
            _sanitize_str(item.get("id")),
        ),
    )
    candidate_records = sorted(candidate_records, key=lambda record: _sanitize_int(record.get("idx"), 9999))

    out_payload = {
        "book_code": book_code,
        "book": bible_sources.BOOK_CODE_TO_EN.get(book_code, book_code),
        "book_he": bible_sources.BOOK_CODE_TO_HE.get(book_code, ""),
        "chapter": chapter,
        "mode": mode,
        "first_k_verses": first_k_verses,
        "items": kept_items,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    audit_payload = {
        "book_code": book_code,
        "book": bible_sources.BOOK_CODE_TO_EN.get(book_code, book_code),
        "chapter": chapter,
        "first_k_verses": first_k_verses,
        "items_total": len(suggestions),
        "kept_items": len(kept_items),
        "dropped_items": len(suggestions) - len(kept_items),
        "results": audit_results,
    }
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(audit_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    draft_payload = {
        "book_code": book_code,
        "book": bible_sources.BOOK_CODE_TO_EN.get(book_code, book_code),
        "book_he": bible_sources.BOOK_CODE_TO_HE.get(book_code, ""),
        "chapter": chapter,
        "mode": mode,
        "first_k_verses": first_k_verses,
        "items": kept_items,
        "verses": _verses_side_by_side(context),
        "candidates": candidate_records,
    }
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text(json.dumps(draft_payload, ensure_ascii=False, indent=2), encoding="utf-8")

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
    parser.add_argument("--min-quote-tokens", type=int, default=10)
    parser.add_argument("--min-riddle-tokens", type=int, default=4)
    parser.add_argument("--max-riddle-tokens", type=int, default=16)
    parser.add_argument("--min-context-tokens", type=int, default=4)
    parser.add_argument("--first-k-verses", type=int, default=0, help="limit each chapter to verses 1..K (0=all)")
    parser.add_argument("--require-single-verse-riddle", action="store_true")
    parser.add_argument("--repair-tries", type=int, default=3)
    parser.add_argument("--out-dir", default="data/rebuilt_quotes")
    parser.add_argument("--audit-dir", default="data/rebuilt_quotes_audit")
    parser.add_argument("--issues-log", default="data/rebuilt_quotes_issues.jsonl")
    parser.add_argument("--english-xml", default=bible_sources.DEFAULT_ENGLISH_COLLECTION)
    parser.add_argument("--hebrew-zip", default=bible_sources.DEFAULT_HEBREW_ZIP)
    parser.add_argument(
        "--llm-progress",
        action="store_true",
        help="print per-step LLM calls and prompt/response token deltas",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.max_window < 1 or args.max_window > 5:
        raise SystemExit("--max-window must be between 1 and 5")
    if args.max_riddle_tokens < args.min_riddle_tokens:
        raise SystemExit("--max-riddle-tokens must be >= --min-riddle-tokens")
    if args.min_context_tokens < 0:
        raise SystemExit("--min-context-tokens must be >= 0")
    if args.first_k_verses < 0:
        raise SystemExit("--first-k-verses must be >= 0")

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
        chapters = chapters[:limit_chapters]

    queue: List[Tuple[str, int, Path, Path, Path]] = []
    skipped_existing = 0
    for code, chapter in chapters:
        filename = _chapter_filename(book_code=code, chapter=chapter)
        out_path = out_dir / filename
        audit_path = audit_dir / filename
        draft_path = _chapter_draft_path(out_path)
        if not args.force and out_path.exists() and draft_path.exists():
            skipped_existing += 1
            continue
        queue.append((code, chapter, out_path, audit_path, draft_path))

    if args.force or not issues_log.exists():
        issues_log.parent.mkdir(parents=True, exist_ok=True)
        issues_log.write_text("", encoding="utf-8")

    tqdm.write(
        f"Rebuild queue: total={len(chapters)} pending={len(queue)} skipped_existing={skipped_existing} mode={args.mode}"
    )
    if not queue:
        return 0

    cfg = ValidationConfig(
        max_window=args.max_window,
        min_quote_tokens=args.min_quote_tokens,
        min_riddle_tokens=args.min_riddle_tokens,
        max_riddle_tokens=args.max_riddle_tokens,
        min_context_tokens=args.min_context_tokens,
        require_single_verse_riddle=bool(args.require_single_verse_riddle),
    )

    total = Stats(skipped_existing=skipped_existing)
    for code, chapter, out_path, audit_path, draft_path in tqdm(queue, desc=f"rebuild-{args.mode}", unit="chap"):
        try:
            stats = _process_chapter(
                tandem=tandem,
                book_code=code,
                chapter=chapter,
                out_path=out_path,
                audit_path=audit_path,
                draft_path=draft_path,
                issues_log_path=issues_log,
                model=args.model,
                mode=args.mode,
                cfg=cfg,
                max_quotes_per_chapter=args.max_quotes_per_chapter,
                repair_tries=max(0, args.repair_tries),
                first_k_verses=max(0, args.first_k_verses),
                llm_progress=bool(args.llm_progress),
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
