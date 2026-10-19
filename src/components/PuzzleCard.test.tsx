import React from "react";
import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { JSDOM } from "jsdom";
import { describe, expect, it, vi } from "vitest";
import { PuzzleCard } from "./PuzzleCard";
import { maskHardWord, pickHardWordPlaceholderForId } from "../lib/format";
import type { Lang, PuzzleItem } from "../types";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { resolvedLanguage: language } }),
}));

let language: Lang = "en";
const puzzles = ["006", "009", "011"].flatMap((chapter) => {
  const payload = JSON.parse(readFileSync(`data/manual_quotes/genesis-${chapter}.json`, "utf8"));
  return payload.items as PuzzleItem[];
});

function renderCard(puzzle: PuzzleItem, props: { revealed?: boolean; quoteRevealed?: boolean; sourceRevealed?: boolean } = {}) {
  const html = renderToStaticMarkup(
    <PuzzleCard
      puzzle={puzzle}
      revealed={false}
      quoteRevealed={false}
      sourceRevealed={false}
      dateLabel="2026-10-18"
      onClear={() => {}}
      {...props}
    />
  );
  return new JSDOM(html).window.document;
}

describe.each(["en", "he"] as const)("PuzzleCard masking in %s", (lang) => {
  it.each(puzzles)("keeps surrounding text hidden when the bonus is in $id's riddle", (puzzle) => {
    language = lang;
    const document = renderCard(puzzle);
    const text = puzzle[lang];
    const placeholder = pickHardWordPlaceholderForId(puzzle.id);
    const highlighted = document.querySelector("#fullQuote .highlight");

    expect(highlighted?.textContent).toBe(maskHardWord(text.riddle, text.bonus!, placeholder, lang));
    expect(highlighted?.textContent).not.toContain(text.bonus);
    const hiddenText = [...document.querySelectorAll("#fullQuote .quote-hidden.veil")]
      .map((node) => node.textContent).join("");
    expect(hiddenText.length).toBeGreaterThan(0);
    expect(document.querySelector("#puzzleCard.quote-revealed")).toBeNull();
    expect(document.querySelector("#puzzleCard.revealed")).toBeNull();
    expect(document.querySelector("#refLine")?.textContent).toBe("");
  });

  it("keeps the bonus masked when the quote and source are revealed", () => {
    language = lang;
    const puzzle = puzzles[0];
    const document = renderCard(puzzle, { quoteRevealed: true, sourceRevealed: true });
    expect(document.querySelector("#puzzleCard.quote-revealed")).not.toBeNull();
    expect(document.querySelector("#fullQuote .highlight")).not.toBeNull();
    expect(document.querySelector("#fullQuote")?.textContent).not.toContain(puzzle[lang].bonus);
  });

  it("restores the complete quote when answers are revealed", () => {
    language = lang;
    const puzzle = puzzles[0];
    const document = renderCard(puzzle, { revealed: true, sourceRevealed: true });
    expect(document.querySelector("#puzzleCard.revealed")).not.toBeNull();
    expect(document.querySelector("#fullQuote")?.textContent).toBe(puzzle[lang].quote);
  });

  it("hides the full passage if the riddle cannot be located", () => {
    language = lang;
    const puzzle = puzzles[0];
    const mismatched = { ...puzzle, [lang]: { ...puzzle[lang], riddle: "missing riddle" } };
    const document = renderCard(mismatched);
    expect(document.querySelector("#fullQuote > .quote-hidden.veil")?.textContent)
      .toBe(document.querySelector("#fullQuote")?.textContent);
  });
});
