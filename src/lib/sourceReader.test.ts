import { describe, expect, it } from "vitest";
import type { SourceRef } from "../types";
import {
  buildReaderHref,
  buildReaderHrefFromSource,
  getOrderedSourceIndexBooks,
  getReaderNeighbors,
  getSourceBookByCode,
} from "./sourceReader";

describe("getSourceBookByCode", () => {
  it("returns the canonical book registry entry", () => {
    expect(getSourceBookByCode("EXO")).toMatchObject({ slug: "exodus", en: "Exodus", he: "שמות" });
  });
});

describe("buildReaderHref", () => {
  it("keeps Hebrew canonical and adds English query plus verse hash", () => {
    expect(buildReaderHref({ lang: "he", bookSlug: "exodus", chapter: 33, verse: 5 })).toBe("/read/exodus/33#v5");
    expect(buildReaderHref({ lang: "en", bookSlug: "exodus", chapter: 33, verse: 5 })).toBe("/read/exodus/33?lng=en#v5");
  });
});

describe("buildReaderHrefFromSource", () => {
  it("builds a reader link from canonical source metadata", () => {
    const source: SourceRef = {
      book_code: "EXO",
      book: "Exodus",
      chapter: 33,
      quote_verse_start: 5,
      quote_verse_end: 5,
    };

    expect(buildReaderHrefFromSource(source, "en")).toBe("/read/exodus/33?lng=en#v5");
  });

  it("returns null when the required reader metadata is missing", () => {
    expect(buildReaderHrefFromSource({ book_code: "EXO", chapter: 33 }, "he")).toBeNull();
  });
});

describe("getOrderedSourceIndexBooks", () => {
  it("sorts books into canonical tanakh order", () => {
    const ordered = getOrderedSourceIndexBooks([
      { code: "EXO", slug: "exodus", en: "Exodus", he: "שמות", chapter_count: 40 },
      { code: "GEN", slug: "genesis", en: "Genesis", he: "בראשית", chapter_count: 50 },
    ]);

    expect(ordered.map((book) => book.slug)).toEqual(["genesis", "exodus"]);
  });
});

describe("getReaderNeighbors", () => {
  const books = [
    { code: "GEN", slug: "genesis", en: "Genesis", he: "בראשית", chapter_count: 50 },
    { code: "EXO", slug: "exodus", en: "Exodus", he: "שמות", chapter_count: 40 },
  ];

  it("moves within the current book when possible", () => {
    expect(getReaderNeighbors(books, "exodus", 33)).toEqual({
      previous: { bookSlug: "exodus", chapter: 32 },
      next: { bookSlug: "exodus", chapter: 34 },
    });
  });

  it("moves across book boundaries at the edges", () => {
    expect(getReaderNeighbors(books, "exodus", 1)).toEqual({
      previous: { bookSlug: "genesis", chapter: 50 },
      next: { bookSlug: "exodus", chapter: 2 },
    });
    expect(getReaderNeighbors(books, "genesis", 50)).toEqual({
      previous: { bookSlug: "genesis", chapter: 49 },
      next: { bookSlug: "exodus", chapter: 1 },
    });
  });
});
