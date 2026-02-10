import { describe, expect, it } from "bun:test";
import { buildMultipleChoiceOptions, parseOptionsDataset, resolveChoicePoolsForPuzzle } from "./easyMode";
import type { BookOptionSet, PuzzleItem } from "../types";

const samplePuzzle: PuzzleItem = {
  id: "genesis-12-01-01",
  en: {
    book: "Genesis",
    quote: "quote",
    riddle: "riddle",
    speaker: "the LORD",
    listener: "Abram",
    bonus: "land",
  },
  he: {
    book: "בראשית",
    quote: "ציטוט",
    riddle: "חידה",
    speaker: "אֲדֹנָי",
    listener: "אַבְרָם",
    bonus: "הארץ",
  },
  portion: { en: "Lech-Lecha", he: "לך-לך" },
};

const sampleItems: PuzzleItem[] = [
  samplePuzzle,
  {
    ...samplePuzzle,
    id: "genesis-22-01-01",
    en: { ...samplePuzzle.en, speaker: "God", listener: "Abraham", bonus: "son" },
    he: { ...samplePuzzle.he, speaker: "אֱלֹהִים", listener: "אברהם", bonus: "בן" },
    portion: { en: "Vayera", he: "וירא" },
  },
];

describe("buildMultipleChoiceOptions", () => {
  it("is deterministic and always includes the answer", () => {
    const pool = ["Moses", "Isaac", "Abraham", "Pharaoh", "Aaron"];
    const a = buildMultipleChoiceOptions({
      answer: "Abraham",
      pool,
      lang: "en",
      seed: "puzzle:listener",
    });
    const b = buildMultipleChoiceOptions({
      answer: "Abraham",
      pool,
      lang: "en",
      seed: "puzzle:listener",
    });
    expect(a).toEqual(b);
    expect(a).toContain("Abraham");
    expect(a).toHaveLength(4);
  });

  it("deduplicates equivalent values and respects maxChoices", () => {
    const options = buildMultipleChoiceOptions({
      answer: "the LORD",
      pool: ["the LORD", "LORD", "Moses", "Moses", "Aaron", "Isaac"],
      lang: "en",
      seed: "puzzle:speaker",
      maxChoices: 3,
    });
    expect(options).toContain("the LORD");
    expect(new Set(options).size).toBe(options.length);
    expect(options).toHaveLength(3);
  });

  it("canonicalizes divine name variants in English options", () => {
    const options = buildMultipleChoiceOptions({
      answer: "God",
      pool: ["the LORD", "Adonai", "Moses", "Aaron"],
      lang: "en",
      seed: "puzzle:speaker:canonical-en",
      maxChoices: 4,
    });
    expect(options).toContain("the LORD");
    expect(options).not.toContain("God");
  });

  it("canonicalizes divine name variants in Hebrew options", () => {
    const options = buildMultipleChoiceOptions({
      answer: "אֱלֹהִים",
      pool: ["אֲדֹנָי", "השם", "משה", "אהרן"],
      lang: "he",
      seed: "puzzle:speaker:canonical-he",
      maxChoices: 4,
    });
    expect(options).toContain("אדני");
    expect(options).not.toContain("אֱלֹהִים");
  });
});

describe("resolveChoicePoolsForPuzzle", () => {
  it("merges static and fallback pools for a matching book", () => {
    const optionSets: BookOptionSet[] = [
      {
        book: { en: "Genesis", he: "בראשית" },
        speaker: { en: ["Jacob"], he: ["יעקב"] },
        listener: { en: ["Joseph"], he: ["יוסף"] },
        portion: { en: ["Noach"], he: ["נח"] },
      },
    ];
    const pools = resolveChoicePoolsForPuzzle({
      puzzle: samplePuzzle,
      items: sampleItems,
      optionSets,
      lang: "en",
    });

    expect(pools.speaker).toContain("Jacob");
    expect(pools.speaker).toContain("the LORD");
    expect(pools.listener).toContain("Joseph");
    expect(pools.listener).toContain("Abram");
  });
});

describe("parseOptionsDataset", () => {
  it("returns an empty list for invalid data", () => {
    expect(parseOptionsDataset(null)).toEqual([]);
    expect(parseOptionsDataset({})).toEqual([]);
    expect(parseOptionsDataset({ books: [{}] })).toEqual([]);
  });
});
