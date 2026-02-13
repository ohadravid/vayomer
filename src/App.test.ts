import { describe, expect, it } from "bun:test";
import { getSearchWithEasyMode, parseEasyModeFromSearch, pickEasyModeForNavigation } from "./App";

describe("parseEasyModeFromSearch", () => {
  it("parses explicit easy mode values", () => {
    expect(parseEasyModeFromSearch("?easy=1")).toBe(true);
    expect(parseEasyModeFromSearch("?easy=0")).toBe(false);
  });

  it("returns null when the query param is missing or invalid", () => {
    expect(parseEasyModeFromSearch("?lng=en")).toBeNull();
    expect(parseEasyModeFromSearch("?easy=2")).toBeNull();
  });
});

describe("pickEasyModeForNavigation", () => {
  it("strictly trusts the URL during navigation", () => {
    expect(pickEasyModeForNavigation("?easy=1")).toBe(true);
    expect(pickEasyModeForNavigation("?easy=0")).toBe(false);
    expect(pickEasyModeForNavigation("?lng=en")).toBe(false);
  });
});

describe("getSearchWithEasyMode", () => {
  it("preserves existing language params when toggling easy mode", () => {
    expect(getSearchWithEasyMode("?lng=en", true)).toBe("?lng=en&easy=1");
    expect(getSearchWithEasyMode("?lng=en&easy=1", false)).toBe("?lng=en&easy=0");
  });

  it("creates easy mode query params when missing", () => {
    expect(getSearchWithEasyMode("", true)).toBe("?easy=1");
    expect(getSearchWithEasyMode("", false)).toBe("?easy=0");
  });
});
