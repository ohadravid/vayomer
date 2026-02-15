import { describe, expect, it } from "bun:test";
import { normalize } from "./format";

describe("normalize", () => {
  it("normalizes english case, punctuation, and leading article", () => {
    expect(normalize(" The, Servant! ", "en")).toBe("servant");
  });

  it("normalizes hebrew cantillation and punctuation", () => {
    expect(normalize(" אֲדֹנָי!! ", "he")).toBe("אדני");
  });

  it("does not unify divine-name aliases", () => {
    expect(normalize("God", "en")).not.toBe(normalize("the LORD", "en"));
    expect(normalize("אלוהים", "he")).not.toBe(normalize("יְהוָה", "he"));
  });
});
