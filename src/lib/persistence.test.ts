import { describe, expect, it } from "vitest";
import { buildPuzzleStorageKey } from "./persistence";

describe("buildPuzzleStorageKey", () => {
  it("stores one shared key per puzzle", () => {
    expect(buildPuzzleStorageKey("pt0101")).toBe("qs:pt0101");
  });
});
