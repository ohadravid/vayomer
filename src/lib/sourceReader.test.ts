import { describe, expect, it } from "vitest";
import type { SourceRef } from "../types";
import { buildReaderHref, buildReaderHrefFromSource, parseReaderRoute, slugifyBookName } from "./sourceReader";

describe("slugifyBookName", () => {
  it("matches the source-reader book slug format", () => {
    expect(slugifyBookName("Exodus")).toBe("exodus");
    expect(slugifyBookName("1 Samuel")).toBe("1-samuel");
    expect(slugifyBookName("Song of Songs")).toBe("song-of-songs");
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

describe("parseReaderRoute", () => {
  it("parses the supported reader paths", () => {
    expect(parseReaderRoute("/read")).toEqual({ kind: "read-books" });
    expect(parseReaderRoute("/read/exodus")).toEqual({ kind: "read-book", bookSlug: "exodus" });
    expect(parseReaderRoute("/read/exodus/33")).toEqual({ kind: "read-chapter", bookSlug: "exodus", chapter: 33 });
  });

  it("returns a reader not-found route for invalid /read paths", () => {
    expect(parseReaderRoute("/read/exodus/not-a-chapter")).toEqual({ kind: "read-not-found" });
    expect(parseReaderRoute("/read/exodus/33/extra")).toEqual({ kind: "read-not-found" });
  });

  it("returns null for non-reader paths", () => {
    expect(parseReaderRoute("/")).toBeNull();
    expect(parseReaderRoute("/preview")).toBeNull();
  });
});
