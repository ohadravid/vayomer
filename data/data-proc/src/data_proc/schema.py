from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from data_proc.utils import bible_sources


@dataclass(frozen=True)
class CandidateSource:
    book_code: str
    book: str
    book_he: str
    chapter: int
    quote_verse_start: int
    quote_verse_end: int

    @classmethod
    def from_dict(cls, data: dict) -> "CandidateSource":
        return cls(
            book_code=data["book_code"],
            book=data["book"],
            book_he=data["book_he"],
            chapter=data["chapter"],
            quote_verse_start=data["quote_verse_start"],
            quote_verse_end=data["quote_verse_end"],
        )

    def to_dict(self) -> dict:
        return {
            "book_code": self.book_code,
            "book": self.book,
            "book_he": self.book_he,
            "chapter": self.chapter,
            "quote_verse_start": self.quote_verse_start,
            "quote_verse_end": self.quote_verse_end,
        }


@dataclass(frozen=True)
class CandidateLangText:
    quote: str
    riddle: str
    speaker: str
    listener: str
    book: str

    @classmethod
    def from_dict(cls, data: dict) -> "CandidateLangText":
        return cls(
            quote=data["quote"],
            riddle=data["riddle"],
            speaker=data["speaker"],
            listener=data["listener"],
            book=data["book"],
        )

    def to_dict(self) -> dict:
        return {
            "quote": self.quote,
            "riddle": self.riddle,
            "speaker": self.speaker,
            "listener": self.listener,
            "book": self.book,
        }


@dataclass(frozen=True)
class RawQuoteSource:
    en: dict[str, str]
    he: dict[str, str]

    @classmethod
    def from_dict(cls, data: dict) -> "RawQuoteSource":
        return cls(en=dict(data["en"]), he=dict(data["he"]))

    def to_dict(self) -> dict:
        return {"en": dict(self.en), "he": dict(self.he)}


@dataclass(frozen=True)
class CandidateMeta:
    reason: str
    confidence: float

    @classmethod
    def from_dict(cls, data: dict) -> "CandidateMeta":
        return cls(reason=data["reason"], confidence=data["confidence"])

    def to_dict(self) -> dict:
        return {"reason": self.reason, "confidence": self.confidence}


@dataclass(frozen=True)
class RefRange:
    chapter: int
    start: int
    end: int

    @classmethod
    def from_dict(cls, data: dict) -> "RefRange":
        return cls(chapter=data["chapter"], start=data["start"], end=data["end"])

    def to_dict(self) -> dict:
        return {"chapter": self.chapter, "start": self.start, "end": self.end}


@dataclass(frozen=True)
class CandidateItem:
    id: str
    source: CandidateSource
    en: CandidateLangText
    he: CandidateLangText
    raw_quote_source: RawQuoteSource
    meta: CandidateMeta
    ref: RefRange

    @classmethod
    def from_dict(cls, data: dict) -> "CandidateItem":
        return cls(
            id=data["id"],
            source=CandidateSource.from_dict(data["source"]),
            en=CandidateLangText.from_dict(data["en"]),
            he=CandidateLangText.from_dict(data["he"]),
            raw_quote_source=RawQuoteSource.from_dict(data["raw_quote_source"]),
            meta=CandidateMeta.from_dict(data["meta"]),
            ref=RefRange.from_dict(data["ref"]),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source.to_dict(),
            "en": self.en.to_dict(),
            "he": self.he.to_dict(),
            "raw_quote_source": self.raw_quote_source.to_dict(),
            "meta": self.meta.to_dict(),
            "ref": self.ref.to_dict(),
        }


@dataclass(frozen=True)
class FinalSource:
    method: str
    book_code: str
    book: str
    book_he: str
    chapter: int
    quote_verse_start: int
    quote_verse_end: int

    @classmethod
    def from_dict(cls, data: dict) -> "FinalSource":
        return cls(
            method=data["method"],
            book_code=data["book_code"],
            book=data["book"],
            book_he=data["book_he"],
            chapter=data["chapter"],
            quote_verse_start=data["quote_verse_start"],
            quote_verse_end=data["quote_verse_end"],
        )

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "book_code": self.book_code,
            "book": self.book,
            "book_he": self.book_he,
            "chapter": self.chapter,
            "quote_verse_start": self.quote_verse_start,
            "quote_verse_end": self.quote_verse_end,
        }


@dataclass(frozen=True)
class HintSourceRef:
    book: str
    chapter: int
    start: int
    end: int

    @classmethod
    def from_dict(cls, data: dict) -> "HintSourceRef":
        return cls(book=data["book"], chapter=data["chapter"], start=data["start"], end=data["end"])

    def to_dict(self) -> dict:
        return {
            "book": self.book,
            "chapter": self.chapter,
            "start": self.start,
            "end": self.end,
        }


@dataclass(frozen=True)
class BonusHint:
    quote: str
    source: HintSourceRef

    @classmethod
    def from_dict(cls, data: dict) -> "BonusHint":
        return cls(quote=data["quote"], source=HintSourceRef.from_dict(data["source"]))

    def to_dict(self) -> dict:
        return {"quote": self.quote, "source": self.source.to_dict()}


@dataclass(frozen=True)
class ChoicePools:
    speaker: list[str]
    listener: list[str]

    @classmethod
    def from_dict(cls, data: dict | list | None) -> "ChoicePools":
        if data in (None, []):
            return cls(speaker=[], listener=[])
        if not isinstance(data, dict):
            raise TypeError(f"Unsupported options payload: {type(data).__name__}")
        return cls(
            speaker=list(data["speaker"]),
            listener=list(data["listener"]),
        )

    def to_dict(self) -> dict:
        return {
            "speaker": list(self.speaker),
            "listener": list(self.listener),
        }

    @classmethod
    def empty(cls) -> "ChoicePools":
        return cls(speaker=[], listener=[])


@dataclass(frozen=True)
class FinalLangText:
    quote: str
    riddle: str
    speaker: str
    listener: str
    book: str
    options: ChoicePools
    bonus: str
    bonus_hint: BonusHint

    @classmethod
    def from_dict(cls, data: dict) -> "FinalLangText":
        return cls(
            quote=data["quote"],
            riddle=data["riddle"],
            speaker=data["speaker"],
            listener=data["listener"],
            book=data["book"],
            options=ChoicePools.from_dict(data["options"]),
            bonus=data["bonus"],
            bonus_hint=BonusHint.from_dict(data["bonus_hint"]),
        )

    def to_dict(self) -> dict:
        return {
            "quote": self.quote,
            "riddle": self.riddle,
            "speaker": self.speaker,
            "listener": self.listener,
            "book": self.book,
            "options": self.options.to_dict(),
            "bonus": self.bonus,
            "bonus_hint": self.bonus_hint.to_dict(),
        }


@dataclass(frozen=True)
class FinalMeta:
    mode: str
    source: str
    template_item_id: str
    bonus_source: str
    bonus_hint_source: str

    @classmethod
    def from_dict(cls, data: dict) -> "FinalMeta":
        return cls(
            mode=data["mode"],
            source=data["source"],
            template_item_id=data["template_item_id"],
            bonus_source=data["bonus_source"],
            bonus_hint_source=data["bonus_hint_source"],
        )

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "source": self.source,
            "template_item_id": self.template_item_id,
            "bonus_source": self.bonus_source,
            "bonus_hint_source": self.bonus_hint_source,
        }


@dataclass(frozen=True)
class FinalQuoteItem:
    id: str
    source: FinalSource
    en: FinalLangText
    he: FinalLangText
    raw_quote_source: RawQuoteSource
    ref: RefRange
    meta: FinalMeta

    @classmethod
    def from_dict(cls, data: dict) -> "FinalQuoteItem":
        return cls(
            id=data["id"],
            source=FinalSource.from_dict(data["source"]),
            en=FinalLangText.from_dict(data["en"]),
            he=FinalLangText.from_dict(data["he"]),
            raw_quote_source=RawQuoteSource.from_dict(data["raw_quote_source"]),
            ref=RefRange.from_dict(data["ref"]),
            meta=FinalMeta.from_dict(data["meta"]),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source.to_dict(),
            "en": self.en.to_dict(),
            "he": self.he.to_dict(),
            "raw_quote_source": self.raw_quote_source.to_dict(),
            "ref": self.ref.to_dict(),
            "meta": self.meta.to_dict(),
        }


@dataclass(frozen=True)
class ChapterPayload:
    book_code: str
    book: str
    book_he: str
    chapter: int
    mode: str
    items: list[FinalQuoteItem]

    @classmethod
    def from_dict(cls, data: dict) -> "ChapterPayload":
        return cls(
            book_code=data["book_code"],
            book=data["book"],
            book_he=data["book_he"],
            chapter=data["chapter"],
            mode=data["mode"],
            items=[FinalQuoteItem.from_dict(item) for item in data["items"]],
        )

    def to_dict(self) -> dict:
        return {
            "book_code": self.book_code,
            "book": self.book,
            "book_he": self.book_he,
            "chapter": self.chapter,
            "mode": self.mode,
            "items": [item.to_dict() for item in self.items],
        }


@dataclass(frozen=True)
class CharacterBankEntry:
    id: str
    en: str
    he: str
    normalized_en_aliases: list[str]
    normalized_he_aliases: list[str]
    books: list[str]
    observed_fields: list[str]
    count: int
    category: str

    @classmethod
    def from_dict(cls, data: dict) -> "CharacterBankEntry":
        return cls(
            id=data["id"],
            en=data["en"],
            he=data["he"],
            normalized_en_aliases=list(data["normalized_en_aliases"]),
            normalized_he_aliases=list(data["normalized_he_aliases"]),
            books=list(data["books"]),
            observed_fields=list(data["observed_fields"]),
            count=int(data["count"]),
            category=data["category"],
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "en": self.en,
            "he": self.he,
            "normalized_en_aliases": list(self.normalized_en_aliases),
            "normalized_he_aliases": list(self.normalized_he_aliases),
            "books": list(self.books),
            "observed_fields": list(self.observed_fields),
            "count": self.count,
            "category": self.category,
        }


@dataclass(frozen=True)
class CharacterBank:
    taxonomy: list[str]
    items: list[CharacterBankEntry]

    @classmethod
    def from_dict(cls, data: dict) -> "CharacterBank":
        return cls(
            taxonomy=list(data["taxonomy"]),
            items=[CharacterBankEntry.from_dict(item) for item in data["items"]],
        )

    def to_dict(self) -> dict:
        return {
            "taxonomy": list(self.taxonomy),
            "items": [item.to_dict() for item in self.items],
        }


@dataclass(frozen=True)
class DropRecord:
    candidate_id: str
    book_code: str
    chapter: int
    start: int
    end: int
    stage: str
    reason: str
    detail: str

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "book_code": self.book_code,
            "chapter": self.chapter,
            "start": self.start,
            "end": self.end,
            "stage": self.stage,
            "reason": self.reason,
            "detail": self.detail,
        }


def iter_candidate_items(path: Path) -> list[CandidateItem]:
    items: list[CandidateItem] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            items.append(CandidateItem.from_dict(json.loads(stripped)))
    return items


def iter_chapter_payloads(path: Path) -> list[ChapterPayload]:
    payloads: list[ChapterPayload] = []
    for chapter_path in sorted(path.glob("*.json")):
        payloads.append(ChapterPayload.from_dict(json.loads(chapter_path.read_text(encoding="utf-8"))))
    return sorted(
        payloads,
        key=lambda payload: (
            bible_sources.BOOK_ORDER.get(payload.book_code, 999),
            payload.chapter,
            payload.book_code,
            payload.book,
        ),
    )


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_path, path)


def append_jsonl(path: Path, payloads: list[dict]) -> None:
    if not payloads:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for payload in payloads:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
