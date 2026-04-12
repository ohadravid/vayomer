import { afterEach, describe, expect, it } from "vitest";
import React, { StrictMode, act } from "react";
import { cleanup, fireEvent, render, type RenderResult } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import userEvent from "@testing-library/user-event";
import { JSDOM } from "jsdom";
import { createInstance } from "i18next";
import { I18nextProvider, initReactI18next } from "react-i18next";
import { PuzzleView } from "./PuzzleView";
import { resources } from "../i18n";
import { pickHardWordPlaceholderForId } from "../lib/format";
import type { GuessResult, Lang, PuzzleItem } from "../types";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "https://example.test/" });
const { window } = dom;

Object.assign(globalThis, {
  window,
  document: window.document,
  HTMLElement: window.HTMLElement,
  HTMLInputElement: window.HTMLInputElement,
  HTMLSelectElement: window.HTMLSelectElement,
  Event: window.Event,
  MouseEvent: window.MouseEvent,
  KeyboardEvent: window.KeyboardEvent,
  MutationObserver: window.MutationObserver,
  getComputedStyle: window.getComputedStyle.bind(window),
  requestAnimationFrame: (cb: FrameRequestCallback) => setTimeout(() => cb(Date.now()), 0),
  cancelAnimationFrame: (id: number) => clearTimeout(id),
});
Object.defineProperty(globalThis, "navigator", {
  value: window.navigator,
  configurable: true,
});
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

type LegacyAttach = ((type: string, listener: EventListener) => void) | undefined;
if (!(window.HTMLElement.prototype as unknown as { attachEvent?: LegacyAttach }).attachEvent) {
  (window.HTMLElement.prototype as unknown as { attachEvent: LegacyAttach }).attachEvent = () => {};
}
if (!(window.HTMLElement.prototype as unknown as { detachEvent?: LegacyAttach }).detachEvent) {
  (window.HTMLElement.prototype as unknown as { detachEvent: LegacyAttach }).detachEvent = () => {};
}

const puzzle: PuzzleItem = {
  id: "genesis-12-01-01",
  en: {
    book: "Genesis",
    quote: "Now the LORD said unto Abram.",
    riddle: "Now the LORD said unto Abram.",
    speaker: "the LORD",
    listener: "Abram",
    bonus: "land",
  },
  he: {
    book: "בראשית",
    quote: "וַיֹּאמֶר אֲדֹנָי אֶל-אַבְרָם.",
    riddle: "וַיֹּאמֶר אֲדֹנָי אֶל-אַבְרָם.",
    speaker: "אֲדֹנָי",
    listener: "אַבְרָם",
    bonus: "הָאָרֶץ",
  },
  portion: { en: "Lech-Lecha", he: "לך-לך" },
  source: { book_code: "GEN", book: "Genesis", book_he: "בראשית", chapter: 12, quote_verse_start: 1, quote_verse_end: 1, ref_start: "Genesis 12:1", ref_end: "Genesis 12:1" },
};

const puzzleWithHint: PuzzleItem = {
  ...puzzle,
  en: {
    ...puzzle.en,
    bonus_hint: {
      quote: "Now the LORD said unto Abram, Get thee out unto the land that I will show thee.",
      source: { book: "Genesis", chapter: 12, start: 1, end: 1 },
    },
  },
  he: {
    ...puzzle.he,
    bonus_hint: {
      quote: "לֶךְ־לְךָ אֶל־הָאָרֶץ אֲשֶׁר אַרְאֶךָּ",
      source: { book: "בראשית", chapter: 12, start: 1, end: 1 },
    },
  },
};

const puzzleWithHebrewHintSpellingMismatch: PuzzleItem = {
  ...puzzleWithHint,
  id: "manual-genesis-37-07-09-69be8e9c",
  he: {
    ...puzzleWithHint.he,
    quote:
      "וַיֹּאמְרוּ לוֹ אֶחָיו הֲמָלֹךְ תִּמְלֹךְ עָלֵינוּ אִם־מָשׁוֹל תִּמְשֹׁל בָּנוּ וַיּוֹסִפוּ עוֹד שֹׂנֵא אֹתוֹ עַל־חֲלֹמֹתָיו וְעַל־דְּבָרָיו",
    riddle: "הֲמָלֹךְ תִּמְלֹךְ עָלֵינוּ",
    speaker: "אֶחָיו",
    listener: "יוֹסֵף",
    bonus: "שְׂנֹא",
    bonus_hint: {
      quote: "וְכִֽי־יִהְיֶה אִישׁ שֹׂנֵא לְרֵעֵהוּ וְאָרַב לוֹ",
      source: { book: "דברים", chapter: 19, start: 11, end: 11 },
    },
  },
};

const puzzleWithBonusBeforeRiddleHe: PuzzleItem = {
  ...puzzle,
  id: "genesis-17-01-bonus-before-riddle",
  en: {
    ...puzzle.en,
    quote: "And when Abram was ninety years old and nine, the LORD appeared to Abram.",
    riddle: "the LORD appeared to Abram.",
    bonus: "nine",
  },
  he: {
    ...puzzle.he,
    quote:
      "וַיְהִי אַבְרָם בֶּן־תִּשְׁעִים שָׁנָה וְתֵשַׁע שָׁנִים יְהוָה אֶל־אַבְרָם וַיֹּאמֶר אֵלָיו אֲנִי־אֵל שַׁדַּי הִתְהַלֵּךְ לְפָנַי וֶהְיֵה תָמִים וְאֶתְּנָה בְרִיתִי בֵּינִי וּבֵינֶךָ",
    riddle: "הִתְהַלֵּךְ לְפָנַי וֶהְיֵה תָמִים",
    speaker: "יְהוָה",
    listener: "אַבְרָם",
    bonus: "וְתֵשַׁע",
  },
  source: { ref_start: "Genesis 17:1", ref_end: "Genesis 17:1" },
};

const coreSolvedAttempt: GuessResult = {
  speakerOk: true,
  listenerOk: true,
  portionOk: true,
  bonusOk: false,
};
const failedAttempt: GuessResult = {
  speakerOk: false,
  listenerOk: false,
  portionOk: true,
  bonusOk: false,
};
const stageTwoTransitionAttempt: GuessResult = {
  speakerOk: true,
  listenerOk: true,
  portionOk: true,
  bonusOk: false,
  countsAsTry: false,
};
const failedBonusAttempt: GuessResult = {
  speakerOk: true,
  listenerOk: true,
  portionOk: true,
  bonusOk: false,
};

type PersistPayload = {
  speaker: string;
  listener: string;
  portion: string;
  bonus: string;
  hintRevealed: boolean;
  attempts: GuessResult[];
};

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

function buildPuzzleView(props: {
  onPersist: (state: PersistPayload) => void;
  lang?: Lang;
  puzzle?: PuzzleItem;
  revealed?: boolean;
  initial?: {
    speaker: string;
    listener: string;
    portion: string;
    bonus: string;
    hintRevealed?: boolean;
    attempts: GuessResult[];
  };
}) {
  const i18n = createI18n(props.lang ?? "en");
  return (
    <I18nextProvider i18n={i18n}>
      <StrictMode>
        <PuzzleView
          puzzle={props.puzzle ?? puzzle}
          revealed={props.revealed ?? false}
          onReveal={() => {}}
          onClear={() => {}}
          onPersist={props.onPersist}
          initial={props.initial}
          syncDocumentDirection={false}
        />
      </StrictMode>
    </I18nextProvider>
  );
}

function byId<T extends HTMLElement = HTMLElement>(id: string): T {
  const found = document.getElementById(id);
  if (!found) throw new Error(`Missing element #${id}`);
  return found as T;
}

function maybeById<T extends HTMLElement = HTMLElement>(id: string): T | null {
  const found = document.getElementById(id);
  return found as T | null;
}

async function clickById(id: string): Promise<void> {
  const user = userEvent.setup({ document: globalThis.document });
  await act(async () => {
    await user.click(byId(id));
  });
}

async function setInputValue(id: string, value: string): Promise<void> {
  const user = userEvent.setup({ document: globalThis.document });
  const input = byId<HTMLInputElement>(id);
  await act(async () => {
    await user.clear(input);
    await user.type(input, value);
  });
}

let view: RenderResult | null = null;

afterEach(() => {
  if (view) {
    act(() => {
      view?.unmount();
    });
    view = null;
  }
  cleanup();
});

describe("PuzzleView persistence hydration", () => {
  it("does not persist when parent re-sends an equivalent initial payload", () => {
    const calls: PersistPayload[] = [];
    const onPersist = (state: PersistPayload) => {
      calls.push(state);
    };
    const initial = {
      speaker: "the LORD",
      listener: "Abram",
      portion: "",
      bonus: "land",
      hintRevealed: false,
      attempts: [coreSolvedAttempt],
    };

    act(() => {
      view = render(buildPuzzleView({ onPersist, initial }));
    });

    expect(calls).toHaveLength(0);

    act(() => {
      view?.rerender(
        buildPuzzleView({
          onPersist,
          initial: {
            ...initial,
            attempts: [...initial.attempts],
          },
        })
      );
    });

    expect(calls).toHaveLength(0);
  });

  it("does not persist on rehydration but resumes persisting after user edits", async () => {
    const calls: PersistPayload[] = [];
    const onPersist = (state: PersistPayload) => {
      calls.push(state);
    };
    const initialA = {
      speaker: "the LORD",
      listener: "Abram",
      portion: "",
      bonus: "land",
      hintRevealed: false,
      attempts: [coreSolvedAttempt],
    };
    const initialB = {
      ...initialA,
      attempts: [coreSolvedAttempt, coreSolvedAttempt],
    };

    act(() => {
      view = render(buildPuzzleView({ onPersist, initial: initialA }));
    });

    await setInputValue("inputBonus", "earth");

    expect(calls.length).toBeGreaterThan(0);
    expect(calls[calls.length - 1]?.bonus).toBe("earth");
    const callsAfterFirstEdit = calls.length;

    act(() => {
      view?.rerender(buildPuzzleView({ onPersist, initial: initialB }));
    });

    expect(calls).toHaveLength(callsAfterFirstEdit);

    await setInputValue("inputBonus", "sand");

    expect(calls.length).toBeGreaterThan(callsAfterFirstEdit);
    expect(calls[calls.length - 1]).toMatchObject({
      bonus: "sand",
      attempts: initialB.attempts,
    });
  });

  it("does not persist stale local state when hydration and persist target change together", async () => {
    const calls: PersistPayload[] = [];
    const onPersistHe = () => {};
    const onPersistEn = (state: PersistPayload) => {
      calls.push(state);
    };
    const initialHe = {
      speaker: "אֲדֹנָי",
      listener: "אַבְרָם",
      portion: "",
      bonus: "טיוטה",
      hintRevealed: false,
      attempts: [coreSolvedAttempt],
    };
    const initialEn = {
      speaker: "the LORD",
      listener: "Abram",
      portion: "",
      bonus: "",
      hintRevealed: false,
      attempts: [coreSolvedAttempt],
    };

    act(() => {
      view = render(buildPuzzleView({ onPersist: onPersistHe, lang: "he", initial: initialHe }));
    });

    act(() => {
      view?.rerender(buildPuzzleView({ onPersist: onPersistEn, lang: "en", initial: initialEn }));
    });

    expect(calls).toHaveLength(0);

    await setInputValue("inputBonus", "earth");

    expect(calls.length).toBeGreaterThan(0);
    expect(calls.every((call) => call.speaker === "the LORD" && call.listener === "Abram")).toBe(true);
    expect(calls[calls.length - 1]).toMatchObject({
      speaker: "the LORD",
      listener: "Abram",
      bonus: "earth",
      attempts: initialEn.attempts,
    });
  });

  it("uses options when options are present", () => {
    const onPersist = () => {};
    const puzzleWithDifficultyOptions: PuzzleItem = {
      ...puzzle,
      en: {
        ...puzzle.en,
        options: {
          speaker: ["Easy Speaker"],
          listener: ["Easy Listener"],
        },
      },
    };

    act(() => {
      view = render(buildPuzzleView({ onPersist, puzzle: puzzleWithDifficultyOptions }));
    });

    const speakerOptions = Array.from(byId<HTMLSelectElement>("inputSpeaker").options).map((opt) => opt.value);
    const listenerOptions = Array.from(byId<HTMLSelectElement>("inputListener").options).map((opt) => opt.value);

    expect(speakerOptions).toContain("Easy Speaker");
    expect(listenerOptions).toContain("Easy Listener");
  });

  it("shows God as speaker option for divine aliases and accepts it as correct", async () => {
    const onPersist = () => {};

    act(() => {
      view = render(buildPuzzleView({ onPersist }));
    });

    const speakerOptions = Array.from(byId<HTMLSelectElement>("inputSpeaker").options).map((opt) => opt.value);
    expect(speakerOptions).toContain("God");
    expect(speakerOptions).not.toContain("the LORD");

    act(() => {
      fireEvent.change(byId("inputSpeaker"), { target: { value: "God" } });
      fireEvent.change(byId("inputListener"), { target: { value: "Abram" } });
    });

    await clickById("submitGuess");

    const feedback = byId("feedback").textContent ?? "";
    expect(feedback).toBe("Nice! Now find the missing word.");
  });

  it("marks bonus field and label as wrong in stage two when bonus is incorrect", () => {
    const onPersist = () => {};

    act(() => {
      view = render(
        buildPuzzleView({
          onPersist,
          initial: {
            speaker: "the LORD",
            listener: "Abram",
            portion: "",
            bonus: "",
            hintRevealed: false,
            attempts: [coreSolvedAttempt],
          },
        })
      );
    });

    expect(byId<HTMLInputElement>("inputBonus").className).toBe("wrong");
    expect(byId("labelBonus").textContent ?? "").toContain("❌");
  });

  it("keeps bonus feedback hidden before the first bonus try", () => {
    const onPersist = () => {};
    const stageTwoOpenAttempt: GuessResult = {
      speakerOk: true,
      listenerOk: true,
      portionOk: true,
      bonusOk: false,
      countsAsTry: false,
    };

    act(() => {
      view = render(
        buildPuzzleView({
          onPersist,
          initial: {
            speaker: "the LORD",
            listener: "Abram",
            portion: "",
            bonus: "",
            hintRevealed: false,
            attempts: [stageTwoOpenAttempt],
          },
        })
      );
    });

    expect(byId<HTMLInputElement>("inputBonus").className).toBe("");
    expect(byId("labelBonus").querySelector('[aria-hidden="true"]')).toBeNull();
  });

  it("wraps masked placeholder emojis in a dedicated span when bonus is before the riddle", () => {
    const onPersist = () => {};

    act(() => {
      view = render(
        buildPuzzleView({
          onPersist,
          lang: "he",
          puzzle: puzzleWithBonusBeforeRiddleHe,
          revealed: false,
          initial: {
            speaker: "יְהוָה",
            listener: "אַבְרָם",
            portion: "",
            bonus: "",
            hintRevealed: false,
            attempts: [coreSolvedAttempt],
          },
        })
      );
    });

    const emojiSpan = document.querySelector("#fullQuote .quote-hidden .quote-emoji");
    expect(emojiSpan).not.toBeNull();
    expect((emojiSpan?.textContent ?? "").length).toBeGreaterThan(0);
  });

  it("masks Hebrew bonus words in the main quote even when the quote uses a different niqqud spelling", () => {
    const onPersist = () => {};

    act(() => {
      view = render(
        buildPuzzleView({
          onPersist,
          lang: "he",
          puzzle: puzzleWithHebrewHintSpellingMismatch,
          revealed: false,
          initial: {
            speaker: "",
            listener: "",
            portion: "",
            bonus: "",
            hintRevealed: false,
            attempts: [],
          },
        })
      );
    });

    const fullQuoteText = byId("fullQuote").textContent ?? "";
    const placeholder = pickHardWordPlaceholderForId(puzzleWithHebrewHintSpellingMismatch.id);

    expect(fullQuoteText.includes("שֹׂנֵא")).toBe(false);
    expect(fullQuoteText.includes(placeholder)).toBe(true);
  });

  it("shows אֱלֹהִים as speaker option for divine aliases in Hebrew and accepts it as correct", () => {
    const onPersist = () => {};

    act(() => {
      view = render(buildPuzzleView({ onPersist, lang: "he" }));
    });

    const speakerOptions = Array.from(byId<HTMLSelectElement>("inputSpeaker").options).map((opt) => opt.value);
    expect(speakerOptions).toContain("אֱלֹהִים");
    expect(speakerOptions).not.toContain("אֲדֹנָי");

    act(() => {
      fireEvent.change(byId("inputSpeaker"), { target: { value: "אֱלֹהִים" } });
      fireEvent.change(byId("inputListener"), { target: { value: "אַבְרָם" } });
    });

    act(() => {
      fireEvent.click(byId("submitGuess"));
    });

    const feedback = byId("feedback").textContent ?? "";
    expect(feedback).toBe("יפה! עכשיו מצאו את המילה החסרה.");
  });

  it("does not overwrite loaded missing-word state on fresh hydration", async () => {
    const calls: PersistPayload[] = [];
    const onPersist = (state: PersistPayload) => {
      calls.push(state);
    };

    act(() => {
      view = render(buildPuzzleView({ onPersist }));
    });

    expect(calls).toHaveLength(0);
    expect(maybeById("bonusHint")).toBeNull();

    const hydratedInitial = {
      speaker: "the LORD",
      listener: "Abram",
      portion: "",
      bonus: "land",
      attempts: [coreSolvedAttempt],
    };

    act(() => {
      view?.rerender(buildPuzzleView({ onPersist, initial: hydratedInitial }));
    });

    expect(calls).toHaveLength(0);
    expect(maybeById("bonusHint")).toBeNull();
    expect(byId("refLine").textContent ?? "").toContain("Genesis 12:1");

    await setInputValue("inputBonus", "earth");

    expect(calls.length).toBeGreaterThan(0);
    expect(calls[calls.length - 1]).toMatchObject({
      speaker: "the LORD",
      listener: "Abram",
      bonus: "earth",
      attempts: [coreSolvedAttempt],
    });
  });

  it("uses manual source emoji override and falls back to grandma emoji", () => {
    const onPersist = () => {};
    const initial = {
      speaker: "the LORD",
      listener: "Abram",
      portion: "",
      bonus: "",
      attempts: [coreSolvedAttempt],
    };

    const customEmojiPuzzle: PuzzleItem = {
      ...puzzle,
      source: { method: "manual", emoji: "🧠", ref_start: "Genesis 12:1", ref_end: "Genesis 12:1" },
    };

    act(() => {
      view = render(buildPuzzleView({ onPersist, puzzle: customEmojiPuzzle, initial }));
    });
    expect(byId("refLine").textContent ?? "").toContain("🧠 Genesis 12:1");

    const defaultEmojiPuzzle: PuzzleItem = {
      ...puzzle,
      source: { method: "manual", ref_start: "Genesis 12:1", ref_end: "Genesis 12:1" },
    };

    act(() => {
      view?.rerender(buildPuzzleView({ onPersist, puzzle: defaultEmojiPuzzle, initial }));
    });
    expect(byId("refLine").textContent ?? "").toContain("👵 Genesis 12:1");
  });

  it("links the revealed source line to the reader route", () => {
    const onPersist = () => {};
    const initial = {
      speaker: "the LORD",
      listener: "Abram",
      portion: "",
      bonus: "",
      attempts: [coreSolvedAttempt],
    };

    act(() => {
      view = render(buildPuzzleView({ onPersist, initial }));
    });

    const refLink = byId("refLine").querySelector("a");
    expect(refLink).not.toBeNull();
    expect(refLink?.getAttribute("href")).toBe("/read/genesis/12?lng=en#v1");
  });

  it("reveals a masked bonus hint quote in stage two and unmasks it after solve", async () => {
    const calls: PersistPayload[] = [];
    const onPersist = (state: PersistPayload) => {
      calls.push(state);
    };

    act(() => {
      view = render(
        buildPuzzleView({
          onPersist,
          puzzle: puzzleWithHint,
          revealed: false,
          initial: {
            speaker: "the LORD",
            listener: "Abram",
            portion: "",
            bonus: "",
            hintRevealed: false,
            attempts: [coreSolvedAttempt],
          },
        })
      );
    });

    expect(calls).toHaveLength(0);
    expect(maybeById("hintQuote")).toBeNull();

    await clickById("bonusHint");

    const hintQuoteText = byId("hintQuote").textContent ?? "";
    const placeholder = pickHardWordPlaceholderForId(puzzleWithHint.id);

    expect(hintQuoteText.includes("land")).toBe(false);
    expect(hintQuoteText.includes(placeholder)).toBe(true);
    expect(byId("hintRefLine").textContent ?? "").toBe("Genesis 12:1");
    expect(calls).toHaveLength(1);
    expect(calls[0]?.hintRevealed).toBe(true);

    await setInputValue("inputBonus", "land");
    await clickById("submitGuess");

    const solvedHintQuoteText = byId("hintQuote").textContent ?? "";
    expect(solvedHintQuoteText.includes("land")).toBe(true);
    expect(solvedHintQuoteText.includes(placeholder)).toBe(false);
  });

  it("masks Hebrew bonus-hint words even when the hint uses a different niqqud spelling", async () => {
    const onPersist = () => {};

    act(() => {
      view = render(
        buildPuzzleView({
          onPersist,
          lang: "he",
          puzzle: puzzleWithHebrewHintSpellingMismatch,
          revealed: false,
          initial: {
            speaker: "אֶחָיו",
            listener: "יוֹסֵף",
            portion: "",
            bonus: "",
            hintRevealed: false,
            attempts: [coreSolvedAttempt],
          },
        })
      );
    });

    await clickById("bonusHint");

    const hintQuoteText = byId("hintQuote").textContent ?? "";
    const placeholder = pickHardWordPlaceholderForId(puzzleWithHebrewHintSpellingMismatch.id);

    expect(hintQuoteText.includes("שֹׂנֵא")).toBe(false);
    expect(hintQuoteText.includes(placeholder)).toBe(true);
  });

  it("restores the bonus hint quote on load when hint was already used", () => {
    const calls: PersistPayload[] = [];
    const onPersist = (state: PersistPayload) => {
      calls.push(state);
    };

    act(() => {
      view = render(
        buildPuzzleView({
          onPersist,
          puzzle: puzzleWithHint,
          revealed: false,
          initial: {
            speaker: "the LORD",
            listener: "Abram",
            portion: "",
            bonus: "",
            hintRevealed: true,
            attempts: [coreSolvedAttempt],
          },
        })
      );
    });

    expect(calls).toHaveLength(0);
    expect(byId("hintQuote")).toBeTruthy();
    expect(byId("hintRefLine").textContent ?? "").toBe("Genesis 12:1");
    expect(byId<HTMLButtonElement>("bonusHint").disabled).toBe(true);
  });

  it("hides bonus hint control until stage two opens", () => {
    const onPersist = () => {};
    act(() => {
      view = render(
        buildPuzzleView({
          onPersist,
          puzzle: puzzleWithHint,
          revealed: false,
          initial: {
            speaker: "the LORD",
            listener: "Abram",
            portion: "",
            bonus: "",
            hintRevealed: false,
            attempts: [],
          },
        })
      );
    });

    expect(maybeById("bonusHint")).toBeNull();
  });

  it("shows the failed-bonus marker after a wrong bonus guess", async () => {
    const onPersist = () => {};
    const stageTwoOpenAttempt: GuessResult = {
      speakerOk: true,
      listenerOk: true,
      portionOk: true,
      bonusOk: false,
      countsAsTry: false,
    };
    act(() => {
      view = render(
        buildPuzzleView({
          onPersist,
          puzzle: puzzleWithHint,
          revealed: false,
          initial: {
            speaker: "the LORD",
            listener: "Abram",
            portion: "",
            bonus: "",
            hintRevealed: false,
            attempts: [stageTwoOpenAttempt],
          },
        })
      );
    });

    expect(document.querySelector(".status-line")?.textContent ?? "").toContain("✅✅✡️⬜");

    await setInputValue("inputBonus", "earth");
    await clickById("submitGuess");

    expect(document.querySelector(".status-line")?.textContent ?? "").toContain("✅✅✴️⬜");
  });

  it("reveals the bonus word in the quote and hint on failure but preserves the typed bonus input", () => {
    const onPersist = () => {};
    const puzzleWithHintAndBonusInQuote: PuzzleItem = {
      ...puzzleWithHint,
      en: {
        ...puzzleWithHint.en,
        quote: "Now the LORD said unto Abram, Get thee out unto the land that I will show thee.",
      },
    };

    act(() => {
      view = render(
        buildPuzzleView({
          onPersist,
          puzzle: puzzleWithHintAndBonusInQuote,
          revealed: false,
          initial: {
            speaker: "the LORD",
            listener: "Abram",
            portion: "",
            bonus: "earth",
            hintRevealed: true,
            attempts: [
              stageTwoTransitionAttempt,
              failedBonusAttempt,
              failedBonusAttempt,
              failedBonusAttempt,
              failedBonusAttempt,
              failedBonusAttempt,
            ],
          },
        })
      );
    });

    const fullQuoteText = byId("fullQuote").textContent ?? "";
    const hintQuoteText = byId("hintQuote").textContent ?? "";
    const placeholder = pickHardWordPlaceholderForId(puzzleWithHintAndBonusInQuote.id);

    expect(byId("feedback").textContent ?? "").toBe("No tries left.");
    expect(fullQuoteText.includes("land")).toBe(true);
    expect(fullQuoteText.includes(placeholder)).toBe(false);
    expect(hintQuoteText.includes("land")).toBe(true);
    expect(hintQuoteText.includes(placeholder)).toBe(false);
    expect(byId<HTMLInputElement>("inputBonus").value).toBe("earth");
    expect(byId<HTMLInputElement>("inputBonus").disabled).toBe(true);
    expect(byId<HTMLInputElement>("inputBonus").className).toBe("wrong");
    expect(byId("labelBonus").textContent ?? "").toContain("❌");
  });

  it("reveals the correct answers when no tries are left", () => {
    const onPersist = () => {};

    act(() => {
      view = render(
        buildPuzzleView({
          onPersist,
          revealed: false,
          initial: {
            speaker: "Sarah",
            listener: "Isaac",
            portion: "",
            bonus: "earth",
            hintRevealed: false,
            attempts: [failedAttempt, failedAttempt, failedAttempt, failedAttempt, failedAttempt],
          },
        })
      );
    });

    expect(byId("feedback").textContent ?? "").toBe("No tries left.");
    expect(byId<HTMLSelectElement>("inputSpeaker").value).toBe("the LORD");
    expect(byId<HTMLSelectElement>("inputListener").value).toBe("Abram");
    expect(byId<HTMLInputElement>("inputBonus").value).toBe("earth");
    expect(byId<HTMLSelectElement>("inputSpeaker").disabled).toBe(true);
    expect(byId<HTMLSelectElement>("inputListener").disabled).toBe(true);
    expect(byId<HTMLInputElement>("inputBonus").disabled).toBe(true);
    expect(byId<HTMLInputElement>("inputBonus").className).toBe("wrong");
    expect(byId("labelSpeaker").textContent ?? "").toContain("✅");
    expect(byId("labelListener").textContent ?? "").toContain("✅");
    expect(byId("labelBonus").textContent ?? "").toContain("❌");
  });
});
