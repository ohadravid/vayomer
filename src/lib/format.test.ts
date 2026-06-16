import { describe, expect, it } from "vitest";
import { maskHardWord, normalize } from "./format";

describe("normalize", () => {
  it("normalizes english case, punctuation, and leading article", () => {
    expect(normalize(" The, Servant! ", "en")).toBe("servant");
  });

  it("normalizes hebrew cantillation and punctuation", () => {
    expect(normalize(" אַבְרָם!! ", "he")).toBe("אברם");
  });

  it("normalizes maqaf and space variants the same in Hebrew", () => {
    expect(normalize("מֶלֶךְ־סְדֹם", "he")).toBe(normalize("מֶלֶךְ סְדֹם", "he"));
  });

  it("unifies divine-name aliases", () => {
    expect(normalize("God", "en")).toBe(normalize("the LORD", "en"));
    expect(normalize("אֱלֹהִים", "he")).toBe(normalize("יְהוָה", "he"));
  });
});

describe("maskHardWord", () => {
  it("masks exact matches", () => {
    const masked = maskHardWord("And they hated him.", "hated", "🪧", "en");
    expect(masked).not.toContain("hated");
    expect(masked).toContain("🪧🪧🪧🪧🪧");
  });

  it("masks Hebrew niqqud variants in main-quote text", () => {
    const quote = "וַיּוֹסִפוּ עוֹד שֹׂנֵא אֹתוֹ עַל־חֲלֹמֹתָיו";
    const masked = maskHardWord(quote, "שְׂנֹא", "🪧", "he");
    expect(masked).not.toContain("שֹׂנֵא");
    expect(masked).toContain("🪧🪧🪧");
  });

  it("masks Hebrew niqqud variants that normalize to the same answer", () => {
    const quote = "וְכִֽי־יִהְיֶה אִישׁ שֹׂנֵא לְרֵעֵהוּ";
    const masked = maskHardWord(quote, "שְׂנֹא", "🪧", "he");
    expect(masked).not.toContain("שֹׂנֵא");
    expect(masked).toContain("🪧🪧🪧");
  });

  it("masks Hebrew hint words when the target appears after a maqaf-joined prefix", () => {
    const quote = "כִּי רִנְנַת רְשָׁעִים מִקָּרוֹב וְשִׂמְחַת חָנֵף עֲדֵי־רָֽגַע";
    const masked = maskHardWord(quote, "רֶגַע", "🪧", "he");
    expect(masked).not.toContain("רָֽגַע");
    expect(masked).toContain("עֲדֵי־🪧🪧🪧");
  });

  it("masks the full Hebrew hint token when yod/vav-insensitive matching finds the word", () => {
    const quote = "וַיִּשָּׂא פָנָיו אֶל־הַחַלּוֹן";
    const masked = maskHardWord(quote, "פָּנָֽיו", "🪧", "he");

    expect(masked).not.toContain("פָנָיו");
    expect(masked).not.toContain("🪧🪧יו");
    expect(masked).toContain("🪧🪧🪧🪧");
  });

  it("partially masks Hebrew substring matches while preserving the suffix", () => {
    const quote = "נִסְעָה";
    const masked = maskHardWord(quote, "נֹסְעִ", "🪧", "he");

    expect(masked).not.toContain("נִסְעָ");
    expect(masked).toBe("🪧🪧🪧ה");
  });
});
