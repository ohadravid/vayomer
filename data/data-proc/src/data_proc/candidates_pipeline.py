from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
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
class CandidateDecision:
    keep: bool
    en_riddle: str
    he_riddle: str
    en_speaker: str
    en_listener: str
    he_speaker: str
    he_listener: str
    reason: str
    confidence: float


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
        "You evaluate one bilingual Bible quote window as a possible riddle candidate. "
        "Be high recall: keep plausible direct speech, memorable questions, commands, warnings, blessings, and vivid declarations even if the listener is only implicit. "
        "Drop only when the window is mostly narration, structurally broken, or lacks a memorable speech core. "
        "Single-verse direct questions or direct speech should usually be kept. "
        "Return JSON only with keys keep, en_riddle, he_riddle, en_speaker, en_listener, he_speaker, he_listener, reason, confidence. "
        "keep must be a boolean. confidence must be a number between 0 and 1. "
        "Return one compact single-line JSON object only. "
        "Use only exact strings from en_riddle_candidates and he_riddle_candidates when keep is true. "
        "Prefer concise core utterances and avoid reporting clauses when a cleaner candidate exists. Prefer the smallest window that already contains the memorable speech. "
        "Use short concrete names or group labels for speakers and listeners when possible. "
        "Keep reason very short, at most six words. "
        "If keep is false, return empty strings for all riddle and role fields."
    )


def _display_hebrew_candidates(candidates: list[str]) -> tuple[list[str], dict[str, str]]:
    display_map: dict[str, str] = {}
    display_candidates: list[str] = []
    for candidate in candidates:
        display = strip_hebrew_marks(cleanup_hebrew_quote(candidate))
        if not display or display in display_map:
            continue
        display_map[display] = candidate
        display_candidates.append(display)
    return display_candidates, display_map


def _candidate_prompt_user(window: RangeQuote, *, en_riddle_candidates: list[str], he_riddle_candidates: list[str]) -> str:
    return (
        f"ref: {window.book_en} {window.chapter}:{window.start}-{window.end}\n"
        f"english_quote: {window.en_quote}\n"
        f"hebrew_quote: {strip_hebrew_marks(window.he_quote)}\n"
        f"en_riddle_candidates: {en_riddle_candidates}\n"
        f"he_riddle_candidates: {he_riddle_candidates}\n"
        "Return the best candidate or keep=false."
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


def _build_candidate_item(window: RangeQuote, decision: CandidateDecision) -> CandidateItem:
    return CandidateItem(
        id=_candidate_id(window.book_en, window.chapter, window.start, window.end),
        source=CandidateSource(
            book_code=window.book_code,
            book=window.book_en,
            book_he=window.book_he,
            chapter=window.chapter,
            quote_verse_start=window.start,
            quote_verse_end=window.end,
        ),
        en=CandidateLangText(
            quote=window.en_quote,
            riddle=decision.en_riddle,
            speaker=decision.en_speaker,
            listener=decision.en_listener,
            book=window.book_en,
        ),
        he=CandidateLangText(
            quote=window.he_quote,
            riddle=decision.he_riddle,
            speaker=decision.he_speaker,
            listener=decision.he_listener,
            book=window.book_he,
        ),
        raw_quote_source=RawQuoteSource(
            en=dict(window.raw_quote_source["en"]),
            he=dict(window.raw_quote_source["he"]),
        ),
        meta=CandidateMeta(reason=decision.reason, confidence=decision.confidence),
        ref=RefRange(chapter=window.chapter, start=window.start, end=window.end),
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


def _decision_from_payload(
    payload: dict,
    *,
    window: RangeQuote,
    en_allowed: list[str],
    he_allowed_map: dict[str, str],
    hebrew_restore_map: dict[str, str],
) -> CandidateDecision:
    keep = bool(payload.get("keep"))
    en_allowed_map = {clean_text(candidate): candidate for candidate in en_allowed}
    en_riddle = _normalize_candidate_choice(payload.get("en_riddle"), en_allowed_map, lang="en") if keep else ""
    he_riddle = _normalize_candidate_choice(payload.get("he_riddle"), he_allowed_map, lang="he") if keep else ""

    en_speaker = clean_text(str(payload.get("en_speaker", ""))) if keep else ""
    en_listener = clean_text(str(payload.get("en_listener", ""))) if keep else ""
    he_speaker = restore_hebrew_surface_from_map(str(payload.get("he_speaker", "")), hebrew_restore_map) if keep else ""
    he_listener = restore_hebrew_surface_from_map(str(payload.get("he_listener", "")), hebrew_restore_map) if keep else ""
    if he_riddle:
        he_riddle = restore_hebrew_surface_from_map(he_riddle, hebrew_restore_map)

    return CandidateDecision(
        keep=keep,
        en_riddle=en_riddle,
        he_riddle=he_riddle,
        en_speaker=en_speaker,
        en_listener=en_listener,
        he_speaker=he_speaker,
        he_listener=he_listener,
        reason=clean_text(str(payload.get("reason", ""))),
        confidence=_validate_confidence(payload.get("confidence")),
    )


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


def _build_chapter_candidates(
    tandem: TandemBible,
    *,
    llm: JsonChatModel,
    book_code: str,
    chapter: int,
) -> tuple[CandidateChapterShard, list[DropRecord]]:
    window_issues: list[DropRecord] = []
    kept_items: list[CandidateItem] = []
    seen_riddle_keys: set[tuple[str, str]] = set()
    prefiltered = 0
    llm_seen = 0

    prepared_windows: list[tuple[RangeQuote, list[str], list[str], dict[str, str], dict[str, str]]] = []
    windows = _chapter_candidate_windows(tandem, book_code=book_code, chapter=chapter)
    for window in windows:
        if not _window_has_dialogue_cues(window):
            prefiltered += 1
            continue

        en_candidates = _window_riddle_candidates(window, "en")
        he_candidates = _window_riddle_candidates(window, "he")
        he_display_candidates, he_display_map = _display_hebrew_candidates(he_candidates)
        if not en_candidates or not he_display_candidates:
            window_issues.append(_candidate_issue(window, "deterministic", "no_riddle_candidates", "No exact riddle substrings survived deterministic candidate generation"))
            continue
        hebrew_restore_map = hebrew_surface_map([window.he_quote, *window.raw_quote_source["he"].values()])
        prepared_windows.append((window, en_candidates, he_display_candidates, he_display_map, hebrew_restore_map))

    def handle_decision(window: RangeQuote, decision: CandidateDecision) -> None:
        if not decision.keep:
            window_issues.append(_candidate_issue(window, "candidate", "llm_drop", decision.reason or "LLM chose keep=false"))
            return
        if not decision.en_riddle or not decision.he_riddle:
            window_issues.append(_candidate_issue(window, "candidate", "bad_riddle_choice", "LLM did not choose valid exact riddle candidates"))
            return

        item = _build_candidate_item(window, decision)
        try:
            _validate_candidate_item(item)
        except ValueError as exc:
            window_issues.append(_candidate_issue(window, "candidate", "invalid_candidate", str(exc)))
            return

        riddle_key = (
            _normalized_riddle_key(item.en.riddle, "en"),
            _normalized_riddle_key(item.he.riddle, "he"),
        )
        if riddle_key in seen_riddle_keys:
            window_issues.append(_candidate_issue(window, "dedupe", "duplicate_candidate_riddle", "A previous candidate in this chapter already used the same riddle turn"))
            return
        seen_riddle_keys.add(riddle_key)
        kept_items.append(item)

    for window, en_candidates, he_display_candidates, he_display_map, hebrew_restore_map in prepared_windows:
        llm_seen += 1
        try:
            payload = llm.chat_json(
                prompt_name="candidate-window",
                system_prompt=_candidate_prompt_system(),
                user_prompt=_candidate_prompt_user(
                    window,
                    en_riddle_candidates=en_candidates,
                    he_riddle_candidates=he_display_candidates,
                ),
                required_keys=(
                    "keep",
                    "en_riddle",
                    "he_riddle",
                    "en_speaker",
                    "en_listener",
                    "he_speaker",
                    "he_listener",
                    "reason",
                    "confidence",
                ),
            )
        except Exception as exc:
            window_issues.append(_candidate_issue(window, "candidate", "llm_error", str(exc)))
            continue
        try:
            decision = _decision_from_payload(
                payload,
                window=window,
                en_allowed=en_candidates,
                he_allowed_map=he_display_map,
                hebrew_restore_map=hebrew_restore_map,
            )
        except Exception as exc:
            window_issues.append(_candidate_issue(window, "candidate", "bad_payload", str(exc)))
            continue
        handle_decision(window, decision)

    first_window = windows[0] if windows else tandem.collect_range(book_code, chapter, 1, 1)
    shard = CandidateChapterShard(
        book_code=book_code,
        book=bible_sources.BOOK_CODE_TO_EN[book_code],
        book_he=bible_sources.BOOK_CODE_TO_HE[book_code],
        chapter=chapter,
        mode="llm",
        items=sorted(kept_items, key=lambda item: (item.ref.start, item.ref.end, item.id)),
        stats={
            "window_count": len(windows),
            "prefiltered_count": prefiltered,
            "llm_window_count": llm_seen,
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
    limit: int | None = None,
    resume: bool = True,
) -> tuple[list[CandidateChapterShard], list[DropRecord]]:
    canonical_book_filter = _canonical_book_filter(book_filter)
    tandem = TandemBible.load(english_xml=english_xml, hebrew_zip=hebrew_zip)
    target_chapters = [
        (book_code, chapter)
        for book_code, chapter in tandem.iter_chapters(book_filter=canonical_book_filter or "")
        if (not canonical_book_filter or book_code == canonical_book_filter)
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
) -> dict:
    canonical_book_filter = _canonical_book_filter(book_filter)
    shards = [
        shard
        for shard in _read_all_candidate_shards(shard_dir)
        if (not canonical_book_filter or shard.book_code == canonical_book_filter)
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
def build_candidates_eval_command(
    candidates_path: Path,
    shard_dir: Path,
    out_dir: Path,
    sample_size: int,
    seed: int,
    book_filter: str | None,
    chapter_filter: int | None,
) -> None:
    payload = build_candidates_eval_pack(
        candidates_path=candidates_path,
        shard_dir=shard_dir,
        out_dir=out_dir,
        sample_size=sample_size,
        seed=seed,
        book_filter=book_filter,
        chapter_filter=chapter_filter,
    )
    click.echo(f"Wrote candidates eval pack with {payload['sample_size']} items to {out_dir}.")
