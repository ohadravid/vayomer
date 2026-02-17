import { describe, expect, it } from "bun:test";
import {
  buildDifficultyLockStorageKey,
  getSearchWithEasyMode,
  parseDifficultyLockFromStorageValue,
  parseEasyModeFromSearch,
  parsePersistedState,
  parsePuzzleIdFromSearch,
  pruneDifficultyLockKeys,
  pickEasyModeForNavigation,
  pickPuzzleIndexForSearch,
  toDifficultyLockStorageValue,
} from "./App";
import type { PuzzleItem } from "./types";
import packageMeta from "../package.json";

const CURRENT_VERSION = packageMeta.version;

describe("parseEasyModeFromSearch", () => {
  it("parses explicit easy mode values", () => {
    expect(parseEasyModeFromSearch("?easy=0")).toBe(true);
    expect(parseEasyModeFromSearch("?easy=1")).toBe(false);
  });

  it("returns null when the query param is missing or invalid", () => {
    expect(parseEasyModeFromSearch("?lng=en")).toBeNull();
    expect(parseEasyModeFromSearch("?easy=2")).toBeNull();
  });
});

describe("pickEasyModeForNavigation", () => {
  it("strictly trusts the URL during navigation", () => {
    expect(pickEasyModeForNavigation("?easy=0")).toBe(true);
    expect(pickEasyModeForNavigation("?easy=1")).toBe(false);
    expect(pickEasyModeForNavigation("?lng=en")).toBe(true);
  });
});

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

describe("getSearchWithEasyMode", () => {
  it("keeps URL canonical for default easy mode", () => {
    expect(getSearchWithEasyMode("?lng=en", true)).toBe("?lng=en");
    expect(getSearchWithEasyMode("?lng=en&easy=0", true)).toBe("?lng=en");
  });

  it("writes easy=1 for explicit non-default mode", () => {
    expect(getSearchWithEasyMode("", false)).toBe("?easy=1");
    expect(getSearchWithEasyMode("?lng=en&easy=0", false)).toBe("?lng=en&easy=1");
  });
});

describe("difficulty lock storage", () => {
  it("builds puzzle-scoped keys", () => {
    expect(buildDifficultyLockStorageKey("genesis-12-01-01")).toBe("qs:difficulty-lock:genesis-12-01-01");
  });

  it("parses and serializes lock values", () => {
    expect(String(toDifficultyLockStorageValue(true))).toBe("1");
    expect(String(toDifficultyLockStorageValue(false))).toBe("0");
    expect(parseDifficultyLockFromStorageValue("1")).toBe(true);
    expect(parseDifficultyLockFromStorageValue("0")).toBe(false);
    expect(parseDifficultyLockFromStorageValue("x")).toBeNull();
  });

  it("prunes old puzzle locks and keeps only the selected puzzle lock", () => {
    const entries = new Map<string, string>([
      ["qs:difficulty-lock:genesis-06-13-13", "1"],
      ["qs:difficulty-lock:genesis-12-01-01", "0"],
      ["qs:easy-mode", "1"],
    ]);
    const fakeStorage = {
      get length() {
        return entries.size;
      },
      key(index: number): string | null {
        return Array.from(entries.keys())[index] ?? null;
      },
      removeItem(key: string): void {
        entries.delete(key);
      },
    };

    pruneDifficultyLockKeys(fakeStorage, "genesis-12-01-01");

    expect(entries.has("qs:difficulty-lock:genesis-06-13-13")).toBe(false);
    expect(entries.has("qs:difficulty-lock:genesis-12-01-01")).toBe(true);
    expect(entries.has("qs:easy-mode")).toBe(true);
  });
});

describe("parsePersistedState", () => {
  it("drops state when persisted version differs from current app version", () => {
    const raw = JSON.stringify({
      version: "0.0.1",
      lang: "he",
      speaker: "אֲדֹנָי",
      listener: "אַבְרָם",
      portion: "",
      bonus: "הָאָרֶץ",
      attempts: [{ speakerOk: true, listenerOk: true, portionOk: true, bonusOk: true }],
      revealed: true,
    });

    const parsed = parsePersistedState(raw, "he", CURRENT_VERSION);
    expect(parsed).toBeNull();
  });

  it("drops state when version is missing", () => {
    const raw = JSON.stringify({
      lang: "he",
      speaker: "אֲדֹנָי",
      listener: "אַבְרָם",
      portion: "",
      bonus: "הָאָרֶץ",
      attempts: [{ speakerOk: true, listenerOk: true, portionOk: true, bonusOk: true }],
      revealed: true,
    });

    const parsed = parsePersistedState(raw, "he", CURRENT_VERSION);
    expect(parsed).toBeNull();
  });

  it("ignores revealed=true when there is no solved core attempt", () => {
    const raw = JSON.stringify({
      version: CURRENT_VERSION,
      lang: "he",
      speaker: "",
      listener: "",
      portion: "",
      bonus: "",
      attempts: [],
      revealed: true,
    });

    const parsed = parsePersistedState(raw, "he", CURRENT_VERSION);
    expect(parsed?.revealed).toBe(false);
  });

  it("keeps revealed=true when a solved core attempt exists", () => {
    const raw = JSON.stringify({
      version: CURRENT_VERSION,
      lang: "he",
      speaker: "אֲדֹנָי",
      listener: "אַבְרָם",
      portion: "",
      bonus: "הָאָרֶץ",
      attempts: [{ speakerOk: true, listenerOk: true, portionOk: true, bonusOk: true }],
      revealed: true,
    });

    const parsed = parsePersistedState(raw, "he", CURRENT_VERSION);
    expect(parsed?.revealed).toBe(true);
  });

  it("keeps hintRevealed=true when explicitly persisted", () => {
    const raw = JSON.stringify({
      version: CURRENT_VERSION,
      lang: "he",
      speaker: "אֲדֹנָי",
      listener: "אַבְרָם",
      portion: "",
      bonus: "הָאָרֶץ",
      attempts: [{ speakerOk: true, listenerOk: true, portionOk: true, bonusOk: true }],
      revealed: true,
      hintRevealed: true,
    });

    const parsed = parsePersistedState(raw, "he", CURRENT_VERSION);
    expect(parsed?.hintRevealed).toBe(true);
  });

  it("restores hintRevealed when bonus hint was used", () => {
    const raw = JSON.stringify({
      version: CURRENT_VERSION,
      lang: "he",
      speaker: "אֲדֹנָי",
      listener: "אַבְרָם",
      portion: "",
      bonus: "הָאָרֶץ",
      attempts: [{ speakerOk: true, listenerOk: true, portionOk: true, bonusOk: false, countsAsTry: false }],
      revealed: false,
      bookHintUsed: true,
      hintRevealed: false,
    });

    const parsed = parsePersistedState(raw, "he", CURRENT_VERSION);
    expect(parsed?.revealed).toBe(false);
    expect(parsed?.bookHintUsed).toBe(true);
    expect(parsed?.hintRevealed).toBe(true);
  });
});
