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

const SOLVED_HINTED: GuessResult = {
  ...SOLVED,
  hintUsed: true,
};

const CORE_ONLY_NO_HINT: GuessResult = {
  ...CORE_ONLY,
  hintUsed: false,
};

describe("buildShareText", () => {
  it("renders game-style status rows with bonus column", () => {
    const text = buildShareText({
      title: "Vayomer",
      attempts: [WRONG, CORE_ONLY, SOLVED],
      solved: true,
      bonusRequired: true,
      maxTries: 5,
      date: new Date(2026, 1, 11),
      gameUrl: "https://example.com",
    });

    expect(text).toContain("Vayomer 2026-02-11 3/5");
    expect(text).toContain("❌❌⬜⬜");
    expect(text).toContain("✅✅✴️⬜");
    expect(text).toContain("✅✅✳️⬜");
    expect(text).toContain("https://example.com");
  });

  it("uses X score when not solved", () => {
    const text = buildShareText({
      title: "Vayomer",
      attempts: [WRONG, WRONG, WRONG],
      solved: false,
      bonusRequired: true,
      maxTries: 5,
      date: new Date(2026, 1, 11),
    });

    expect(text).toContain("Vayomer 2026-02-11 X/5");
    expect(text).toContain("❌❌⬜⬜");
  });

  it("omits bonus column when puzzle has no bonus", () => {
    const text = buildShareText({
      title: "Vayomer",
      attempts: [WRONG, CORE_ONLY],
      solved: true,
      bonusRequired: false,
      maxTries: 5,
      date: new Date(2026, 1, 11),
    });

    expect(text).toContain("❌❌");
    expect(text).toContain("✅✅");
    expect(text).not.toContain("✅✅✴️");
  });

  it("uses the game emoji set instead of wordle squares", () => {
    const text = buildShareText({
      title: "Vayomer",
      attempts: [WRONG, SOLVED],
      solved: true,
      bonusRequired: true,
      maxTries: 5,
      date: new Date(2026, 1, 11),
    });

    expect(text).toContain("❌❌⬜⬜");
    expect(text).toContain("✅✅✳️⬜");
    expect(text).not.toContain("🟩");
    expect(text).not.toContain("⬛");
  });

  it("shows lightbulb marker only on tries after hint was used", () => {
    const text = buildShareText({
      title: "Vayomer",
      attempts: [CORE_ONLY_NO_HINT, SOLVED_HINTED],
      solved: true,
      bonusRequired: true,
      maxTries: 5,
      date: new Date(2026, 1, 11),
    });

    expect(text).toContain("✅✅✴️⬜");
    expect(text).toContain("✅✅✳️💡");
  });

  it("uses localized title text in the header", () => {
    const text = buildShareText({
      title: "וַיֹּאמֶר",
      attempts: [SOLVED],
      solved: true,
      bonusRequired: true,
      maxTries: 5,
      date: new Date(2026, 1, 11),
    });

    expect(text).toContain("וַיֹּאמֶר 2026-02-11 1/5");
  });

  it("uses custom success emoji for hard mode rows", () => {
    const text = buildShareText({
      title: "Vayomer",
      attempts: [CORE_ONLY, SOLVED],
      solved: true,
      bonusRequired: true,
      successMark: "🔥",
      maxTries: 5,
      date: new Date(2026, 1, 11),
    });

    expect(text).toContain("🔥🔥✴️⬜");
    expect(text).toContain("🔥🔥✳️⬜");
    expect(text).not.toContain("✅✅");
  });

  it("adds grandma emoji in the header for manually selected quotes", () => {
    const manualText = buildShareText({
      title: "Vayomer",
      attempts: [SOLVED],
      solved: true,
      bonusRequired: true,
      manualSource: true,
      maxTries: 5,
      date: new Date(2026, 1, 11),
    });
    const llmText = buildShareText({
      title: "Vayomer",
      attempts: [SOLVED],
      solved: true,
      bonusRequired: true,
      manualSource: false,
      maxTries: 5,
      date: new Date(2026, 1, 11),
    });

    expect(manualText).toContain("Vayomer 👵 2026-02-11 1/5");
    expect(llmText).toContain("Vayomer 2026-02-11 1/5");
    expect(llmText).not.toContain("👵");
  });
});
