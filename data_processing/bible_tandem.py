#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Tuple

try:
    from data_processing import bible_sources, text_cleanup
except ModuleNotFoundError:
    import bible_sources  # type: ignore[no-redef]
    import text_cleanup  # type: ignore[no-redef]

# Re-export the most-used mechanical helpers for compatibility.
clean_text = text_cleanup.clean_text
cleanup_hebrew_quote = text_cleanup.cleanup_hebrew_quote


@dataclass(frozen=True)
class VerseTandem:
    book_code: str
    book_en: str
    book_he: str
    chapter: int
    verse: int
    en_raw: str
    he_raw: str
    he_clean: str


@dataclass(frozen=True)
class RangeQuote:
    book_code: str
    book_en: str
    book_he: str
    chapter: int
    start: int
    end: int
    en_quote: str
    he_quote: str
    raw_quote_source: Dict[str, Dict[str, str]]
    missing: List[int]


class TandemBible:
    """Iterator over English+Hebrew verses aligned by (book, chapter, verse)."""

    def __init__(
        self,
        english_map: bible_sources.VerseMap,
        hebrew_map: bible_sources.VerseMap,
    ) -> None:
        self.english_map = english_map
        self.hebrew_map = hebrew_map

        by_chapter: Dict[Tuple[str, int], List[int]] = {}
        for (code, chapter, verse), en_text in english_map.items():
            if not en_text:
                continue
            he_text = hebrew_map.get((code, chapter, verse), "")
            if not he_text:
                continue
            by_chapter.setdefault((code, chapter), []).append(verse)

        self._by_chapter = {
            key: sorted(set(verses))
            for key, verses in by_chapter.items()
        }

    @classmethod
    def load(
        cls,
        english_xml: Path,
        hebrew_zip: Path,
    ) -> "TandemBible":
        english_map = bible_sources.load_english_verse_map(english_xml)
        hebrew_map = bible_sources.load_tanach_zip_verse_map(hebrew_zip)
        return cls(english_map=english_map, hebrew_map=hebrew_map)

    def iter_books(self, book_filter: str = "") -> Iterator[Tuple[str, str, str]]:
        key = book_filter.strip().casefold()
        for code, en_name, he_name in bible_sources.OT_BOOKS:
            if key and key not in {code.casefold(), en_name.casefold(), he_name.casefold()}:
                continue
            has_any = any(ch_code == code for ch_code, _ in self._by_chapter.keys())
            if has_any:
                yield code, en_name, he_name

    def iter_chapters(self, book_filter: str = "") -> Iterator[Tuple[str, int]]:
        allowed_codes = {code for code, _, _ in self.iter_books(book_filter=book_filter)}
        for code, chapter in sorted(
            self._by_chapter.keys(),
            key=lambda c: (bible_sources.BOOK_ORDER.get(c[0], 999), c[1]),
        ):
            if allowed_codes and code not in allowed_codes:
                continue
            yield code, chapter

    def iter_verses(self, book_code: str, chapter: int) -> Iterator[VerseTandem]:
        verse_nums = self._by_chapter.get((book_code, chapter), [])
        book_en = bible_sources.BOOK_CODE_TO_EN.get(book_code, book_code)
        book_he = bible_sources.BOOK_CODE_TO_HE.get(book_code, "")

        for verse in verse_nums:
            en_raw = text_cleanup.clean_text(self.english_map.get((book_code, chapter, verse), ""))
            he_raw = text_cleanup.clean_text(self.hebrew_map.get((book_code, chapter, verse), ""))
            if not en_raw or not he_raw:
                continue

            yield VerseTandem(
                book_code=book_code,
                book_en=book_en,
                book_he=book_he,
                chapter=chapter,
                verse=verse,
                en_raw=en_raw,
                he_raw=he_raw,
                he_clean=text_cleanup.cleanup_hebrew_quote(he_raw),
            )

    def collect_range(self, book_code: str, chapter: int, start: int, end: int) -> RangeQuote:
        start, end = sorted((start, end))
        missing: List[int] = []
        en_parts: List[str] = []
        he_parts: List[str] = []
        raw_en: Dict[str, str] = {}
        raw_he: Dict[str, str] = {}

        for verse in range(start, end + 1):
            en_raw = text_cleanup.clean_text(self.english_map.get((book_code, chapter, verse), ""))
            he_raw = text_cleanup.clean_text(self.hebrew_map.get((book_code, chapter, verse), ""))
            if not en_raw or not he_raw:
                missing.append(verse)
                continue
            raw_en[str(verse)] = en_raw
            raw_he[str(verse)] = he_raw
            en_parts.append(en_raw)
            he_parts.append(text_cleanup.cleanup_hebrew_quote(he_raw))

        return RangeQuote(
            book_code=book_code,
            book_en=bible_sources.BOOK_CODE_TO_EN.get(book_code, book_code),
            book_he=bible_sources.BOOK_CODE_TO_HE.get(book_code, ""),
            chapter=chapter,
            start=start,
            end=end,
            en_quote=text_cleanup.clean_text(" ".join(en_parts)),
            he_quote=text_cleanup.clean_text(" ".join(he_parts)),
            raw_quote_source={"en": raw_en, "he": raw_he},
            missing=missing,
        )

    def iter_windows(
        self,
        book_code: str,
        chapter: int,
        max_window: int = 5,
        min_window: int = 1,
    ) -> Iterator[RangeQuote]:
        verse_nums = self._by_chapter.get((book_code, chapter), [])
        if not verse_nums:
            return

        verse_set = set(verse_nums)
        for start in verse_nums:
            for end in range(start + min_window - 1, start + max_window):
                if end not in verse_set:
                    break
                if any(v not in verse_set for v in range(start, end + 1)):
                    continue
                yield self.collect_range(book_code=book_code, chapter=chapter, start=start, end=end)
