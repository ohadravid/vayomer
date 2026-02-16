from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, Dict, Iterator, Tuple

import pytest

ROOT = Path(__file__).resolve().parents[1]

from data_processing import bible_sources, bible_tandem, text_cleanup

DATA_QUOTES_DIR = ROOT / "data" / "quotes"


@dataclass(frozen=True)
class QuoteCase:
    file_path: Path
    item_id: str
    chapter_book_code: str
    chapter_number: int
    item: Dict


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


def _iter_quote_cases() -> Iterator[QuoteCase]:
    for path in sorted(DATA_QUOTES_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue

        chapter_book_code = _sanitize_str(payload.get("book_code"))
        chapter_number = _sanitize_int(payload.get("chapter"), 0)
        items = payload.get("items", [])
        if not isinstance(items, list):
            continue

        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            item_id = _sanitize_str(item.get("id")) or f"{path.stem}-item-{idx}"
            yield QuoteCase(
                file_path=path,
                item_id=item_id,
                chapter_book_code=chapter_book_code,
                chapter_number=chapter_number,
                item=item,
            )


QUOTE_CASES: Tuple[QuoteCase, ...] = tuple(_iter_quote_cases())


def _build_book_code_lookup() -> Dict[str, str]:
    lookup: Dict[str, str] = {}
    for code, en_name, he_name in bible_sources.OT_BOOKS:
        lookup[code.casefold()] = code
        lookup[en_name.casefold()] = code
        lookup[he_name.casefold()] = code
    for en_name, code in bible_sources.BOOK_NAME_TO_CODE.items():
        lookup[en_name.casefold()] = code
    return lookup


def _resolve_book_code(book: str, lookup: Dict[str, str]) -> str:
    cleaned = _sanitize_str(book)
    if not cleaned:
        return ""
    code = lookup.get(cleaned.casefold(), "")
    if code:
        return code
    upper = cleaned.upper()
    if upper in bible_sources.BOOK_CODE_TO_EN:
        return upper
    return ""


def _normalize_for_contains(text: str, lang: str) -> str:
    if lang == "he":
        return bible_sources.normalize_hebrew_for_compare(text)
    return bible_sources.normalize_english_for_compare(text)


def _contains_text(haystack: str, needle: str, lang: str) -> bool:
    cleaned_haystack = _sanitize_str(haystack)
    cleaned_needle = _sanitize_str(needle)
    if not cleaned_haystack or not cleaned_needle:
        return False
    if cleaned_needle in cleaned_haystack:
        return True
    return _normalize_for_contains(cleaned_needle, lang) in _normalize_for_contains(cleaned_haystack, lang)


def _bible_verse_text(
    *,
    tandem_bible: bible_tandem.TandemBible,
    lang: str,
    book_code: str,
    chapter: int,
    verse: int,
) -> str:
    if lang == "en":
        return text_cleanup.clean_text(tandem_bible.english_map.get((book_code, chapter, verse), ""))
    return text_cleanup.clean_text(tandem_bible.hebrew_map.get((book_code, chapter, verse), ""))


@pytest.fixture(scope="session")
def tandem_bible() -> bible_tandem.TandemBible:
    english_xml = ROOT / bible_sources.DEFAULT_ENGLISH_COLLECTION
    hebrew_zip = ROOT / bible_sources.DEFAULT_HEBREW_ZIP
    assert english_xml.is_file(), f"Missing English Bible XML: {english_xml}"
    assert hebrew_zip.is_file(), f"Missing Hebrew Bible zip: {hebrew_zip}"
    return bible_tandem.TandemBible.load(english_xml=english_xml, hebrew_zip=hebrew_zip)


@pytest.fixture(scope="session")
def collect_range(
    tandem_bible: bible_tandem.TandemBible,
) -> Callable[[str, int, int, int], bible_tandem.RangeQuote]:
    @lru_cache(maxsize=4096)
    def _collect(book_code: str, chapter: int, start: int, end: int) -> bible_tandem.RangeQuote:
        return tandem_bible.collect_range(book_code=book_code, chapter=chapter, start=start, end=end)

    return _collect


@pytest.fixture(scope="session")
def book_code_lookup() -> Dict[str, str]:
    return _build_book_code_lookup()


@pytest.fixture(params=QUOTE_CASES, ids=lambda case: case.item_id)
def quote_case(request: pytest.FixtureRequest) -> QuoteCase:
    return request.param


def test_quote_items_exist() -> None:
    assert QUOTE_CASES, f"No quote items found in {DATA_QUOTES_DIR}"


def test_quote_item_integrity(
    quote_case: QuoteCase,
    tandem_bible: bible_tandem.TandemBible,
    collect_range: Callable[[str, int, int, int], bible_tandem.RangeQuote],
    book_code_lookup: Dict[str, str],
) -> None:
    item = quote_case.item
    source = item.get("source", {})
    assert isinstance(source, dict), f"{quote_case.item_id}: missing source object"

    source_book_code = _resolve_book_code(
        _sanitize_str(source.get("book_code")) or quote_case.chapter_book_code,
        book_code_lookup,
    )
    source_chapter = _sanitize_int(source.get("chapter"), quote_case.chapter_number)
    source_start = _sanitize_int(source.get("quote_verse_start"), 0)
    source_end = _sanitize_int(source.get("quote_verse_end"), 0)

    assert source_book_code, f"{quote_case.item_id}: source.book_code is missing/invalid"
    assert source_chapter > 0, f"{quote_case.item_id}: source.chapter must be > 0"
    assert source_start > 0, f"{quote_case.item_id}: source.quote_verse_start must be > 0"
    assert source_end >= source_start, f"{quote_case.item_id}: invalid source verse range {source_start}-{source_end}"

    range_quote = collect_range(source_book_code, source_chapter, source_start, source_end)
    assert not range_quote.missing, (
        f"{quote_case.item_id}: source range missing verses in Bible data: {range_quote.missing}"
    )

    raw_quote_source = item.get("raw_quote_source", {})
    assert isinstance(raw_quote_source, dict), f"{quote_case.item_id}: missing raw_quote_source object"

    for lang in ("en", "he"):
        section = item.get(lang, {})
        assert isinstance(section, dict), f"{quote_case.item_id}:{lang}: missing language section"

        quote = _sanitize_str(section.get("quote"))
        riddle = _sanitize_str(section.get("riddle"))
        assert quote, f"{quote_case.item_id}:{lang}: quote is empty"
        assert riddle, f"{quote_case.item_id}:{lang}: riddle is empty"

        # 1) Riddle must appear in the full quote.
        assert _contains_text(quote, riddle, lang), (
            f"{quote_case.item_id}:{lang}: riddle not contained in quote"
        )

        raw_by_verse = raw_quote_source.get(lang, {})
        assert isinstance(raw_by_verse, dict), (
            f"{quote_case.item_id}:{lang}: raw_quote_source.{lang} missing or invalid"
        )

        source_verse_texts = []
        for verse in range(source_start, source_end + 1):
            verse_key = str(verse)
            assert verse_key in raw_by_verse, (
                f"{quote_case.item_id}:{lang}: raw_quote_source missing verse {verse}"
            )

            raw_verse = _sanitize_str(raw_by_verse.get(verse_key))
            assert raw_verse, f"{quote_case.item_id}:{lang}: raw source verse {verse} is empty"

            expected_verse = _bible_verse_text(
                tandem_bible=tandem_bible,
                lang=lang,
                book_code=source_book_code,
                chapter=source_chapter,
                verse=verse,
            )
            assert expected_verse, (
                f"{quote_case.item_id}:{lang}: source points to missing verse "
                f"{source_book_code} {source_chapter}:{verse}"
            )
            assert raw_verse == expected_verse, (
                f"{quote_case.item_id}:{lang}: raw source verse mismatch at "
                f"{source_book_code} {source_chapter}:{verse}"
            )

            source_verse_texts.append(raw_verse)

        # 2) Full quote must be contained in source verses; source verses must match Bible text.
        source_joined = text_cleanup.clean_text(" ".join(source_verse_texts))
        if lang == "he":
            source_joined = text_cleanup.cleanup_hebrew_quote(source_joined)
        assert _contains_text(source_joined, quote, lang), (
            f"{quote_case.item_id}:{lang}: quote not contained in raw_quote_source verses"
        )

        source_range_quote = range_quote.en_quote if lang == "en" else range_quote.he_quote
        assert _contains_text(source_range_quote, quote, lang), (
            f"{quote_case.item_id}:{lang}: quote not contained in Bible source range"
        )

        bonus = _sanitize_str(section.get("bonus"))
        # 3) Bonus word must appear in the full quote.
        assert bonus, f"{quote_case.item_id}:{lang}: bonus is missing"
        assert _contains_text(quote, bonus, lang), (
            f"{quote_case.item_id}:{lang}: bonus not contained in quote"
        )

        hint = section.get("bonus_hint")
        if hint is None:
            continue

        assert isinstance(hint, dict), f"{quote_case.item_id}:{lang}: bonus_hint must be an object or null"
        hint_quote = _sanitize_str(hint.get("quote"))
        assert hint_quote, f"{quote_case.item_id}:{lang}: bonus_hint.quote is empty"

        # 4) Bonus word must appear in hint quote (if hint exists).
        assert _contains_text(hint_quote, bonus, lang), (
            f"{quote_case.item_id}:{lang}: bonus not contained in bonus_hint.quote"
        )

        hint_source = hint.get("source", {})
        assert isinstance(hint_source, dict), f"{quote_case.item_id}:{lang}: bonus_hint.source is missing/invalid"

        hint_book_code = _resolve_book_code(_sanitize_str(hint_source.get("book")), book_code_lookup)
        hint_chapter = _sanitize_int(hint_source.get("chapter"), 0)
        hint_start = _sanitize_int(hint_source.get("start"), 0)
        hint_end = _sanitize_int(hint_source.get("end"), 0)

        assert hint_book_code, f"{quote_case.item_id}:{lang}: bonus_hint.source.book is missing/invalid"
        assert hint_chapter > 0, f"{quote_case.item_id}:{lang}: bonus_hint.source.chapter must be > 0"
        assert hint_start > 0, f"{quote_case.item_id}:{lang}: bonus_hint.source.start must be > 0"
        assert hint_end >= hint_start, (
            f"{quote_case.item_id}:{lang}: invalid bonus_hint source range {hint_start}-{hint_end}"
        )

        hint_range = collect_range(hint_book_code, hint_chapter, hint_start, hint_end)
        assert not hint_range.missing, (
            f"{quote_case.item_id}:{lang}: bonus_hint source range missing verses {hint_range.missing}"
        )

        hint_source_quote = hint_range.en_quote if lang == "en" else hint_range.he_quote
        # 5) Hint quote must exist in the Bible location pointed to by bonus_hint.source.
        assert _contains_text(hint_source_quote, hint_quote, lang), (
            f"{quote_case.item_id}:{lang}: bonus_hint.quote not found in pointed Bible source"
        )
