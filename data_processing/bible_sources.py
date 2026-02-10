#!/usr/bin/env python3
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple
import xml.etree.ElementTree as ET

DEFAULT_ENGLISH_COLLECTION = "English_Collection.4921q.0.xml"
DEFAULT_HEBREW_ZIP = "Tanach.xml.zip"

NS = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"

VERSE_ID_RE = re.compile(r"^b\.([A-Z0-9]+)\.([0-9]{3})\.([0-9]{3})\.")
REF_RE = re.compile(r"^(.*\S)\s+(\d+):(\d+)$")

HEBREW_CANTILLATION_RE = re.compile(r"[\u0591-\u05AF]")
HEBREW_ALL_MARKS_RE = re.compile(r"[\u0591-\u05C7]")

# Canonical Tanakh order (39 books).
OT_BOOKS: List[Tuple[str, str, str]] = [
    ("GEN", "Genesis", "בראשית"),
    ("EXO", "Exodus", "שמות"),
    ("LEV", "Leviticus", "ויקרא"),
    ("NUM", "Numbers", "במדבר"),
    ("DEU", "Deuteronomy", "דברים"),
    ("JOS", "Joshua", "יהושע"),
    ("JDG", "Judges", "שופטים"),
    ("RUT", "Ruth", "רות"),
    ("1SA", "1 Samuel", "שמואל א"),
    ("2SA", "2 Samuel", "שמואל ב"),
    ("1KI", "1 Kings", "מלכים א"),
    ("2KI", "2 Kings", "מלכים ב"),
    ("1CH", "1 Chronicles", "דברי הימים א"),
    ("2CH", "2 Chronicles", "דברי הימים ב"),
    ("EZR", "Ezra", "עזרא"),
    ("NEH", "Nehemiah", "נחמיה"),
    ("EST", "Esther", "אסתר"),
    ("JOB", "Job", "איוב"),
    ("PSA", "Psalms", "תהילים"),
    ("PRO", "Proverbs", "משלי"),
    ("ECC", "Ecclesiastes", "קהלת"),
    ("SON", "Song of Songs", "שיר השירים"),
    ("ISA", "Isaiah", "ישעיהו"),
    ("JER", "Jeremiah", "ירמיהו"),
    ("LAM", "Lamentations", "איכה"),
    ("EZE", "Ezekiel", "יחזקאל"),
    ("DAN", "Daniel", "דניאל"),
    ("HOS", "Hosea", "הושע"),
    ("JOE", "Joel", "יואל"),
    ("AMO", "Amos", "עמוס"),
    ("OBA", "Obadiah", "עובדיה"),
    ("JON", "Jonah", "יונה"),
    ("MIC", "Micah", "מיכה"),
    ("NAH", "Nahum", "נחום"),
    ("HAB", "Habakkuk", "חבקוק"),
    ("ZEP", "Zephaniah", "צפניה"),
    ("HAG", "Haggai", "חגי"),
    ("ZEC", "Zechariah", "זכריה"),
    ("MAL", "Malachi", "מלאכי"),
]

BOOK_CODE_TO_EN: Dict[str, str] = {code: en for code, en, _ in OT_BOOKS}
BOOK_CODE_TO_HE: Dict[str, str] = {code: he for code, _, he in OT_BOOKS}
BOOK_NAME_TO_CODE: Dict[str, str] = {en: code for code, en, _ in OT_BOOKS}
BOOK_NAME_TO_CODE["Song of Solomon"] = "SON"
BOOK_ORDER: Dict[str, int] = {code: idx for idx, (code, _, _) in enumerate(OT_BOOKS)}

VerseMap = Dict[Tuple[str, int, int], str]


@dataclass(frozen=True)
class Verse:
    verse: int
    en: str
    he: str


@dataclass(frozen=True)
class ChapterRecord:
    book_code: str
    book_name_en: str
    book_name_he: str
    chapter: int
    verses: List[Verse]

    @property
    def source_ref(self) -> str:
        return f"{self.book_name_en} {self.chapter}"


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def strip_hebrew_cantillation(text: str) -> str:
    text = (text or "").replace("\u034F", "")
    return HEBREW_CANTILLATION_RE.sub("", text)


def chapter_filename(chapter: ChapterRecord) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", chapter.book_name_en.lower()).strip("-")
    return f"{slug}-{chapter.chapter:03d}.json"


def parse_reference(ref: str) -> Tuple[str, int, int]:
    match = REF_RE.match((ref or "").strip())
    if not match:
        raise ValueError(f"Bad reference: {ref}")
    return match.group(1), int(match.group(2)), int(match.group(3))


def normalize_english_for_compare(text: str) -> str:
    return re.sub(r"[^a-z]+", "", clean_text(text).casefold())


def normalize_hebrew_for_compare(text: str) -> str:
    text = clean_text(strip_hebrew_cantillation(text))
    return re.sub(r"[^\u05D0-\u05EA]+", "", text)


def _itertext_without_x(elem: ET.Element) -> str:
    parts: List[str] = []
    if elem.text:
        parts.append(elem.text)
    for child in list(elem):
        if child.tag == "x":
            if child.tail:
                parts.append(child.tail)
            continue
        parts.append(_itertext_without_x(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def _clean_hebrew_token(token: str) -> str:
    text = strip_hebrew_cantillation(token)
    text = re.sub(r"[A-Za-z0-9]", "", text)
    text = clean_text(text)
    return re.sub(r"\s*־\s*", "־", text)


def _tanach_verse_text(verse_elem: ET.Element) -> str:
    tokens: List[str] = []
    children = list(verse_elem)
    i = 0
    while i < len(children):
        child = children[i]
        tag = child.tag

        if tag == "w":
            token = _clean_hebrew_token(_itertext_without_x(child))
            if token:
                tokens.append(token)
            i += 1
            continue

        if tag == "k":
            q_tokens: List[str] = []
            j = i + 1
            while j < len(children) and children[j].tag == "q":
                q_token = _clean_hebrew_token(_itertext_without_x(children[j]))
                if q_token:
                    q_tokens.append(q_token)
                j += 1
            if q_tokens:
                tokens.extend(q_tokens)
                i = j
                continue
            token = _clean_hebrew_token(_itertext_without_x(child))
            if token:
                tokens.append(token)
            i += 1
            continue

        if tag == "q":
            token = _clean_hebrew_token(_itertext_without_x(child))
            if token:
                tokens.append(token)

        i += 1

    text = clean_text(" ".join(tokens))
    return re.sub(r"־\s+", "־", text)


def _tanach_book_xml_files(names: Iterable[str]) -> List[str]:
    out: List[str] = []
    for name in names:
        if not name.startswith("Books/"):
            continue
        if not name.endswith(".xml"):
            continue
        if name.endswith(".DH.xml"):
            continue
        if name.endswith("TanachHeader.xml") or name.endswith("TanachIndex.xml"):
            continue
        out.append(name)
    return sorted(out)


def load_english_verse_map(path: Path) -> VerseMap:
    verses: VerseMap = {}
    for _, elem in ET.iterparse(path, events=("end",)):
        if elem.tag != f"{NS}ab" or elem.attrib.get("type") != "verse":
            continue

        xml_id = elem.attrib.get(XML_ID, "")
        match = VERSE_ID_RE.match(xml_id)
        if not match:
            elem.clear()
            continue

        code = match.group(1)
        if code not in BOOK_CODE_TO_EN:
            elem.clear()
            continue

        chapter = int(match.group(2))
        verse = int(match.group(3))
        text = clean_text("".join(elem.itertext()))
        if text:
            verses[(code, chapter, verse)] = text
        elem.clear()

    return verses


def load_tanach_zip_verse_map(path: Path) -> VerseMap:
    verses: VerseMap = {}
    with zipfile.ZipFile(path) as archive:
        for name in _tanach_book_xml_files(archive.namelist()):
            root = ET.fromstring(archive.read(name))
            book_name = clean_text(root.findtext("./tanach/book/names/name") or "")
            code = BOOK_NAME_TO_CODE.get(book_name)
            if not code:
                continue

            for chapter_elem in root.findall("./tanach/book/c"):
                try:
                    chapter = int(chapter_elem.attrib.get("n", ""))
                except ValueError:
                    continue
                for verse_elem in chapter_elem.findall("./v"):
                    try:
                        verse = int(verse_elem.attrib.get("n", ""))
                    except ValueError:
                        continue
                    text = _tanach_verse_text(verse_elem)
                    if text:
                        verses[(code, chapter, verse)] = text

    return verses


def collect_range_text(
    code: str,
    chapter: int,
    start: int,
    end: int,
    english_map: VerseMap,
    hebrew_map: VerseMap,
) -> Tuple[str, str, List[int]]:
    missing: List[int] = []
    en_parts: List[str] = []
    he_parts: List[str] = []
    for verse in range(start, end + 1):
        en_text = english_map.get((code, chapter, verse), "")
        he_text = hebrew_map.get((code, chapter, verse), "")
        if not en_text or not he_text:
            missing.append(verse)
            continue
        en_parts.append(en_text)
        he_parts.append(he_text)

    return clean_text(" ".join(en_parts)), clean_text(" ".join(he_parts)), missing


def build_common_chapters(english_map: VerseMap, hebrew_map: VerseMap) -> List[ChapterRecord]:
    by_chapter: Dict[Tuple[str, int], List[int]] = {}
    for (code, chapter, verse), en_text in english_map.items():
        if not en_text:
            continue
        he_text = hebrew_map.get((code, chapter, verse))
        if not he_text:
            continue
        by_chapter.setdefault((code, chapter), []).append(verse)

    chapters: List[ChapterRecord] = []
    for (code, chapter), verse_numbers in by_chapter.items():
        verse_set = sorted(set(verse_numbers))
        verses = [
            Verse(
                verse=verse_num,
                en=english_map[(code, chapter, verse_num)],
                he=hebrew_map[(code, chapter, verse_num)],
            )
            for verse_num in verse_set
        ]
        chapters.append(
            ChapterRecord(
                book_code=code,
                book_name_en=BOOK_CODE_TO_EN.get(code, code),
                book_name_he=BOOK_CODE_TO_HE.get(code, ""),
                chapter=chapter,
                verses=verses,
            )
        )

    chapters.sort(key=lambda c: (BOOK_ORDER.get(c.book_code, 999), c.chapter))
    return chapters
