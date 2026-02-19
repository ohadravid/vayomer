from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable

import click
from tqdm import tqdm

from data_proc.corpus import BibleCorpus, HintMatch
from data_proc.llm import JsonChatModel
from data_proc.schema import (
    BonusHint,
    CandidateItem,
    ChapterPayload,
    ChoicePools,
    DropRecord,
    FinalLangText,
    FinalMeta,
    FinalQuoteItem,
    FinalSource,
    RefRange,
    append_jsonl,
    iter_candidate_items,
    write_json,
    write_json_atomic,
)
from data_proc.utils import bible_sources
from data_proc.utils.text_cleanup import (
    candidate_bonus_words,
    candidate_riddle_spans,
    clean_text,
    cleanup_hebrew_quote,
    forbidden_word_set,
    normalize_word,
    restore_hebrew_surface,
    strip_hebrew_marks,
    whole_word_occurs,
)

LOG = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_ENGLISH_XML = REPO_ROOT / bible_sources.DEFAULT_ENGLISH_COLLECTION
DEFAULT_HEBREW_ZIP = REPO_ROOT / bible_sources.DEFAULT_HEBREW_ZIP


class CandidateDropError(RuntimeError):
    def __init__(self, record: DropRecord) -> None:
        super().__init__(record.reason)
        self.record = record


@dataclass(frozen=True)
class ValidationResult:
    speaker_is_speaking: bool
    listener_is_addressed: bool
    speaker_is_character: bool
    listener_is_character: bool
    reason: str

    @property
    def passed(self) -> bool:
        return (
            self.speaker_is_speaking
            and self.listener_is_addressed
            and self.speaker_is_character
            and self.listener_is_character
        )


@dataclass(frozen=True)
class BonusSelection:
    en_word: str
    he_word: str
    hint: HintMatch


@dataclass(frozen=True)
class PreparedBonusCandidate:
    candidate: CandidateItem
    en_words: list[str]
    he_words: list[str]
    expansion: str


@dataclass(frozen=True)
class PreparedContextCandidate:
    candidate: CandidateItem
    expansion: str


@dataclass(frozen=True)
class ResolvedCandidateValidation:
    candidate: CandidateItem
    english: ValidationResult
    hebrew: ValidationResult


EN_REPORTING_PREFIX_RE = re.compile(
    r"^(?:and\s+)?(?:[^,]{0,160}\b(?:said|saith|spake|saying|answered|answering|asked|asking|called|calling|cried|replying|replied)\b)\s*,\s*(?P<utterance>.+)$",
    re.IGNORECASE,
)
HEBREW_REPORTING_VERBS = {
    normalize_word(word, "he")
    for word in (
        "וַיֹּאמֶר",
        "וַיֹּאמְרוּ",
        "וַתֹּאמֶר",
        "וַתֹּאמְרוּ",
        "וַיַּעַן",
        "וַיַּעֲנוּ",
        "אָמַר",
        "אָמְרוּ",
    )
}
MAX_RIDDLE_WORDS = 28
MAX_ALIGNMENT_PAIRS = 3
MAX_CONTEXT_EXPANSION_TOTAL_VERSES = 7
ENGLISH_ROLE_PRONOUNS = {
    "i",
    "me",
    "my",
    "mine",
    "myself",
    "you",
    "your",
    "yours",
    "yourself",
    "yourselves",
    "thou",
    "thee",
    "thy",
    "thine",
    "ye",
    "we",
    "us",
    "our",
    "ours",
    "ourselves",
    "he",
    "she",
    "him",
    "her",
    "they",
    "them",
}
HEBREW_ROLE_PRONOUNS = {
    normalize_word(word, "he")
    for word in (
        "אני",
        "אנכי",
        "אתה",
        "את",
        "אתם",
        "אתן",
        "אנחנו",
        "הוא",
        "היא",
        "הם",
        "הן",
        "אותי",
        "אתי",
        "אִתְּכֶם",
        "עִמָּכֶם",
        "לְךָ",
        "לָךְ",
    )
}
EN_WEAK_CONTEXT_ROLES = {
    "all that hear",
    "brethren",
    "children of heth",
    "damsel",
    "father",
    "his brethren",
    "his father",
    "his household",
    "his sons",
    "his sons in law",
    "his young men",
    "master's wife",
    "officers",
    "one",
    "servant",
    "sons of heth",
}
HE_WEAK_CONTEXT_ROLES = {
    normalize_word(word, "he")
    for word in (
        "אחד",
        "אחיו",
        "אבי",
        "אביה",
        "אביו",
        "אליו",
        "אלהם",
        "העבד",
        "הנערה",
        "ביתו",
        "בניו",
        "בניחת",
        "בניחתאתאברהם",
        "בנייעקב",
        "בני חת",
        "חתניו",
        "כלהעם",
        "כלהשמע",
        "לבניו",
        "משרתת",
        "נעריו",
        "עבד",
        "עמו",
        "פקידים",
        "שר המשקים",
    )
}


def _slugify_book_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _chapter_sort_key(book_code: str, chapter: int) -> tuple[int, int]:
    return bible_sources.BOOK_ORDER.get(book_code, 999), chapter


def _canonical_book_filter(book_filter: str | None) -> str | None:
    if not book_filter:
        return None
    stripped = book_filter.strip()
    upper = stripped.upper()
    if upper in bible_sources.BOOK_CODE_TO_EN:
        return upper
    for code, en_name, he_name in bible_sources.OT_BOOKS:
        if stripped.casefold() in {en_name.casefold(), he_name.casefold()}:
            return code
    return stripped


def chapter_output_path(out_dir: Path, payload: ChapterPayload) -> Path:
    return out_dir / f"{_slugify_book_name(payload.book)}-{payload.chapter:03d}.json"


def _iter_existing_chapter_files(
    out_dir: Path,
    *,
    book_filter: str | None,
    chapter_filter: int | None,
) -> list[tuple[tuple[str, int], Path]]:
    if not out_dir.exists():
        return []

    entries: list[tuple[tuple[str, int], Path]] = []
    for path in sorted(out_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            book_code = payload["book_code"]
            chapter = int(payload["chapter"])
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            continue
        if book_filter and book_code != book_filter:
            continue
        if chapter_filter is not None and chapter != chapter_filter:
            continue
        entries.append(((book_code, chapter), path))
    return entries


def _find_resume_point(
    out_dir: Path,
    *,
    book_filter: str | None,
    chapter_filter: int | None,
) -> tuple[str, int] | None:
    latest: tuple[str, int] | None = None
    for key, _ in _iter_existing_chapter_files(out_dir, book_filter=book_filter, chapter_filter=chapter_filter):
        if latest is None or _chapter_sort_key(*key) > _chapter_sort_key(*latest):
            latest = key
    return latest


def _existing_output_item_ids_by_chapter(
    out_dir: Path,
    *,
    book_filter: str | None,
    chapter_filter: int | None,
) -> dict[tuple[str, int], set[str]]:
    item_ids: dict[tuple[str, int], set[str]] = {}
    for key, path in _iter_existing_chapter_files(out_dir, book_filter=book_filter, chapter_filter=chapter_filter):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            items = payload.get("items", [])
        except (OSError, TypeError, json.JSONDecodeError):
            continue
        item_ids[key] = {
            str(item["id"])
            for item in items
            if isinstance(item, dict) and item.get("id")
        }
    return item_ids


def _issue_log_candidate_ids_by_chapter(
    issues_log: Path | None,
    *,
    book_filter: str | None,
    chapter_filter: int | None,
) -> dict[tuple[str, int], set[str]]:
    if issues_log is None or not issues_log.exists():
        return {}

    item_ids: dict[tuple[str, int], set[str]] = {}
    with issues_log.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
                key = (str(payload["book_code"]), int(payload["chapter"]))
                candidate_id = str(payload["candidate_id"])
            except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                continue
            if book_filter and key[0] != book_filter:
                continue
            if chapter_filter is not None and key[1] != chapter_filter:
                continue
            item_ids.setdefault(key, set()).add(candidate_id)
    return item_ids


def _find_resume_point_for_candidates(
    candidates: list[CandidateItem],
    *,
    out_dir: Path,
    issues_log: Path | None,
    book_filter: str | None,
    chapter_filter: int | None,
) -> tuple[str, int] | None:
    expected_counts: dict[tuple[str, int], set[str]] = {}
    ordered_keys: list[tuple[str, int]] = []
    for candidate in candidates:
        key = (candidate.source.book_code, candidate.source.chapter)
        if key not in expected_counts:
            expected_counts[key] = set()
            ordered_keys.append(key)
        expected_counts[key].add(candidate.id)

    if not ordered_keys:
        return None

    output_ids = _existing_output_item_ids_by_chapter(
        out_dir,
        book_filter=book_filter,
        chapter_filter=chapter_filter,
    )
    issue_ids = _issue_log_candidate_ids_by_chapter(
        issues_log,
        book_filter=book_filter,
        chapter_filter=chapter_filter,
    )

    for key in ordered_keys:
        expected_ids = expected_counts[key]
        processed_ids = (output_ids.get(key, set()) | issue_ids.get(key, set())) & expected_ids
        if len(processed_ids) < len(expected_ids):
            return key

    return ordered_keys[-1]


def _find_resume_point_for_payloads(
    payloads: list[ChapterPayload],
    *,
    out_dir: Path,
    book_filter: str | None,
    chapter_filter: int | None,
) -> tuple[str, int] | None:
    ordered_keys: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for payload in payloads:
        key = (payload.book_code, payload.chapter)
        if key not in seen:
            seen.add(key)
            ordered_keys.append(key)

    if not ordered_keys:
        return None

    existing_keys = {
        key
        for key, _ in _iter_existing_chapter_files(
            out_dir,
            book_filter=book_filter,
            chapter_filter=chapter_filter,
        )
    }

    for key in ordered_keys:
        if key not in existing_keys:
            return key

    return ordered_keys[-1]


def _drop_outputs_from_resume_point(
    out_dir: Path,
    *,
    resume_point: tuple[str, int] | None,
    book_filter: str | None,
    chapter_filter: int | None,
) -> None:
    if resume_point is None:
        return
    for key, path in _iter_existing_chapter_files(out_dir, book_filter=book_filter, chapter_filter=chapter_filter):
        if _chapter_sort_key(*key) >= _chapter_sort_key(*resume_point):
            path.unlink(missing_ok=True)


def _trim_issues_log(
    issues_log: Path,
    *,
    resume_point: tuple[str, int] | None,
    book_filter: str | None,
    chapter_filter: int | None,
) -> None:
    if not issues_log.exists():
        return
    if resume_point is None:
        issues_log.write_text("", encoding="utf-8")
        return

    kept_lines: list[str] = []
    with issues_log.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
                key = (payload["book_code"], int(payload["chapter"]))
            except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                continue
            if book_filter and key[0] != book_filter:
                kept_lines.append(stripped)
                continue
            if chapter_filter is not None and key[1] != chapter_filter:
                kept_lines.append(stripped)
                continue
            if _chapter_sort_key(*key) < _chapter_sort_key(*resume_point):
                kept_lines.append(stripped)
    issues_log.write_text("".join(f"{line}\n" for line in kept_lines), encoding="utf-8")


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().casefold()
        if lowered in {"true", "yes"}:
            return True
        if lowered in {"false", "no"}:
            return False
    raise ValueError(f"Expected boolean-like value, got {value!r}")


def _clean_for_lang(text: str, lang: str) -> str:
    return cleanup_hebrew_quote(text) if lang == "he" else clean_text(text)


def _llm_hebrew(text: str) -> str:
    return strip_hebrew_marks(cleanup_hebrew_quote(text))


def _riddle_turn_text(text: str, lang: str) -> str:
    cleaned = _clean_for_lang(text, lang)
    if lang == "en":
        match = EN_REPORTING_PREFIX_RE.match(cleaned)
        if match:
            return match.group("utterance").strip()
        return cleaned

    words = cleaned.split()
    if len(words) > 1 and normalize_word(words[0], "he") in HEBREW_REPORTING_VERBS:
        return " ".join(words[1:]).strip()
    return cleaned


def _normalized_riddle_key(text: str, lang: str) -> str:
    base = _riddle_turn_text(text, lang)
    if lang == "he":
        base = strip_hebrew_marks(cleanup_hebrew_quote(base))
    else:
        base = clean_text(base)
    base = re.sub(r"[^\w\s]+", " ", base, flags=re.UNICODE).casefold()
    return " ".join(base.split())


def _canonicalize_role_text(role: str, lang: str) -> str:
    if lang == "he":
        return cleanup_hebrew_quote(role)
    cleaned = clean_text(role)
    return re.sub(r"^(?:all\s+the\s+|the\s+)", "", cleaned, flags=re.IGNORECASE)


def _role_alias_from_source(role: str) -> str | None:
    match = re.search(r"\(([^()]+)\)\s*$", role)
    if not match:
        return None
    alias = clean_text(match.group(1))
    return alias or None


def _project_hebrew_substring_to_original(quote: str, stripped_substring: str) -> str | None:
    cleaned_quote = cleanup_hebrew_quote(quote)
    stripped_quote_parts: list[str] = []
    stripped_to_original: list[int] = []
    for index, char in enumerate(cleaned_quote):
        stripped_char = strip_hebrew_marks(char)
        if not stripped_char:
            continue
        stripped_quote_parts.append(stripped_char)
        stripped_to_original.extend([index] * len(stripped_char))

    stripped_quote = "".join(stripped_quote_parts)
    target = strip_hebrew_marks(cleanup_hebrew_quote(stripped_substring))
    if not target:
        return None
    start = stripped_quote.find(target)
    if start < 0:
        return None
    end = start + len(target) - 1
    return cleaned_quote[stripped_to_original[start] : stripped_to_original[end] + 1]


def _final_item_dedupe_key(item: FinalQuoteItem) -> tuple[str, int, str, str]:
    return (
        item.source.book_code,
        item.source.chapter,
        _normalized_riddle_key(item.en.riddle, "en"),
        _normalized_riddle_key(item.he.riddle, "he"),
    )


def _riddle_needs_edit(riddle: str, speaker: str, listener: str, lang: str) -> bool:
    cleaned = _clean_for_lang(riddle, lang)
    if _riddle_turn_text(cleaned, lang) != cleaned:
        return True
    if len(cleaned.split()) > MAX_RIDDLE_WORDS:
        return True
    return False


def _role_requires_exclusion(role: str, lang: str) -> bool:
    normalized = normalize_word(role, lang)
    if not normalized:
        return False
    if lang == "en":
        return normalized not in ENGLISH_ROLE_PRONOUNS
    return normalized not in HEBREW_ROLE_PRONOUNS


def _role_is_context_weak(role: str, lang: str) -> bool:
    if lang == "en":
        return clean_text(role).casefold() in EN_WEAK_CONTEXT_ROLES
    return normalize_word(role, "he") in HE_WEAK_CONTEXT_ROLES


def _candidate_might_need_context_expansion(candidate: CandidateItem) -> bool:
    if candidate.source.quote_verse_end - candidate.source.quote_verse_start + 1 >= MAX_CONTEXT_EXPANSION_TOTAL_VERSES:
        return False
    return _context_roles_need_clarification(candidate)


def _context_roles_need_clarification(candidate: CandidateItem) -> bool:
    for lang, text in (("en", candidate.en), ("he", candidate.he)):
        quote = _clean_for_lang(text.quote, lang)
        if not whole_word_occurs(quote, text.speaker, lang):
            return True
        if not whole_word_occurs(quote, text.listener, lang):
            return True
        if _role_is_context_weak(text.speaker, lang):
            return True
        if _role_is_context_weak(text.listener, lang):
            return True
    return False


def _candidate_missing_named_speaker(candidate: CandidateItem) -> bool:
    for lang, text in (("en", candidate.en), ("he", candidate.he)):
        normalized_speaker = normalize_word(text.speaker, lang)
        if not normalized_speaker:
            continue
        if lang == "en" and normalized_speaker in ENGLISH_ROLE_PRONOUNS:
            continue
        if lang == "he" and normalized_speaker in HEBREW_ROLE_PRONOUNS:
            continue
        if _role_is_context_weak(text.speaker, lang):
            continue
        quote = _clean_for_lang(text.quote, lang)
        if not whole_word_occurs(quote, text.speaker, lang):
            return True
    return False


def _candidate_riddle_needs_edit(candidate: CandidateItem, lang: str) -> bool:
    text = candidate.he if lang == "he" else candidate.en
    cleaned = _clean_for_lang(text.riddle, lang)
    if _riddle_turn_text(cleaned, lang) != cleaned:
        return True
    if _role_requires_exclusion(text.speaker, lang) and whole_word_occurs(cleaned, text.speaker, lang):
        return True
    if _role_requires_exclusion(text.listener, lang) and whole_word_occurs(cleaned, text.listener, lang):
        return True
    if (
        candidate.source.quote_verse_end > candidate.source.quote_verse_start
        and len(cleaned.split()) > MAX_RIDDLE_WORDS
    ):
        return True
    return False


def _is_before_resume_point(candidate: CandidateItem, resume_point: tuple[str, int] | None) -> bool:
    if resume_point is None:
        return False
    candidate_key = (candidate.source.book_code, candidate.source.chapter)
    return _chapter_sort_key(*candidate_key) < _chapter_sort_key(*resume_point)


def _drop(candidate: CandidateItem, stage: str, reason: str, detail: str) -> CandidateDropError:
    return CandidateDropError(
        DropRecord(
            candidate_id=candidate.id,
            book_code=candidate.source.book_code,
            chapter=candidate.source.chapter,
            start=candidate.source.quote_verse_start,
            end=candidate.source.quote_verse_end,
            stage=stage,
            reason=reason,
            detail=detail,
        )
    )


def _validate_required_text(candidate: CandidateItem) -> None:
    if candidate.source.chapter != candidate.ref.chapter:
        raise _drop(candidate, "deterministic", "source_ref_mismatch", "source.chapter != ref.chapter")
    if candidate.source.quote_verse_start != candidate.ref.start or candidate.source.quote_verse_end != candidate.ref.end:
        raise _drop(candidate, "deterministic", "source_ref_mismatch", "source verse range != ref range")
    if candidate.ref.start > candidate.ref.end:
        raise _drop(candidate, "deterministic", "bad_range", "ref start is greater than ref end")
    if candidate.source.book != candidate.en.book or candidate.source.book_he != candidate.he.book:
        raise _drop(candidate, "deterministic", "book_mismatch", "source book names do not match language payloads")

    verse_keys = {str(verse) for verse in range(candidate.ref.start, candidate.ref.end + 1)}
    if set(candidate.raw_quote_source.en.keys()) != verse_keys or set(candidate.raw_quote_source.he.keys()) != verse_keys:
        raise _drop(candidate, "deterministic", "raw_source_mismatch", "raw_quote_source keys do not match source verse range")

    for lang, lang_text in (("en", candidate.en), ("he", candidate.he)):
        quote = _clean_for_lang(lang_text.quote, lang)
        riddle = _clean_for_lang(lang_text.riddle, lang)
        if not quote or not riddle:
            raise _drop(candidate, "deterministic", "empty_text", f"{lang} quote or riddle is empty")
        if riddle not in quote:
            raise _drop(candidate, "deterministic", "riddle_not_in_quote", f"{lang} riddle is not a substring of the full quote")
        if not clean_text(lang_text.speaker) or not clean_text(lang_text.listener):
            raise _drop(candidate, "deterministic", "empty_role", f"{lang} speaker or listener is empty")


def _validation_system_prompt(lang: str, *, retry: bool = False) -> str:
    language = "Hebrew" if lang == "he" else "English"
    bilingual_clause = (
        " English support lines may be provided for the same riddle turn; use them to disambiguate the Hebrew roles, but still answer for the Hebrew target_riddle."
        if lang == "he"
        else ""
    )
    retry_clause = (
        " Re-check carefully and only use false when the quote directly contradicts the proposed speaker or listener."
        if retry
        else ""
    )
    return (
        f"You validate Bible riddle metadata in {language}. "
        "The target utterance is the riddle span, not the whole quote. "
        "Use the full quote only as supporting context for the riddle. "
        "If the quote contains multiple turns of speech, answer for the riddle span only. "
        "Return JSON only with keys: speaker_is_speaking, listener_is_addressed, "
        "speaker_is_character, listener_is_character, reason. "
        "Use booleans for the first four keys. "
        "Keep reason short, plain, and high-level. "
        "Do not quote the riddle or copy long source text into reason. "
        "Judge exactly the provided speaker_for_riddle and listener_for_riddle. "
        "Do not swap them and do not replace them with another speaker or listener from the surrounding quote. "
        "Treat named people, concrete beings, and concrete groups or roles as real entities, for example Adam, Noah, woman, man, serpent, people, sons, young men, king, prophet, and God. "
        "If the speaker or listener names or clearly describes a concrete being in the riddle scene, mark *_is_character true. "
        "If the riddle says or clearly implies 'X said/spake/called/asked unto Y', then speaker_is_speaking must be true for X and listener_is_addressed must be true for Y. "
        "Groups such as people, the people, all the people, sons, family, or young men count as true entities for this task. "
        "If the provided speaker field is only a reporting clause such as 'And he said' or 'וַיֹּאמֶר', speaker_is_character must be false. "
        "Mark *_is_character false only for pronouns, reporting clauses, or abstractions like creation."
        f"{bilingual_clause}"
        f"{retry_clause}"
    )


def _role_validation_system_prompt(lang: str, *, retry: bool = False) -> str:
    language = "Hebrew" if lang == "he" else "English"
    bilingual_clause = (
        " English support lines may be provided for the same riddle turn. Use them to return the matching Hebrew speaker and listener for that same turn. "
        "If the English validation booleans show that the listener is addressed in that reply turn, the matching Hebrew listener should also be treated as addressed unless the Hebrew text directly contradicts it."
        if lang == "he"
        else ""
    )
    retry_clause = (
        " Re-check carefully. If the current roles are generic, weak, or reversed, correct them before scoring the booleans."
        if retry
        else ""
    )
    return (
        f"You resolve and validate Bible riddle roles in {language}. "
        "The target utterance is the riddle span only. Use the full quote only as supporting context. "
        "Return JSON only with keys speaker, listener, speaker_is_speaking, listener_is_addressed, speaker_is_character, listener_is_character, reason. "
        "speaker and listener must be short concrete names or group labels for the target_riddle. "
        "Do not return a reporting clause such as 'And he said' or 'וַיֹּאמֶר'. "
        "Do not leave pronouns when a nearby concrete person or group is clear. "
        "If the target riddle is an answer or reply, return the speaker and listener for that answer turn, not for an earlier turn in the same quote. "
        "If the target riddle is an answer or reply to someone, listener_is_addressed should be true for the person or group being answered, even if the name is stated only in nearby context. "
        "Concrete groups count as characters for this task. "
        "Use booleans for the four validation keys and keep reason short. "
        f"{bilingual_clause}"
        f"{retry_clause}"
    )


def _riddle_edit_system_prompt(lang: str) -> str:
    language = "Hebrew" if lang == "he" else "English"
    return (
        f"You select the best exact riddle substring in {language}. "
        "Return JSON only with key riddle. "
        "Use exactly one string from allowed_riddles. "
        "Prefer the main command, claim, or question of the speech. "
        "Do not include a reporting clause, the speaker name, or the listener name when a cleaner option exists. "
        "If english_target_riddle is provided, choose the candidate that matches that English target most closely in meaning and position. "
        f"Prefer concise candidates, ideally no more than {MAX_RIDDLE_WORDS} words."
    )


def _riddle_edit_user_prompt(candidate: CandidateItem, lang: str, *, english_target_riddle: str, allowed_riddles: list[str]) -> str:
    text = candidate.he if lang == "he" else candidate.en
    quote = _llm_hebrew(text.quote) if lang == "he" else text.quote
    riddle = _llm_hebrew(text.riddle) if lang == "he" else text.riddle
    speaker = _llm_hebrew(text.speaker) if lang == "he" else text.speaker
    listener = _llm_hebrew(text.listener) if lang == "he" else text.listener
    lines = [
        f"quote: {quote}",
        f"current_riddle: {riddle}",
        f"speaker: {speaker}",
        f"listener: {listener}",
        f"allowed_riddles: {allowed_riddles}",
    ]
    if lang == "he":
        lines.append(f"english_target_riddle: {english_target_riddle}")
        lines.append("Match the Hebrew clause to english_target_riddle as closely as possible. Prefer the earliest matching clause in the quote.")
    lines.append("Return one exact candidate from allowed_riddles.")
    return "\n".join(lines)


def _role_resolution_system_prompt(lang: str) -> str:
    language = "Hebrew" if lang == "he" else "English"
    bilingual_clause = (
        " English support lines may be provided for the same riddle turn; return the Hebrew speaker and listener for those same roles, not reversed."
        if lang == "he"
        else ""
    )
    return (
        f"You extract the speaker and listener for a Bible speech turn in {language}. "
        "The target utterance is the riddle span, not the whole quote. "
        "Use the full quote only as supporting context. "
        "If the riddle scene says a person or group answered and said the riddle, that person or group is the speaker. "
        "The listener is the person or group being addressed or answered in that riddle scene, even if named only in nearby context. "
        "If the target riddle is first-person speech, prefer the named person or group who introduced that speech in nearby context over a different character merely mentioned later in the quote. "
        "Correct reversed roles when needed. "
        "Use short concrete names or group labels from the quote context. "
        "Never return a reporting clause such as 'And he said' or 'וַיֹּאמֶר'. "
        f"{bilingual_clause} "
        'Return JSON only with keys "speaker" and "listener".'
    )


def _role_resolution_user_prompt(
    candidate: CandidateItem,
    lang: str,
    *,
    english_speaker: str | None = None,
    english_listener: str | None = None,
) -> str:
    text = candidate.he if lang == "he" else candidate.en
    quote = _llm_hebrew(text.quote) if lang == "he" else text.quote
    riddle = _llm_hebrew(text.riddle) if lang == "he" else text.riddle
    speaker = _llm_hebrew(text.speaker) if lang == "he" else text.speaker
    listener = _llm_hebrew(text.listener) if lang == "he" else text.listener
    prompt = (
        f"supporting_quote_context: {quote}\n"
        f"target_riddle: {riddle}\n"
        f"proposed_speaker: {speaker}\n"
        f"proposed_listener: {listener}\n"
        f"swapped_speaker: {listener}\n"
        f"swapped_listener: {speaker}\n"
        "Return the actual speaker and listener for the target_riddle only."
    )
    if lang == "he" and english_speaker and english_listener:
        prompt += (
            f"\nenglish_supporting_quote_context: {candidate.en.quote}\n"
            f"english_target_riddle: {candidate.en.riddle}\n"
            f"english_speaker_for_same_riddle: {english_speaker}\n"
            f"english_listener_for_same_riddle: {english_listener}\n"
            "Return the Hebrew names for those same speaker and listener roles."
        )
    return prompt


def _role_validation_user_prompt(
    candidate: CandidateItem,
    lang: str,
    *,
    english_speaker: str | None = None,
    english_listener: str | None = None,
    english_result: ValidationResult | None = None,
) -> str:
    text = candidate.he if lang == "he" else candidate.en
    quote = _llm_hebrew(text.quote) if lang == "he" else text.quote
    riddle = _llm_hebrew(text.riddle) if lang == "he" else text.riddle
    speaker = _llm_hebrew(text.speaker) if lang == "he" else text.speaker
    listener = _llm_hebrew(text.listener) if lang == "he" else text.listener
    lines = [
        f"supporting_quote_context: {quote}",
        f"target_riddle: {riddle}",
        f"proposed_speaker: {speaker}",
        f"proposed_listener: {listener}",
        f"swapped_speaker: {listener}",
        f"swapped_listener: {speaker}",
        "Return the actual speaker and listener for target_riddle, then score those returned roles with the validation booleans.",
    ]
    if lang == "he" and english_speaker and english_listener:
        lines.extend(
            [
                f"english_supporting_quote_context: {candidate.en.quote}",
                f"english_target_riddle: {candidate.en.riddle}",
                f"english_speaker_for_same_riddle: {english_speaker}",
                f"english_listener_for_same_riddle: {english_listener}",
                "Return the Hebrew speaker and listener for those same roles.",
            ]
        )
        if english_result is not None:
            lines.extend(
                [
                    f"english_speaker_is_speaking: {str(english_result.speaker_is_speaking).lower()}",
                    f"english_listener_is_addressed: {str(english_result.listener_is_addressed).lower()}",
                    f"english_speaker_is_character: {str(english_result.speaker_is_character).lower()}",
                    f"english_listener_is_character: {str(english_result.listener_is_character).lower()}",
                ]
            )
    return "\n".join(lines)


def _role_validation_retry_user_prompt(
    candidate: CandidateItem,
    lang: str,
    *,
    previous_speaker: str,
    previous_listener: str,
    previous_result: ValidationResult,
    english_speaker: str | None = None,
    english_listener: str | None = None,
    english_result: ValidationResult | None = None,
) -> str:
    return (
        f"{_role_validation_user_prompt(candidate, lang, english_speaker=english_speaker, english_listener=english_listener, english_result=english_result)}\n"
        f"previous_speaker: {previous_speaker}\n"
        f"previous_listener: {previous_listener}\n"
        f"previous_validation: speaker_is_speaking={previous_result.speaker_is_speaking}, "
        f"listener_is_addressed={previous_result.listener_is_addressed}, "
        f"speaker_is_character={previous_result.speaker_is_character}, "
        f"listener_is_character={previous_result.listener_is_character}\n"
        f"previous_reason: {previous_result.reason}\n"
        "Correct any weak, generic, or reversed roles before rescoring."
    )


def _validation_user_prompt(candidate: CandidateItem, lang: str) -> str:
    text = candidate.he if lang == "he" else candidate.en
    quote = _llm_hebrew(text.quote) if lang == "he" else text.quote
    riddle = _llm_hebrew(text.riddle) if lang == "he" else text.riddle
    speaker = _llm_hebrew(text.speaker) if lang == "he" else text.speaker
    listener = _llm_hebrew(text.listener) if lang == "he" else text.listener
    prompt = (
        f"supporting_quote_context: {quote}\n"
        f"target_riddle: {riddle}\n"
        f"speaker_for_riddle: {speaker}\n"
        f"listener_for_riddle: {listener}\n"
        "Judge the provided speaker_for_riddle and listener_for_riddle for the target_riddle only. Use the full quote only as context. Do not swap the roles."
    )
    if lang == "he":
        prompt += (
            f"\nenglish_supporting_quote_context: {candidate.en.quote}\n"
            f"english_target_riddle: {candidate.en.riddle}\n"
            f"english_speaker_for_riddle: {candidate.en.speaker}\n"
            f"english_listener_for_riddle: {candidate.en.listener}\n"
            "The English lines describe the same riddle turn."
        )
    return prompt


def _hebrew_role_repair_system_prompt() -> str:
    return (
        "You repair Hebrew speaker and listener names for a Bible riddle using English support. "
        'Return JSON only with keys "speaker" and "listener". '
        "Use the same roles as the English speaker and listener for the same riddle turn. "
        "Return short concrete Hebrew names or Hebrew group labels. "
        "Do not return Hebrew pronouns or weak placeholders such as אליו, לו, להם, אותו, עמו, אחד, or reporting clauses when the English role is concrete. "
        "If nearby Hebrew context names the same role more concretely, use that Hebrew name or group label."
    )


def _hebrew_role_repair_user_prompt(
    candidate: CandidateItem,
    *,
    english_speaker: str,
    english_listener: str,
    nearby_hebrew_context: str,
    nearby_english_context: str,
) -> str:
    return (
        f"hebrew_quote_context: {_llm_hebrew(candidate.he.quote)}\n"
        f"hebrew_riddle: {_llm_hebrew(candidate.he.riddle)}\n"
        f"current_hebrew_speaker: {_llm_hebrew(candidate.he.speaker)}\n"
        f"current_hebrew_listener: {_llm_hebrew(candidate.he.listener)}\n"
        f"english_quote_context: {candidate.en.quote}\n"
        f"english_riddle: {candidate.en.riddle}\n"
        f"english_speaker_for_same_riddle: {english_speaker}\n"
        f"english_listener_for_same_riddle: {english_listener}\n"
        f"nearby_hebrew_context: {_llm_hebrew(nearby_hebrew_context)}\n"
        f"nearby_english_context: {nearby_english_context}\n"
        "Return the corrected Hebrew speaker and listener for the same roles."
    )


def _validation_repair_user_prompt(candidate: CandidateItem, lang: str, previous: ValidationResult) -> str:
    return (
        f"{_validation_user_prompt(candidate, lang)}\n"
        f"previous_result: speaker_is_speaking={previous.speaker_is_speaking}, "
        f"listener_is_addressed={previous.listener_is_addressed}, "
        f"speaker_is_character={previous.speaker_is_character}, "
        f"listener_is_character={previous.listener_is_character}\n"
        f"previous_reason: {previous.reason}\n"
        "Correct any false negatives. If the quote explicitly says the speaker spoke to the listener, those booleans should be true. Do not swap the provided roles."
    )


def _parse_validation_result(payload: dict) -> ValidationResult:
    return ValidationResult(
        speaker_is_speaking=_coerce_bool(payload["speaker_is_speaking"]),
        listener_is_addressed=_coerce_bool(payload["listener_is_addressed"]),
        speaker_is_character=_coerce_bool(payload["speaker_is_character"]),
        listener_is_character=_coerce_bool(payload["listener_is_character"]),
        reason=str(payload["reason"]),
    )


def _reconcile_hebrew_validation_from_english(
    candidate: CandidateItem,
    english_result: ValidationResult | None,
    hebrew_result: ValidationResult,
) -> ValidationResult:
    if english_result is None or hebrew_result.passed:
        return hebrew_result
    if _role_is_context_weak(candidate.he.speaker, "he") or _role_is_context_weak(candidate.he.listener, "he"):
        return hebrew_result
    if normalize_word(candidate.he.speaker, "he") in HEBREW_ROLE_PRONOUNS:
        return hebrew_result
    if normalize_word(candidate.he.listener, "he") in HEBREW_ROLE_PRONOUNS:
        return hebrew_result

    speaker_is_speaking = hebrew_result.speaker_is_speaking or (
        english_result.speaker_is_speaking and hebrew_result.speaker_is_character
    )
    listener_is_addressed = hebrew_result.listener_is_addressed or (
        english_result.listener_is_addressed and hebrew_result.listener_is_character
    )
    if (
        speaker_is_speaking == hebrew_result.speaker_is_speaking
        and listener_is_addressed == hebrew_result.listener_is_addressed
    ):
        return hebrew_result

    return replace(
        hebrew_result,
        speaker_is_speaking=speaker_is_speaking,
        listener_is_addressed=listener_is_addressed,
        reason=f"{hebrew_result.reason} English support confirms the same riddle turn roles.".strip(),
    )


def _bonus_words_system_prompt() -> str:
    return (
        "Pick interesting one-word English bonus candidates for a Bible riddle. "
        "Return JSON only. "
        'Return exactly one JSON object in this shape: {"words":["word1","word2"]}. '
        'The top-level key must be "words". Even if you choose one word, it must still be inside the "words" array. '
        'Use only exact strings from allowed_words. Prefer concrete, memorable words. '
        'Valid example: {"words":["faint","pursuing"]}. '
        'Invalid example: {"word":"faint"}. '
        'Invalid example: {"choices":["faint"]}. '
        'If none fit, return {"words":[]}.'
    )


def _bonus_words_user_prompt(candidate: CandidateItem, allowed_words: list[str]) -> str:
    return (
        f"quote: {candidate.en.quote}\n"
        f"riddle: {candidate.en.riddle}\n"
        f"allowed_words: {allowed_words}\n"
        "Return the best words first."
    )


def _alignment_system_prompt() -> str:
    return (
        "Align English bonus words to Hebrew words from the same bilingual Bible quote. "
        "Return JSON only. "
        'Return exactly one JSON object in this shape: {"pairs":[{"en":"english_word","he":"hebrew_word"}]}. '
        'The top-level key must be "pairs". Even if you choose one pair, it must still be inside the "pairs" array. '
        'Each item inside "pairs" must have exactly the keys "en" and "he". '
        "Use only the provided words exactly and keep only same or very similar meanings. "
        f"Return at most {MAX_ALIGNMENT_PAIRS} pairs total. Prefer 1 or 2 strong pairs over a long list. "
        "Do not try to cover every possible word. Omit weak, redundant, or uncertain pairs. "
        "Keep the response short so the JSON object stays complete. "
        'Valid example: {"pairs":[{"en":"faint","he":"עיפים"}]}. '
        'Invalid example: {"en":"faint","he":"עיפים"}. '
        'Invalid example: {"alignment":{"en":"faint","he":"עיפים"}}. '
        'Invalid example: {"alignments":[{"en":"faint","he":"עיפים"}]}. '
        'If none fit, return {"pairs":[]}.'
    )


def _quote_expansion_system_prompt() -> str:
    return (
        "Choose whether adding one adjacent verse BEFORE or AFTER gives a better Bible quote for selecting a bonus word. "
        "Return JSON only with key choice. The value must be one of before, after, or none. "
        "Prefer the option that adds concrete memorable words not already in the riddle and not equal to the speaker or listener."
    )


def _context_expansion_system_prompt(*, retry: bool = False) -> str:
    retry_clause = (
        " Re-check carefully: generic weak labels such as one, servant, father, brethren, or אחד do not count as sufficiently clear speaker or listener context by themselves."
        if retry
        else ""
    )
    return (
        "Choose whether a Bible quote should stay as-is or include exactly one adjacent verse BEFORE or AFTER to make the full quote better UX for the same riddle. "
        "Return JSON only with keys choice and reason. "
        "choice must be one of before, after, or none. "
        "Prefer none unless the current quote is too context-thin. "
        "Expand only when one adjacent verse makes the speaker, listener, or scene materially clearer while still keeping the quote minimal. "
        "Prefer the adjacent verse that explicitly names a currently missing or weak speaker or listener in the full quote. "
        "Generic weak labels such as one, servant, father, brethren, or אחד do not count as sufficiently clear by themselves for UX, even if they literally appear in the current quote. "
        "The current quote already stays in place; BEFORE means prepend the single before verse, AFTER means append the single after verse. "
        "If the current quote still lacks a named speaker for the riddle, BEFORE is usually better than AFTER because speech introductions normally come before the speech. "
        "Prefer BEFORE when it introduces the same speech turn more clearly. "
        "Avoid AFTER if it starts a different main speech turn after the target_riddle. "
        "Never choose an expansion just to add extra detail. "
        "Keep the reason short."
        f"{retry_clause}"
    )


def _context_expansion_user_prompt(
    candidate: CandidateItem,
    *,
    before_added_verse_en: str | None,
    before_added_verse_he: str | None,
    after_added_verse_en: str | None,
    after_added_verse_he: str | None,
) -> str:
    current_en_has_speaker = whole_word_occurs(candidate.en.quote, candidate.en.speaker, "en")
    current_en_has_listener = whole_word_occurs(candidate.en.quote, candidate.en.listener, "en")
    current_he_has_speaker = whole_word_occurs(candidate.he.quote, candidate.he.speaker, "he")
    current_he_has_listener = whole_word_occurs(candidate.he.quote, candidate.he.listener, "he")
    english_weak_roles = [
        role_name
        for role_name, role_value in (("speaker", candidate.en.speaker), ("listener", candidate.en.listener))
        if _role_is_context_weak(role_value, "en")
    ]
    hebrew_weak_roles = [
        role_name
        for role_name, role_value in (("speaker", candidate.he.speaker), ("listener", candidate.he.listener))
        if _role_is_context_weak(role_value, "he")
    ]
    lines = [
        f"current_quote: {candidate.en.quote}",
        f"current_riddle: {candidate.en.riddle}",
        f"speaker_for_riddle: {candidate.en.speaker}",
        f"listener_for_riddle: {candidate.en.listener}",
        f"current_quote_has_english_speaker: {str(current_en_has_speaker).lower()}",
        f"current_quote_has_english_listener: {str(current_en_has_listener).lower()}",
        f"english_weak_roles: {english_weak_roles}",
        f"hebrew_current_quote: {_llm_hebrew(candidate.he.quote)}",
        f"hebrew_riddle: {_llm_hebrew(candidate.he.riddle)}",
        f"hebrew_speaker_for_riddle: {_llm_hebrew(candidate.he.speaker)}",
        f"hebrew_listener_for_riddle: {_llm_hebrew(candidate.he.listener)}",
        f"current_quote_has_hebrew_speaker: {str(current_he_has_speaker).lower()}",
        f"current_quote_has_hebrew_listener: {str(current_he_has_listener).lower()}",
        f"hebrew_weak_roles: {hebrew_weak_roles}",
    ]
    if before_added_verse_en is not None:
        lines.append(f"before_added_verse: {before_added_verse_en}")
        if before_added_verse_he is not None:
            lines.append(f"hebrew_before_added_verse: {_llm_hebrew(before_added_verse_he)}")
    if after_added_verse_en is not None:
        lines.append(f"after_added_verse: {after_added_verse_en}")
        if after_added_verse_he is not None:
            lines.append(f"hebrew_after_added_verse: {_llm_hebrew(after_added_verse_he)}")
    lines.append("Choose before, after, or none.")
    return "\n".join(lines)


def _context_expansion_retry_user_prompt(candidate: CandidateItem, *, base_prompt: str, previous_choice: str, previous_reason: str) -> str:
    return (
        f"{base_prompt}\n"
        f"previous_choice: {previous_choice}\n"
        f"previous_reason: {previous_reason}\n"
        "Re-evaluate carefully. If the current quote only names the speaker or listener with a weak generic role, that is not clear enough UX by itself."
    )


def _forced_context_expansion_system_prompt() -> str:
    return (
        "The current Bible quote needs one adjacent verse to improve UX for the same riddle. "
        "Choose the better minimal fix between BEFORE and AFTER only. "
        "Return JSON only with keys choice and reason. "
        "choice must be before or after. "
        "Prefer BEFORE when it introduces the same speech turn more clearly. "
        "Avoid AFTER if it starts a different main speech turn after the target_riddle. "
        "Keep the reason short."
    )


def _forced_context_expansion_user_prompt(candidate: CandidateItem, *, base_prompt: str) -> str:
    return (
        f"{base_prompt}\n"
        "The current quote is not clear enough UX because at least one speaker/listener role is weak or missing in context. "
        "Choose the better minimal expansion: before or after."
    )


def _quote_expansion_user_prompt(
    candidate: CandidateItem,
    *,
    before_quote: str | None,
    before_words: list[str],
    after_quote: str | None,
    after_words: list[str],
) -> str:
    lines = [
        f"current_quote: {candidate.en.quote}",
        f"riddle: {candidate.en.riddle}",
        f"speaker: {candidate.en.speaker}",
        f"listener: {candidate.en.listener}",
    ]
    if before_quote is not None:
        lines.append(f"before_quote: {before_quote}")
        lines.append(f"before_allowed_words: {before_words}")
    if after_quote is not None:
        lines.append(f"after_quote: {after_quote}")
        lines.append(f"after_allowed_words: {after_words}")
    lines.append("Choose the best option.")
    return "\n".join(lines)


def _alignment_user_prompt(candidate: CandidateItem, english_words: list[str], hebrew_words: list[str]) -> str:
    return (
        f"Choose zero to {MAX_ALIGNMENT_PAIRS} aligned pairs.\n"
        f"Return the strongest pairs first and stop after {MAX_ALIGNMENT_PAIRS}.\n"
        'The output must always be one object with top-level key "pairs".\n'
        'If there is one pair, still return {"pairs":[{"en":"...","he":"..."}]}.\n'
        f"english_riddle: {candidate.en.riddle}\n"
        f"hebrew_riddle: {_llm_hebrew(candidate.he.riddle)}\n"
        f"english_words: {english_words}\n"
        f"hebrew_words: {[ _llm_hebrew(word) for word in hebrew_words ]}\n"
        f"english_quote_context: {candidate.en.quote}\n"
        f"hebrew_quote_context: {_llm_hebrew(candidate.he.quote)}\n"
        'Return only JSON in the exact shape {"pairs":[{"en":"...","he":"..."}]}. '
        'Do not return {"en":"...","he":"..."} and do not use "alignment" or "alignments". '
        "Do not output extra pairs once the strongest matches are listed."
    )


def _validated_word_choices(payload: dict, allowed_words: list[str], lang: str) -> list[str]:
    allowed_by_normalized = {normalize_word(word, lang): word for word in allowed_words}
    raw_words = payload.get("words", [])
    if isinstance(raw_words, str):
        raw_words = [raw_words]
    if not raw_words and isinstance(payload.get("word"), str):
        raw_words = [payload["word"]]
    if not isinstance(raw_words, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw_word in raw_words:
        if not isinstance(raw_word, str):
            continue
        normalized = normalize_word(raw_word, lang)
        if not normalized or normalized in seen or normalized not in allowed_by_normalized:
            continue
        seen.add(normalized)
        out.append(allowed_by_normalized[normalized])
    return out


def _validated_pairs(payload: dict, allowed_en: list[str], allowed_he: list[str]) -> list[tuple[str, str]]:
    allowed_en_map = {normalize_word(word, "en"): word for word in allowed_en}
    allowed_he_map = {normalize_word(word, "he"): word for word in allowed_he}
    raw_pairs = payload.get("pairs", [])
    if isinstance(raw_pairs, dict):
        raw_pairs = [raw_pairs]
    if not raw_pairs and isinstance(payload.get("en"), str) and isinstance(payload.get("he"), str):
        raw_pairs = [{"en": payload["en"], "he": payload["he"]}]
    if not isinstance(raw_pairs, list):
        return []

    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw_pair in raw_pairs:
        if not isinstance(raw_pair, dict):
            continue
        raw_en = raw_pair.get("en")
        raw_he = raw_pair.get("he")
        if not isinstance(raw_en, str) or not isinstance(raw_he, str):
            continue
        normalized_en = normalize_word(raw_en, "en")
        normalized_he = normalize_word(raw_he, "he")
        if not normalized_en or not normalized_he:
            continue
        if normalized_en not in allowed_en_map or normalized_he not in allowed_he_map:
            continue
        pair = (allowed_en_map[normalized_en], allowed_he_map[normalized_he])
        key = (normalized_en, normalized_he)
        if key in seen:
            continue
        seen.add(key)
        out.append(pair)
    return out


def _display_riddle_candidates(candidates: list[str], lang: str) -> tuple[list[str], dict[str, str]]:
    display_candidates: list[str] = []
    display_map: dict[str, str] = {}
    for candidate in candidates:
        display = _llm_hebrew(candidate) if lang == "he" else clean_text(candidate)
        if not display or display in display_map:
            continue
        display_candidates.append(display)
        display_map[display] = candidate
    return display_candidates, display_map


def _validated_expansion_choice(payload: dict, allowed_choices: set[str]) -> str:
    choice = payload.get("choice")
    if not isinstance(choice, str):
        return "none"
    normalized = choice.strip().casefold()
    if normalized in allowed_choices:
        return normalized
    return "none"


class CandidatePipeline:
    def __init__(self, corpus: BibleCorpus, llm: JsonChatModel) -> None:
        self.corpus = corpus
        self.llm = llm

    def _nearby_context_texts(self, candidate: CandidateItem, *, radius: int = 3) -> tuple[str, str]:
        hebrew_parts = [candidate.he.quote, candidate.he.riddle, *candidate.raw_quote_source.he.values()]
        english_parts = [candidate.en.quote, candidate.en.riddle, *candidate.raw_quote_source.en.values()]
        start = max(1, candidate.source.quote_verse_start - radius)
        end = candidate.source.quote_verse_end + radius
        for verse in range(start, end + 1):
            range_quote = self.corpus.collect_range(candidate.source.book_code, candidate.source.chapter, verse, verse)
            if range_quote is None:
                continue
            hebrew_parts.extend(range_quote.raw_quote_source["he"].values())
            english_parts.extend(range_quote.raw_quote_source["en"].values())
        return " ".join(hebrew_parts), " ".join(english_parts)

    def _needs_hebrew_role_repair(self, he_role: str, en_role: str, *, nearby_hebrew_context: str) -> bool:
        normalized_he = normalize_word(he_role, "he")
        normalized_en = normalize_word(en_role, "en")
        if not normalized_en or normalized_en in ENGLISH_ROLE_PRONOUNS or _role_is_context_weak(en_role, "en"):
            return False
        if not normalized_he:
            return True
        if normalized_he in HEBREW_ROLE_PRONOUNS or _role_is_context_weak(he_role, "he"):
            return True
        return not whole_word_occurs(nearby_hebrew_context, he_role, "he")

    def _repair_hebrew_roles(
        self,
        candidate: CandidateItem,
        *,
        english_speaker: str,
        english_listener: str,
        hebrew_speaker: str,
        hebrew_listener: str,
    ) -> tuple[str, str]:
        nearby_hebrew_context, nearby_english_context = self._nearby_context_texts(candidate)
        if not (
            self._needs_hebrew_role_repair(hebrew_speaker, english_speaker, nearby_hebrew_context=nearby_hebrew_context)
            or self._needs_hebrew_role_repair(hebrew_listener, english_listener, nearby_hebrew_context=nearby_hebrew_context)
        ):
            return hebrew_speaker, hebrew_listener
        repair_candidate = replace(
            candidate,
            en=replace(candidate.en, speaker=english_speaker, listener=english_listener),
            he=replace(candidate.he, speaker=hebrew_speaker, listener=hebrew_listener),
        )
        payload = self.llm.chat_json(
            prompt_name="he-role-repair",
            system_prompt=_hebrew_role_repair_system_prompt(),
            user_prompt=_hebrew_role_repair_user_prompt(
                repair_candidate,
                english_speaker=english_speaker,
                english_listener=english_listener,
                nearby_hebrew_context=nearby_hebrew_context,
                nearby_english_context=nearby_english_context,
            ),
            required_keys=("speaker", "listener"),
        )
        repaired_speaker = _canonicalize_role_text(str(payload["speaker"]), "he")
        repaired_listener = _canonicalize_role_text(str(payload["listener"]), "he")
        return repaired_speaker, repaired_listener

    def _payload_roles_and_validation(self, payload: dict, lang: str) -> tuple[str, str, ValidationResult]:
        speaker = _canonicalize_role_text(str(payload["speaker"]), lang)
        listener = _canonicalize_role_text(str(payload["listener"]), lang)
        result = _parse_validation_result(payload)
        return speaker, listener, result

    def _resolved_roles_need_retry(self, speaker: str, listener: str, result: ValidationResult, lang: str) -> bool:
        if not result.passed:
            return True
        for role in (speaker, listener):
            normalized = normalize_word(role, lang)
            if not normalized:
                return True
            if lang == "en" and normalized in ENGLISH_ROLE_PRONOUNS:
                return True
            if lang == "he" and normalized in HEBREW_ROLE_PRONOUNS:
                return True
            if _role_is_context_weak(role, lang):
                return True
        return False

    def _resolve_and_validate_lang(
        self,
        candidate: CandidateItem,
        lang: str,
        *,
        english_speaker: str | None = None,
        english_listener: str | None = None,
        english_result: ValidationResult | None = None,
    ) -> tuple[str, str, ValidationResult]:
        payload = self.llm.chat_json(
            prompt_name=f"{lang}-role-validation",
            system_prompt=_role_validation_system_prompt(lang),
            user_prompt=_role_validation_user_prompt(
                candidate,
                lang,
                english_speaker=english_speaker,
                english_listener=english_listener,
                english_result=english_result,
            ),
            required_keys=(
                "speaker",
                "listener",
                "speaker_is_speaking",
                "listener_is_addressed",
                "speaker_is_character",
                "listener_is_character",
                "reason",
            ),
        )
        speaker, listener, result = self._payload_roles_and_validation(payload, lang)
        if not self._resolved_roles_need_retry(speaker, listener, result, lang):
            return speaker, listener, result

        retry_payload = self.llm.chat_json(
            prompt_name=f"{lang}-role-validation-retry",
            system_prompt=_role_validation_system_prompt(lang, retry=True),
            user_prompt=_role_validation_retry_user_prompt(
                candidate,
                lang,
                previous_speaker=speaker,
                previous_listener=listener,
                previous_result=result,
                english_speaker=english_speaker,
                english_listener=english_listener,
                english_result=english_result,
            ),
            required_keys=(
                "speaker",
                "listener",
                "speaker_is_speaking",
                "listener_is_addressed",
                "speaker_is_character",
                "listener_is_character",
                "reason",
            ),
        )
        return self._payload_roles_and_validation(retry_payload, lang)

    def _resolve_and_validate_candidate(self, candidate: CandidateItem) -> ResolvedCandidateValidation:
        english_speaker, english_listener, english_result = self._resolve_and_validate_lang(candidate, "en")
        for field_name, resolved_value, source_value in (
            ("speaker", english_speaker, candidate.en.speaker),
            ("listener", english_listener, candidate.en.listener),
        ):
            normalized_resolved = normalize_word(resolved_value, "en")
            if not normalized_resolved or normalized_resolved in ENGLISH_ROLE_PRONOUNS or _role_is_context_weak(resolved_value, "en"):
                alias = _role_alias_from_source(source_value)
                if alias:
                    if field_name == "speaker":
                        english_speaker = alias
                    else:
                        english_listener = alias

        candidate_with_english = replace(
            candidate,
            en=replace(candidate.en, speaker=english_speaker, listener=english_listener),
        )
        hebrew_speaker, hebrew_listener, hebrew_result = self._resolve_and_validate_lang(
            candidate_with_english,
            "he",
            english_speaker=english_speaker,
            english_listener=english_listener,
            english_result=english_result,
        )
        hebrew_result = _reconcile_hebrew_validation_from_english(candidate_with_english, english_result, hebrew_result)
        hebrew_speaker, hebrew_listener = self._repair_hebrew_roles(
            candidate_with_english,
            english_speaker=english_speaker,
            english_listener=english_listener,
            hebrew_speaker=hebrew_speaker,
            hebrew_listener=hebrew_listener,
        )
        resolved = replace(
            candidate_with_english,
            he=replace(candidate.he, speaker=hebrew_speaker, listener=hebrew_listener),
        )
        LOG.info(
            "Resolved+validated roles candidate=%s en=(%s -> %s %s) he=(%s -> %s %s)",
            candidate.id,
            resolved.en.speaker,
            resolved.en.listener,
            english_result,
            resolved.he.speaker,
            resolved.he.listener,
            hebrew_result,
        )
        return ResolvedCandidateValidation(candidate=resolved, english=english_result, hebrew=hebrew_result)

    def resolve_roles(self, candidate: CandidateItem) -> CandidateItem:
        return self._resolve_and_validate_candidate(candidate).candidate

    def restore_hebrew_roles(self, candidate: CandidateItem) -> CandidateItem:
        nearby_hebrew_context, _ = self._nearby_context_texts(candidate)
        context_texts = [candidate.he.quote, candidate.he.riddle, *candidate.raw_quote_source.he.values(), nearby_hebrew_context]
        restored_speaker = restore_hebrew_surface(candidate.he.speaker, context_texts)
        restored_listener = restore_hebrew_surface(candidate.he.listener, context_texts)
        restored = replace(
            candidate,
            he=replace(
                candidate.he,
                speaker=restored_speaker,
                listener=restored_listener,
            ),
        )
        LOG.info(
            "Restored Hebrew roles candidate=%s he=(%s -> %s)",
            candidate.id,
            restored.he.speaker,
            restored.he.listener,
        )
        return restored

    def _edit_riddle_for_lang(self, candidate: CandidateItem, lang: str, *, english_target_riddle: str) -> str:
        preferred_word_count = len(clean_text(english_target_riddle).split()) if english_target_riddle else None
        allowed_riddles = candidate_riddle_spans(
            candidate.he.quote if lang == "he" else candidate.en.quote,
            lang,
            preferred_word_count=preferred_word_count,
        )
        display_riddles, display_map = _display_riddle_candidates(allowed_riddles, lang)
        if not display_riddles:
            raise _drop(candidate, "riddle", "bad_riddle_edit", f"{lang} has no exact riddle substring candidates")
        payload = self.llm.chat_json(
            prompt_name=f"{lang}-riddle-edit",
            system_prompt=_riddle_edit_system_prompt(lang),
            user_prompt=_riddle_edit_user_prompt(
                candidate,
                lang,
                english_target_riddle=english_target_riddle,
                allowed_riddles=display_riddles,
            ),
            required_keys=("riddle",),
        )
        edited_choice = _llm_hebrew(str(payload["riddle"])) if lang == "he" else clean_text(str(payload["riddle"]))
        edited = display_map.get(edited_choice, "")
        quote = candidate.he.quote if lang == "he" else candidate.en.quote
        speaker = candidate.he.speaker if lang == "he" else candidate.en.speaker
        listener = candidate.he.listener if lang == "he" else candidate.en.listener
        original_riddle = candidate.he.riddle if lang == "he" else candidate.en.riddle
        if not edited:
            raise _drop(candidate, "riddle", "bad_riddle_edit", f"{lang} edited riddle is not one of the allowed exact substring candidates")
        if lang == "he":
            projected = _project_hebrew_substring_to_original(quote, edited)
            if projected is None:
                raise _drop(candidate, "riddle", "bad_riddle_edit", f"{lang} edited riddle is not an exact substring of the quote")
            edited = projected
        elif edited not in _clean_for_lang(quote, lang):
            raise _drop(candidate, "riddle", "bad_riddle_edit", f"{lang} edited riddle is not an exact substring of the quote")
        if _riddle_needs_edit(edited, speaker, listener, lang):
            raise _drop(candidate, "riddle", "bad_riddle_edit", f"{lang} edited riddle still includes a role, reporting clause, or excessive length")
        if _role_requires_exclusion(speaker, lang) and whole_word_occurs(edited, speaker, lang):
            raise _drop(candidate, "riddle", "bad_riddle_edit", f"{lang} edited riddle still includes the speaker name")
        if _role_requires_exclusion(listener, lang) and whole_word_occurs(edited, listener, lang):
            raise _drop(candidate, "riddle", "bad_riddle_edit", f"{lang} edited riddle still includes the listener name")
        if len(edited.split()) > len(_clean_for_lang(original_riddle, lang).split()):
            raise _drop(candidate, "riddle", "bad_riddle_edit", f"{lang} edited riddle is longer than the original")
        return edited

    def refine_riddles(self, candidate: CandidateItem) -> CandidateItem:
        english_riddle = candidate.en.riddle
        if _candidate_riddle_needs_edit(candidate, "en"):
            english_riddle = self._edit_riddle_for_lang(candidate, "en", english_target_riddle=candidate.en.riddle)

        candidate_with_english = replace(candidate, en=replace(candidate.en, riddle=english_riddle))

        hebrew_riddle = candidate.he.riddle
        if _candidate_riddle_needs_edit(candidate, "he") or english_riddle != candidate.en.riddle:
            hebrew_riddle = self._edit_riddle_for_lang(
                candidate_with_english,
                "he",
                english_target_riddle=english_riddle,
            )

        refined = replace(candidate_with_english, he=replace(candidate.he, riddle=hebrew_riddle))
        LOG.info(
            "Refined riddles candidate=%s en=%s he=%s",
            candidate.id,
            refined.en.riddle,
            refined.he.riddle,
        )
        return refined

    def validate_candidate(self, candidate: CandidateItem, lang: str) -> ValidationResult:
        english_result: ValidationResult | None = None
        if lang == "he":
            _english_speaker, _english_listener, english_result = self._resolve_and_validate_lang(candidate, "en")
        _speaker, _listener, result = self._resolve_and_validate_lang(
            candidate,
            lang,
            english_speaker=candidate.en.speaker if lang == "he" else None,
            english_listener=candidate.en.listener if lang == "he" else None,
            english_result=english_result,
        )
        if lang == "he":
            result = _reconcile_hebrew_validation_from_english(candidate, english_result, result)
        LOG.info("Validation result candidate=%s lang=%s result=%s", candidate.id, lang, result)
        return result

    def _candidate_bonus_words(self, candidate: CandidateItem) -> tuple[list[str], list[str]]:
        english_words = candidate_bonus_words(
            candidate.en.quote,
            candidate.en.riddle,
            "en",
            forbidden_texts=(candidate.en.speaker, candidate.en.listener),
        )
        hebrew_words = candidate_bonus_words(
            candidate.he.quote,
            candidate.he.riddle,
            "he",
            forbidden_texts=(candidate.he.speaker, candidate.he.listener),
        )
        return english_words, hebrew_words

    def _expand_candidate(self, candidate: CandidateItem, direction: str) -> CandidateItem | None:
        if direction == "before":
            start = candidate.source.quote_verse_start - 1
            end = candidate.source.quote_verse_end
        else:
            start = candidate.source.quote_verse_start
            end = candidate.source.quote_verse_end + 1
        if start < 1:
            return None
        range_quote = self.corpus.collect_range(
            candidate.source.book_code,
            candidate.source.chapter,
            start,
            end,
        )
        if range_quote is None:
            return None
        expanded = CandidateItem(
            id=candidate.id,
            source=replace(candidate.source, quote_verse_start=start, quote_verse_end=end),
            en=replace(candidate.en, quote=range_quote.en_quote),
            he=replace(candidate.he, quote=range_quote.he_quote),
            raw_quote_source=replace(candidate.raw_quote_source, en=range_quote.raw_quote_source["en"], he=range_quote.raw_quote_source["he"]),
            meta=candidate.meta,
            ref=replace(candidate.ref, start=start, end=end),
        )
        return self.restore_hebrew_roles(expanded)

    def prepare_context_candidate(self, candidate: CandidateItem) -> PreparedContextCandidate:
        if not _candidate_might_need_context_expansion(candidate):
            return PreparedContextCandidate(candidate=candidate, expansion="original")

        options: dict[str, CandidateItem] = {}
        added_verses: dict[str, tuple[str, str]] = {}
        before_candidate = self._expand_candidate(candidate, "before")
        if before_candidate is not None:
            options["before"] = before_candidate
            before_added = self.corpus.collect_range(
                candidate.source.book_code,
                candidate.source.chapter,
                candidate.source.quote_verse_start - 1,
                candidate.source.quote_verse_start - 1,
            )
            if before_added is not None and not before_added.missing:
                added_verses["before"] = (before_added.en_quote, before_added.he_quote)
        after_candidate = self._expand_candidate(candidate, "after")
        if after_candidate is not None:
            options["after"] = after_candidate
            after_added = self.corpus.collect_range(
                candidate.source.book_code,
                candidate.source.chapter,
                candidate.source.quote_verse_end + 1,
                candidate.source.quote_verse_end + 1,
            )
            if after_added is not None and not after_added.missing:
                added_verses["after"] = (after_added.en_quote, after_added.he_quote)
        if not options:
            return PreparedContextCandidate(candidate=candidate, expansion="original")
        if _candidate_missing_named_speaker(candidate) and "before" in options:
            LOG.info("Context quote expansion selected candidate=%s choice=before reason=missing_named_speaker", candidate.id)
            return PreparedContextCandidate(candidate=options["before"], expansion="before")

        base_user_prompt = _context_expansion_user_prompt(
            candidate,
            before_added_verse_en=added_verses["before"][0] if "before" in added_verses else None,
            before_added_verse_he=added_verses["before"][1] if "before" in added_verses else None,
            after_added_verse_en=added_verses["after"][0] if "after" in added_verses else None,
            after_added_verse_he=added_verses["after"][1] if "after" in added_verses else None,
        )
        payload = self.llm.chat_json(
            prompt_name="quote-context-expansion",
            system_prompt=_context_expansion_system_prompt(),
            user_prompt=base_user_prompt,
            required_keys=("choice", "reason"),
        )
        choice = _validated_expansion_choice(payload, set(options) | {"none"})
        if choice == "none":
            retry_payload = self.llm.chat_json(
                prompt_name="quote-context-expansion-retry",
                system_prompt=_context_expansion_system_prompt(retry=True),
                user_prompt=_context_expansion_retry_user_prompt(
                    candidate,
                    base_prompt=base_user_prompt,
                    previous_choice=choice,
                    previous_reason=str(payload.get("reason", "")),
                ),
                required_keys=("choice", "reason"),
            )
            choice = _validated_expansion_choice(retry_payload, set(options) | {"none"})
        if choice == "none" and len(options) > 1 and _context_roles_need_clarification(candidate):
            forced_payload = self.llm.chat_json(
                prompt_name="quote-context-expansion-forced",
                system_prompt=_forced_context_expansion_system_prompt(),
                user_prompt=_forced_context_expansion_user_prompt(candidate, base_prompt=base_user_prompt),
                required_keys=("choice", "reason"),
            )
            choice = _validated_expansion_choice(forced_payload, set(options))
        if choice in options:
            expanded = options[choice]
            _validate_required_text(expanded)
            LOG.info("Context quote expansion selected candidate=%s choice=%s", candidate.id, choice)
            return PreparedContextCandidate(candidate=expanded, expansion=choice)
        LOG.info("Context quote expansion kept original candidate=%s", candidate.id)
        return PreparedContextCandidate(candidate=candidate, expansion="original")

    def prepare_bonus_candidate(self, candidate: CandidateItem) -> PreparedBonusCandidate:
        english_words, hebrew_words = self._candidate_bonus_words(candidate)
        if english_words and hebrew_words:
            return PreparedBonusCandidate(candidate=candidate, en_words=english_words, he_words=hebrew_words, expansion="original")

        options: dict[str, PreparedBonusCandidate] = {}
        before_candidate = self._expand_candidate(candidate, "before")
        if before_candidate is not None:
            before_en_words, before_he_words = self._candidate_bonus_words(before_candidate)
            if before_en_words and before_he_words:
                options["before"] = PreparedBonusCandidate(
                    candidate=before_candidate,
                    en_words=before_en_words,
                    he_words=before_he_words,
                    expansion="before",
                )

        after_candidate = self._expand_candidate(candidate, "after")
        if after_candidate is not None:
            after_en_words, after_he_words = self._candidate_bonus_words(after_candidate)
            if after_en_words and after_he_words:
                options["after"] = PreparedBonusCandidate(
                    candidate=after_candidate,
                    en_words=after_en_words,
                    he_words=after_he_words,
                    expansion="after",
                )

        if not options:
            raise _drop(candidate, "bonus", "no_bonus_words", "No candidate bonus words remained after deterministic filtering or one-verse quote expansion")

        if len(options) == 1:
            selection = next(iter(options.values()))
            LOG.info("Bonus quote expansion auto-selected candidate=%s choice=%s", candidate.id, selection.expansion)
            return selection

        expansion_payload = self.llm.chat_json(
            prompt_name="bonus-quote-expansion",
            system_prompt=_quote_expansion_system_prompt(),
            user_prompt=_quote_expansion_user_prompt(
                candidate,
                before_quote=options["before"].candidate.en.quote if "before" in options else None,
                before_words=options["before"].en_words[:8] if "before" in options else [],
                after_quote=options["after"].candidate.en.quote if "after" in options else None,
                after_words=options["after"].en_words[:8] if "after" in options else [],
            ),
            required_keys=("choice",),
        )
        choice = _validated_expansion_choice(expansion_payload, set(options) | {"none"})
        if choice in options:
            LOG.info("Bonus quote expansion selected candidate=%s choice=%s", candidate.id, choice)
            return options[choice]
        raise _drop(candidate, "bonus", "no_bonus_words", "No candidate bonus words remained after deterministic filtering or one-verse quote expansion")

    def select_bonus(self, prepared: PreparedBonusCandidate) -> BonusSelection:
        candidate = prepared.candidate
        english_words = prepared.en_words
        hebrew_words = prepared.he_words

        english_payload = self.llm.chat_json(
            prompt_name="english-bonus-words",
            system_prompt=_bonus_words_system_prompt(),
            user_prompt=_bonus_words_user_prompt(candidate, english_words[:12]),
            required_keys=("words",),
        )
        picked_english = _validated_word_choices(english_payload, english_words[:12], "en")
        if not picked_english:
            raise _drop(candidate, "bonus", "bad_bonus_response", "LLM did not return a valid English bonus word")

        alignment_payload = self.llm.chat_json(
            prompt_name="bonus-word-alignment",
            system_prompt=_alignment_system_prompt(),
            user_prompt=_alignment_user_prompt(candidate, picked_english[:6], hebrew_words[:12]),
            required_keys=("pairs",),
        )
        aligned_pairs = _validated_pairs(alignment_payload, picked_english[:6], hebrew_words[:12])
        selection = self._first_pair_with_hint(candidate, aligned_pairs)
        if selection is not None:
            return selection

        fallback_pairs = [(en_word, he_word) for en_word in picked_english[:6] for he_word in hebrew_words[:12]]
        selection = self._first_pair_with_hint(candidate, fallback_pairs)
        if selection is not None:
            return selection

        if not aligned_pairs:
            raise _drop(
                candidate,
                "bonus",
                "bad_alignment_response",
                "LLM did not return a valid aligned EN/HE bonus pair and deterministic fallback found no valid hint pair",
            )

        raise _drop(candidate, "bonus", "no_bonus_hint_match", "No aligned external verse matched the proposed bonus pairs")

    def _bonus_pair_is_valid(self, candidate: CandidateItem, en_word: str, he_word: str) -> bool:
        en_role_words = forbidden_word_set(candidate.en.speaker, "en") | forbidden_word_set(candidate.en.listener, "en")
        he_role_words = forbidden_word_set(candidate.he.speaker, "he") | forbidden_word_set(candidate.he.listener, "he")
        if not whole_word_occurs(candidate.en.quote, en_word, "en"):
            return False
        if not whole_word_occurs(candidate.he.quote, he_word, "he"):
            return False
        if whole_word_occurs(candidate.en.riddle, en_word, "en"):
            return False
        if whole_word_occurs(candidate.he.riddle, he_word, "he"):
            return False
        if normalize_word(en_word, "en") in en_role_words:
            return False
        if normalize_word(he_word, "he") in he_role_words:
            return False
        return True

    def _first_pair_with_hint(
        self,
        candidate: CandidateItem,
        pairs: Iterable[tuple[str, str]],
    ) -> BonusSelection | None:
        for en_word, he_word in pairs:
            if not self._bonus_pair_is_valid(candidate, en_word, he_word):
                continue
            hint = self.corpus.find_first_aligned_hint(
                en_word,
                he_word,
                source_book_code=candidate.source.book_code,
                source_chapter=candidate.source.chapter,
                source_start=candidate.source.quote_verse_start,
                source_end=candidate.source.quote_verse_end,
            )
            if hint is None:
                continue
            LOG.info("Bonus selected candidate=%s en=%s he=%s", candidate.id, en_word, he_word)
            return BonusSelection(en_word=en_word, he_word=he_word, hint=hint)
        return None

    def build_final_item(self, candidate: CandidateItem, bonus: BonusSelection) -> FinalQuoteItem:
        return FinalQuoteItem(
            id=candidate.id,
            source=FinalSource(
                method="llm",
                book_code=candidate.source.book_code,
                book=candidate.source.book,
                book_he=candidate.source.book_he,
                chapter=candidate.source.chapter,
                quote_verse_start=candidate.source.quote_verse_start,
                quote_verse_end=candidate.source.quote_verse_end,
            ),
            en=FinalLangText(
                quote=candidate.en.quote,
                riddle=candidate.en.riddle,
                speaker=candidate.en.speaker,
                listener=candidate.en.listener,
                book=candidate.en.book,
                options=ChoicePools.empty(),
                bonus=bonus.en_word,
                bonus_hint=BonusHint(quote=bonus.hint.en_quote, source=bonus.hint.en_source),
            ),
            he=FinalLangText(
                quote=cleanup_hebrew_quote(candidate.he.quote),
                riddle=cleanup_hebrew_quote(candidate.he.riddle),
                speaker=cleanup_hebrew_quote(candidate.he.speaker),
                listener=cleanup_hebrew_quote(candidate.he.listener),
                book=candidate.he.book,
                options=ChoicePools.empty(),
                bonus=bonus.he_word,
                bonus_hint=BonusHint(quote=bonus.hint.he_quote, source=bonus.hint.he_source),
            ),
            raw_quote_source=candidate.raw_quote_source,
            ref=RefRange(
                chapter=candidate.ref.chapter,
                start=candidate.ref.start,
                end=candidate.ref.end,
            ),
            meta=FinalMeta(
                mode="llm",
                source="data-proc",
                template_item_id="",
                bonus_source="llm",
                bonus_hint_source="aligned-bible-search",
            ),
        )

    def process_candidate(self, candidate: CandidateItem) -> FinalQuoteItem:
        _validate_required_text(candidate)
        resolved_validation = self._resolve_and_validate_candidate(candidate)
        candidate = self.restore_hebrew_roles(resolved_validation.candidate)
        while _candidate_might_need_context_expansion(candidate):
            prepared_context = self.prepare_context_candidate(candidate)
            candidate = prepared_context.candidate
            if prepared_context.expansion == "original":
                break
            resolved_validation = self._resolve_and_validate_candidate(candidate)
            candidate = self.restore_hebrew_roles(resolved_validation.candidate)
        candidate = self.refine_riddles(candidate)
        candidate = self.restore_hebrew_roles(candidate)
        _validate_required_text(candidate)
        resolved_validation = self._resolve_and_validate_candidate(candidate)
        candidate = self.restore_hebrew_roles(resolved_validation.candidate)
        if not resolved_validation.english.passed:
            raise _drop(candidate, "semantic", "english_validation_failed", resolved_validation.english.reason)
        if not resolved_validation.hebrew.passed:
            raise _drop(candidate, "semantic", "hebrew_validation_failed", resolved_validation.hebrew.reason)

        prepared_bonus = self.prepare_bonus_candidate(candidate)
        prepared_bonus = replace(prepared_bonus, candidate=self.restore_hebrew_roles(prepared_bonus.candidate))
        bonus = self.select_bonus(prepared_bonus)
        return self.build_final_item(prepared_bonus.candidate, bonus)


def build_chapter_payloads(items: Iterable[FinalQuoteItem]) -> list[ChapterPayload]:
    grouped: dict[tuple[str, int], list[FinalQuoteItem]] = {}
    for item in items:
        grouped.setdefault((item.source.book_code, item.source.chapter), []).append(item)

    payloads: list[ChapterPayload] = []
    for (_, _), grouped_items in sorted(
        grouped.items(),
        key=lambda entry: (bible_sources.BOOK_ORDER.get(entry[0][0], 999), entry[0][1]),
    ):
        first = grouped_items[0]
        payloads.append(
            ChapterPayload(
                book_code=first.source.book_code,
                book=first.source.book,
                book_he=first.source.book_he,
                chapter=first.source.chapter,
                mode="llm",
                items=sorted(grouped_items, key=lambda item: (item.ref.start, item.ref.end, item.id)),
            )
        )
    return payloads


def _chapter_payload_for_items(items: list[FinalQuoteItem]) -> ChapterPayload:
    first = items[0]
    return ChapterPayload(
        book_code=first.source.book_code,
        book=first.source.book,
        book_he=first.source.book_he,
        chapter=first.source.chapter,
        mode="llm",
        items=sorted(items, key=lambda item: (item.ref.start, item.ref.end, item.id)),
    )


def write_chapter_payloads(payloads: Iterable[ChapterPayload], out_dir: Path) -> list[Path]:
    written: list[Path] = []
    for payload in payloads:
        out_path = chapter_output_path(out_dir, payload)
        write_json(out_path, payload.to_dict())
        written.append(out_path)
    return written


def run_pipeline(
    *,
    candidates_path: Path,
    out_dir: Path,
    issues_log: Path | None,
    llm: JsonChatModel,
    english_xml: Path,
    hebrew_zip: Path,
    book_filter: str | None = None,
    chapter_filter: int | None = None,
    limit: int | None = None,
    resume: bool = True,
) -> tuple[list[ChapterPayload], list[DropRecord]]:
    canonical_book_filter = _canonical_book_filter(book_filter)
    candidates = [
        candidate
        for candidate in iter_candidate_items(candidates_path)
        if (not canonical_book_filter or candidate.source.book_code == canonical_book_filter)
        and (chapter_filter is None or candidate.source.chapter == chapter_filter)
    ]
    resume_point = _find_resume_point_for_candidates(
        candidates,
        out_dir=out_dir,
        issues_log=issues_log,
        book_filter=canonical_book_filter,
        chapter_filter=chapter_filter,
    ) if resume else None

    seen_ids: set[str] = set()
    seen_output_keys: dict[tuple[str, int, str, str], FinalQuoteItem] = {}
    kept: list[FinalQuoteItem] = []
    dropped: list[DropRecord] = []
    grouped_kept: dict[tuple[str, int], list[FinalQuoteItem]] = {}
    processed = 0

    out_dir.mkdir(parents=True, exist_ok=True)
    if issues_log is not None:
        issues_log.parent.mkdir(parents=True, exist_ok=True)
        _trim_issues_log(
            issues_log,
            resume_point=resume_point if resume else None,
            book_filter=canonical_book_filter,
            chapter_filter=chapter_filter,
        )
    _drop_outputs_from_resume_point(
        out_dir,
        resume_point=resume_point,
        book_filter=canonical_book_filter,
        chapter_filter=chapter_filter,
    )

    corpus = BibleCorpus(english_xml=english_xml, hebrew_zip=hebrew_zip)
    pipeline = CandidatePipeline(corpus=corpus, llm=llm)
    for candidate in tqdm(candidates, desc="build-quotes"):
        if _is_before_resume_point(candidate, resume_point):
            continue
        if candidate.id in seen_ids:
            record = DropRecord(
                candidate_id=candidate.id,
                book_code=candidate.source.book_code,
                chapter=candidate.source.chapter,
                start=candidate.source.quote_verse_start,
                end=candidate.source.quote_verse_end,
                stage="dedupe",
                reason="duplicate_candidate_id",
                detail="A previous candidate with the same id was already processed",
            )
            dropped.append(record)
            if issues_log is not None:
                append_jsonl(issues_log, [record.to_dict()])
            continue
        seen_ids.add(candidate.id)
        if limit is not None and processed >= limit:
            break
        processed += 1
        try:
            item = pipeline.process_candidate(candidate)
            output_key = _final_item_dedupe_key(item)
            if output_key in seen_output_keys:
                existing = seen_output_keys[output_key]
                record = DropRecord(
                    candidate_id=item.id,
                    book_code=item.source.book_code,
                    chapter=item.source.chapter,
                    start=item.source.quote_verse_start,
                    end=item.source.quote_verse_end,
                    stage="dedupe",
                    reason="duplicate_riddle_turn",
                    detail=f"Same chapter riddle turn already kept as {existing.id}",
                )
                dropped.append(record)
                if issues_log is not None:
                    append_jsonl(issues_log, [record.to_dict()])
                continue
            seen_output_keys[output_key] = item
            kept.append(item)
            key = (item.source.book_code, item.source.chapter)
            grouped_kept.setdefault(key, []).append(item)
            chapter_payload = _chapter_payload_for_items(grouped_kept[key])
            write_json(chapter_output_path(out_dir, chapter_payload), chapter_payload.to_dict())
        except CandidateDropError as exc:
            dropped.append(exc.record)
            if issues_log is not None:
                append_jsonl(issues_log, [exc.record.to_dict()])

    payloads = build_chapter_payloads(kept)
    return payloads, dropped


def _stable_quote_eval_sample(candidates: list[CandidateItem], sample_size: int) -> list[CandidateItem]:
    per_book: dict[str, list[CandidateItem]] = {}
    for candidate in sorted(
        candidates,
        key=lambda value: (
            bible_sources.BOOK_ORDER.get(value.source.book_code, 999),
            value.source.chapter,
            value.ref.start,
            value.ref.end,
            value.id,
        ),
    ):
        per_book.setdefault(candidate.source.book_code, []).append(candidate)
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


def build_quotes_eval_pack(
    *,
    candidates_path: Path,
    out_dir: Path,
    llm: JsonChatModel,
    english_xml: Path,
    hebrew_zip: Path,
    sample_size: int,
    seed: int | None,
    book_filter: str | None = None,
    chapter_filter: int | None = None,
) -> dict:
    canonical_book_filter = _canonical_book_filter(book_filter)
    candidates = [
        candidate
        for candidate in iter_candidate_items(candidates_path)
        if (not canonical_book_filter or candidate.source.book_code == canonical_book_filter)
        and (chapter_filter is None or candidate.source.chapter == chapter_filter)
    ]
    sample_candidates = _stable_quote_eval_sample(candidates, sample_size)
    pipeline = CandidatePipeline(corpus=BibleCorpus(english_xml=english_xml, hebrew_zip=hebrew_zip), llm=llm)

    eval_items: list[dict] = []
    for candidate in tqdm(sample_candidates, desc="build-quotes-eval"):
        try:
            final_item = pipeline.process_candidate(candidate)
        except CandidateDropError as exc:
            eval_items.append(
                {
                    "id": candidate.id,
                    "book_code": candidate.source.book_code,
                    "book": candidate.source.book,
                    "chapter": candidate.source.chapter,
                    "candidate": candidate.to_dict(),
                    "status": "dropped",
                    "drop": exc.record.to_dict(),
                }
            )
            continue
        eval_items.append(
            {
                "id": candidate.id,
                "book_code": candidate.source.book_code,
                "book": candidate.source.book,
                "chapter": candidate.source.chapter,
                "candidate": candidate.to_dict(),
                "status": "kept",
                "final": final_item.to_dict(),
            }
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "seed": seed,
        "sample_size": len(eval_items),
        "items": eval_items,
    }
    write_json_atomic(out_dir / "eval_items.json", payload)
    lines = ["# Quotes Eval", ""]
    if seed is not None:
        lines.extend([f"- Seed: `{seed}`", ""])
    lines.extend([f"- Items: `{len(eval_items)}`", ""])
    for item in eval_items:
        lines.extend(
            [
                f"## {item['id']}",
                f"- Ref: `{item['book']} {item['chapter']}:{item['candidate']['ref']['start']}-{item['candidate']['ref']['end']}`",
                f"- Status: `{item['status']}`",
                f"- EN candidate riddle: {item['candidate']['en']['riddle']}",
                f"- HE candidate riddle: {item['candidate']['he']['riddle']}",
            ]
        )
        if item["status"] == "kept":
            lines.extend(
                [
                    f"- EN final riddle: {item['final']['en']['riddle']}",
                    f"- EN speaker/listener: `{item['final']['en']['speaker']}` / `{item['final']['en']['listener']}`",
                    f"- Bonus: `{item['final']['en']['bonus']}`",
                ]
            )
        else:
            lines.append(f"- Drop: `{item['drop']['stage']} / {item['drop']['reason']}`")
        lines.append("")
    (out_dir / "review.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return payload


def _build_llm_client(model: str, fallback_model: str | None, seed: int | None = None):
    from data_proc.llm import OllamaJsonClient

    normalized_fallback_model = (fallback_model or "").strip() or None
    options = {"seed": seed} if seed is not None else None
    return OllamaJsonClient(model=model, fallback_model=normalized_fallback_model, request_options=options)


@click.command("build-quotes")
@click.option("--candidates", "candidates_path", type=click.Path(path_type=Path, exists=True, dir_okay=False), required=True)
@click.option("--out-dir", type=click.Path(path_type=Path, file_okay=False), required=True)
@click.option("--issues-log", type=click.Path(path_type=Path, dir_okay=False), default=None)
@click.option("--model", default="gemma4:26b", show_default=True)
@click.option(
    "--fallback-model",
    default="gemma4:26b",
    show_default=True,
    help="Secondary model used after repeated JSON parse/schema failures. Pass an empty string to disable fallback.",
)
@click.option("--english-xml", type=click.Path(path_type=Path, exists=True, dir_okay=False), default=DEFAULT_ENGLISH_XML, show_default=True)
@click.option("--hebrew-zip", type=click.Path(path_type=Path, exists=True, dir_okay=False), default=DEFAULT_HEBREW_ZIP, show_default=True)
@click.option("--book", "book_filter", default=None)
@click.option("--chapter", "chapter_filter", type=int, default=None)
@click.option("--limit", type=int, default=None)
@click.option("--seed", type=int, default=None)
@click.option("--resume/--no-resume", default=True, show_default=True)
@click.option("--quiet-llm", is_flag=True, default=False)
def build_quotes_command(
    candidates_path: Path,
    out_dir: Path,
    issues_log: Path | None,
    model: str,
    fallback_model: str | None,
    english_xml: Path,
    hebrew_zip: Path,
    book_filter: str | None,
    chapter_filter: int | None,
    limit: int | None,
    seed: int | None,
    resume: bool,
    quiet_llm: bool,
) -> None:
    logging.basicConfig(level=logging.WARNING if quiet_llm else logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    payloads, dropped = run_pipeline(
        candidates_path=candidates_path,
        out_dir=out_dir,
        issues_log=issues_log,
        llm=_build_llm_client(model, fallback_model, seed),
        english_xml=english_xml,
        hebrew_zip=hebrew_zip,
        book_filter=book_filter,
        chapter_filter=chapter_filter,
        limit=limit,
        resume=resume,
    )
    click.echo(f"Wrote {sum(len(payload.items) for payload in payloads)} items across {len(payloads)} chapter files; dropped {len(dropped)} candidates.")


@click.command("build-quotes-eval")
@click.option("--candidates", "candidates_path", type=click.Path(path_type=Path, exists=True, dir_okay=False), default=Path("data/processed/candidates.jsonl"), show_default=True)
@click.option("--out-dir", type=click.Path(path_type=Path, file_okay=False), default=Path("data/processed/quotes_eval"), show_default=True)
@click.option("--model", default="gemma4:26b", show_default=True)
@click.option("--fallback-model", default="", show_default=False)
@click.option("--english-xml", type=click.Path(path_type=Path, exists=True, dir_okay=False), default=DEFAULT_ENGLISH_XML, show_default=True)
@click.option("--hebrew-zip", type=click.Path(path_type=Path, exists=True, dir_okay=False), default=DEFAULT_HEBREW_ZIP, show_default=True)
@click.option("--sample-size", type=int, default=24, show_default=True)
@click.option("--seed", type=int, default=32988, show_default=True)
@click.option("--book", "book_filter", default=None)
@click.option("--chapter", "chapter_filter", type=int, default=None)
@click.option("--quiet-llm", is_flag=True, default=False)
def build_quotes_eval_command(
    candidates_path: Path,
    out_dir: Path,
    model: str,
    fallback_model: str | None,
    english_xml: Path,
    hebrew_zip: Path,
    sample_size: int,
    seed: int,
    book_filter: str | None,
    chapter_filter: int | None,
    quiet_llm: bool,
) -> None:
    logging.basicConfig(level=logging.WARNING if quiet_llm else logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    payload = build_quotes_eval_pack(
        candidates_path=candidates_path,
        out_dir=out_dir,
        llm=_build_llm_client(model, fallback_model, seed),
        english_xml=english_xml,
        hebrew_zip=hebrew_zip,
        sample_size=sample_size,
        seed=seed,
        book_filter=book_filter,
        chapter_filter=chapter_filter,
    )
    click.echo(f"Wrote quotes eval pack with {payload['sample_size']} items to {out_dir}.")
