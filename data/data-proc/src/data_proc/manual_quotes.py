from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Protocol

import click

from data_proc.corpus import BibleCorpus
from data_proc.pipeline import DEFAULT_ENGLISH_XML, DEFAULT_HEBREW_ZIP
from data_proc.schema import write_json
from data_proc.utils import bible_sources
from data_proc.utils.text_cleanup import clean_text, cleanup_hebrew_quote, normalize_word, word_pairs

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_SPEC_DIR = REPO_ROOT / "data" / "manual_quote_specs"
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "manual_quotes"


class RangeCollector(Protocol):
    def collect_range(self, book_code: str, chapter: int, start: int, end: int) -> Any:
        ...


@dataclass(frozen=True)
class ManualQuoteSpec:
    id: str
    book_code: str
    chapter: int
    quote_verse_start: int
    quote_verse_end: int
    en: dict[str, Any]
    he: dict[str, Any]
    source_emoji: str = ""


def _slugify_book_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_manual_specs(spec_dir: Path = DEFAULT_SPEC_DIR) -> list[ManualQuoteSpec]:
    specs: list[ManualQuoteSpec] = []
    for path in sorted(spec_dir.glob("*.json")):
        raw = _read_json(path)
        specs.append(
            ManualQuoteSpec(
                id=str(raw["id"]),
                book_code=str(raw["book_code"]),
                chapter=int(raw["chapter"]),
                quote_verse_start=int(raw["quote_verse_start"]),
                quote_verse_end=int(raw["quote_verse_end"]),
                en=dict(raw["en"]),
                he=dict(raw["he"]),
                source_emoji=str(raw.get("source_emoji", "")),
            )
        )
    return specs


def _bonus_hint_payload(spec: dict[str, Any], *, lang: str) -> dict[str, Any] | None:
    hint = spec["bonus_hint"]
    if hint is None:
        return None

    hint = dict(hint)
    hint_quote = clean_text(str(hint["quote"]))
    if lang == "he":
        hint_quote = cleanup_hebrew_quote(hint_quote)
    return {
        "quote": hint_quote,
        "source": dict(hint["source"]),
    }


def _language_text(spec: dict[str, Any], *, quote: str, book: str, lang: str) -> dict[str, Any]:
    riddle = clean_text(str(spec["riddle"]))
    speaker = clean_text(str(spec["speaker"]))
    listener = clean_text(str(spec["listener"]))
    bonus = clean_text(str(spec["bonus"]))
    if lang == "he":
        riddle = cleanup_hebrew_quote(riddle)
        speaker = cleanup_hebrew_quote(speaker)
        listener = cleanup_hebrew_quote(listener)
        bonus = cleanup_hebrew_quote(bonus)

    return {
        "quote": quote,
        "riddle": riddle,
        "speaker": speaker,
        "listener": listener,
        "book": book,
        "options": {
            "speaker": [clean_text(str(value)) for value in spec.get("options", {}).get("speaker", [])],
            "listener": [clean_text(str(value)) for value in spec.get("options", {}).get("listener", [])],
        },
        "bonus": bonus,
        "bonus_hint": _bonus_hint_payload(spec, lang=lang),
    }


def _ranges_overlap(first_start: int, first_end: int, second_start: int, second_end: int) -> bool:
    return first_start <= second_end and second_start <= first_end


def _hint_source_overlaps_quote(spec: ManualQuoteSpec, hint: dict[str, Any], *, quote_book: str) -> bool:
    source = dict(hint["source"])
    source_book_code = str(hint.get("source_book_code", ""))
    same_book = source_book_code == spec.book_code if source_book_code else str(source.get("book", "")) == quote_book
    if not same_book or int(source["chapter"]) != spec.chapter:
        return False
    return _ranges_overlap(
        spec.quote_verse_start,
        spec.quote_verse_end,
        int(source["start"]),
        int(source["end"]),
    )


def _validate_bonus_hint_source(
    spec: ManualQuoteSpec,
    lang_spec: dict[str, Any],
    *,
    lang: str,
    quote_book: str,
    corpus: RangeCollector,
) -> None:
    hint = lang_spec["bonus_hint"]
    if hint is None:
        return
    hint = dict(hint)
    if _hint_source_overlaps_quote(spec, hint, quote_book=quote_book):
        raise ValueError(f"{spec.id}: {lang} bonus hint must come from a different verse")

    source_book_code = str(hint.get("source_book_code", ""))
    if not source_book_code:
        return

    source = dict(hint["source"])
    range_quote = corpus.collect_range(
        book_code=source_book_code,
        chapter=int(source["chapter"]),
        start=int(source["start"]),
        end=int(source["end"]),
    )
    if range_quote is None or range_quote.missing:
        missing = [] if range_quote is None else range_quote.missing
        raise ValueError(f"{spec.id}: {lang} bonus hint source is missing verses {missing}")

    source_quote = clean_text(range_quote.he_quote if lang == "he" else range_quote.en_quote)
    hint_quote = clean_text(str(hint["quote"]))
    if lang == "he":
        source_quote = cleanup_hebrew_quote(source_quote)
        hint_quote = cleanup_hebrew_quote(hint_quote)
    if hint_quote not in source_quote:
        raise ValueError(f"{spec.id}: {lang} bonus hint quote does not match its source")


def _clean_hint_match_terms(lang_spec: dict[str, Any], *, bonus: str, lang: str) -> list[str]:
    hint = lang_spec["bonus_hint"]
    if hint is None:
        return []
    raw_terms = dict(hint).get("match_terms") or [bonus]
    terms: list[str] = []
    for value in raw_terms:
        term = clean_text(str(value))
        if lang == "he":
            term = cleanup_hebrew_quote(term)
        if term:
            terms.append(term)
    return terms


def _hint_quote_contains_match_term(hint_quote: str, terms: list[str], *, lang: str) -> bool:
    for term in terms:
        if term in hint_quote:
            return True

        normalized_term = normalize_word(term, lang)
        if not normalized_term:
            continue
        if any(normalized_word.startswith(normalized_term) for _, normalized_word in word_pairs(hint_quote, lang)):
            return True
    return False


def _validate_manual_item(item: dict[str, Any], spec: ManualQuoteSpec) -> None:
    for lang in ("en", "he"):
        text = item[lang]
        lang_spec = spec.en if lang == "en" else spec.he
        quote = text["quote"]
        riddle = text["riddle"]
        bonus = text["bonus"]
        if riddle not in quote:
            raise ValueError(f"{item['id']}: {lang} riddle is not present in quote")
        if bonus not in quote:
            raise ValueError(f"{item['id']}: {lang} bonus is not present in quote")
        hint = text["bonus_hint"]
        if hint is None:
            continue
        hint_quote = hint["quote"]
        match_terms = _clean_hint_match_terms(lang_spec, bonus=bonus, lang=lang)
        if not _hint_quote_contains_match_term(hint_quote, match_terms, lang=lang):
            raise ValueError(f"{item['id']}: {lang} bonus hint does not contain a configured match term")


def build_manual_quote_item(spec: ManualQuoteSpec, corpus: RangeCollector) -> dict[str, Any]:
    range_quote = corpus.collect_range(
        book_code=spec.book_code,
        chapter=spec.chapter,
        start=spec.quote_verse_start,
        end=spec.quote_verse_end,
    )
    if range_quote is None or range_quote.missing:
        missing = [] if range_quote is None else range_quote.missing
        raise ValueError(f"{spec.id}: missing source verses {missing}")

    _validate_bonus_hint_source(spec, spec.en, lang="en", quote_book=range_quote.book_en, corpus=corpus)
    _validate_bonus_hint_source(spec, spec.he, lang="he", quote_book=range_quote.book_he, corpus=corpus)

    source = {
        "method": "manual",
        "book_code": spec.book_code,
        "book": range_quote.book_en,
        "book_he": range_quote.book_he,
        "chapter": spec.chapter,
        "quote_verse_start": spec.quote_verse_start,
        "quote_verse_end": spec.quote_verse_end,
    }
    if spec.source_emoji:
        source["emoji"] = spec.source_emoji

    item = {
        "id": spec.id,
        "source": source,
        "en": _language_text(spec.en, quote=range_quote.en_quote, book=range_quote.book_en, lang="en"),
        "he": _language_text(spec.he, quote=range_quote.he_quote, book=range_quote.book_he, lang="he"),
        "raw_quote_source": range_quote.raw_quote_source,
        "ref": {
            "chapter": spec.chapter,
            "start": spec.quote_verse_start,
            "end": spec.quote_verse_end,
        },
        "meta": {
            "mode": "manual",
            "source": "manual-spec",
            "template_item_id": "",
            "bonus_source": "manual",
            "bonus_hint_source": "manual",
        },
    }
    _validate_manual_item(item, spec)
    return item


def build_manual_chapter_payloads(specs: Iterable[ManualQuoteSpec], corpus: RangeCollector) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for spec in specs:
        item = build_manual_quote_item(spec, corpus)
        grouped.setdefault((spec.book_code, spec.chapter), []).append(item)

    payloads: list[dict[str, Any]] = []
    for (book_code, chapter), items in sorted(
        grouped.items(),
        key=lambda entry: (bible_sources.BOOK_ORDER.get(entry[0][0], 999), entry[0][1]),
    ):
        first = items[0]
        payloads.append(
            {
                "book_code": book_code,
                "book": first["source"]["book"],
                "book_he": first["source"]["book_he"],
                "chapter": chapter,
                "mode": "manual",
                "items": sorted(items, key=lambda item: (item["ref"]["start"], item["ref"]["end"], item["id"])),
            }
        )
    return payloads


def manual_chapter_output_path(out_dir: Path, payload: dict[str, Any]) -> Path:
    return out_dir / f"{_slugify_book_name(str(payload['book']))}-{int(payload['chapter']):03d}.json"


def write_manual_chapter_payloads(payloads: Iterable[dict[str, Any]], out_dir: Path) -> list[Path]:
    written: list[Path] = []
    for payload in payloads:
        output_path = manual_chapter_output_path(out_dir, payload)
        write_json(output_path, payload)
        written.append(output_path)
    return written


@click.command("build-manual-quotes")
@click.option("--spec-dir", type=click.Path(path_type=Path, exists=True, file_okay=False), default=DEFAULT_SPEC_DIR, show_default=True)
@click.option("--out-dir", type=click.Path(path_type=Path, file_okay=False), default=DEFAULT_OUT_DIR, show_default=True)
@click.option("--english-xml", type=click.Path(path_type=Path, exists=True, dir_okay=False), default=DEFAULT_ENGLISH_XML, show_default=True)
@click.option("--hebrew-zip", type=click.Path(path_type=Path, exists=True, dir_okay=False), default=DEFAULT_HEBREW_ZIP, show_default=True)
def build_manual_quotes_command(spec_dir: Path, out_dir: Path, english_xml: Path, hebrew_zip: Path) -> None:
    specs = load_manual_specs(spec_dir)
    corpus = BibleCorpus(english_xml=english_xml, hebrew_zip=hebrew_zip)
    payloads = build_manual_chapter_payloads(specs, corpus)
    written = write_manual_chapter_payloads(payloads, out_dir)
    click.echo(f"Prepared {sum(len(payload['items']) for payload in payloads)} manual quotes in {len(written)} files.")
