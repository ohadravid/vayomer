import { describe, expect, it } from "bun:test";
import { buildShareText } from "./share";
import type { GuessResult } from "../types";

const WRONG: GuessResult = {
  speakerOk: false,
  listenerOk: false,
  portionOk: false,
  bonusOk: false,
};

const CORE_ONLY: GuessResult = {
  speakerOk: true,
  listenerOk: true,
  portionOk: true,
  bonusOk: false,
};

const SOLVED: GuessResult = {
  speakerOk: true,
  listenerOk: true,
  portionOk: true,
  bonusOk: true,
};

describe("buildShareText", () => {
  it("renders a wordle-style grid with bonus column", () => {
    const text = buildShareText({
      attempts: [WRONG, CORE_ONLY, SOLVED],
      solved: true,
      bonusRequired: true,
      maxTries: 5,
      date: new Date(2026, 1, 11),
      gameUrl: "https://example.com",
    });

    expect(text).toContain("Vayomer 2026-02-11 3/5");
    expect(text).toContain("⬛⬛⬜");
    expect(text).toContain("🟩🟩⬛");
    expect(text).toContain("🟩🟩🟩");
    expect(text).toContain("https://example.com");
  });

  it("uses X score when not solved", () => {
    const text = buildShareText({
      attempts: [WRONG, WRONG, WRONG],
      solved: false,
      bonusRequired: true,
      maxTries: 5,
      date: new Date(2026, 1, 11),
    });

    expect(text).toContain("Vayomer 2026-02-11 X/5");
    expect(text).toContain("⬛⬛⬜");
  });

  it("omits bonus column when puzzle has no bonus", () => {
    const text = buildShareText({
      attempts: [WRONG, CORE_ONLY],
      solved: true,
      bonusRequired: false,
      maxTries: 5,
      date: new Date(2026, 1, 11),
    });

    expect(text).toContain("⬛⬛");
    expect(text).toContain("🟩🟩");
    expect(text).not.toContain("🟩🟩⬛");
  });
});
