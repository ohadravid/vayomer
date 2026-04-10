import { describe, expect, it } from "vitest";
import { compareDailyOrderIds } from "../../scripts/prepare_quote_assets";
import manifest from "./puzzleManifest.json";

describe("puzzleManifest", () => {
  it("is generated in seeded daily order", () => {
    const ids = manifest.map((entry) => entry.id);
    const expectedIds = [...ids].sort((left, right) => compareDailyOrderIds(left, right));

    expect(ids).toEqual(expectedIds);
  });
});
