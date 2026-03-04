import { afterEach, describe, expect, it } from "vitest";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { createInstance } from "i18next";
import { I18nextProvider, initReactI18next } from "react-i18next";
import { QuoteBrowser } from "./DebugPage";
import { resources } from "./i18n";
import type { Lang, PuzzleItem } from "./types";

function createI18n(lang: Lang) {
  const i18n = createInstance();
  void i18n.use(initReactI18next).init({
    resources,
    lng: lang,
    fallbackLng: "en",
    supportedLngs: ["en", "he"],
    load: "languageOnly",
    interpolation: { escapeValue: false },
    initImmediate: false,
  });
  return i18n;
}

function renderQuoteBrowser(lang: Lang, items: PuzzleItem[]) {
  const i18n = createI18n(lang);
  return (
    <I18nextProvider i18n={i18n}>
      <QuoteBrowser lang={lang} items={items} />
    </I18nextProvider>
  );
}

const puzzleWithDifficultyOptions: PuzzleItem = {
  id: "genesis-12-01-01",
  en: {
    book: "Genesis",
    quote: "Now God said to Abram.",
    riddle: "Now God said to Abram.",
    speaker: "God",
    listener: "Abram",
    options: {
      speaker: ["God", "Moses"],
      listener: ["Abram", "Sarah"],
    },
    bonus_hint: {
      quote: "Get thee out unto the land that I will show thee.",
      source: {
        book: "Genesis",
        chapter: 12,
        start: 1,
        end: 2,
      },
    },
  },
  he: {
    book: "בראשית",
    quote: "וַיֹּאמֶר אֱלֹהִים אֶל־אַבְרָם.",
    riddle: "וַיֹּאמֶר אֱלֹהִים אֶל־אַבְרָם.",
    speaker: "אֱלֹהִים",
    listener: "אַבְרָם",
    options: {
      speaker: ["אֱלֹהִים", "משה"],
      listener: ["אַבְרָם", "שָׂרָה"],
    },
    bonus_hint: {
      quote: "לֶךְ־לְךָ אֶל־הָאָרֶץ אֲשֶׁר אַרְאֶךָּ",
      source: {
        book: "בראשית",
        chapter: 12,
        start: 1,
        end: 2,
      },
    },
  },
  source: {
    ref_start: "Genesis 12:1",
    ref_end: "Genesis 12:1",
  },
};

const puzzleWithoutDifficultyOptions: PuzzleItem = {
  ...puzzleWithDifficultyOptions,
  id: "genesis-12-01-02",
  en: {
    ...puzzleWithDifficultyOptions.en,
    options: null,
    bonus_hint: null,
  },
  he: {
    ...puzzleWithDifficultyOptions.he,
    options: null,
    bonus_hint: null,
  },
};

let root: ReactTestRenderer | null = null;

afterEach(() => {
  if (root) {
    act(() => root?.unmount());
    root = null;
  }
});

describe("QuoteBrowser difficulty option rows", () => {
  it("shows options values in the answers card", () => {
    act(() => {
      root = create(renderQuoteBrowser("en", [puzzleWithDifficultyOptions]));
    });

    const rendered = JSON.stringify(root?.toJSON());
    expect(rendered).toContain("Bonus hint");
    expect(rendered).toContain("Get thee out unto the land that I will show thee.");
    expect(rendered).toContain("Genesis 12:1-2");
    expect(rendered).toContain("Options");
    expect(rendered).toContain("God, Moses");
    expect(rendered).toContain("Abram, Sarah");
  });

  it("shows Not set when difficulty options are missing", () => {
    act(() => {
      root = create(renderQuoteBrowser("en", [puzzleWithoutDifficultyOptions]));
    });

    const rendered = JSON.stringify(root?.toJSON());
    expect(rendered).toContain("Bonus hint");
    expect(rendered).toContain("Options");
    expect(rendered).toContain("Not set");
    expect(rendered.split("Not set").length - 1).toBe(2);
  });
});
