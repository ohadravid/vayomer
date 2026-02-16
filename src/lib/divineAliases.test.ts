import { describe, expect, it } from "bun:test";
import { canonicalizeDivineName, normalizeDivineAlias } from "./divineAliases";

describe("divineAliases", () => {
  it("uses canonical English and Hebrew display labels", () => {
    expect(canonicalizeDivineName("the LORD", "en")).toBe("God");
    expect(canonicalizeDivineName("יְהוָה", "he")).toBe("אֱלֹהִים");
    expect(canonicalizeDivineName("יְהוָה אֱלֹהִים", "he")).toBe("אֱלֹהִים");
    expect(canonicalizeDivineName("יהוה אלוהים", "he")).toBe("אֱלֹהִים");
  });

  it("normalizes divine aliases to a shared key per language", () => {
    expect(normalizeDivineAlias("God", "en")).toBe(normalizeDivineAlias("the LORD", "en"));
    expect(normalizeDivineAlias("אֱלֹהִים", "he")).toBe(normalizeDivineAlias("יְהוָה", "he"));
  });
});
