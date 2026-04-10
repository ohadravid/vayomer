import { Temporal } from "@js-temporal/polyfill";
import { describe, expect, it } from "vitest";
import { pickDailyItemIndex } from "./daily";
import {
  DEFAULT_EXAMPLE_PUZZLE,
  EXAMPLE_PUZZLES,
  EXAMPLE_SEEN_STORAGE_KEY,
  findExamplePuzzleById,
  hasSeenExample,
  markExampleSeen,
  pickExamplePuzzle,
} from "./examplePuzzles";

function createFakeStorage() {
  const store = new Map<string, string>();
  return {
    getItem(key: string) {
      return store.get(key) ?? null;
    },
    setItem(key: string, value: string) {
      store.set(key, value);
    },
  };
}

describe("examplePuzzles", () => {
  it("loads items from every exampleQuote json file", () => {
    const ids = EXAMPLE_PUZZLES.map((item) => item.id);

    expect(ids).toContain("exodus-03-04-04-example");
    expect(ids).toContain("hp-example-1");
    expect(ids).toContain("hp-example-2");
  });

  it("keeps every example riddle as an exact substring of its quote", () => {
    for (const item of EXAMPLE_PUZZLES) {
      expect(item.en.quote.includes(item.en.riddle)).toBe(true);
      expect(item.he.quote.includes(item.he.riddle)).toBe(true);
    }
  });

  it("uses the regular bible example before the seen marker exists", () => {
    expect(pickExamplePuzzle("hp-example-1", false)?.id).toBe(DEFAULT_EXAMPLE_PUZZLE?.id);
  });

  it("uses the same daily picker after the seen marker exists", () => {
    const date = Temporal.PlainDate.from("2026-04-08");
    const expected = EXAMPLE_PUZZLES[pickDailyItemIndex(EXAMPLE_PUZZLES, date)];

    expect(pickExamplePuzzle(null, true, date)?.id).toBe(expected?.id);
  });

  it("resolves an explicit example by id once the seen marker exists", () => {
    expect(findExamplePuzzleById("hp-example-1")?.en.book).toBe("Harry Potter and the Philosopher's Stone");
    expect(pickExamplePuzzle("hp-example-1", true)?.id).toBe("hp-example-1");
  });

  it("stores and reads the seen marker in local storage", () => {
    const storage = createFakeStorage();

    expect(hasSeenExample(storage)).toBe(false);
    markExampleSeen(storage);

    expect(storage.getItem(EXAMPLE_SEEN_STORAGE_KEY)).toBe("1");
    expect(hasSeenExample(storage)).toBe(true);
  });
});
