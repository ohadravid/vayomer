#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from tqdm import tqdm

try:
    from data_processing import add_bonus_words, bible_sources, bonus_hint_picker, postprocess_hard_options
except ModuleNotFoundError:
    import add_bonus_words  # type: ignore[no-redef]
    import bible_sources  # type: ignore[no-redef]
    import bonus_hint_picker  # type: ignore[no-redef]
    import postprocess_hard_options  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ("speaker", "listener")
LANGS = ("en", "he")
BANNED_OPTION_LABELS_EN = {
    "his sons in law",
}
BANNED_OPTION_LABELS_HE = {
    "חתניו",
}

REGULAR_PICK_PROMPT = [
    "You are selecting normal-difficulty multiple-choice distractors for a Bible quote puzzle.",
    "Each candidate index is one aligned EN/HE entity pair from another puzzle item.",
    "Return strict JSON only with shape:",
    '{"add":[0,1],"reason":"..."}',
    "Goal:",
    "1) Pick distractors that are plausible and confusable for this exact quote+riddle context.",
    "2) Prioritize human/agent entities (people, named groups, titles, roles).",
    "3) Prefer same-domain confusion (king vs king, prophet vs prophet, family vs family, etc).",
    "3b) Prefer candidates from nearby chapters when available.",
    "4) Avoid trivial distractors that are obviously unrelated in role or interaction type.",
    "Entity hygiene:",
    "5) Reject clauses/fragments ('and he said', 'when ...', 'let ...').",
    "6) Reject pronouns/generic placeholders ('he', 'them', 'the man').",
    "7) Reject object/place nouns unless clearly used as a concrete addressed entity label in this context.",
    "8) Keep at most one divine-name alias in selected output.",
    "8b) If target answer is not divine, avoid divine distractors unless no good alternatives exist.",
    "8c) Never select labels like 'his sons in law' / 'חֲתָנָיו'.",
    "Rules:",
    "9) Use only indices from candidates[].",
    "10) Do not invent labels.",
    "11) If uncertain, return fewer picks.",
]

REGULAR_VALIDATE_PROMPT = [
    "You are validating selected normal-difficulty distractor options for a Bible quote puzzle.",
    "Return strict JSON only with shape:",
    '{"drop":[1],"reason":"..."}',
    "Task:",
    "1) Drop weak/easy/irrelevant distractors for this target answer and quote context.",
    "2) Drop non-entity labels, clauses, pronouns, placeholders, and generic filler.",
    "2b) Drop labels like 'his sons in law' / 'חֲתָנָיו'.",
    "3) Keep only options that remain plausible confusions for this interaction.",
    "3b) Prefer nearby-chapter and same-role distractors when available.",
    "4) Keep at most one divine-name alias in selected output.",
    "Rules:",
    "5) Use only indices from selected[].",
    "6) If all selected options are good, return an empty drop array.",
]

BONUS_WORD_REVIEW_PROMPT = [
    "You are validating one bonus word for a bilingual Bible quote puzzle.",
    "Return strict JSON only with shape:",
    '{"accept":true,"reason":"..."}',
    "Rules:",
    "1) Accept only if bonus_word is a specific, content-bearing anchor in the quote context.",
    "2) Reject generic/function words and weak fillers (pronouns, particles, prepositions, generic time words, generic discourse words).",
    "2b) Reject connector words like 'unto', 'thereof', 'therein', 'saying'.",
    "3) Prefer meaningful words that make the quote memorable.",
    "4) If uncertain, reject.",
]

BONUS_WORD_REVIEW_EXAMPLES = [
    {"lang": "he", "bonus_word": "מתי", "expected": "reject", "reason": "generic question/time word"},
    {"lang": "en", "bonus_word": "unto", "expected": "reject", "reason": "generic connector/preposition"},
    {"lang": "he", "bonus_word": "הַפֶּסַח", "expected": "accept", "reason": "specific content word"},
    {"lang": "en", "bonus_word": "passover", "expected": "accept", "reason": "specific content word"},
]

BONUS_PAIR_REVIEW_PROMPT = [
    "You are validating whether EN bonus matches HE bonus for the same quote pair.",
    "Return strict JSON only with shape:",
    '{"accept_en":true,"reason":"..."}',
    "Rules:",
    "1) accept_en=true only when bonus_en is a close lexical match/translation of bonus_he in quote context.",
    "2) Reject loose thematic relation (same scene/topic is not enough).",
    "3) Hebrew quality is primary; if EN is weak or mismatched, reject EN.",
    "4) If uncertain, reject EN.",
]

BONUS_PAIR_REVIEW_EXAMPLES = [
    {"bonus_en": "search", "bonus_he": "לַחְפֹּר", "expected": "accept_en"},
    {"bonus_en": "servant", "bonus_he": "עַבְדִּי", "expected": "accept_en"},
    {"bonus_en": "Nun", "bonus_he": "מוֹת", "expected": "reject_en"},
    {"bonus_en": "Israel", "bonus_he": "אֶהְיֶה", "expected": "reject_en"},
]


@dataclass
class Stats:
    files_seen: int = 0
    files_written: int = 0
    files_skipped_existing: int = 0
    items_seen: int = 0
    items_solution_checked: int = 0
    items_dropped_solution_python: int = 0
    items_dropped_solution_check: int = 0
    items_bonus_failed: int = 0
    items_written: int = 0
    fields_built: int = 0
    fields_insufficient: int = 0
    bonus_hints_set: int = 0
    bonus_hints_null: int = 0
    llm_calls: int = 0
    prompt_tokens: int = 0
    response_tokens: int = 0
    estimated_calls: int = 0
    errors: int = 0


@dataclass
class BonusOutcome:
    changed: bool
    failed_bonus: bool
    hint_en_set: bool
    hint_he_set: bool
    llm_stats: Dict[str, int | bool]
    issues: List[Dict]


def _add_llm_stats(stats: Stats, llm_stats: Dict[str, int | bool]) -> None:
    stats.llm_calls += int(llm_stats.get("calls", 0))
    stats.prompt_tokens += int(llm_stats.get("prompt_tokens", 0))
    stats.response_tokens += int(llm_stats.get("response_tokens", 0))
    if bool(llm_stats.get("estimated", False)):
        stats.estimated_calls += 1


def _merge_llm_stats(a: Dict[str, int | bool], b: Dict[str, int | bool]) -> Dict[str, int | bool]:
    return {
        "calls": int(a.get("calls", 0)) + int(b.get("calls", 0)),
        "prompt_tokens": int(a.get("prompt_tokens", 0)) + int(b.get("prompt_tokens", 0)),
        "response_tokens": int(a.get("response_tokens", 0)) + int(b.get("response_tokens", 0)),
        "estimated": bool(a.get("estimated", False) or b.get("estimated", False)),
    }


def _clean_entity_label(value: str) -> str:
    # Remove dangling Hebrew maqaf / hyphen artifacts around labels (e.g., "יִהוֹשֻֽׁעַ־").
    text = postprocess_hard_options._sanitize_str(value)
    if not text:
        return ""
    text = re.sub(r"^[\u05BE\-]+", "", text)
    text = re.sub(r"[\u05BE\-]+$", "", text)
    return postprocess_hard_options._sanitize_str(text)


def _normalized_label_key(value: str, lang: str) -> str:
    tokens = postprocess_hard_options.text_cleanup.tokenize_for_match(_clean_entity_label(value), lang)
    return " ".join(tokens)


def _is_banned_option_label(candidate: postprocess_hard_options.AlignedCandidate) -> bool:
    en_key = _normalized_label_key(candidate.en.label, "en")
    he_key = _normalized_label_key(candidate.he.label, "he")
    return en_key in BANNED_OPTION_LABELS_EN or he_key in BANNED_OPTION_LABELS_HE


def _ordered_unique_bonus_candidates(primary: Sequence[str], fallback: Sequence[str], lang: str) -> List[str]:
    ordered: List[str] = []
    seen: Set[str] = set()
    for raw in list(primary) + list(fallback):
        cleaned = postprocess_hard_options._sanitize_str(raw)
        if not cleaned:
            continue
        key = _normalized_label_key(cleaned, lang)
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(cleaned)
    return ordered


def _llm_validate_bonus_word(
    *,
    model: str,
    lang: str,
    quote: str,
    riddle: str,
    bonus_word: str,
) -> Tuple[bool, str, Dict[str, int | bool]]:
    payload = {
        "instructions": BONUS_WORD_REVIEW_PROMPT,
        "examples": BONUS_WORD_REVIEW_EXAMPLES,
        "lang": lang,
        "quote": quote,
        "riddle": riddle,
        "bonus_word": bonus_word,
    }
    data, llm_stats = add_bonus_words._call_llm_json(
        model=model,
        payload=payload,
        max_attempts=2,
    )
    if add_bonus_words._to_bool(data.get("accept")):
        return True, "", llm_stats
    return False, (postprocess_hard_options._sanitize_str(data.get("reason")) or "bonus_word_rejected"), llm_stats


def _llm_validate_bonus_pair_quality(
    *,
    model: str,
    quote_en: str,
    quote_he: str,
    bonus_en: str,
    bonus_he: str,
) -> Tuple[bool, str, Dict[str, int | bool]]:
    payload = {
        "instructions": BONUS_PAIR_REVIEW_PROMPT,
        "examples": BONUS_PAIR_REVIEW_EXAMPLES,
        "quote_en": quote_en,
        "quote_he": quote_he,
        "bonus_en": bonus_en,
        "bonus_he": bonus_he,
    }
    data, llm_stats = add_bonus_words._call_llm_json(
        model=model,
        payload=payload,
        max_attempts=2,
    )
    if add_bonus_words._to_bool(data.get("accept_en")):
        return True, "", llm_stats
    return False, (postprocess_hard_options._sanitize_str(data.get("reason")) or "bonus_pair_rejected"), llm_stats


def _item_overlap_key(item: Dict) -> Tuple[str, str, str, str]:
    en = item.get("en", {}) if isinstance(item.get("en"), dict) else {}
    he = item.get("he", {}) if isinstance(item.get("he"), dict) else {}
    return (
        _normalized_label_key(postprocess_hard_options._sanitize_str(en.get("speaker")), "en"),
        _normalized_label_key(postprocess_hard_options._sanitize_str(en.get("listener")), "en"),
        _normalized_label_key(postprocess_hard_options._sanitize_str(he.get("speaker")), "he"),
        _normalized_label_key(postprocess_hard_options._sanitize_str(he.get("listener")), "he"),
    )


def _item_source_span(item: Dict, payload: Dict) -> Tuple[int, int, int]:
    source = item.get("source", {}) if isinstance(item.get("source"), dict) else {}
    chapter = postprocess_hard_options._sanitize_int(source.get("chapter"), postprocess_hard_options._sanitize_int(payload.get("chapter"), 0))
    start = postprocess_hard_options._sanitize_int(source.get("quote_verse_start"), 0)
    end = postprocess_hard_options._sanitize_int(source.get("quote_verse_end"), 0)
    if end < start:
        start, end = end, start
    return chapter, start, end


def _ranges_overlap(a: Tuple[int, int, int], b: Tuple[int, int, int]) -> bool:
    if a[0] <= 0 or b[0] <= 0 or a[0] != b[0]:
        return False
    if a[1] <= 0 or a[2] <= 0 or b[1] <= 0 or b[2] <= 0:
        return False
    return not (a[2] < b[1] or b[2] < a[1])


def _item_keep_score(item: Dict, payload: Dict) -> Tuple[int, int]:
    chapter, start, end = _item_source_span(item, payload)
    span = (end - start + 1) if chapter > 0 and start > 0 and end > 0 else 0
    en = item.get("en", {}) if isinstance(item.get("en"), dict) else {}
    he = item.get("he", {}) if isinstance(item.get("he"), dict) else {}
    quote_len = len(postprocess_hard_options._sanitize_str(en.get("quote"))) + len(
        postprocess_hard_options._sanitize_str(he.get("quote"))
    )
    return span, quote_len


def _dedupe_overlapping_items(
    items: List[Tuple[int, Dict]],
    payload: Dict,
) -> Tuple[List[Tuple[int, Dict]], List[Dict]]:
    kept: List[Tuple[int, Dict]] = []
    issues: List[Dict] = []
    for idx, item in items:
        key = _item_overlap_key(item)
        span = _item_source_span(item, payload)
        score = _item_keep_score(item, payload)
        overlap_positions: List[int] = []
        should_drop_current = False
        for pos, (kept_idx, kept_item) in enumerate(kept):
            if not isinstance(kept_item, dict):
                continue
            if _item_overlap_key(kept_item) != key:
                continue
            kept_span = _item_source_span(kept_item, payload)
            if not _ranges_overlap(span, kept_span):
                continue
            kept_score = _item_keep_score(kept_item, payload)
            if score > kept_score:
                overlap_positions.append(pos)
            else:
                should_drop_current = True
                issues.append(
                    {
                        "idx": idx,
                        "id": postprocess_hard_options._sanitize_str(item.get("id")),
                        "status": "drop_overlap_shorter",
                        "reason": "kept_longer_overlapping_item",
                    }
                )
                break
        if should_drop_current:
            continue
        if overlap_positions:
            for pos in sorted(overlap_positions, reverse=True):
                old_idx, old_item = kept[pos]
                issues.append(
                    {
                        "idx": old_idx,
                        "id": postprocess_hard_options._sanitize_str(old_item.get("id")),
                        "status": "drop_overlap_shorter",
                        "reason": "replaced_by_longer_overlapping_item",
                    }
                )
                kept.pop(pos)
        kept.append((idx, item))
    kept.sort(key=lambda pair: pair[0])
    return kept, issues


def _is_strict_pair(candidate: postprocess_hard_options.AlignedCandidate) -> bool:
    return postprocess_hard_options._is_viable_entity_label(candidate.en.label, "en", strict=True) and (
        postprocess_hard_options._is_viable_entity_label(candidate.he.label, "he", strict=True)
    )


def _fill_regular_with_fallback(
    *,
    bucket: List[postprocess_hard_options.AlignedCandidate],
    queue: Sequence[postprocess_hard_options.AlignedCandidate],
    max_count: int,
    answer_tokens_en: Set[str],
    answer_tokens_he: Set[str],
    target_quote_tokens_en: Set[str],
    target_quote_tokens_he: Set[str],
    target_riddle_tokens_en: Set[str],
    target_riddle_tokens_he: Set[str],
    allow_relaxed: bool,
) -> None:
    if len(bucket) >= max_count:
        return

    bucket_en_norms = {candidate.en.label_norm for candidate in bucket}
    bucket_he_norms = {candidate.he.label_norm for candidate in bucket}
    strict_scored: List[Tuple[float, postprocess_hard_options.AlignedCandidate]] = []
    relaxed_scored: List[Tuple[float, postprocess_hard_options.AlignedCandidate]] = []

    for candidate in queue:
        regular_score, _ = postprocess_hard_options._aligned_candidate_score(
            candidate=candidate,
            answer_tokens_en=answer_tokens_en,
            answer_tokens_he=answer_tokens_he,
            target_quote_tokens_en=target_quote_tokens_en,
            target_quote_tokens_he=target_quote_tokens_he,
            target_riddle_tokens_en=target_riddle_tokens_en,
            target_riddle_tokens_he=target_riddle_tokens_he,
        )
        if regular_score <= 0:
            continue
        if _is_strict_pair(candidate):
            strict_scored.append((regular_score, candidate))
            continue
        if allow_relaxed and (
            postprocess_hard_options._is_viable_entity_label(candidate.en.label, "en", strict=False)
            and postprocess_hard_options._is_viable_entity_label(candidate.he.label, "he", strict=False)
        ):
            relaxed_scored.append((regular_score, candidate))

    strict_scored.sort(key=lambda pair: pair[0], reverse=True)
    relaxed_scored.sort(key=lambda pair: pair[0], reverse=True)

    def consume(
        scored: Sequence[Tuple[float, postprocess_hard_options.AlignedCandidate]],
        min_score: float,
    ) -> None:
        nonlocal bucket_en_norms, bucket_he_norms
        for score, candidate in scored:
            if score < min_score:
                continue
            if candidate.en.label_norm in bucket_en_norms or candidate.he.label_norm in bucket_he_norms:
                continue
            postprocess_hard_options._append_candidate(
                bucket=bucket,
                bucket_en_norms=bucket_en_norms,
                bucket_he_norms=bucket_he_norms,
                candidate=candidate,
                max_count=max_count,
            )
            if len(bucket) >= max_count:
                return

    for threshold in (0.12, 0.08, 0.04):
        consume(strict_scored, threshold)
        if len(bucket) >= max_count:
            return

    if allow_relaxed and len(bucket) < max_count:
        for threshold in (0.10, 0.06):
            consume(relaxed_scored, threshold)
            if len(bucket) >= max_count:
                return


def _aligned_candidate_id(candidate: postprocess_hard_options.AlignedCandidate) -> str:
    return f"{candidate.en.label_norm}|{candidate.he.label_norm}"


def _pick_hard_anchor_candidate(
    *,
    queue: Sequence[postprocess_hard_options.AlignedCandidate],
    answer_tokens_en: Set[str],
    answer_tokens_he: Set[str],
    target_quote_tokens_en: Set[str],
    target_quote_tokens_he: Set[str],
    target_riddle_tokens_en: Set[str],
    target_riddle_tokens_he: Set[str],
) -> Tuple[Optional[postprocess_hard_options.AlignedCandidate], float]:
    best_candidate: Optional[postprocess_hard_options.AlignedCandidate] = None
    best_hard = -1.0
    for candidate in queue:
        _, hard = postprocess_hard_options._aligned_candidate_score(
            candidate=candidate,
            answer_tokens_en=answer_tokens_en,
            answer_tokens_he=answer_tokens_he,
            target_quote_tokens_en=target_quote_tokens_en,
            target_quote_tokens_he=target_quote_tokens_he,
            target_riddle_tokens_en=target_riddle_tokens_en,
            target_riddle_tokens_he=target_riddle_tokens_he,
        )
        if hard > best_hard:
            best_hard = hard
            best_candidate = candidate
    if best_candidate is None or best_hard <= 0:
        return None, 0.0
    return best_candidate, best_hard


def _ensure_hard_anchor_in_selected(
    *,
    selected: List[postprocess_hard_options.AlignedCandidate],
    hard_anchor: Optional[postprocess_hard_options.AlignedCandidate],
    option_count: int,
    answer_tokens_en: Set[str],
    answer_tokens_he: Set[str],
    target_quote_tokens_en: Set[str],
    target_quote_tokens_he: Set[str],
    target_riddle_tokens_en: Set[str],
    target_riddle_tokens_he: Set[str],
) -> bool:
    if hard_anchor is None:
        return False
    anchor_id = _aligned_candidate_id(hard_anchor)
    selected_ids = {_aligned_candidate_id(candidate) for candidate in selected}
    if anchor_id in selected_ids:
        return False

    if len(selected) < option_count:
        selected.append(hard_anchor)
        return True

    if not selected:
        return False

    weakest_idx = -1
    weakest_hard = 10.0
    for idx, candidate in enumerate(selected):
        _, hard = postprocess_hard_options._aligned_candidate_score(
            candidate=candidate,
            answer_tokens_en=answer_tokens_en,
            answer_tokens_he=answer_tokens_he,
            target_quote_tokens_en=target_quote_tokens_en,
            target_quote_tokens_he=target_quote_tokens_he,
            target_riddle_tokens_en=target_riddle_tokens_en,
            target_riddle_tokens_he=target_riddle_tokens_he,
        )
        if hard < weakest_hard:
            weakest_hard = hard
            weakest_idx = idx
    if weakest_idx < 0:
        return False

    selected[weakest_idx] = hard_anchor
    return True


def _select_regular_options_for_field(
    *,
    model: str,
    field: str,
    item_id: str,
    answer_en: str,
    answer_he: str,
    target_quote_en: str,
    target_quote_he: str,
    target_riddle_en: str,
    target_riddle_he: str,
    candidates: Sequence[postprocess_hard_options.AlignedCandidate],
    option_count: int,
    sample_size: int,
    max_rounds: int,
    llm_retries: int,
    same_book_only: bool,
    target_book_code: str,
    target_book: str,
    target_chapter: int,
    chapter_window: int,
    allow_relaxed_options: bool,
) -> Tuple[List[postprocess_hard_options.AlignedCandidate], Dict[str, int | bool], List[str]]:
    llm_totals: Dict[str, int | bool] = {
        "calls": 0,
        "prompt_tokens": 0,
        "response_tokens": 0,
        "estimated": False,
    }
    notes: List[str] = []

    answer_norm_en = postprocess_hard_options._normalize_label(answer_en, "en")
    answer_norm_he = postprocess_hard_options._normalize_label(answer_he, "he")
    queue = postprocess_hard_options._prepare_candidate_queue(
        candidates=candidates,
        answer_norm_en=answer_norm_en,
        answer_norm_he=answer_norm_he,
        seed=f"{item_id}:{field}",
        option_count=option_count,
        same_book_only=same_book_only,
        target_book_code=target_book_code,
        target_book=target_book,
    )
    pre_ban_count = len(queue)
    queue = [candidate for candidate in queue if not _is_banned_option_label(candidate)]
    if len(queue) != pre_ban_count:
        notes.append(f"banned_options_removed:{pre_ban_count - len(queue)}")
    if target_chapter > 0 and chapter_window > 0:
        nearby = [
            candidate
            for candidate in queue
            if candidate.en.chapter > 0 and abs(candidate.en.chapter - target_chapter) <= chapter_window
        ]
        nearby_strict = [candidate for candidate in nearby if _is_strict_pair(candidate)]
        if len(nearby_strict) >= max(2, min(option_count, 2)):
            queue = nearby
            notes.append(f"chapter_window_applied:{chapter_window}")

    answer_divine_en = postprocess_hard_options._normalize_divine_alias(answer_en, "en")
    answer_divine_he = postprocess_hard_options._normalize_divine_alias(answer_he, "he")
    if not answer_divine_en and not answer_divine_he:
        non_divine = [
            candidate
            for candidate in queue
            if not postprocess_hard_options._normalize_divine_alias(candidate.en.label, "en")
            and not postprocess_hard_options._normalize_divine_alias(candidate.he.label, "he")
        ]
        non_divine_strict = [candidate for candidate in non_divine if _is_strict_pair(candidate)]
        if len(non_divine_strict) >= max(2, min(option_count, 2)):
            queue = non_divine
            notes.append("exclude_divine_non_divine_target")

    strict_queue = [candidate for candidate in queue if _is_strict_pair(candidate)]
    if strict_queue:
        queue = strict_queue
    elif not allow_relaxed_options:
        queue = []

    strict_count = len(strict_queue)
    if strict_count < option_count:
        notes.append(f"low_strict_candidates:{strict_count}")

    answer_tokens_en = postprocess_hard_options._token_set(answer_en, "en")
    answer_tokens_he = postprocess_hard_options._token_set(answer_he, "he")
    target_quote_tokens_en = postprocess_hard_options._token_set(target_quote_en, "en")
    target_quote_tokens_he = postprocess_hard_options._token_set(target_quote_he, "he")
    target_riddle_tokens_en = postprocess_hard_options._token_set(target_riddle_en, "en")
    target_riddle_tokens_he = postprocess_hard_options._token_set(target_riddle_he, "he")
    hard_anchor, hard_anchor_score = _pick_hard_anchor_candidate(
        queue=queue,
        answer_tokens_en=answer_tokens_en,
        answer_tokens_he=answer_tokens_he,
        target_quote_tokens_en=target_quote_tokens_en,
        target_quote_tokens_he=target_quote_tokens_he,
        target_riddle_tokens_en=target_riddle_tokens_en,
        target_riddle_tokens_he=target_riddle_tokens_he,
    )
    if hard_anchor is not None:
        notes.append(f"hard_anchor_score:{hard_anchor_score:.3f}")

    selected: List[postprocess_hard_options.AlignedCandidate] = []
    selected_en_norms: Set[str] = set()
    selected_he_norms: Set[str] = set()
    if hard_anchor is not None:
        postprocess_hard_options._append_candidate(
            bucket=selected,
            bucket_en_norms=selected_en_norms,
            bucket_he_norms=selected_he_norms,
            candidate=hard_anchor,
            max_count=option_count,
        )

    rounds = 0
    cursor = 0
    if queue:
        while rounds < max_rounds:
            if len(selected) >= option_count:
                break
            if cursor >= len(queue):
                break
            batch = list(queue[cursor : cursor + sample_size])
            cursor += sample_size
            rounds += 1
            if not batch:
                break

            payload = {
                "instructions": REGULAR_PICK_PROMPT,
                "target": {
                    "item_id": item_id,
                    "field": field,
                    "answer_en": answer_en,
                    "answer_he": answer_he,
                    "quote_en": target_quote_en,
                    "quote_he": target_quote_he,
                    "riddle_en": target_riddle_en,
                    "riddle_he": target_riddle_he,
                },
                "limits": {
                    "target_count": option_count,
                },
                "already_selected": postprocess_hard_options._selected_to_prompt(selected),
                "candidates": [postprocess_hard_options._candidate_to_prompt(candidate, idx) for idx, candidate in enumerate(batch)],
            }
            data, llm_stats = postprocess_hard_options._call_llm_json(
                model=model,
                payload=payload,
                max_attempts=max(1, llm_retries),
            )
            llm_totals = _merge_llm_stats(llm_totals, llm_stats)

            add_indices = postprocess_hard_options._sanitize_indices(data.get("add"), len(batch))
            if not add_indices:
                add_indices = postprocess_hard_options._sanitize_indices(data.get("regular_add"), len(batch))

            for idx in add_indices:
                candidate = batch[idx]
                postprocess_hard_options._append_candidate(
                    bucket=selected,
                    bucket_en_norms=selected_en_norms,
                    bucket_he_norms=selected_he_norms,
                    candidate=candidate,
                    max_count=option_count,
                )

        if selected:
            payload = {
                "instructions": REGULAR_VALIDATE_PROMPT,
                "target": {
                    "item_id": item_id,
                    "field": field,
                    "answer_en": answer_en,
                    "answer_he": answer_he,
                    "quote_en": target_quote_en,
                    "quote_he": target_quote_he,
                    "riddle_en": target_riddle_en,
                    "riddle_he": target_riddle_he,
                },
                "selected": postprocess_hard_options._selected_to_prompt(selected),
            }
            data, llm_stats = postprocess_hard_options._call_llm_json(
                model=model,
                payload=payload,
                max_attempts=max(1, llm_retries),
            )
            llm_totals = _merge_llm_stats(llm_totals, llm_stats)

            drop_indices = postprocess_hard_options._sanitize_indices(data.get("drop"), len(selected))
            if not drop_indices:
                drop_indices = postprocess_hard_options._sanitize_indices(data.get("drop_regular"), len(selected))
            if drop_indices:
                drop_set = set(drop_indices)
                selected = [candidate for idx, candidate in enumerate(selected) if idx not in drop_set]
                selected_en_norms = {candidate.en.label_norm for candidate in selected}
                selected_he_norms = {candidate.he.label_norm for candidate in selected}

    if _ensure_hard_anchor_in_selected(
        selected=selected,
        hard_anchor=hard_anchor,
        option_count=option_count,
        answer_tokens_en=answer_tokens_en,
        answer_tokens_he=answer_tokens_he,
        target_quote_tokens_en=target_quote_tokens_en,
        target_quote_tokens_he=target_quote_tokens_he,
        target_riddle_tokens_en=target_riddle_tokens_en,
        target_riddle_tokens_he=target_riddle_tokens_he,
    ):
        notes.append("hard_anchor_forced")

    _fill_regular_with_fallback(
        bucket=selected,
        queue=queue,
        max_count=option_count,
        answer_tokens_en=answer_tokens_en,
        answer_tokens_he=answer_tokens_he,
        target_quote_tokens_en=target_quote_tokens_en,
        target_quote_tokens_he=target_quote_tokens_he,
        target_riddle_tokens_en=target_riddle_tokens_en,
        target_riddle_tokens_he=target_riddle_tokens_he,
        allow_relaxed=allow_relaxed_options,
    )

    if _ensure_hard_anchor_in_selected(
        selected=selected,
        hard_anchor=hard_anchor,
        option_count=option_count,
        answer_tokens_en=answer_tokens_en,
        answer_tokens_he=answer_tokens_he,
        target_quote_tokens_en=target_quote_tokens_en,
        target_quote_tokens_he=target_quote_tokens_he,
        target_riddle_tokens_en=target_riddle_tokens_en,
        target_riddle_tokens_he=target_riddle_tokens_he,
    ):
        notes.append("hard_anchor_forced_after_fallback")

    selected = selected[:option_count]
    if len(selected) < option_count:
        notes.append(f"short:{len(selected)}/{option_count}")
    return selected, llm_totals, notes


def _build_item_with_options(
    *,
    item: Dict,
    pools: Dict[str, List[postprocess_hard_options.AlignedCandidate]],
    model: str,
    option_count: int,
    sample_size: int,
    max_rounds: int,
    llm_retries: int,
    same_book_only: bool,
    target_book_code: str,
    target_book: str,
    target_chapter: int,
    chapter_window: int,
    allow_relaxed_options: bool,
) -> Tuple[Dict, Dict[str, int | bool], List[Dict]]:
    item_id = postprocess_hard_options._sanitize_str(item.get("id"))
    out_item = copy.deepcopy(item)
    for lang in LANGS:
        section = out_item.get(lang)
        if not isinstance(section, dict):
            section = {}
            out_item[lang] = section
        section["speaker"] = _clean_entity_label(postprocess_hard_options._sanitize_str(section.get("speaker")))
        section["listener"] = _clean_entity_label(postprocess_hard_options._sanitize_str(section.get("listener")))
        section["options"] = {"speaker": [], "listener": []}
        if "hard_difficulty_options" in section:
            section.pop("hard_difficulty_options", None)

    llm_totals: Dict[str, int | bool] = {
        "calls": 0,
        "prompt_tokens": 0,
        "response_tokens": 0,
        "estimated": False,
    }
    issues: List[Dict] = []

    en_section = out_item.get("en", {}) if isinstance(out_item.get("en"), dict) else {}
    he_section = out_item.get("he", {}) if isinstance(out_item.get("he"), dict) else {}

    for field in FIELDS:
        answer_en = _clean_entity_label(postprocess_hard_options._sanitize_str(en_section.get(field)))
        answer_he = _clean_entity_label(postprocess_hard_options._sanitize_str(he_section.get(field)))
        target_quote_en = postprocess_hard_options._sanitize_str(en_section.get("quote"))
        target_quote_he = postprocess_hard_options._sanitize_str(he_section.get("quote"))
        target_riddle_en = postprocess_hard_options._sanitize_str(en_section.get("riddle"))
        target_riddle_he = postprocess_hard_options._sanitize_str(he_section.get("riddle"))
        if not answer_en or not answer_he or not target_quote_en or not target_quote_he:
            issues.append(
                {
                    "id": item_id,
                    "field": field,
                    "status": "skip_missing_target_data",
                }
            )
            continue

        regular, field_stats, notes = _select_regular_options_for_field(
            model=model,
            field=field,
            item_id=item_id,
            answer_en=answer_en,
            answer_he=answer_he,
            target_quote_en=target_quote_en,
            target_quote_he=target_quote_he,
            target_riddle_en=target_riddle_en,
            target_riddle_he=target_riddle_he,
            candidates=pools[field],
            option_count=option_count,
            sample_size=sample_size,
            max_rounds=max_rounds,
            llm_retries=llm_retries,
            same_book_only=same_book_only,
            target_book_code=target_book_code,
            target_book=target_book,
            target_chapter=target_chapter,
            chapter_window=chapter_window,
            allow_relaxed_options=allow_relaxed_options,
        )
        llm_totals = _merge_llm_stats(llm_totals, field_stats)

        out_item["en"]["options"][field] = [_clean_entity_label(candidate.en.label) for candidate in regular]
        out_item["he"]["options"][field] = [_clean_entity_label(candidate.he.label) for candidate in regular]

        if notes:
            issues.append(
                {
                    "id": item_id,
                    "field": field,
                    "status": "notes",
                    "notes": notes,
                }
            )

    return out_item, llm_totals, issues


def _pick_bonus_words_hebrew_priority(
    *,
    model: str,
    item: Dict,
    hint_picker: Optional[bonus_hint_picker.BonusHintPicker],
    max_retries: int,
    min_tokens: int,
    max_tokens: int,
) -> Tuple[Optional[Tuple[str, str]], Dict[str, int | bool], List[str], str]:
    pair, llm_stats, retries, fail_reason = add_bonus_words._pick_bonus_words(
        model=model,
        item=item,
        hint_picker=hint_picker,
        max_retries=max_retries,
        min_tokens=min_tokens,
        max_tokens=max_tokens,
    )

    initial_bonus_en = ""
    initial_bonus_he = ""
    if pair is not None:
        initial_bonus_en = postprocess_hard_options._sanitize_str(pair[0])
        initial_bonus_he = postprocess_hard_options._sanitize_str(pair[1])

    en = item.get("en", {}) if isinstance(item.get("en"), dict) else {}
    he = item.get("he", {}) if isinstance(item.get("he"), dict) else {}
    source = item.get("source", {}) if isinstance(item.get("source"), dict) else {}
    quote_en = postprocess_hard_options._sanitize_str(en.get("quote"))
    quote_he = postprocess_hard_options._sanitize_str(he.get("quote"))
    riddle_en = postprocess_hard_options._sanitize_str(en.get("riddle"))
    riddle_he = postprocess_hard_options._sanitize_str(he.get("riddle"))
    speaker_en = postprocess_hard_options._sanitize_str(en.get("speaker"))
    listener_en = postprocess_hard_options._sanitize_str(en.get("listener"))
    speaker_he = postprocess_hard_options._sanitize_str(he.get("speaker"))
    listener_he = postprocess_hard_options._sanitize_str(he.get("listener"))

    cand_he = add_bonus_words._candidate_bonus_words(quote=quote_he, riddle=riddle_he, lang="he")
    if not cand_he:
        cand_he = add_bonus_words._candidate_bonus_words(
            quote=quote_he,
            riddle=riddle_he,
            lang="he",
            include_stopwords=True,
        )
    cand_he = _ordered_unique_bonus_candidates(
        [initial_bonus_he] if initial_bonus_he else [],
        add_bonus_words._rank_bonus_candidates(cand_he, "he", hint_picker),
        "he",
    )

    chosen_he = ""
    for candidate in cand_he[:36]:
        fixed_he, reason_he = add_bonus_words._validate_lang_bonus(
            quote=quote_he,
            riddle=riddle_he,
            candidate=candidate,
            lang="he",
            min_tokens=min_tokens,
            max_tokens=max_tokens,
        )
        if not fixed_he:
            retries.append(f"he_candidate_reject:{reason_he}")
            continue
        if add_bonus_words.text_cleanup.riddle_mentions_entities(fixed_he, speaker_he, listener_he, "he"):
            retries.append("he_candidate_mentions_entities")
            continue
        if not add_bonus_words._has_hint_candidates(
            hint_picker=hint_picker,
            lang="he",
            bonus_word=fixed_he,
            current_quote=quote_he,
            source=source,
        ):
            retries.append("he_candidate_no_hint_candidates")
            continue
        he_ok, he_reason, he_stats = _llm_validate_bonus_word(
            model=model,
            lang="he",
            quote=quote_he,
            riddle=riddle_he,
            bonus_word=fixed_he,
        )
        llm_stats = _merge_llm_stats(llm_stats, he_stats)
        if not he_ok:
            retries.append(f"he_candidate_llm_reject:{he_reason}")
            continue
        chosen_he = fixed_he
        break

    if not chosen_he:
        return None, llm_stats, retries, (fail_reason or "he_bonus_not_found")

    cand_en = add_bonus_words._candidate_bonus_words(quote=quote_en, riddle=riddle_en, lang="en")
    if not cand_en:
        cand_en = add_bonus_words._candidate_bonus_words(
            quote=quote_en,
            riddle=riddle_en,
            lang="en",
            include_stopwords=True,
        )
    cand_en = _ordered_unique_bonus_candidates(
        [initial_bonus_en] if initial_bonus_en else [],
        add_bonus_words._rank_bonus_candidates(cand_en, "en", hint_picker),
        "en",
    )

    chosen_en = ""
    for candidate in cand_en[:36]:
        fixed_en, reason_en = add_bonus_words._validate_lang_bonus(
            quote=quote_en,
            riddle=riddle_en,
            candidate=candidate,
            lang="en",
            min_tokens=min_tokens,
            max_tokens=max_tokens,
        )
        if not fixed_en:
            retries.append(f"en_candidate_reject:{reason_en}")
            continue
        if add_bonus_words.text_cleanup.riddle_mentions_entities(fixed_en, speaker_en, listener_en, "en"):
            retries.append("en_candidate_mentions_entities")
            continue
        if not add_bonus_words._has_hint_candidates(
            hint_picker=hint_picker,
            lang="en",
            bonus_word=fixed_en,
            current_quote=quote_en,
            source=source,
        ):
            retries.append("en_candidate_no_hint_candidates")
            continue
        en_ok, en_reason, en_stats = _llm_validate_bonus_word(
            model=model,
            lang="en",
            quote=quote_en,
            riddle=riddle_en,
            bonus_word=fixed_en,
        )
        llm_stats = _merge_llm_stats(llm_stats, en_stats)
        if not en_ok:
            retries.append(f"en_candidate_llm_reject:{en_reason}")
            continue
        pair_ok, pair_reason, pair_stats = _llm_validate_bonus_pair_quality(
            model=model,
            quote_en=quote_en,
            quote_he=quote_he,
            bonus_en=fixed_en,
            bonus_he=chosen_he,
        )
        llm_stats = _merge_llm_stats(llm_stats, pair_stats)
        if not pair_ok:
            retries.append(f"en_candidate_pair_reject:{pair_reason}")
            continue
        chosen_en = fixed_en
        break

    if not chosen_en:
        retries.append("en_missing_accepted_he_priority")

    return (chosen_en, chosen_he), llm_stats, retries, ""


def _ensure_bonus_and_hints(
    *,
    item: Dict,
    payload: Dict,
    bonus_model: str,
    hint_model: str,
    hint_picker: bonus_hint_picker.BonusHintPicker,
    max_bonus_retries: int,
    min_bonus_tokens: int,
    max_bonus_tokens: int,
    hint_max_candidates: int,
    hint_retries: int,
    overwrite_existing_bonus: bool,
) -> BonusOutcome:
    changed = False
    llm_stats: Dict[str, int | bool] = {
        "calls": 0,
        "prompt_tokens": 0,
        "response_tokens": 0,
        "estimated": False,
    }
    issues: List[Dict] = []

    if add_bonus_words._normalize_item_book_and_ref(item=item, payload=payload):
        changed = True

    if not isinstance(item.get("en"), dict):
        item["en"] = {}
        changed = True
    if not isinstance(item.get("he"), dict):
        item["he"] = {}
        changed = True

    en = item["en"]
    he = item["he"]
    existing_bonus_en = postprocess_hard_options._sanitize_str(en.get("bonus"))
    existing_bonus_he = postprocess_hard_options._sanitize_str(he.get("bonus"))

    bonus_en = existing_bonus_en
    bonus_he = existing_bonus_he

    should_generate_bonus = (
        bool(overwrite_existing_bonus)
        or (not existing_bonus_he)
    )
    if should_generate_bonus:
        pair, pick_stats, retries, fail_reason = _pick_bonus_words_hebrew_priority(
            model=bonus_model,
            item=item,
            hint_picker=hint_picker,
            max_retries=max_bonus_retries,
            min_tokens=min_bonus_tokens,
            max_tokens=max_bonus_tokens,
        )
        llm_stats = _merge_llm_stats(llm_stats, pick_stats)
        if pair is None:
            issues.append(
                {
                    "id": postprocess_hard_options._sanitize_str(item.get("id")),
                    "status": "failed_bonus",
                    "reason": fail_reason,
                    "retries": retries,
                }
            )
            return BonusOutcome(
                changed=changed,
                failed_bonus=True,
                hint_en_set=False,
                hint_he_set=False,
                llm_stats=llm_stats,
                issues=issues,
            )

        bonus_en, bonus_he = pair
        if postprocess_hard_options._sanitize_str(en.get("bonus")) != bonus_en:
            en["bonus"] = bonus_en
            changed = True
        if postprocess_hard_options._sanitize_str(he.get("bonus")) != bonus_he:
            he["bonus"] = bonus_he
            changed = True
        if "meta" not in item or not isinstance(item.get("meta"), dict):
            item["meta"] = {}
            changed = True
        if item["meta"].get("bonus_source") != "llm":
            item["meta"]["bonus_source"] = "llm"
            changed = True
        if postprocess_hard_options._sanitize_int(item["meta"].get("bonus_retries"), -1) != len(retries):
            item["meta"]["bonus_retries"] = len(retries)
            changed = True

    bonus_en = postprocess_hard_options._sanitize_str(en.get("bonus"))
    bonus_he = postprocess_hard_options._sanitize_str(he.get("bonus"))
    if not bonus_he:
        issues.append(
            {
                "id": postprocess_hard_options._sanitize_str(item.get("id")),
                "status": "missing_bonus_after_generation",
            }
        )
        return BonusOutcome(
            changed=changed,
            failed_bonus=True,
            hint_en_set=False,
            hint_he_set=False,
            llm_stats=llm_stats,
            issues=issues,
        )

    source = item.get("source", {}) if isinstance(item.get("source"), dict) else {}
    hint_en = None
    hint_en_reason = "no_bonus_word"
    if bonus_en:
        hint_en, hint_en_stats, hint_en_reason = hint_picker.pick_hint(
            model=hint_model,
            lang="en",
            bonus_word=bonus_en,
            current_quote=postprocess_hard_options._sanitize_str(en.get("quote")),
            source=source,
            max_candidates=hint_max_candidates,
            max_retries=hint_retries,
        )
        llm_stats = _merge_llm_stats(llm_stats, hint_en_stats)

    hint_he, hint_he_stats, hint_he_reason = hint_picker.pick_hint(
        model=hint_model,
        lang="he",
        bonus_word=bonus_he,
        current_quote=postprocess_hard_options._sanitize_str(he.get("quote")),
        source=source,
        max_candidates=hint_max_candidates,
        max_retries=hint_retries,
    )
    llm_stats = _merge_llm_stats(llm_stats, hint_he_stats)

    if add_bonus_words._set_bonus_hint(item=item, lang="en", hint=hint_en):
        changed = True
    if add_bonus_words._set_bonus_hint(item=item, lang="he", hint=hint_he):
        changed = True

    if bonus_en and hint_en is None and hint_en_reason not in {"", "no_candidates", "llm_none"}:
        issues.append(
            {
                "id": postprocess_hard_options._sanitize_str(item.get("id")),
                "status": "bonus_hint_none",
                "lang": "en",
                "reason": hint_en_reason,
                "bonus": bonus_en,
            }
        )
    if hint_he is None and hint_he_reason not in {"", "no_candidates", "llm_none"}:
        issues.append(
            {
                "id": postprocess_hard_options._sanitize_str(item.get("id")),
                "status": "bonus_hint_none",
                "lang": "he",
                "reason": hint_he_reason,
                "bonus": bonus_he,
            }
        )

    if "meta" not in item or not isinstance(item.get("meta"), dict):
        item["meta"] = {}
        changed = True
    if item["meta"].get("bonus_hint_source") != "llm":
        item["meta"]["bonus_hint_source"] = "llm"
        changed = True

    return BonusOutcome(
        changed=changed,
        failed_bonus=False,
        hint_en_set=hint_en is not None,
        hint_he_set=hint_he is not None,
        llm_stats=llm_stats,
        issues=issues,
    )


def _out_path_for_input(in_path: Path, out_dir: Path, in_dir: Path) -> Path:
    try:
        rel = in_path.relative_to(in_dir)
    except ValueError:
        rel = Path(in_path.name)
    return out_dir / rel


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gemma3:27b")
    parser.add_argument("--option-model", default="", help="override model used for option selection/validation")
    parser.add_argument(
        "--solution-check-model",
        default="gemma3:27b",
        help="model for solution validation (larger model recommended)",
    )
    parser.add_argument("--bonus-model", default="", help="override model for bonus selection and quality checks")
    parser.add_argument("--hint-model", default="", help="override model for bonus hint selection")
    parser.add_argument("--in-dir", default="data/rebuilt_quotes")
    parser.add_argument("--out-dir", default="data/quotes_options")
    parser.add_argument("--issues-log", default="data/quotes_options_issues.jsonl")
    parser.add_argument("--book", default="", help="book filter by code or name, e.g. GEN or Genesis")
    parser.add_argument("--chapters", default="", help="chapter filter, e.g. 1-3,12,15")
    parser.add_argument("--limit-files", type=int, default=0)
    parser.add_argument("--option-count", type=int, default=4)
    parser.add_argument("--sample-size", type=int, default=10)
    parser.add_argument("--max-rounds", type=int, default=6)
    parser.add_argument("--llm-retries", type=int, default=2)
    parser.add_argument("--solution-check-retries", type=int, default=2)
    parser.add_argument("--max-bonus-retries", type=int, default=6)
    parser.add_argument("--min-bonus-tokens", type=int, default=1)
    parser.add_argument("--max-bonus-tokens", type=int, default=2)
    parser.add_argument("--hint-max-candidates", type=int, default=10)
    parser.add_argument("--hint-retries", type=int, default=3)
    parser.add_argument("--same-book-only", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--chapter-window", type=int, default=4, help="prefer candidates within +/- this chapter distance")
    parser.add_argument("--allow-relaxed-options", action="store_true")
    parser.add_argument("--include-draft", action="store_true")
    parser.add_argument("--overwrite-existing-bonus", action="store_true")
    parser.add_argument("--english-xml", default=bible_sources.DEFAULT_ENGLISH_COLLECTION)
    parser.add_argument("--hebrew-zip", default=bible_sources.DEFAULT_HEBREW_ZIP)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.option_count < 1:
        raise SystemExit("--option-count must be >= 1")
    if args.sample_size < 1:
        raise SystemExit("--sample-size must be >= 1")
    if args.max_rounds < 0:
        raise SystemExit("--max-rounds must be >= 0")
    if args.llm_retries < 1:
        raise SystemExit("--llm-retries must be >= 1")
    if args.solution_check_retries < 1:
        raise SystemExit("--solution-check-retries must be >= 1")
    if args.max_bonus_retries < 1:
        raise SystemExit("--max-bonus-retries must be >= 1")
    if args.min_bonus_tokens < 1:
        raise SystemExit("--min-bonus-tokens must be >= 1")
    if args.max_bonus_tokens < args.min_bonus_tokens:
        raise SystemExit("--max-bonus-tokens must be >= --min-bonus-tokens")
    if args.hint_max_candidates < 1:
        raise SystemExit("--hint-max-candidates must be >= 1")
    if args.hint_retries < 1:
        raise SystemExit("--hint-retries must be >= 1")
    if args.chapter_window < 0:
        raise SystemExit("--chapter-window must be >= 0")

    in_dir = (ROOT / args.in_dir).resolve()
    out_dir = (ROOT / args.out_dir).resolve()
    issues_log = (ROOT / args.issues_log).resolve()
    english_xml = (ROOT / args.english_xml).resolve()
    hebrew_zip = (ROOT / args.hebrew_zip).resolve()

    option_model = postprocess_hard_options._sanitize_str(args.option_model) or postprocess_hard_options._sanitize_str(
        args.model
    )
    solution_check_model = (
        postprocess_hard_options._sanitize_str(args.solution_check_model)
        or postprocess_hard_options._sanitize_str(args.model)
    )
    bonus_model = postprocess_hard_options._sanitize_str(args.bonus_model) or postprocess_hard_options._sanitize_str(
        args.model
    )
    hint_model = postprocess_hard_options._sanitize_str(args.hint_model) or postprocess_hard_options._sanitize_str(
        args.model
    )
    if not option_model or not solution_check_model or not bonus_model or not hint_model:
        raise SystemExit("All model selections must resolve to non-empty values.")

    if not in_dir.exists() or not in_dir.is_dir():
        raise SystemExit(f"Input directory does not exist: {in_dir}")
    if not english_xml.exists():
        raise SystemExit(f"English XML does not exist: {english_xml}")
    if not hebrew_zip.exists():
        raise SystemExit(f"Hebrew ZIP does not exist: {hebrew_zip}")

    tqdm.write(f"Loading bonus-hint Bible index: en={english_xml} he={hebrew_zip}")
    hint_picker = bonus_hint_picker.BonusHintPicker.load(english_xml=english_xml, hebrew_zip=hebrew_zip)

    chapter_filter = postprocess_hard_options._chapter_filter(args.chapters)
    in_files = list(postprocess_hard_options._iter_input_files(in_dir, include_draft=bool(args.include_draft)))
    if args.limit_files > 0:
        in_files = in_files[: args.limit_files]

    payloads: List[Tuple[Path, Dict]] = []
    stats = Stats()
    issue_lines: List[str] = []

    for in_path in tqdm(in_files, desc="load-files", unit="file"):
        stats.files_seen += 1
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
        payloads.append((in_path, payload))

    if not payloads:
        tqdm.write("No readable payloads to process.")
        return 1 if stats.errors else 0

    pools = postprocess_hard_options._collect_candidate_pools(payloads)

    queue: List[Tuple[Path, Dict]] = []
    for in_path, payload in payloads:
        if not postprocess_hard_options._book_match(payload, args.book):
            continue
        chapter = postprocess_hard_options._sanitize_int(payload.get("chapter"), 0)
        if chapter_filter and chapter not in chapter_filter:
            continue
        out_path = _out_path_for_input(in_path, out_dir, in_dir)
        if out_path.exists() and not args.force:
            stats.files_skipped_existing += 1
            continue
        queue.append((in_path, payload))

    tqdm.write(
        "Options+bonus queue: files={files} pending={pending} skipped_existing={skipped} "
        "in_dir={in_dir} out_dir={out_dir} include_draft={include_draft} "
        "same_book_only={same_book_only} allow_relaxed_options={allow_relaxed_options} "
        "option_model={option_model} solution_check_model={solution_check_model} "
        "bonus_model={bonus_model} hint_model={hint_model}".format(
            files=len(payloads),
            pending=len(queue),
            skipped=stats.files_skipped_existing,
            in_dir=in_dir,
            out_dir=out_dir,
            include_draft=bool(args.include_draft),
            same_book_only=bool(args.same_book_only),
            allow_relaxed_options=bool(args.allow_relaxed_options),
            option_model=option_model,
            solution_check_model=solution_check_model,
            bonus_model=bonus_model,
            hint_model=hint_model,
        )
    )
    if not queue:
        return 1 if stats.errors else 0

    issues_log.parent.mkdir(parents=True, exist_ok=True)
    if args.force or not issues_log.exists():
        issues_log.write_text("", encoding="utf-8")

    for in_path, payload in tqdm(queue, desc="options+bonus", unit="file"):
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

        out_items: List[Dict] = []
        file_issues: List[Dict] = []
        indexed_items: List[Tuple[int, Dict]] = []
        for original_idx, raw_item in enumerate(items):
            if not isinstance(raw_item, dict):
                stats.errors += 1
                file_issues.append(
                    {
                        "idx": original_idx,
                        "status": "item_not_object",
                    }
                )
                continue
            indexed_items.append((original_idx, raw_item))

        indexed_items, overlap_issues = _dedupe_overlapping_items(indexed_items, payload)
        if overlap_issues:
            file_issues.extend(overlap_issues)

        for original_idx, item in indexed_items:
            idx = original_idx

            stats.items_seen += 1
            python_solution_ok, python_solution_reason = postprocess_hard_options._python_validate_solution(item)
            if not python_solution_ok:
                stats.items_dropped_solution_python += 1

            llm_solution_ok = True
            llm_solution_reason = ""
            stats.items_solution_checked += 1
            llm_solution_ok, llm_solution_reason, solution_stats = postprocess_hard_options._llm_validate_solution(
                model=solution_check_model,
                item=item,
                retries=args.solution_check_retries,
            )
            _add_llm_stats(stats, solution_stats)

            if not python_solution_ok or not llm_solution_ok:
                stats.items_dropped_solution_check += 1
                reasons: List[str] = []
                if not python_solution_ok:
                    reasons.append(f"python:{python_solution_reason}")
                if not llm_solution_ok:
                    reasons.append(f"llm:{llm_solution_reason or 'solution_check_failed'}")
                file_issues.append(
                    {
                        "idx": idx,
                        "id": postprocess_hard_options._sanitize_str(item.get("id")),
                        "status": "drop_invalid_solution",
                        "reason": "; ".join(reasons) if reasons else "solution_check_failed",
                    }
                )
                continue

            out_item = copy.deepcopy(item)
            source = out_item.get("source", {}) if isinstance(out_item.get("source"), dict) else {}
            target_book_code = postprocess_hard_options._sanitize_str(source.get("book_code")) or postprocess_hard_options._sanitize_str(
                payload.get("book_code")
            )
            target_book = postprocess_hard_options._sanitize_str(source.get("book")) or postprocess_hard_options._sanitize_str(
                payload.get("book")
            )
            target_chapter = postprocess_hard_options._sanitize_int(source.get("chapter"), 0) or postprocess_hard_options._sanitize_int(
                payload.get("chapter"),
                0,
            )

            bonus_outcome = _ensure_bonus_and_hints(
                item=out_item,
                payload=payload,
                bonus_model=bonus_model,
                hint_model=hint_model,
                hint_picker=hint_picker,
                max_bonus_retries=args.max_bonus_retries,
                min_bonus_tokens=args.min_bonus_tokens,
                max_bonus_tokens=args.max_bonus_tokens,
                hint_max_candidates=args.hint_max_candidates,
                hint_retries=args.hint_retries,
                overwrite_existing_bonus=bool(args.overwrite_existing_bonus),
            )
            _add_llm_stats(stats, bonus_outcome.llm_stats)
            if bonus_outcome.failed_bonus:
                stats.items_bonus_failed += 1
            stats.bonus_hints_set += 1 if bonus_outcome.hint_en_set else 0
            stats.bonus_hints_set += 1 if bonus_outcome.hint_he_set else 0
            stats.bonus_hints_null += 0 if bonus_outcome.hint_en_set else 1
            stats.bonus_hints_null += 0 if bonus_outcome.hint_he_set else 1
            for issue in bonus_outcome.issues:
                merged = {"idx": idx}
                merged.update(issue)
                file_issues.append(merged)

            out_item, option_stats, option_issues = _build_item_with_options(
                item=out_item,
                pools=pools,
                model=option_model,
                option_count=args.option_count,
                sample_size=args.sample_size,
                max_rounds=args.max_rounds,
                llm_retries=args.llm_retries,
                same_book_only=bool(args.same_book_only),
                target_book_code=target_book_code,
                target_book=target_book,
                target_chapter=target_chapter,
                chapter_window=args.chapter_window,
                allow_relaxed_options=bool(args.allow_relaxed_options),
            )
            _add_llm_stats(stats, option_stats)

            for lang in LANGS:
                for field in FIELDS:
                    stats.fields_built += 1
                    if len(out_item[lang]["options"][field]) < args.option_count:
                        stats.fields_insufficient += 1

            if option_issues:
                for issue in option_issues:
                    merged = {"idx": idx}
                    merged.update(issue)
                    file_issues.append(merged)

            out_items.append(out_item)
            stats.items_written += 1

        out_payload = copy.deepcopy(payload)
        out_payload["items"] = out_items

        out_path = _out_path_for_input(in_path, out_dir, in_dir)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        stats.files_written += 1

        if file_issues:
            issue_lines.append(
                json.dumps(
                    {
                        "file": str(in_path),
                        "output_file": str(out_path),
                        "status": "item_issues",
                        "issues": file_issues,
                    },
                    ensure_ascii=False,
                )
            )

    if issue_lines:
        with issues_log.open("a", encoding="utf-8") as handle:
            for line in issue_lines:
                handle.write(line + "\n")

    tqdm.write(
        "Done: files_seen={files_seen}, files_written={files_written}, files_skipped_existing={files_skipped_existing}, "
        "items_seen={items_seen}, items_solution_checked={items_solution_checked}, "
        "items_dropped_solution_python={items_dropped_solution_python}, items_dropped_solution_check={items_dropped_solution_check}, "
        "items_bonus_failed={items_bonus_failed}, items_written={items_written}, "
        "fields_built={fields_built}, fields_insufficient={fields_insufficient}, "
        "bonus_hints_set={bonus_hints_set}, bonus_hints_null={bonus_hints_null}, "
        "llm_calls={llm_calls}, prompt_tokens={prompt_tokens}, response_tokens={response_tokens}, "
        "estimated_calls={estimated_calls}, errors={errors}, out_dir={out_dir}, issues_log={issues_log}".format(
            files_seen=stats.files_seen,
            files_written=stats.files_written,
            files_skipped_existing=stats.files_skipped_existing,
            items_seen=stats.items_seen,
            items_solution_checked=stats.items_solution_checked,
            items_dropped_solution_python=stats.items_dropped_solution_python,
            items_dropped_solution_check=stats.items_dropped_solution_check,
            items_bonus_failed=stats.items_bonus_failed,
            items_written=stats.items_written,
            fields_built=stats.fields_built,
            fields_insufficient=stats.fields_insufficient,
            bonus_hints_set=stats.bonus_hints_set,
            bonus_hints_null=stats.bonus_hints_null,
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
