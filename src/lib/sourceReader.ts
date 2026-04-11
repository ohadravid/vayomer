import type { Lang, SourceRef } from "../types";
import { getSearchWithLanguage } from "./language";

export type SourceBook = {
  code: string;
  en: string;
  he: string;
  slug: string;
};

export type SourceIndexBook = {
  code: string;
  slug: string;
  en: string;
  he: string;
  chapters: number[];
};

export type SourceIndexPayload = {
  books: SourceIndexBook[];
};

export type SourceVerse = {
  verse: number;
  en: string;
  he: string;
};

export type SourceChapterPayload = {
  book_code: string;
  slug: string;
  book: string;
  book_he: string;
  chapter: number;
  verses: SourceVerse[];
};

export type ReaderRoute =
  | { kind: "read-books" }
  | { kind: "read-book"; bookSlug: string }
  | { kind: "read-chapter"; bookSlug: string; chapter: number }
  | { kind: "read-not-found" };

const SOURCE_BOOK_DEFS = [
  { code: "GEN", en: "Genesis", he: "בראשית" },
  { code: "EXO", en: "Exodus", he: "שמות" },
  { code: "LEV", en: "Leviticus", he: "ויקרא" },
  { code: "NUM", en: "Numbers", he: "במדבר" },
  { code: "DEU", en: "Deuteronomy", he: "דברים" },
  { code: "JOS", en: "Joshua", he: "יהושע" },
  { code: "JDG", en: "Judges", he: "שופטים" },
  { code: "RUT", en: "Ruth", he: "רות" },
  { code: "1SA", en: "1 Samuel", he: "שמואל א" },
  { code: "2SA", en: "2 Samuel", he: "שמואל ב" },
  { code: "1KI", en: "1 Kings", he: "מלכים א" },
  { code: "2KI", en: "2 Kings", he: "מלכים ב" },
  { code: "1CH", en: "1 Chronicles", he: "דברי הימים א" },
  { code: "2CH", en: "2 Chronicles", he: "דברי הימים ב" },
  { code: "EZR", en: "Ezra", he: "עזרא" },
  { code: "NEH", en: "Nehemiah", he: "נחמיה" },
  { code: "EST", en: "Esther", he: "אסתר" },
  { code: "JOB", en: "Job", he: "איוב" },
  { code: "PSA", en: "Psalms", he: "תהילים" },
  { code: "PRO", en: "Proverbs", he: "משלי" },
  { code: "ECC", en: "Ecclesiastes", he: "קהלת" },
  { code: "SON", en: "Song of Songs", he: "שיר השירים" },
  { code: "ISA", en: "Isaiah", he: "ישעיהו" },
  { code: "JER", en: "Jeremiah", he: "ירמיהו" },
  { code: "LAM", en: "Lamentations", he: "איכה" },
  { code: "EZE", en: "Ezekiel", he: "יחזקאל" },
  { code: "DAN", en: "Daniel", he: "דניאל" },
  { code: "HOS", en: "Hosea", he: "הושע" },
  { code: "JOE", en: "Joel", he: "יואל" },
  { code: "AMO", en: "Amos", he: "עמוס" },
  { code: "OBA", en: "Obadiah", he: "עובדיה" },
  { code: "JON", en: "Jonah", he: "יונה" },
  { code: "MIC", en: "Micah", he: "מיכה" },
  { code: "NAH", en: "Nahum", he: "נחום" },
  { code: "HAB", en: "Habakkuk", he: "חבקוק" },
  { code: "ZEP", en: "Zephaniah", he: "צפניה" },
  { code: "HAG", en: "Haggai", he: "חגי" },
  { code: "ZEC", en: "Zechariah", he: "זכריה" },
  { code: "MAL", en: "Malachi", he: "מלאכי" },
] as const;

export const SOURCE_BOOKS: readonly SourceBook[] = SOURCE_BOOK_DEFS.map((book) => ({
  ...book,
  slug: slugifyBookName(book.en),
}));

const BOOK_BY_CODE = new Map(SOURCE_BOOKS.map((book) => [book.code, book]));

export function slugifyBookName(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

function toPositiveInt(value: number | undefined): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  const rounded = Math.floor(value);
  return rounded > 0 ? rounded : null;
}

export function buildVerseHash(verse: number): string {
  return `#v${Math.floor(verse)}`;
}

export function getSourceBookSlug(bookCode: string | undefined, fallbackBookName = ""): string | null {
  const book = typeof bookCode === "string" ? BOOK_BY_CODE.get(bookCode.trim()) : undefined;
  if (book) return book.slug;
  const trimmedFallback = fallbackBookName.trim();
  return trimmedFallback ? slugifyBookName(trimmedFallback) : null;
}

export function buildReaderPath(bookSlug?: string, chapter?: number): string {
  const cleanBookSlug = typeof bookSlug === "string" ? bookSlug.trim().replace(/^\/+|\/+$/g, "") : "";
  const chapterNumber = toPositiveInt(chapter);

  if (!cleanBookSlug) return "/read";
  if (chapterNumber === null) return `/read/${cleanBookSlug}`;
  return `/read/${cleanBookSlug}/${chapterNumber}`;
}

export function buildReaderHref(params: {
  lang: Lang;
  bookSlug: string;
  chapter?: number;
  verse?: number;
}): string {
  const path = buildReaderPath(params.bookSlug, params.chapter);
  const search = getSearchWithLanguage("", params.lang);
  const verse = toPositiveInt(params.verse);
  const hash = verse === null ? "" : buildVerseHash(verse);
  return `${path}${search}${hash}`;
}

export function buildReaderHrefFromSource(source: SourceRef | undefined, lang: Lang): string | null {
  if (!source) return null;
  const bookSlug = getSourceBookSlug(source.book_code, source.book);
  const chapter = toPositiveInt(source.chapter);
  const verse = toPositiveInt(source.quote_verse_start);
  if (!bookSlug || chapter === null || verse === null) return null;
  return buildReaderHref({ lang, bookSlug, chapter, verse });
}

export function parseReaderRoute(pathname: string): ReaderRoute | null {
  const parts = pathname
    .trim()
    .split("/")
    .filter(Boolean);

  if (parts.length === 0 || parts[0] !== "read") return null;
  if (parts.length === 1) return { kind: "read-books" };
  if (parts.length === 2) return { kind: "read-book", bookSlug: parts[1] };
  if (parts.length === 3) {
    const chapter = Number.parseInt(parts[2] ?? "", 10);
    if (Number.isInteger(chapter) && chapter > 0) {
      return { kind: "read-chapter", bookSlug: parts[1], chapter };
    }
  }
  return { kind: "read-not-found" };
}
