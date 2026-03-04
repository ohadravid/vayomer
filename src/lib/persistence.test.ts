import { describe, expect, it } from "vitest";
import { buildPuzzleStorageKey } from "./persistence";

describe("buildPuzzleStorageKey", () => {
  it("scopes keys by language for the same puzzle", () => {
    expect(buildPuzzleStorageKey("pt0101", "en")).toBe("qs:pt0101:en");
    expect(buildPuzzleStorageKey("pt0101", "he")).toBe("qs:pt0101:he");
    expect(buildPuzzleStorageKey("pt0101", "en")).not.toBe(buildPuzzleStorageKey("pt0101", "he"));
  });
});
