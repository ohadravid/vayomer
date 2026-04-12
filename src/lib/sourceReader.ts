import type { Lang, SourceRef } from "../types";
import { getSearchWithLanguage } from "./language";

export type SourceBook = {
  code: string;
  slug: string;
  en: string;
  he: string;
};

export type SourceIndexBook = {
  code: string;
  slug: string;
  en: string;
  he: string;
  chapter_count: number;
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

const SOURCE_BOOK_DEFS = [
  { code: "GEN", slug: "genesis", en: "Genesis", he: "בראשית" },
  { code: "EXO", slug: "exodus", en: "Exodus", he: "שמות" },
  { code: "LEV", slug: "leviticus", en: "Leviticus", he: "ויקרא" },
  { code: "NUM", slug: "numbers", en: "Numbers", he: "במדבר" },
  { code: "DEU", slug: "deuteronomy", en: "Deuteronomy", he: "דברים" },
  { code: "JOS", slug: "joshua", en: "Joshua", he: "יהושע" },
  { code: "JDG", slug: "judges", en: "Judges", he: "שופטים" },
  { code: "RUT", slug: "ruth", en: "Ruth", he: "רות" },
  { code: "1SA", slug: "1-samuel", en: "1 Samuel", he: "שמואל א" },
  { code: "2SA", slug: "2-samuel", en: "2 Samuel", he: "שמואל ב" },
  { code: "1KI", slug: "1-kings", en: "1 Kings", he: "מלכים א" },
  { code: "2KI", slug: "2-kings", en: "2 Kings", he: "מלכים ב" },
  { code: "1CH", slug: "1-chronicles", en: "1 Chronicles", he: "דברי הימים א" },
  { code: "2CH", slug: "2-chronicles", en: "2 Chronicles", he: "דברי הימים ב" },
  { code: "EZR", slug: "ezra", en: "Ezra", he: "עזרא" },
  { code: "NEH", slug: "nehemiah", en: "Nehemiah", he: "נחמיה" },
  { code: "EST", slug: "esther", en: "Esther", he: "אסתר" },
  { code: "JOB", slug: "job", en: "Job", he: "איוב" },
  { code: "PSA", slug: "psalms", en: "Psalms", he: "תהילים" },
  { code: "PRO", slug: "proverbs", en: "Proverbs", he: "משלי" },
  { code: "ECC", slug: "ecclesiastes", en: "Ecclesiastes", he: "קהלת" },
  { code: "SON", slug: "song-of-songs", en: "Song of Songs", he: "שיר השירים" },
  { code: "ISA", slug: "isaiah", en: "Isaiah", he: "ישעיהו" },
  { code: "JER", slug: "jeremiah", en: "Jeremiah", he: "ירמיהו" },
  { code: "LAM", slug: "lamentations", en: "Lamentations", he: "איכה" },
  { code: "EZE", slug: "ezekiel", en: "Ezekiel", he: "יחזקאל" },
  { code: "DAN", slug: "daniel", en: "Daniel", he: "דניאל" },
  { code: "HOS", slug: "hosea", en: "Hosea", he: "הושע" },
  { code: "JOE", slug: "joel", en: "Joel", he: "יואל" },
  { code: "AMO", slug: "amos", en: "Amos", he: "עמוס" },
  { code: "OBA", slug: "obadiah", en: "Obadiah", he: "עובדיה" },
  { code: "JON", slug: "jonah", en: "Jonah", he: "יונה" },
  { code: "MIC", slug: "micah", en: "Micah", he: "מיכה" },
  { code: "NAH", slug: "nahum", en: "Nahum", he: "נחום" },
  { code: "HAB", slug: "habakkuk", en: "Habakkuk", he: "חבקוק" },
  { code: "ZEP", slug: "zephaniah", en: "Zephaniah", he: "צפניה" },
  { code: "HAG", slug: "haggai", en: "Haggai", he: "חגי" },
  { code: "ZEC", slug: "zechariah", en: "Zechariah", he: "זכריה" },
  { code: "MAL", slug: "malachi", en: "Malachi", he: "מלאכי" },
] as const;

export const SOURCE_BOOKS: readonly SourceBook[] = SOURCE_BOOK_DEFS;

const BOOK_BY_CODE = new Map(SOURCE_BOOKS.map((book) => [book.code, book]));
const ORDER_BY_SLUG = new Map(SOURCE_BOOKS.map((book, index) => [book.slug, index]));

export type ReaderNeighbor = {
  bookSlug: string;
  chapter: number;
};

export function getSourceBookByCode(bookCode: string | undefined): SourceBook | undefined {
  return bookCode ? BOOK_BY_CODE.get(bookCode) : undefined;
}

export function buildVerseHash(verse: number): string {
  return `#v${verse}`;
}

export function buildReaderPath(bookSlug?: string, chapter?: number): string {
  if (!bookSlug) return "/read";
  if (chapter === undefined) return `/read/${bookSlug}`;
  return `/read/${bookSlug}/${chapter}`;
}

export function buildReaderHref(params: {
  lang: Lang;
  bookSlug: string;
  chapter?: number;
  verse?: number;
}): string {
  const path = buildReaderPath(params.bookSlug, params.chapter);
  const search = getSearchWithLanguage("", params.lang);
  const hash = params.verse === undefined ? "" : buildVerseHash(params.verse);
  return `${path}${search}${hash}`;
}

export function buildReaderHrefFromSource(source: SourceRef | undefined, lang: Lang): string | null {
  if (!source?.book_code || source.chapter === undefined || source.quote_verse_start === undefined) return null;
  const book = getSourceBookByCode(source.book_code);
  if (!book) return null;
  return buildReaderHref({ lang, bookSlug: book.slug, chapter: source.chapter, verse: source.quote_verse_start });
}

export function getOrderedSourceIndexBooks(books: readonly SourceIndexBook[]): SourceIndexBook[] {
  return [...books].sort((left, right) => {
    const leftOrder = ORDER_BY_SLUG.get(left.slug) ?? Number.MAX_SAFE_INTEGER;
    const rightOrder = ORDER_BY_SLUG.get(right.slug) ?? Number.MAX_SAFE_INTEGER;
    return leftOrder - rightOrder;
  });
}

export function getReaderNeighbors(
  books: readonly SourceIndexBook[],
  bookSlug: string,
  chapter: number
): { previous: ReaderNeighbor | null; next: ReaderNeighbor | null } {
  const orderedBooks = getOrderedSourceIndexBooks(books);
  const bookIndex = orderedBooks.findIndex((book) => book.slug === bookSlug);
  if (bookIndex < 0) return { previous: null, next: null };

  const currentBook = orderedBooks[bookIndex];
  const previous =
    chapter > 1
      ? { bookSlug, chapter: chapter - 1 }
      : bookIndex > 0
        ? { bookSlug: orderedBooks[bookIndex - 1]!.slug, chapter: orderedBooks[bookIndex - 1]!.chapter_count }
        : null;
  const next =
    chapter < currentBook.chapter_count
      ? { bookSlug, chapter: chapter + 1 }
      : bookIndex < orderedBooks.length - 1
        ? { bookSlug: orderedBooks[bookIndex + 1]!.slug, chapter: 1 }
        : null;

  return { previous, next };
}
