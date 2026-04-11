from __future__ import annotations

import json
import logging
import os
import re
from difflib import SequenceMatcher
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable

import click
from tqdm import tqdm

from data_proc.llm import JsonChatModel
from data_proc.pipeline import (
    DEFAULT_ENGLISH_XML,
    DEFAULT_HEBREW_ZIP,
    _canonical_book_filter,
    _chapter_sort_key,
    _normalized_riddle_key,
    _project_hebrew_substring_to_original,
)
from data_proc.schema import CandidateItem, CandidateMeta, CandidateSource, CandidateLangText, DropRecord, RawQuoteSource, RefRange
from data_proc.utils import bible_sources
from data_proc.utils.bible_tandem import RangeQuote, TandemBible
from data_proc.utils.text_cleanup import (
    candidate_riddle_spans,
    clean_text,
    cleanup_hebrew_quote,
    hebrew_surface_map,
    normalize_word,
    restore_hebrew_surface_from_map,
    strip_hebrew_marks,
)

LOG = logging.getLogger(__name__)

EN_CANDIDATE_REPORTING_WORDS = {
    "answered",
    "asked",
    "called",
    "commanded",
    "cried",
    "pray",
    "said",
    "saith",
    "say",
    "saying",
    "spake",
}
HE_CANDIDATE_REPORTING_WORDS = {
    "אמר",
    "ויאמר",
    "ויאמרו",
    "ותאמר",
    "ותאמרו",
    "ויקרא",
    "ויען",
    "ויענו",
}
EN_DIALOG_PRONOUNS = {
    "i",
    "me",
    "my",
    "mine",
    "thou",
    "thee",
    "thy",
    "thine",
    "ye",
    "you",
    "your",
    "yours",
    "we",
    "us",
    "our",
    "ours",
}
HE_DIALOG_PRONOUNS = {
    "אני",
    "אנכי",
    "אתה",
    "את",
    "אתם",
    "אתן",
    "אנחנו",
    "אותי",
    "אתי",
    "לך",
    "לכם",
    "לכן",
    "לי",
    "לו",
    "לה",
}
REPO_ROOT = Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class CandidateChapterShard:
    book_code: str
    book: str
    book_he: str
    chapter: int
    mode: str
    items: list[CandidateItem]
    stats: dict[str, int]

    @classmethod
    def from_dict(cls, data: dict) -> "CandidateChapterShard":
        return cls(
            book_code=data["book_code"],
            book=data["book"],
            book_he=data["book_he"],
            chapter=int(data["chapter"]),
            mode=data.get("mode", "llm"),
            items=[CandidateItem.from_dict(item) for item in data.get("items", [])],
            stats={str(key): int(value) for key, value in dict(data.get("stats", {})).items()},
        )

    def to_dict(self) -> dict:
        return {
            "book_code": self.book_code,
            "book": self.book,
            "book_he": self.book_he,
            "chapter": self.chapter,
            "mode": self.mode,
            "items": [item.to_dict() for item in self.items],
            "stats": dict(self.stats),
        }


@dataclass(frozen=True)
class CandidateSpec:
    quote_verse_start: int
    quote_verse_end: int
    speaker_mention_verse: int | None
    listener_mention_verse: int | None
    en_riddle: str
    en_speaker: str
    en_listener: str
    reason: str
    confidence: float


@dataclass(frozen=True)
class HebrewProjection:
    keep: bool
    he_riddle: str
    he_speaker: str
    he_listener: str


@dataclass(frozen=True)
class CandidateStrategyEvaluation:
    strategy: str
    passed_must_pass: bool
    recall_hits: int
    issue_count: int
    llm_call_count: int


MINIMAL_CANDIDATE_BOOK_CODES = (
    "GEN",
    "EXO",
    "LEV",
    "NUM",
    "DEU",
    "JOS",
    "JDG",
    "1SA",
    "2SA",
    "1KI",
    "2KI",
)
FULL_CHAPTER_STRATEGY = "full_chapter"
DIALOGUE_BLOCKS_STRATEGY = "dialogue_blocks"
PRODUCTION_CANDIDATE_EXTRACTION_STRATEGY = DIALOGUE_BLOCKS_STRATEGY
SHORT_RIDDLE_WORD_THRESHOLD = 3
BLOCK_CONTEXT_BEFORE = 2
BLOCK_CONTEXT_AFTER = 1
BLOCK_MAX_VERSES = 8
BLOCK_OVERLAP_VERSES = 1


def select_best_candidate_strategy(evaluations: Iterable[CandidateStrategyEvaluation]) -> str:
    ordered = sorted(
        evaluations,
        key=lambda evaluation: (
            not evaluation.passed_must_pass,
            -evaluation.recall_hits,
            evaluation.issue_count,
            evaluation.llm_call_count,
            evaluation.strategy,
        ),
    )
    if not ordered:
        raise ValueError("No candidate strategy evaluations were provided")
    return ordered[0].strategy


def _slugify_book_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _candidate_id(book: str, chapter: int, start: int, end: int) -> str:
    return f"{_slugify_book_name(book)}-{chapter:02d}-{start:02d}-{end:02d}"


def _chapter_shard_path(shard_dir: Path, *, book: str, chapter: int) -> Path:
    return shard_dir / f"{_slugify_book_name(book)}-{chapter:03d}.json"


def _iter_existing_shards(
    shard_dir: Path,
    *,
    book_filter: str | None,
    chapter_filter: int | None,
) -> list[tuple[tuple[str, int], Path]]:
    if not shard_dir.exists():
        return []

    entries: list[tuple[tuple[str, int], Path]] = []
    for path in sorted(shard_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            key = (str(payload["book_code"]), int(payload["chapter"]))
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            continue
        if book_filter and key[0] != book_filter:
            continue
        if chapter_filter is not None and key[1] != chapter_filter:
            continue
        entries.append((key, path))
    return entries


def _find_resume_point_for_chapters(
    chapter_keys: list[tuple[str, int]],
    *,
    shard_dir: Path,
    book_filter: str | None,
    chapter_filter: int | None,
) -> tuple[str, int] | None:
    if not chapter_keys:
        return None
    existing_keys = {key for key, _ in _iter_existing_shards(shard_dir, book_filter=book_filter, chapter_filter=chapter_filter)}
    for key in chapter_keys:
        if key not in existing_keys:
            return key
    return None


def _rebuild_candidates_jsonl(candidates_path: Path, shards: Iterable[CandidateChapterShard]) -> None:
    candidates_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = candidates_path.with_name(f".{candidates_path.name}.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        ordered_shards = sorted(shards, key=lambda shard: _chapter_sort_key(shard.book_code, shard.chapter))
        for shard in ordered_shards:
            ordered_items = sorted(shard.items, key=lambda item: (item.ref.start, item.ref.end, item.id))
            for item in ordered_items:
                handle.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")
    os.replace(tmp_path, candidates_path)


def _read_all_candidate_shards(shard_dir: Path) -> list[CandidateChapterShard]:
    shards: list[CandidateChapterShard] = []
    if not shard_dir.exists():
        return shards
    for _, path in _iter_existing_shards(shard_dir, book_filter=None, chapter_filter=None):
        try:
            shards.append(CandidateChapterShard.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, TypeError, KeyError, ValueError, json.JSONDecodeError):
            continue
    return sorted(shards, key=lambda shard: _chapter_sort_key(shard.book_code, shard.chapter))


def _candidate_prompt_system() -> str:
    return (
        "You extract Bible riddle candidates from English verses only. "
        "Be high recall for direct speech, questions, commands, replies, warnings, blessings, and vivid declarations. "
        "Drop narration, indirect reports without a memorable speech core, and obvious self-talk. "
        "Return exactly one JSON object with a single top-level key items. "
        'If there are no candidates, return {"items": []}. '
        "Do not return a bare array. Do not use markdown fences. Do not add any keys other than items at the top level. "
        "Each object must have exactly these keys: quote_verse_start, quote_verse_end, speaker_mention_verse, listener_mention_verse, en_riddle, en_speaker, en_listener, reason, confidence. "
        "quote_verse_start and quote_verse_end must be integers. speaker_mention_verse and listener_mention_verse must be integers or null. confidence must be a number between 0 and 1. "
        "quote_verse_start..quote_verse_end must be the minimal verse span of the speech turn itself, not the setup verses. "
        "speaker_mention_verse and listener_mention_verse may point to nearby provided verses that name the same roles more clearly; use null when the quote verses already provide enough context. "
        "en_riddle must be an exact substring of the English quote built from quote_verse_start..quote_verse_end. "
        "Copy en_riddle character-for-character from the provided verse text. Do not paraphrase. Do not modernize spelling. Keep words like ye, thou, hath, and midwife exactly as written. "
        "If the spoken core is shorter than 3 words, expand en_riddle to an exact substring that begins with the speech and may include immediate trailing narrative from the same verse for better UX. "
        "Use short concrete names or group labels for speakers and listeners when possible. "
        "Do not output duplicate items or overlapping variants of the same speech core. "
        "Keep reason very short, at most six words. "
        "Return items in verse order. "
        'Output shape example: {"items":[{"quote_verse_start":7,"quote_verse_end":7,"speaker_mention_verse":null,"listener_mention_verse":null,"en_riddle":"Shall I go and call thee a nurse","en_speaker":"sister","en_listener":"Pharaoh\'s daughter","reason":"direct question","confidence":0.92}]}.'
    )


def _display_hebrew_candidates(candidates: list[str]) -> tuple[list[str], dict[str, str]]:
    display_map: dict[str, str] = {}
    display_candidates: list[str] = []
    for candidate in candidates:
        normalized_display = strip_hebrew_marks(cleanup_hebrew_quote(candidate))
        display = cleanup_hebrew_quote(candidate)
        if not normalized_display or normalized_display in display_map:
            continue
        display_map[normalized_display] = candidate
        display_candidates.append(display)
    return display_candidates, display_map


def _candidate_prompt_user(*, book: str, chapter: int, verses: list[dict[str, object]]) -> str:
    return (
        f"ref: {book} {chapter}\n"
        f"english_verses: {json.dumps(verses, ensure_ascii=False)}\n"
        "Use only the provided verse numbers.\n"
        'Return exactly one JSON object shaped like {"items":[...]}.\n'
        "Never wrap the response in markdown.\n"
        "Every candidate must use verse numbers from the provided verses only."
    )


def _normalize_candidate_choice(value: object, allowed_map: dict[str, str], *, lang: str) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = strip_hebrew_marks(cleanup_hebrew_quote(value)) if lang == "he" else clean_text(value)
    return allowed_map.get(cleaned, "")


def _validate_confidence(value: object) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, confidence))


def _coerce_optional_verse(value: object, available_verses: set[int]) -> int | None:
    if value in (None, "", 0):
        return None
    try:
        verse = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid mention verse {value!r}") from exc
    if verse not in available_verses:
        raise ValueError(f"mention verse {verse} is outside the provided verses")
    return verse


def _quote_text_from_source(raw_source: dict[str, str], start: int, end: int) -> str:
    return clean_text(" ".join(raw_source[str(verse)] for verse in range(start, end + 1)))


def _english_similarity_score(target: str, candidate: str) -> tuple[float, int]:
    target_tokens = {normalize_word(token, "en") for token in clean_text(target).split()}
    candidate_tokens = {normalize_word(token, "en") for token in clean_text(candidate).split()}
    target_tokens.discard("")
    candidate_tokens.discard("")
    shared = target_tokens & candidate_tokens
    if not shared:
        return 0.0, 0
    overlap = len(shared) / max(len(target_tokens | candidate_tokens), 1)
    seq = SequenceMatcher(None, clean_text(target).casefold(), clean_text(candidate).casefold()).ratio()
    return (overlap * 0.7) + (seq * 0.3), len(shared)


def _align_english_riddle_to_quote(quote: str, riddle: str) -> str:
    cleaned_quote = clean_text(quote)
    cleaned_riddle = clean_text(riddle)
    if not cleaned_riddle:
        return ""
    if cleaned_riddle in cleaned_quote:
        return cleaned_riddle

    preferred_word_count = len(cleaned_riddle.split()) or None
    seen: set[str] = set()
    best_candidate = ""
    best_score = 0.0
    best_shared = 0
    candidate_pool = list(
        candidate_riddle_spans(
            cleaned_quote,
            "en",
            preferred_word_count=preferred_word_count,
            max_candidates=24,
        )
    )
    quote_tokens = cleaned_quote.split()
    if quote_tokens:
        min_words = max(1, (preferred_word_count or 1) - 2)
        max_words = min(len(quote_tokens), (preferred_word_count or len(quote_tokens)) + 3)
        for window_size in range(min_words, max_words + 1):
            for start_index in range(0, len(quote_tokens) - window_size + 1):
                candidate_pool.append(" ".join(quote_tokens[start_index : start_index + window_size]))

    for candidate in candidate_pool:
        cleaned_candidate = clean_text(candidate)
        if not cleaned_candidate or cleaned_candidate in seen:
            continue
        seen.add(cleaned_candidate)
        score, shared = _english_similarity_score(cleaned_riddle, cleaned_candidate)
        if (score, shared, -len(cleaned_candidate)) > (best_score, best_shared, -len(best_candidate)):
            best_candidate = cleaned_candidate
            best_score = score
            best_shared = shared

    if best_candidate and (
        (best_score >= 0.72 and best_shared >= 2)
        or (best_score >= 0.62 and best_shared >= 4)
    ):
        return best_candidate
    return ""


def _maybe_expand_short_english_riddle(quote: str, riddle: str) -> str:
    cleaned_quote = clean_text(quote)
    cleaned_riddle = clean_text(riddle)
    if len(cleaned_riddle.split()) >= SHORT_RIDDLE_WORD_THRESHOLD:
        return cleaned_riddle
    start = cleaned_quote.find(cleaned_riddle)
    if start < 0:
        return cleaned_riddle
    expanded = clean_text(cleaned_quote[start:])
    if len(expanded.split()) <= 28:
        return expanded
    return cleaned_riddle


def _candidate_specs_from_payload(
    payload: dict,
    *,
    block: RangeQuote,
) -> tuple[list[CandidateSpec], list[str]]:
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("items must be a list")

    available_verses = {int(key) for key in block.raw_quote_source["en"]}
    specs: list[CandidateSpec] = []
    errors: list[str] = []
    seen_keys: set[tuple[int, int, str]] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"item {index}: must be an object")
            continue
        try:
            start = int(item["quote_verse_start"])
            end = int(item["quote_verse_end"])
            if start > end:
                raise ValueError("start is after end")
            if any(verse not in available_verses for verse in range(start, end + 1)):
                raise ValueError("quote verse range is outside the provided verses")
            quote = _quote_text_from_source(block.raw_quote_source["en"], start, end)
            raw_riddle = clean_text(str(item["en_riddle"]))
            if not raw_riddle:
                raise ValueError("en_riddle is empty")
            aligned_riddle = _align_english_riddle_to_quote(quote, raw_riddle)
            if not aligned_riddle:
                raise ValueError("en_riddle is not an exact substring of the quote")
            raw_speaker = item.get("en_speaker")
            raw_listener = item.get("en_listener")
            speaker = clean_text(raw_speaker) if isinstance(raw_speaker, str) else ""
            listener = clean_text(raw_listener) if isinstance(raw_listener, str) else ""
            if not speaker or not listener:
                raise ValueError("speaker or listener is empty")
            riddle = _maybe_expand_short_english_riddle(quote, aligned_riddle)
            if riddle not in quote:
                raise ValueError("expanded en_riddle is not an exact substring of the quote")
            spec = CandidateSpec(
                quote_verse_start=start,
                quote_verse_end=end,
                speaker_mention_verse=_coerce_optional_verse(item.get("speaker_mention_verse"), available_verses),
                listener_mention_verse=_coerce_optional_verse(item.get("listener_mention_verse"), available_verses),
                en_riddle=riddle,
                en_speaker=speaker,
                en_listener=listener,
                reason=clean_text(str(item.get("reason", ""))),
                confidence=_validate_confidence(item.get("confidence")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"item {index}: {exc}")
            continue
        dedupe_key = (spec.quote_verse_start, spec.quote_verse_end, _normalized_riddle_key(spec.en_riddle, "en"))
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        specs.append(spec)
    return specs, errors


def _candidate_hebrew_projection_system() -> str:
    return (
        "You align one English Bible riddle candidate to Hebrew from the same verses. "
        "Return exactly one JSON object with keys keep, he_riddle, he_speaker, he_listener. "
        "keep must be a boolean. "
        "If keep is true, he_riddle must be exactly one string from he_riddle_candidates. "
        "Copy he_riddle character-for-character from he_riddle_candidates. Do not paraphrase it. "
        "Return the Hebrew speaker and listener for the same roles as the English speaker and listener. "
        "he_speaker and he_listener must be Hebrew strings taken from the Hebrew quote or Hebrew supporting context, never English or transliteration. "
        "Use short concrete Hebrew names or Hebrew group labels, not pronouns or reporting clauses. "
        "If the English riddle starts with a one- or two-word speech and then keeps trailing narrative, choose the Hebrew exact substring for that same speech turn and trailing context. "
        "If the Hebrew quote does not contain the same speech turn, set keep to false and return empty strings."
    )


def _candidate_hebrew_projection_retry_system() -> str:
    return (
        _candidate_hebrew_projection_system()
        + " Re-check carefully before returning keep=false. "
        + "If the same speech turn appears anywhere in he_riddle_candidates, set keep=true and choose the closest exact candidate."
    )


def _candidate_hebrew_projection_user(
    *,
    quote_range: RangeQuote,
    raw_quote_source: RawQuoteSource,
    spec: CandidateSpec,
    he_riddle_candidates: list[str],
) -> str:
    hebrew_context = [
        raw_quote_source.he[key]
        for key in sorted(raw_quote_source.he, key=lambda key: int(key))
    ]
    lines = [
        f"ref: {quote_range.book_en} {quote_range.chapter}:{spec.quote_verse_start}-{spec.quote_verse_end}",
        f"english_quote: {quote_range.en_quote}",
        f"english_riddle: {spec.en_riddle}",
        f"english_speaker: {spec.en_speaker}",
        f"english_listener: {spec.en_listener}",
        f"hebrew_quote: {cleanup_hebrew_quote(quote_range.he_quote)}",
        f"hebrew_supporting_context: {json.dumps(hebrew_context, ensure_ascii=False)}",
        f"he_riddle_candidates: {he_riddle_candidates}",
    ]
    if spec.speaker_mention_verse is not None:
        lines.append(f"speaker_mention_verse: {spec.speaker_mention_verse}")
    if spec.listener_mention_verse is not None:
        lines.append(f"listener_mention_verse: {spec.listener_mention_verse}")
    lines.append("Return the matching Hebrew riddle, speaker, and listener.")
    lines.append("he_speaker and he_listener must be Hebrew, not English.")
    return "\n".join(lines)


def _candidate_hebrew_projection_retry_user(*, base_prompt: str) -> str:
    return (
        f"{base_prompt}\n"
        "Previous answer kept false or failed to choose a valid exact Hebrew riddle.\n"
        "Re-check the Hebrew quote and he_riddle_candidates.\n"
        "If the same speech turn is present, choose the closest exact he_riddle candidate and keep=true."
    )


def _hebrew_projection_from_payload(
    payload: dict,
    *,
    he_allowed_map: dict[str, str],
    hebrew_restore_map: dict[str, str],
    hebrew_quote: str,
) -> HebrewProjection:
    keep = bool(payload.get("keep"))
    raw_he_riddle = str(payload.get("he_riddle", "")) if keep else ""
    he_riddle = _normalize_candidate_choice(raw_he_riddle, he_allowed_map, lang="he") if keep else ""
    if keep and not he_riddle and raw_he_riddle:
        projected = _project_hebrew_substring_to_original(hebrew_quote, raw_he_riddle)
        if projected is not None:
            he_riddle = projected
    he_speaker = restore_hebrew_surface_from_map(str(payload.get("he_speaker", "")), hebrew_restore_map) if keep else ""
    he_listener = restore_hebrew_surface_from_map(str(payload.get("he_listener", "")), hebrew_restore_map) if keep else ""
    return HebrewProjection(
        keep=keep,
        he_riddle=he_riddle,
        he_speaker=he_speaker,
        he_listener=he_listener,
    )


def _window_has_dialogue_cues(window: RangeQuote) -> bool:
    en_words = {normalize_word(word, "en") for word in clean_text(window.en_quote).split()}
    he_words = {normalize_word(word, "he") for word in cleanup_hebrew_quote(window.he_quote).split()}
    if en_words & EN_CANDIDATE_REPORTING_WORDS:
        return True
    if he_words & HE_CANDIDATE_REPORTING_WORDS:
        return True
    if "?" in window.en_quote:
        return True
    en_pronouns = sum(1 for word in en_words if word in EN_DIALOG_PRONOUNS)
    he_pronouns = sum(1 for word in he_words if word in HE_DIALOG_PRONOUNS)
    return en_pronouns >= 2 or he_pronouns >= 2


def _window_has_strong_dialogue_cues(window: RangeQuote) -> bool:
    en_words = {normalize_word(word, "en") for word in clean_text(window.en_quote).split()}
    he_words = {normalize_word(word, "he") for word in cleanup_hebrew_quote(window.he_quote).split()}
    return bool(en_words & EN_CANDIDATE_REPORTING_WORDS or he_words & HE_CANDIDATE_REPORTING_WORDS or "?" in window.en_quote)


def _window_riddle_candidates(window: RangeQuote, lang: str) -> list[str]:
    quote = window.he_quote if lang == "he" else window.en_quote
    candidates = candidate_riddle_spans(quote, lang, max_candidates=10)
    return candidates[:10]


def _candidate_issue(window: RangeQuote, stage: str, reason: str, detail: str) -> DropRecord:
    return DropRecord(
        candidate_id=_candidate_id(window.book_en, window.chapter, window.start, window.end),
        book_code=window.book_code,
        chapter=window.chapter,
        start=window.start,
        end=window.end,
        stage=stage,
        reason=reason,
        detail=detail,
    )


def _candidate_issue_for_spec(
    *,
    book_code: str,
    book: str,
    chapter: int,
    start: int,
    end: int,
    stage: str,
    reason: str,
    detail: str,
) -> DropRecord:
    return DropRecord(
        candidate_id=_candidate_id(book, chapter, start, end),
        book_code=book_code,
        chapter=chapter,
        start=start,
        end=end,
        stage=stage,
        reason=reason,
        detail=detail,
    )


def _assign_unique_candidate_ids(items: list[CandidateItem]) -> list[CandidateItem]:
    if not items:
        return []

    base_counts: dict[str, int] = {}
    for item in items:
        base_counts[item.id] = base_counts.get(item.id, 0) + 1

    seen_per_base: dict[str, int] = {}
    out: list[CandidateItem] = []
    for item in items:
        if base_counts[item.id] == 1:
            out.append(item)
            continue
        ordinal = seen_per_base.get(item.id, 0) + 1
        seen_per_base[item.id] = ordinal
        out.append(replace(item, id=f"{item.id}-{ordinal}"))
    return out


def _build_candidate_item(
    *,
    quote_range: RangeQuote,
    raw_quote_source: RawQuoteSource,
    spec: CandidateSpec,
    projection: HebrewProjection,
) -> CandidateItem:
    return CandidateItem(
        id=_candidate_id(quote_range.book_en, quote_range.chapter, spec.quote_verse_start, spec.quote_verse_end),
        source=CandidateSource(
            book_code=quote_range.book_code,
            book=quote_range.book_en,
            book_he=quote_range.book_he,
            chapter=quote_range.chapter,
            quote_verse_start=spec.quote_verse_start,
            quote_verse_end=spec.quote_verse_end,
            speaker_mention_verse=spec.speaker_mention_verse,
            listener_mention_verse=spec.listener_mention_verse,
        ),
        en=CandidateLangText(
            quote=quote_range.en_quote,
            riddle=spec.en_riddle,
            speaker=spec.en_speaker,
            listener=spec.en_listener,
            book=quote_range.book_en,
        ),
        he=CandidateLangText(
            quote=quote_range.he_quote,
            riddle=projection.he_riddle,
            speaker=projection.he_speaker,
            listener=projection.he_listener,
            book=quote_range.book_he,
        ),
        raw_quote_source=raw_quote_source,
        meta=CandidateMeta(reason=spec.reason, confidence=spec.confidence),
        ref=RefRange(chapter=quote_range.chapter, start=spec.quote_verse_start, end=spec.quote_verse_end),
    )


def _validate_candidate_item(item: CandidateItem) -> None:
    if not item.en.riddle or item.en.riddle not in item.en.quote:
        raise ValueError("english riddle is not an exact substring of the quote")
    if not item.he.riddle or cleanup_hebrew_quote(item.he.riddle) not in cleanup_hebrew_quote(item.he.quote):
        raise ValueError("hebrew riddle is not an exact substring of the quote")
    if not clean_text(item.en.speaker) or not clean_text(item.en.listener):
        raise ValueError("english speaker/listener is empty")
    if not cleanup_hebrew_quote(item.he.speaker) or not cleanup_hebrew_quote(item.he.listener):
        raise ValueError("hebrew speaker/listener is empty")
    if item.source.chapter != item.ref.chapter:
        raise ValueError("source chapter does not match ref chapter")


def _chapter_candidate_windows(tandem: TandemBible, *, book_code: str, chapter: int) -> list[RangeQuote]:
    single_verse_windows = list(tandem.iter_windows(book_code, chapter, max_window=1, min_window=1))
    if not single_verse_windows:
        return []

    last_verse = max(window.end for window in single_verse_windows)
    strong_anchor_verses = {
        window.start
        for window in single_verse_windows
        if _window_has_strong_dialogue_cues(window)
    }
    ranges: set[tuple[int, int]] = set()
    for window in single_verse_windows:
        if window.start not in strong_anchor_verses:
            continue
        verse = window.start
        ranges.add((verse, verse))
        if verse < last_verse and verse + 1 not in strong_anchor_verses:
            ranges.add((verse, verse + 1))

    out: list[RangeQuote] = []
    for start, end in sorted(ranges):
        collected = tandem.collect_range(book_code, chapter, start, end)
        if collected is not None:
            out.append(collected)
    return out


def _chapter_dialogue_blocks(tandem: TandemBible, *, book_code: str, chapter: int) -> list[RangeQuote]:
    single_verse_windows = list(tandem.iter_windows(book_code, chapter, max_window=1, min_window=1))
    if not single_verse_windows:
        return []

    verse_numbers = [window.start for window in single_verse_windows]
    anchor_indexes = [
        index
        for index, window in enumerate(single_verse_windows)
        if _window_has_strong_dialogue_cues(window)
    ]
    if not anchor_indexes:
        return []

    index_ranges: list[tuple[int, int]] = []
    for anchor_index in anchor_indexes:
        start_index = max(0, anchor_index - BLOCK_CONTEXT_BEFORE)
        end_index = min(len(verse_numbers) - 1, anchor_index + BLOCK_CONTEXT_AFTER)
        index_ranges.append((start_index, end_index))

    merged_ranges: list[list[int]] = []
    for start_index, end_index in sorted(index_ranges):
        if not merged_ranges or start_index > merged_ranges[-1][1]:
            merged_ranges.append([start_index, end_index])
            continue
        merged_ranges[-1][1] = max(merged_ranges[-1][1], end_index)

    split_ranges: list[tuple[int, int]] = []
    step = max(1, BLOCK_MAX_VERSES - BLOCK_OVERLAP_VERSES)
    for start_index, end_index in merged_ranges:
        current_start = start_index
        while current_start <= end_index:
            current_end = min(end_index, current_start + BLOCK_MAX_VERSES - 1)
            split_ranges.append((current_start, current_end))
            if current_end >= end_index:
                break
            current_start += step

    out: list[RangeQuote] = []
    for start_index, end_index in split_ranges:
        collected = tandem.collect_range(
            book_code,
            chapter,
            verse_numbers[start_index],
            verse_numbers[end_index],
        )
        if collected is not None:
            out.append(collected)
    return out


def _chapter_extraction_blocks(
    tandem: TandemBible,
    *,
    book_code: str,
    chapter: int,
    strategy: str,
) -> list[RangeQuote]:
    if strategy == FULL_CHAPTER_STRATEGY:
        windows = list(tandem.iter_windows(book_code, chapter, max_window=1, min_window=1))
        if not windows:
            return []
        return [tandem.collect_range(book_code, chapter, windows[0].start, windows[-1].end)]
    if strategy == DIALOGUE_BLOCKS_STRATEGY:
        return _chapter_dialogue_blocks(tandem, book_code=book_code, chapter=chapter)
    raise ValueError(f"Unsupported candidate extraction strategy: {strategy}")


def _candidate_spec_prompt_payload(block: RangeQuote) -> list[dict[str, object]]:
    return [
        {"verse": int(verse), "text": block.raw_quote_source["en"][verse]}
        for verse in sorted(block.raw_quote_source["en"], key=lambda key: int(key))
    ]


def _support_raw_quote_source(
    tandem: TandemBible,
    *,
    book_code: str,
    chapter: int,
    spec: CandidateSpec,
) -> RawQuoteSource:
    support_verses = set(range(spec.quote_verse_start, spec.quote_verse_end + 1))
    if spec.speaker_mention_verse is not None:
        support_verses.add(spec.speaker_mention_verse)
    if spec.listener_mention_verse is not None:
        support_verses.add(spec.listener_mention_verse)

    raw_en: dict[str, str] = {}
    raw_he: dict[str, str] = {}
    for verse in sorted(support_verses):
        range_quote = tandem.collect_range(book_code, chapter, verse, verse)
        if range_quote is None or range_quote.missing:
            raise ValueError(f"missing source verse {verse}")
        raw_en[str(verse)] = range_quote.raw_quote_source["en"][str(verse)]
        raw_he[str(verse)] = range_quote.raw_quote_source["he"][str(verse)]
    return RawQuoteSource(en=raw_en, he=raw_he)


def _project_hebrew_candidate(
    *,
    llm: JsonChatModel,
    quote_range: RangeQuote,
    raw_quote_source: RawQuoteSource,
    spec: CandidateSpec,
) -> HebrewProjection:
    preferred_word_count = len(clean_text(spec.en_riddle).split()) or None
    he_candidates = candidate_riddle_spans(
        quote_range.he_quote,
        "he",
        preferred_word_count=preferred_word_count,
        max_candidates=16,
    )
    he_display_candidates, he_display_map = _display_hebrew_candidates(he_candidates)
    if not he_display_candidates:
        raise ValueError("No Hebrew riddle candidates remained")
    hebrew_restore_map = hebrew_surface_map([quote_range.he_quote, *raw_quote_source.he.values()])
    base_user_prompt = _candidate_hebrew_projection_user(
        quote_range=quote_range,
        raw_quote_source=raw_quote_source,
        spec=spec,
        he_riddle_candidates=he_display_candidates,
    )
    payload = llm.chat_json(
        prompt_name="candidate-hebrew-projection",
        system_prompt=_candidate_hebrew_projection_system(),
        user_prompt=base_user_prompt,
        required_keys=("keep", "he_riddle", "he_speaker", "he_listener"),
    )
    projection = _hebrew_projection_from_payload(
        payload,
        he_allowed_map=he_display_map,
        hebrew_restore_map=hebrew_restore_map,
        hebrew_quote=quote_range.he_quote,
    )
    if not projection.keep or not projection.he_riddle:
        retry_payload = llm.chat_json(
            prompt_name="candidate-hebrew-projection-retry",
            system_prompt=_candidate_hebrew_projection_retry_system(),
            user_prompt=_candidate_hebrew_projection_retry_user(base_prompt=base_user_prompt),
            required_keys=("keep", "he_riddle", "he_speaker", "he_listener"),
        )
        projection = _hebrew_projection_from_payload(
            retry_payload,
            he_allowed_map=he_display_map,
            hebrew_restore_map=hebrew_restore_map,
            hebrew_quote=quote_range.he_quote,
        )
    return projection


def _build_chapter_candidates(
    tandem: TandemBible,
    *,
    llm: JsonChatModel,
    book_code: str,
    chapter: int,
    strategy: str = PRODUCTION_CANDIDATE_EXTRACTION_STRATEGY,
) -> tuple[CandidateChapterShard, list[DropRecord]]:
    window_issues: list[DropRecord] = []
    kept_items: list[CandidateItem] = []
    seen_riddle_keys: set[tuple[str, str]] = set()
    prefiltered = 0
    llm_seen = 0
    projection_seen = 0

    blocks = _chapter_extraction_blocks(tandem, book_code=book_code, chapter=chapter, strategy=strategy)
    extracted_specs: list[CandidateSpec] = []
    seen_spec_keys: set[tuple[int, int, str]] = set()
    for block in blocks:
        llm_seen += 1
        try:
            payload = llm.chat_json(
                prompt_name="candidate-chapter-extract",
                system_prompt=_candidate_prompt_system(),
                user_prompt=_candidate_prompt_user(
                    book=block.book_en,
                    chapter=block.chapter,
                    verses=_candidate_spec_prompt_payload(block),
                ),
                required_keys=("items",),
            )
            specs, errors = _candidate_specs_from_payload(payload, block=block)
        except Exception as exc:
            window_issues.append(_candidate_issue(block, "candidate", "llm_error", str(exc)))
            continue
        if errors:
            detail = "; ".join(errors[:3])
            window_issues.append(_candidate_issue(block, "candidate", "bad_payload_items", detail))
        for spec in specs:
            spec_key = (
                spec.quote_verse_start,
                spec.quote_verse_end,
                _normalized_riddle_key(spec.en_riddle, "en"),
            )
            if spec_key in seen_spec_keys:
                continue
            seen_spec_keys.add(spec_key)
            extracted_specs.append(spec)

    for spec in extracted_specs:
        issue_kwargs = {
            "book_code": book_code,
            "book": bible_sources.BOOK_CODE_TO_EN[book_code],
            "chapter": chapter,
            "start": spec.quote_verse_start,
            "end": spec.quote_verse_end,
        }
        try:
            quote_range = tandem.collect_range(book_code, chapter, spec.quote_verse_start, spec.quote_verse_end)
            if quote_range is None or quote_range.missing:
                raise ValueError("quote source verses are missing")
            raw_quote_source = _support_raw_quote_source(
                tandem,
                book_code=book_code,
                chapter=chapter,
                spec=spec,
            )
            projection_seen += 1
            projection = _project_hebrew_candidate(
                llm=llm,
                quote_range=quote_range,
                raw_quote_source=raw_quote_source,
                spec=spec,
            )
            if not projection.keep or not projection.he_riddle:
                raise ValueError("Hebrew projection did not return a valid riddle")
            item = _build_candidate_item(
                quote_range=quote_range,
                raw_quote_source=raw_quote_source,
                spec=spec,
                projection=projection,
            )
            _validate_candidate_item(item)
        except Exception as exc:
            window_issues.append(
                _candidate_issue_for_spec(
                    **issue_kwargs,
                    stage="candidate",
                    reason="invalid_candidate",
                    detail=str(exc),
                )
            )
            continue

        riddle_key = (
            _normalized_riddle_key(item.en.riddle, "en"),
            _normalized_riddle_key(item.he.riddle, "he"),
        )
        if riddle_key in seen_riddle_keys:
            window_issues.append(
                _candidate_issue_for_spec(
                    **issue_kwargs,
                    stage="dedupe",
                    reason="duplicate_candidate_riddle",
                    detail="A previous candidate in this chapter already used the same riddle turn",
                )
            )
            continue
        seen_riddle_keys.add(riddle_key)
        kept_items.append(item)

    first_window = blocks[0] if blocks else tandem.collect_range(book_code, chapter, 1, 1)
    shard = CandidateChapterShard(
        book_code=book_code,
        book=bible_sources.BOOK_CODE_TO_EN[book_code],
        book_he=bible_sources.BOOK_CODE_TO_HE[book_code],
        chapter=chapter,
        mode="llm",
        items=_assign_unique_candidate_ids(sorted(kept_items, key=lambda item: (item.ref.start, item.ref.end, item.id))),
        stats={
            "window_count": len(blocks),
            "prefiltered_count": prefiltered,
            "llm_window_count": llm_seen,
            "projection_llm_count": projection_seen,
            "llm_call_count": llm_seen + projection_seen,
            "spec_count": len(extracted_specs),
            "kept_count": len(kept_items),
            "issue_count": len(window_issues),
        },
    )
    if first_window is None:
        shard = CandidateChapterShard(
            book_code=book_code,
            book=bible_sources.BOOK_CODE_TO_EN[book_code],
            book_he=bible_sources.BOOK_CODE_TO_HE[book_code],
            chapter=chapter,
            mode="llm",
            items=[],
            stats={
                "window_count": 0,
                "prefiltered_count": 0,
                "llm_window_count": 0,
                "projection_llm_count": 0,
                "llm_call_count": 0,
                "spec_count": 0,
                "kept_count": 0,
                "issue_count": len(window_issues),
            },
        )
    return shard, window_issues


def _append_jsonl(path: Path, payloads: list[dict]) -> None:
    if not payloads:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for payload in payloads:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_path, path)


def _stable_candidate_eval_sample(shards: list[CandidateChapterShard], sample_size: int) -> list[CandidateItem]:
    per_book: dict[str, list[CandidateItem]] = {}
    for shard in sorted(shards, key=lambda value: _chapter_sort_key(value.book_code, value.chapter)):
        per_book.setdefault(shard.book_code, []).extend(sorted(shard.items, key=lambda item: (item.ref.start, item.ref.end, item.id)))
    selected: list[CandidateItem] = []
    ordered_books = sorted(per_book, key=lambda code: bible_sources.BOOK_ORDER.get(code, 999))
    cursors = {book_code: 0 for book_code in ordered_books}
    while len(selected) < sample_size and any(cursors[book_code] < len(per_book[book_code]) for book_code in ordered_books):
        for book_code in ordered_books:
            cursor = cursors[book_code]
            if cursor >= len(per_book[book_code]):
                continue
            selected.append(per_book[book_code][cursor])
            cursors[book_code] += 1
            if len(selected) >= sample_size:
                break
    return selected


def run_build_candidates(
    *,
    candidates_path: Path,
    shard_dir: Path,
    issues_log: Path | None,
    llm: JsonChatModel,
    english_xml: Path,
    hebrew_zip: Path,
    book_filter: str | None = None,
    chapter_filter: int | None = None,
    allowed_book_codes: tuple[str, ...] | None = None,
    limit: int | None = None,
    resume: bool = True,
) -> tuple[list[CandidateChapterShard], list[DropRecord]]:
    canonical_book_filter = _canonical_book_filter(book_filter)
    tandem = TandemBible.load(english_xml=english_xml, hebrew_zip=hebrew_zip)
    target_chapters = [
        (book_code, chapter)
        for book_code, chapter in tandem.iter_chapters(book_filter=canonical_book_filter or "")
        if (not canonical_book_filter or book_code == canonical_book_filter)
        and (canonical_book_filter or allowed_book_codes is None or book_code in allowed_book_codes)
        and (chapter_filter is None or chapter == chapter_filter)
    ]
    resume_point = _find_resume_point_for_chapters(
        target_chapters,
        shard_dir=shard_dir,
        book_filter=canonical_book_filter,
        chapter_filter=chapter_filter,
    ) if resume else None

    shard_dir.mkdir(parents=True, exist_ok=True)
    if issues_log is not None:
        issues_log.parent.mkdir(parents=True, exist_ok=True)

    written_shards: list[CandidateChapterShard] = []
    all_issues: list[DropRecord] = []
    processed = 0
    existing_shards = {
        (shard.book_code, shard.chapter): shard
        for shard in _read_all_candidate_shards(shard_dir)
    }
    if resume and resume_point is None:
        _rebuild_candidates_jsonl(candidates_path, existing_shards.values())
        return written_shards, all_issues
    for book_code, chapter in tqdm(target_chapters, desc="build-candidates"):
        if resume_point is not None and _chapter_sort_key(book_code, chapter) < _chapter_sort_key(*resume_point):
            continue
        if limit is not None and processed >= limit:
            break
        processed += 1
        shard, issues = _build_chapter_candidates(
            tandem,
            llm=llm,
            book_code=book_code,
            chapter=chapter,
        )
        shard_path = _chapter_shard_path(shard_dir, book=shard.book, chapter=shard.chapter)
        _write_json_atomic(shard_path, shard.to_dict())
        if issues_log is not None and issues:
            _append_jsonl(issues_log, [issue.to_dict() for issue in issues])
        existing_shards[(book_code, chapter)] = shard
        _rebuild_candidates_jsonl(candidates_path, existing_shards.values())
        written_shards.append(shard)
        all_issues.extend(issues)
    if not written_shards:
        _rebuild_candidates_jsonl(candidates_path, existing_shards.values())
    return written_shards, all_issues


def build_candidates_eval_pack(
    *,
    candidates_path: Path,
    shard_dir: Path,
    out_dir: Path,
    sample_size: int,
    seed: int | None,
    book_filter: str | None = None,
    chapter_filter: int | None = None,
    allowed_book_codes: tuple[str, ...] | None = None,
) -> dict:
    canonical_book_filter = _canonical_book_filter(book_filter)
    shards = [
        shard
        for shard in _read_all_candidate_shards(shard_dir)
        if (not canonical_book_filter or shard.book_code == canonical_book_filter)
        and (canonical_book_filter or allowed_book_codes is None or shard.book_code in allowed_book_codes)
        and (chapter_filter is None or shard.chapter == chapter_filter)
    ]
    sample_items = _stable_candidate_eval_sample(shards, sample_size)
    out_dir.mkdir(parents=True, exist_ok=True)
    eval_payload = {
        "seed": seed,
        "sample_size": len(sample_items),
        "items": [item.to_dict() for item in sample_items],
    }
    _write_json_atomic(out_dir / "eval_items.json", eval_payload)
    lines = ["# Candidate Eval", ""]
    if seed is not None:
        lines.extend([f"- Seed: `{seed}`", ""])
    lines.extend([f"- Items: `{len(sample_items)}`", ""])
    for item in sample_items:
        lines.extend(
            [
                f"## {item.id}",
                f"- Ref: `{item.source.book} {item.source.chapter}:{item.ref.start}-{item.ref.end}`",
                f"- EN quote: {item.en.quote}",
                f"- EN riddle: {item.en.riddle}",
                f"- EN speaker/listener: `{item.en.speaker}` / `{item.en.listener}`",
                f"- HE riddle: {item.he.riddle}",
                f"- HE speaker/listener: `{item.he.speaker}` / `{item.he.listener}`",
                f"- Reason: {item.meta.reason}",
                "",
            ]
        )
    (out_dir / "review.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return eval_payload


def _build_llm_client(model: str, seed: int | None):
    from data_proc.llm import OllamaJsonClient

    options = {"seed": seed} if seed is not None else None
    return OllamaJsonClient(model=model, fallback_model=None, request_options=options)


def _default_candidate_book_scope(*, book_filter: str | None, full_canon: bool) -> tuple[str, ...] | None:
    if full_canon or book_filter:
        return None
    return MINIMAL_CANDIDATE_BOOK_CODES


@click.command("build-candidates")
@click.option("--candidates-out", "candidates_path", type=click.Path(path_type=Path, dir_okay=False), default=Path("data/processed/candidates.jsonl"), show_default=True)
@click.option("--shard-dir", type=click.Path(path_type=Path, file_okay=False), default=Path("data/processed/candidate_chapters"), show_default=True)
@click.option("--issues-log", type=click.Path(path_type=Path, dir_okay=False), default=Path("data/processed/candidates_issues.jsonl"), show_default=True)
@click.option("--model", default="gemma4:26b", show_default=True)
@click.option("--seed", type=int, default=None)
@click.option("--english-xml", type=click.Path(path_type=Path, exists=True, dir_okay=False), default=DEFAULT_ENGLISH_XML, show_default=True)
@click.option("--hebrew-zip", type=click.Path(path_type=Path, exists=True, dir_okay=False), default=DEFAULT_HEBREW_ZIP, show_default=True)
@click.option("--book", "book_filter", default=None)
@click.option("--chapter", "chapter_filter", type=int, default=None)
@click.option("--full-canon", is_flag=True, default=False)
@click.option("--limit", type=int, default=None)
@click.option("--resume/--no-resume", default=True, show_default=True)
@click.option("--quiet-llm", is_flag=True, default=False)
def build_candidates_command(
    candidates_path: Path,
    shard_dir: Path,
    issues_log: Path | None,
    model: str,
    seed: int | None,
    english_xml: Path,
    hebrew_zip: Path,
    book_filter: str | None,
    chapter_filter: int | None,
    full_canon: bool,
    limit: int | None,
    resume: bool,
    quiet_llm: bool,
) -> None:
    logging.basicConfig(level=logging.WARNING if quiet_llm else logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    shards, issues = run_build_candidates(
        candidates_path=candidates_path,
        shard_dir=shard_dir,
        issues_log=issues_log,
        llm=_build_llm_client(model, seed),
        english_xml=english_xml,
        hebrew_zip=hebrew_zip,
        book_filter=book_filter,
        chapter_filter=chapter_filter,
        allowed_book_codes=_default_candidate_book_scope(book_filter=book_filter, full_canon=full_canon),
        limit=limit,
        resume=resume,
    )
    click.echo(f"Wrote {sum(len(shard.items) for shard in shards)} candidates across {len(shards)} chapter shards; logged {len(issues)} issues.")


@click.command("build-candidates-eval")
@click.option("--candidates-out", "candidates_path", type=click.Path(path_type=Path, exists=False, dir_okay=False), default=Path("data/processed/candidates.jsonl"), show_default=True)
@click.option("--shard-dir", type=click.Path(path_type=Path, exists=True, file_okay=False), default=Path("data/processed/candidate_chapters"), show_default=True)
@click.option("--out-dir", type=click.Path(path_type=Path, file_okay=False), default=Path("data/processed/candidates_eval"), show_default=True)
@click.option("--sample-size", type=int, default=24, show_default=True)
@click.option("--seed", type=int, default=32988, show_default=True)
@click.option("--book", "book_filter", default=None)
@click.option("--chapter", "chapter_filter", type=int, default=None)
@click.option("--full-canon", is_flag=True, default=False)
def build_candidates_eval_command(
    candidates_path: Path,
    shard_dir: Path,
    out_dir: Path,
    sample_size: int,
    seed: int,
    book_filter: str | None,
    chapter_filter: int | None,
    full_canon: bool,
) -> None:
    payload = build_candidates_eval_pack(
        candidates_path=candidates_path,
        shard_dir=shard_dir,
        out_dir=out_dir,
        sample_size=sample_size,
        seed=seed,
        book_filter=book_filter,
        chapter_filter=chapter_filter,
        allowed_book_codes=_default_candidate_book_scope(book_filter=book_filter, full_canon=full_canon),
    )
    click.echo(f"Wrote candidates eval pack with {payload['sample_size']} items to {out_dir}.")
