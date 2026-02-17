import { describe, expect, it } from "bun:test";
import { answersMatch, normalizeForAnswerMatch } from "./answerMatcher";

describe("answersMatch", () => {
  it("matches english guesses with or without leading article", () => {
    expect(answersMatch("LORD", "the LORD", "en")).toBe(true);
  });

  it("matches hebrew guesses while ignoring niqqud and punctuation", () => {
    expect(answersMatch("אַבְרָם!!", "אברם", "he")).toBe(true);
  });

  it("does not match different answers", () => {
    expect(answersMatch("Moses", "Aaron", "en")).toBe(false);
  });
});

describe("normalizeForAnswerMatch", () => {
  it("applies default normalization", () => {
    expect(normalizeForAnswerMatch(" The, Servant! ", "en")).toBe("servant");
  });
});
