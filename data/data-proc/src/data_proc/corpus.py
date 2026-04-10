from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from data_proc.schema import HintSourceRef
from data_proc.utils import bible_sources
from data_proc.utils.bible_tandem import TandemBible
from data_proc.utils.text_cleanup import normalize_word, word_set


@dataclass(frozen=True)
class VerseRecord:
    book_code: str
    book: str
    book_he: str
    chapter: int
    verse: int
    en_quote: str
    he_quote: str

    @property
    def ref_key(self) -> tuple[str, int, int]:
        return self.book_code, self.chapter, self.verse


@dataclass(frozen=True)
class HintMatch:
    en_quote: str
    he_quote: str
    en_source: HintSourceRef
    he_source: HintSourceRef


class BibleCorpus:
    def __init__(self, english_xml: Path, hebrew_zip: Path) -> None:
        self.tandem = TandemBible.load(english_xml=english_xml, hebrew_zip=hebrew_zip)
        self._verses: list[VerseRecord] = []
        self._en_index: dict[str, list[VerseRecord]] = {}
        self._he_index: dict[str, list[VerseRecord]] = {}
        self._build_indexes()

    def _build_indexes(self) -> None:
        for book_code, _, _ in bible_sources.OT_BOOKS:
            for chapter_code, chapter in self.tandem.iter_chapters(book_filter=book_code):
                if chapter_code != book_code:
                    continue
                for verse in self.tandem.iter_verses(book_code, chapter):
                    record = VerseRecord(
                        book_code=verse.book_code,
                        book=verse.book_en,
                        book_he=verse.book_he,
                        chapter=verse.chapter,
                        verse=verse.verse,
                        en_quote=verse.en_raw,
                        he_quote=verse.he_clean,
                    )
                    self._verses.append(record)
                    for word in word_set(record.en_quote, "en"):
                        self._en_index.setdefault(word, []).append(record)
                    for word in word_set(record.he_quote, "he"):
                        self._he_index.setdefault(word, []).append(record)

    def word_occurrence_count(self, word: str, lang: str) -> int:
        normalized = normalize_word(word, lang)
        if not normalized:
            return 0
        index = self._he_index if lang == "he" else self._en_index
        return len(index.get(normalized, []))

    def collect_range(self, book_code: str, chapter: int, start: int, end: int):
        range_quote = self.tandem.collect_range(book_code=book_code, chapter=chapter, start=start, end=end)
        if range_quote.missing:
            return None
        return range_quote

    def find_first_aligned_hint(
        self,
        en_word: str,
        he_word: str,
        *,
        source_book_code: str,
        source_chapter: int,
        source_start: int,
        source_end: int,
    ) -> HintMatch | None:
        normalized_en = normalize_word(en_word, "en")
        normalized_he = normalize_word(he_word, "he")
        if not normalized_en or not normalized_he:
            return None

        en_records = self._en_index.get(normalized_en, [])
        he_records_by_ref = {
            record.ref_key: record
            for record in self._he_index.get(normalized_he, [])
        }

        for record in en_records:
            if record.book_code == source_book_code and record.chapter == source_chapter:
                continue
            he_record = he_records_by_ref.get(record.ref_key)
            if he_record is None:
                continue
            return HintMatch(
                en_quote=record.en_quote,
                he_quote=he_record.he_quote,
                en_source=HintSourceRef(
                    book=record.book,
                    chapter=record.chapter,
                    start=record.verse,
                    end=record.verse,
                ),
                he_source=HintSourceRef(
                    book=record.book_he,
                    chapter=record.chapter,
                    start=record.verse,
                    end=record.verse,
                ),
            )
        return None
