import { describe, expect, it } from "vitest";
import {
  parsePersistedState,
  parsePuzzleIdFromSearch,
  pickPuzzleIndexForSearch,
  resolvePersistedGameFields,
} from "./App";
import type { PuzzleItem } from "./types";
import packageMeta from "../package.json";

const CURRENT_VERSION = packageMeta.version;
const hydrationPuzzle: PuzzleItem = {
  id: "hydra-puzzle",
  en: {
    book: "Genesis",
    quote: "Now the LORD said unto Abram.",
    riddle: "Now the LORD said unto Abram.",
    speaker: "the LORD",
    listener: "Abram",
    bonus: "land",
  },
  he: {
    book: "בראשית",
    quote: "וַיֹּאמֶר אֲדֹנָי אֶל-אַבְרָם.",
    riddle: "וַיֹּאמֶר אֲדֹנָי אֶל-אַבְרָם.",
    speaker: "אֲדֹנָי",
    listener: "אַבְרָם",
    bonus: "הָאָרֶץ",
  },
};

describe("parsePuzzleIdFromSearch", () => {
  it("returns the puzzle id from query params", () => {
    expect(parsePuzzleIdFromSearch("?puzzle=genesis-16-06-06")).toBe("genesis-16-06-06");
    expect(parsePuzzleIdFromSearch("?lng=en&puzzle=genesis-16-06-06")).toBe("genesis-16-06-06");
  });

  it("returns null when puzzle is missing or blank", () => {
    expect(parsePuzzleIdFromSearch("?lng=en")).toBeNull();
    expect(parsePuzzleIdFromSearch("?puzzle=")).toBeNull();
    expect(parsePuzzleIdFromSearch("?puzzle=%20")).toBeNull();
  });
});

describe("pickPuzzleIndexForSearch", () => {
  const puzzles: PuzzleItem[] = [
    {
      id: "puzzle-a",
      en: { book: "Genesis", quote: "a", riddle: "a", speaker: "A", listener: "B", bonus: "x" },
      he: { book: "בראשית", quote: "א", riddle: "א", speaker: "א", listener: "ב", bonus: "איקס" },
    },
    {
      id: "puzzle-b",
      en: { book: "Genesis", quote: "b", riddle: "b", speaker: "C", listener: "D", bonus: "y" },
      he: { book: "בראשית", quote: "ב", riddle: "ב", speaker: "ג", listener: "ד", bonus: "ואי" },
    },
  ];

  it("picks explicit puzzle id when present", () => {
    expect(pickPuzzleIndexForSearch(puzzles, "?puzzle=puzzle-b")).toBe(1);
  });

  it("falls back to daily selection when id is missing or unknown", () => {
    expect(pickPuzzleIndexForSearch(puzzles, "")).toBeGreaterThanOrEqual(0);
    expect(pickPuzzleIndexForSearch(puzzles, "")).toBeLessThan(puzzles.length);
    expect(pickPuzzleIndexForSearch(puzzles, "?puzzle=unknown")).toBeGreaterThanOrEqual(0);
    expect(pickPuzzleIndexForSearch(puzzles, "?puzzle=unknown")).toBeLessThan(puzzles.length);
  });
});

describe("parsePersistedState", () => {
  it("drops state when persisted version differs from current app version", () => {
    const raw = JSON.stringify({
      version: "0.0.1",
      drafts: {
        he: {
          speaker: "אֲדֹנָי",
          listener: "אַבְרָם",
          portion: "",
          bonus: "הָאָרֶץ",
        },
      },
      attempts: [{ speakerOk: true, listenerOk: true, portionOk: true, bonusOk: true }],
      revealed: true,
    });

    const parsed = parsePersistedState(raw, CURRENT_VERSION);
    expect(parsed).toBeNull();
  });

  it("drops state when required shared fields are missing", () => {
    const raw = JSON.stringify({
      version: CURRENT_VERSION,
      revealed: false,
    });

    const parsed = parsePersistedState(raw, CURRENT_VERSION);
    expect(parsed).toBeNull();
  });

  it("ignores revealed=true when there is no solved core attempt", () => {
    const raw = JSON.stringify({
      version: CURRENT_VERSION,
      drafts: {
        he: {
          speaker: "",
          listener: "",
          portion: "",
          bonus: "",
        },
      },
      attempts: [],
      revealed: true,
    });

    const parsed = parsePersistedState(raw, CURRENT_VERSION);
    expect(parsed?.revealed).toBe(false);
  });

  it("keeps revealed=true when a solved core attempt exists", () => {
    const raw = JSON.stringify({
      version: CURRENT_VERSION,
      drafts: {
        he: {
          speaker: "אֲדֹנָי",
          listener: "אַבְרָם",
          portion: "",
          bonus: "הָאָרֶץ",
        },
      },
      attempts: [{ speakerOk: true, listenerOk: true, portionOk: true, bonusOk: true }],
      revealed: true,
    });

    const parsed = parsePersistedState(raw, CURRENT_VERSION);
    expect(parsed?.revealed).toBe(true);
  });

  it("keeps hintRevealed=true when explicitly persisted", () => {
    const raw = JSON.stringify({
      version: CURRENT_VERSION,
      drafts: {
        he: {
          speaker: "אֲדֹנָי",
          listener: "אַבְרָם",
          portion: "",
          bonus: "הָאָרֶץ",
        },
      },
      attempts: [{ speakerOk: true, listenerOk: true, portionOk: true, bonusOk: true }],
      revealed: true,
      hintRevealed: true,
    });

    const parsed = parsePersistedState(raw, CURRENT_VERSION);
    expect(parsed?.hintRevealed).toBe(true);
  });

  it("keeps only structurally valid attempts", () => {
    const raw = JSON.stringify({
      version: CURRENT_VERSION,
      drafts: {
        he: {
          speaker: "אֲדֹנָי",
          listener: "אַבְרָם",
          portion: "",
          bonus: "הָאָרֶץ",
        },
      },
      attempts: [
        { speakerOk: true, listenerOk: true, portionOk: true, bonusOk: false },
        { speakerOk: true, listenerOk: true, portionOk: true },
      ],
      revealed: false,
    });

    const parsed = parsePersistedState(raw, CURRENT_VERSION);
    expect(parsed?.attempts).toHaveLength(1);
    expect(parsed?.attempts[0]).toMatchObject({
      speakerOk: true,
      listenerOk: true,
      portionOk: true,
      bonusOk: false,
    });
  });
});

describe("resolvePersistedGameFields", () => {
  it("hydrates the current language draft and shared progress", () => {
    const state = parsePersistedState(
      JSON.stringify({
        version: CURRENT_VERSION,
        drafts: {
          he: {
            speaker: "אֲדֹנָי",
            listener: "אַבְרָם",
            portion: "",
            bonus: "טיוטה",
          },
        },
        attempts: [{ speakerOk: true, listenerOk: true, portionOk: true, bonusOk: false }],
        hintRevealed: true,
        revealed: false,
      }),
      CURRENT_VERSION
    );

    expect(state).not.toBeNull();
    const resolved = resolvePersistedGameFields(state!, hydrationPuzzle, "he");

    expect(resolved).toMatchObject({
      speaker: "אֲדֹנָי",
      listener: "אַבְרָם",
      bonus: "טיוטה",
      hintRevealed: true,
    });
    expect(resolved.attempts).toHaveLength(1);
  });

  it("prefills the active language with correct locked answers when stage two is already open", () => {
    const state = parsePersistedState(
      JSON.stringify({
        version: CURRENT_VERSION,
        drafts: {
          he: {
            speaker: "אֲדֹנָי",
            listener: "אַבְרָם",
            portion: "",
            bonus: "טיוטה",
          },
        },
        attempts: [{ speakerOk: true, listenerOk: true, portionOk: true, bonusOk: false }],
        hintRevealed: false,
        revealed: false,
      }),
      CURRENT_VERSION
    );

    expect(state).not.toBeNull();
    const resolved = resolvePersistedGameFields(state!, hydrationPuzzle, "en");

    expect(resolved).toMatchObject({
      speaker: "the LORD",
      listener: "Abram",
      bonus: "",
      hintRevealed: false,
    });
  });

  it("prefills the solved bonus in the active language when that draft is missing", () => {
    const state = parsePersistedState(
      JSON.stringify({
        version: CURRENT_VERSION,
        drafts: {
          he: {
            speaker: "אֲדֹנָי",
            listener: "אַבְרָם",
            portion: "",
            bonus: "הָאָרֶץ",
          },
        },
        attempts: [{ speakerOk: true, listenerOk: true, portionOk: true, bonusOk: true }],
        hintRevealed: false,
        revealed: true,
      }),
      CURRENT_VERSION
    );

    expect(state).not.toBeNull();
    const resolved = resolvePersistedGameFields(state!, hydrationPuzzle, "en");

    expect(resolved).toMatchObject({
      speaker: "the LORD",
      listener: "Abram",
      bonus: "land",
    });
  });
});
