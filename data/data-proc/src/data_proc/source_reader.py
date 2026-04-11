from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import click

from data_proc.schema import write_json_atomic
from data_proc.utils import bible_sources
from data_proc.utils.bible_tandem import TandemBible

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_ENGLISH_XML = REPO_ROOT / bible_sources.DEFAULT_ENGLISH_COLLECTION
DEFAULT_HEBREW_ZIP = REPO_ROOT / bible_sources.DEFAULT_HEBREW_ZIP
DEFAULT_OUT_DIR = REPO_ROOT / "source"


def _slugify_book_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _chapter_output_path(out_dir: Path, slug: str, chapter: int) -> Path:
    return out_dir / slug / f"chapter{chapter}.json"


def _build_index_from_output(out_dir: Path) -> dict:
    books: dict[str, dict] = {}
    if not out_dir.exists():
        return {"books": []}

    for chapter_path in sorted(out_dir.glob("*/chapter*.json")):
        try:
            payload = json.loads(chapter_path.read_text(encoding="utf-8"))
            code = str(payload["book_code"])
            entry = books.setdefault(
                code,
                {
                    "code": code,
                    "slug": str(payload["slug"]),
                    "en": str(payload["book"]),
                    "he": str(payload["book_he"]),
                    "chapters": [],
                },
            )
            entry["chapters"].append(int(payload["chapter"]))
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            continue

    ordered = sorted(books.values(), key=lambda item: bible_sources.BOOK_ORDER.get(item["code"], 999))
    for entry in ordered:
        entry["chapters"] = sorted(set(entry["chapters"]))
    return {"books": ordered}


def build_source_reader_outputs(
    tandem: TandemBible,
    out_dir: Path,
    *,
    book_filter: str | None = None,
    chapter_filter: int | None = None,
) -> tuple[int, dict]:
    if book_filter is None and chapter_filter is None:
        shutil.rmtree(out_dir, ignore_errors=True)

    chapters_written = 0
    book_key = (book_filter or "").strip()

    for book_code, book_en, book_he in tandem.iter_books(book_filter=book_key):
        slug = _slugify_book_name(book_en)
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
            write_json_atomic(_chapter_output_path(out_dir, slug, chapter), payload)
            chapters_written += 1

    index_payload = _build_index_from_output(out_dir)
    write_json_atomic(out_dir / "index.json", index_payload)
    return chapters_written, index_payload


@click.command("build-source-reader")
@click.option("--out-dir", type=click.Path(path_type=Path, file_okay=False), default=DEFAULT_OUT_DIR, show_default=True)
@click.option("--english-xml", type=click.Path(path_type=Path, exists=True, dir_okay=False), default=DEFAULT_ENGLISH_XML, show_default=True)
@click.option("--hebrew-zip", type=click.Path(path_type=Path, exists=True, dir_okay=False), default=DEFAULT_HEBREW_ZIP, show_default=True)
@click.option("--book", "book_filter", default=None)
@click.option("--chapter", "chapter_filter", type=int, default=None)
def build_source_reader_command(
    out_dir: Path,
    english_xml: Path,
    hebrew_zip: Path,
    book_filter: str | None,
    chapter_filter: int | None,
) -> None:
    tandem = TandemBible.load(english_xml=english_xml, hebrew_zip=hebrew_zip)
    chapters_written, index_payload = build_source_reader_outputs(
        tandem,
        out_dir,
        book_filter=book_filter,
        chapter_filter=chapter_filter,
    )
    click.echo(f"Wrote {chapters_written} source-reader chapter files across {len(index_payload['books'])} books to {out_dir}.")
