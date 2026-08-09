import { describe, expect, it } from "vitest";
import {
  bonusGuessMatches,
  bonusWordLength,
  isBonusGuessComplete,
  sanitizeBonusGuess,
  scoreBonusGuess,
  splitBonusCharacters,
} from "./bonusWord";

describe("bonus word helpers", () => {
  it("keeps letters and apostrophes while ignoring niqqud and other punctuation", () => {
    expect(splitBonusCharacters("הָאָרֶץ")).toEqual(["ה", "א", "ר", "ץ"]);
    expect(splitBonusCharacters("father’s")).toEqual(["f", "a", "t", "h", "e", "r", "'", "s"]);
    expect(bonusWordLength("father's")).toBe(8);
  });

  it("sanitizes pasted text, preserves apostrophes, and caps it to the answer length", () => {
    expect(sanitizeBonusGuess(" F-a.t,h!e?r’s ", "father's")).toBe("Father's");
    expect(sanitizeBonusGuess("הָאָרֶץ!!!", "הָאָרֶץ")).toBe("הארץ");
  });

  it("matches the displayed characters without applying name aliases", () => {
    expect(bonusGuessMatches("father’s", "father's", "en")).toBe(true);
    expect(bonusGuessMatches("LORD", "God", "en")).toBe(false);
    expect(bonusGuessMatches("אתם", "וְאַתֶּם", "he")).toBe(false);
    expect(bonusGuessMatches("הארץ", "הָאָרֶץ", "he")).toBe(true);
  });

  it("requires exactly the displayed number of characters", () => {
    expect(isBonusGuessComplete("lands", "earth")).toBe(true);
    expect(isBonusGuessComplete("land", "earth")).toBe(false);
    expect(isBonusGuessComplete("fathers", "father's")).toBe(false);
    expect(isBonusGuessComplete("father’s", "father's")).toBe(true);
    expect(isBonusGuessComplete("הארץ", "הָאָרֶץ")).toBe(true);
  });

  it("scores exact and misplaced characters in both directions", () => {
    expect(scoreBonusGuess("parse", "spare", "en")).toEqual([
      "present",
      "present",
      "present",
      "present",
      "correct",
    ]);
    expect(scoreBonusGuess("באר", "אבר", "he")).toEqual(["present", "present", "correct"]);
    expect(scoreBonusGuess("fathers'", "father's", "en")).toEqual([
      "correct",
      "correct",
      "correct",
      "correct",
      "correct",
      "correct",
      "present",
      "present",
    ]);
  });

  it("does not over-credit duplicate characters", () => {
    expect(scoreBonusGuess("eerie", "serve", "en")).toEqual([
      "absent",
      "correct",
      "correct",
      "absent",
      "correct",
    ]);
  });
});
