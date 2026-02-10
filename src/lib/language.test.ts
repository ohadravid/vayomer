import { describe, expect, it } from "bun:test";
import { DEFAULT_LANGUAGE, normalizeLanguageTag } from "./language";

describe("normalizeLanguageTag", () => {
  it("uses language base tags", () => {
    expect(normalizeLanguageTag("he-IL")).toBe("he");
    expect(normalizeLanguageTag("en-US")).toBe("en");
  });

  it("falls back to default for unsupported values", () => {
    expect(normalizeLanguageTag("fr-FR")).toBe(DEFAULT_LANGUAGE);
    expect(normalizeLanguageTag(null)).toBe(DEFAULT_LANGUAGE);
  });
});
