import { describe, expect, it } from "bun:test";
import { canonicalizeDivineName } from "./divineAliases";
import { normalize } from "./format";

describe("divine aliases", () => {
  it("canonicalizes English divine aliases to God", () => {
    expect(canonicalizeDivineName("the LORD", "en")).toBe("God");
    expect(canonicalizeDivineName("Adonai", "en")).toBe("God");
    expect(canonicalizeDivineName("Hashem", "en")).toBe("God");
  });

  it("canonicalizes Hebrew divine aliases to אלוהים", () => {
    expect(canonicalizeDivineName("יְהוָה", "he")).toBe("אֱלֹהִים");
    expect(canonicalizeDivineName("אֲדֹנָי", "he")).toBe("אֱלֹהִים");
    expect(canonicalizeDivineName("ה׳", "he")).toBe("אֱלֹהִים");
  });

  it("treats divine aliases as equivalent answers", () => {
    expect(normalize("God", "en")).toBe(normalize("the LORD", "en"));
    expect(normalize("God", "en")).toBe(normalize("Hashem", "en"));
    expect(normalize("אלוהים", "he")).toBe(normalize("השם", "he"));
    expect(normalize("אלוהים", "he")).toBe(normalize("יְהוָה", "he"));
  });
});
