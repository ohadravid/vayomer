import { describe, expect, it } from "bun:test";
import { normalize } from "./format";

describe("normalize", () => {
  it("normalizes english case, punctuation, and leading article", () => {
    expect(normalize(" The, Servant! ", "en")).toBe("servant");
  });

  it("normalizes hebrew cantillation and punctuation", () => {
    expect(normalize(" אַבְרָם!! ", "he")).toBe("אברם");
  });

  it("unifies divine-name aliases", () => {
    expect(normalize("God", "en")).toBe(normalize("the LORD", "en"));
    expect(normalize("אֱלֹהִים", "he")).toBe(normalize("יְהוָה", "he"));
  });
});
