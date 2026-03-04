import { describe, expect, it } from "vitest";
import { DEFAULT_LANGUAGE, getSearchWithLanguage, normalizeLanguageTag, parseLanguageFromSearch, parseLanguageTag } from "./language";

describe("language defaults", () => {
  it("defaults to Hebrew", () => {
    expect(DEFAULT_LANGUAGE).toBe("he");
  });
});

describe("normalizeLanguageTag", () => {
  it("uses language base tags", () => {
    expect(normalizeLanguageTag("he-IL")).toBe("he");
    expect(normalizeLanguageTag("en-US")).toBe("en");
    expect(normalizeLanguageTag("iw")).toBe("he");
  });

  it("falls back to default for unsupported values", () => {
    expect(normalizeLanguageTag("fr-FR")).toBe(DEFAULT_LANGUAGE);
    expect(normalizeLanguageTag(null)).toBe(DEFAULT_LANGUAGE);
  });
});

describe("parseLanguageTag", () => {
  it("returns null for unsupported language tags", () => {
    expect(parseLanguageTag("fr-FR")).toBeNull();
    expect(parseLanguageTag(null)).toBeNull();
  });
});

describe("parseLanguageFromSearch", () => {
  it("reads the language from query params", () => {
    expect(parseLanguageFromSearch("?lng=en")).toBe("en");
    expect(parseLanguageFromSearch("?lng=iw")).toBe("he");
  });

  it("returns null when language is missing", () => {
    expect(parseLanguageFromSearch("?easy=1")).toBeNull();
    expect(parseLanguageFromSearch("")).toBeNull();
  });
});

describe("getSearchWithLanguage", () => {
  it("sets english and keeps other query params", () => {
    expect(getSearchWithLanguage("?easy=1", "en")).toBe("?easy=1&lng=en");
  });

  it("removes language query param for default Hebrew", () => {
    expect(getSearchWithLanguage("?easy=1&lng=en", "he")).toBe("?easy=1");
    expect(getSearchWithLanguage("?lng=en", "he")).toBe("");
  });
});
