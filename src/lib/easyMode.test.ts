import { describe, expect, it } from "bun:test";
import {
  buildMultipleChoiceOptions,
  resolveChoicePoolsForDifficulty,
  resolveChoicePoolsForPuzzle,
} from "./easyMode";
import { normalize } from "./format";
import type { PuzzleItem } from "../types";

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
    expect(options).toContain("God");
    expect(options).not.toContain("the LORD");
    expect(options).not.toContain("LORD");
    expect(new Set(options).size).toBe(options.length);
    expect(options).toHaveLength(3);
  });

  it("canonicalizes divine-name variants to God", () => {
    const options = buildMultipleChoiceOptions({
      answer: "the LORD",
      pool: ["God", "Moses", "Aaron"],
      lang: "en",
      seed: "puzzle:speaker:canonical-en",
      maxChoices: 4,
    });

    expect(options).toContain("God");
    expect(options).not.toContain("the LORD");
  });

  it("canonicalizes hebrew divine-name variants to אֱלֹהִים", () => {
    const options = buildMultipleChoiceOptions({
      answer: "אֲדֹנָי",
      pool: ["יְהוָה", "משה", "אהרן"],
      lang: "he",
      seed: "puzzle:speaker:canonical-he",
      maxChoices: 4,
    });

    expect(options).toContain("אֱלֹהִים");
    expect(options).not.toContain("אֲדֹנָי");
    expect(options).not.toContain("יְהוָה");
  });

  it("canonicalizes compound hebrew divine-name variants to אֱלֹהִים", () => {
    const options = buildMultipleChoiceOptions({
      answer: "יְהוָה אֱלֹהִים",
      pool: ["יהוה אלוהים", "משה", "אהרן"],
      lang: "he",
      seed: "puzzle:speaker:compound-canonical-he",
      maxChoices: 4,
    });

    expect(options).toContain("אֱלֹהִים");
    expect(options).not.toContain("יהוה אלוהים");
    expect(options).not.toContain("יְהוָה אֱלֹהִים");
  });

  it("deduplicates Hebrew maqaf and space variants as a single option", () => {
    const options = buildMultipleChoiceOptions({
      answer: "מֶלֶךְ־סְדֹם",
      pool: ["מֶלֶךְ סְדֹם", "אַבְרָם", "שָׂרַי"],
      lang: "he",
      seed: "puzzle:speaker:maqaf-he",
      maxChoices: 4,
    });

    const matchingVariantCount = options.filter(
      (option) => normalize(option, "he") === normalize("מֶלֶךְ סְדֹם", "he")
    ).length;
    expect(matchingVariantCount).toBe(1);
  });
});

describe("resolveChoicePoolsForPuzzle", () => {
  it("uses same-book fallback pools", () => {
    const pools = resolveChoicePoolsForPuzzle({
      puzzle: samplePuzzle,
      items: sampleItems,
      lang: "en",
    });

    expect(pools.speaker).toContain("God");
    expect(pools.speaker).toHaveLength(1);
    expect(pools.listener).toContain("Abram");
    expect(pools.listener).toContain("Abraham");
  });
});

describe("resolveChoicePoolsForDifficulty", () => {
  it("uses hard_difficulty_options in hard mode when present", () => {
    const puzzle: PuzzleItem = {
      ...samplePuzzle,
      en: {
        ...samplePuzzle.en,
        options: {
          speaker: ["Easy Speaker"],
          listener: ["Easy Listener"],
        },
        hard_difficulty_options: {
          speaker: ["Hard Speaker"],
          listener: ["Hard Listener"],
        },
      },
    };

    const pools = resolveChoicePoolsForDifficulty({
      puzzle,
      lang: "en",
      easyMode: false,
    });

    expect(pools.speaker).toContain("Hard Speaker");
    expect(pools.listener).toContain("Hard Listener");
    expect(pools.speaker).not.toContain("Easy Speaker");
  });

  it("falls back to options for hard mode when hard_difficulty_options is missing", () => {
    const puzzle: PuzzleItem = {
      ...samplePuzzle,
      en: {
        ...samplePuzzle.en,
        options: {
          speaker: ["Shared Speaker"],
          listener: ["Shared Listener"],
        },
      },
    };

    const pools = resolveChoicePoolsForDifficulty({
      puzzle,
      lang: "en",
      easyMode: false,
    });

    expect(pools.speaker).toContain("Shared Speaker");
    expect(pools.listener).toContain("Shared Listener");
  });
});
