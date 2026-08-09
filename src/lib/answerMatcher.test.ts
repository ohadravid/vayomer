import { describe, expect, it } from "vitest";
import { answersMatch } from "./answerMatcher";

describe("answersMatch", () => {
  it("matches english guesses with or without leading article", () => {
    expect(answersMatch("LORD", "the LORD", "en")).toBe(true);
  });

  it("matches hebrew guesses while ignoring niqqud and punctuation", () => {
    expect(answersMatch("אַבְרָם!!", "אברם", "he")).toBe(true);
  });

  it("requires the same Hebrew letters after removing niqqud", () => {
    expect(answersMatch("מזוזות", "מְזוּזוֹת", "he")).toBe(true);
    expect(answersMatch("מזוזות", "מְזוּזת", "he")).toBe(false);
  });

  it("requires punctuation that separates English word parts", () => {
    expect(answersMatch("father’s", "father's", "en")).toBe(true);
    expect(answersMatch("fathers", "father's", "en")).toBe(false);
  });

  it("does not match different answers", () => {
    expect(answersMatch("Moses", "Aaron", "en")).toBe(false);
  });
});
