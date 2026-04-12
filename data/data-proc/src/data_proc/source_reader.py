from __future__ import annotations

import json
import zipfile
from pathlib import Path

import click

from data_proc.utils import bible_sources
from data_proc.utils.bible_tandem import TandemBible

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_ENGLISH_XML = REPO_ROOT / bible_sources.DEFAULT_ENGLISH_COLLECTION
DEFAULT_HEBREW_ZIP = REPO_ROOT / bible_sources.DEFAULT_HEBREW_ZIP
DEFAULT_OUT_FILE = REPO_ROOT / "source.zip"

BOOK_SLUGS = {
    "GEN": "genesis",
    "EXO": "exodus",
    "LEV": "leviticus",
    "NUM": "numbers",
    "DEU": "deuteronomy",
    "JOS": "joshua",
    "JDG": "judges",
    "RUT": "ruth",
    "1SA": "1-samuel",
    "2SA": "2-samuel",
    "1KI": "1-kings",
    "2KI": "2-kings",
    "1CH": "1-chronicles",
    "2CH": "2-chronicles",
    "EZR": "ezra",
    "NEH": "nehemiah",
    "EST": "esther",
    "JOB": "job",
    "PSA": "psalms",
    "PRO": "proverbs",
    "ECC": "ecclesiastes",
    "SON": "song-of-songs",
    "ISA": "isaiah",
    "JER": "jeremiah",
    "LAM": "lamentations",
    "EZE": "ezekiel",
    "DAN": "daniel",
    "HOS": "hosea",
    "JOE": "joel",
    "AMO": "amos",
    "OBA": "obadiah",
    "JON": "jonah",
    "MIC": "micah",
    "NAH": "nahum",
    "HAB": "habakkuk",
    "ZEP": "zephaniah",
    "HAG": "haggai",
    "ZEC": "zechariah",
    "MAL": "malachi",
}


def _chapter_archive_name(slug: str, chapter: int) -> str:
    return f"{slug}/chapter{chapter}.json"


def _directory_zip_info(path: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(path)
    info.external_attr = 0o755 << 16
    info.compress_type = zipfile.ZIP_STORED
    return info


def _build_index_payload(
    tandem: TandemBible,
    *,
    included_book_codes: set[str],
) -> dict:
    books = []

    for book_code, book_en, book_he in tandem.iter_books():
        if book_code not in included_book_codes:
            continue

        chapter_count = max(
            (chapter for _, chapter in tandem.iter_chapters(book_filter=book_code)),
            default=0,
        )
        books.append(
            {
                "code": book_code,
                "slug": BOOK_SLUGS[book_code],
                "en": book_en,
                "he": book_he,
                "chapter_count": chapter_count,
            }
        )

    books.sort(key=lambda item: bible_sources.BOOK_ORDER.get(item["code"], 999))
    return {"books": books}


def build_source_reader_archive(
    tandem: TandemBible,
    out_file: Path,
    *,
    book_filter: str | None = None,
    chapter_filter: int | None = None,
) -> tuple[int, dict]:
    chapters_written = 0
    book_key = (book_filter or "").strip()
    included_book_codes: set[str] = set()

    out_file.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(out_file, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for book_code, book_en, book_he in tandem.iter_books(book_filter=book_key):
            slug = BOOK_SLUGS[book_code]
            wrote_book_directory = False

            for _, chapter in tandem.iter_chapters(book_filter=book_code):
                if chapter_filter is not None and chapter != chapter_filter:
                    continue

                verses = [
                    {
                        "verse": verse.verse,
                        "en": verse.en_raw,
                        "he": verse.he_clean,
                    }
                    for verse in tandem.iter_verses(book_code, chapter)
                ]
                if not verses:
                    continue

                payload = {
                    "book_code": book_code,
                    "slug": slug,
                    "book": book_en,
                    "book_he": book_he,
                    "chapter": chapter,
                    "verses": verses,
                }
                if not wrote_book_directory:
                    archive.writestr(_directory_zip_info(f"{slug}/"), "")
                    wrote_book_directory = True
                archive.writestr(
                    _chapter_archive_name(slug, chapter),
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                )
                included_book_codes.add(book_code)
                chapters_written += 1

        index_payload = _build_index_payload(tandem, included_book_codes=included_book_codes)
        archive.writestr("index.json", json.dumps(index_payload, ensure_ascii=False, separators=(",", ":")))

    return chapters_written, index_payload


@click.command("build-source-reader")
@click.option("--out-file", type=click.Path(path_type=Path, dir_okay=False), default=DEFAULT_OUT_FILE, show_default=True)
@click.option("--english-xml", type=click.Path(path_type=Path, exists=True, dir_okay=False), default=DEFAULT_ENGLISH_XML, show_default=True)
@click.option("--hebrew-zip", type=click.Path(path_type=Path, exists=True, dir_okay=False), default=DEFAULT_HEBREW_ZIP, show_default=True)
@click.option("--book", "book_filter", default=None)
@click.option("--chapter", "chapter_filter", type=int, default=None)
def build_source_reader_command(
    out_file: Path,
    english_xml: Path,
    hebrew_zip: Path,
    book_filter: str | None,
    chapter_filter: int | None,
) -> None:
    tandem = TandemBible.load(english_xml=english_xml, hebrew_zip=hebrew_zip)
    chapters_written, index_payload = build_source_reader_archive(
        tandem,
        out_file,
        book_filter=book_filter,
        chapter_filter=chapter_filter,
    )
    click.echo(f"Wrote {chapters_written} source-reader chapter files across {len(index_payload['books'])} books to {out_file}.")
