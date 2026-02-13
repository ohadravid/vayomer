import { afterEach, describe, expect, it } from "bun:test";
import React, { StrictMode } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { createInstance } from "i18next";
import { I18nextProvider, initReactI18next } from "react-i18next";
import { PuzzleView } from "./PuzzleView";
import { resources } from "../i18n";
import type { GuessResult, Lang, PuzzleItem } from "../types";

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
  source: { ref_start: "Genesis 12:1", ref_end: "Genesis 12:1" },
};

const coreSolvedAttempt: GuessResult = {
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
  bookHintUsed: boolean;
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

function renderPuzzleView(props: {
  onPersist: (state: PersistPayload) => void;
  initial?: {
    speaker: string;
    listener: string;
    portion: string;
    bonus: string;
    bookHintUsed?: boolean;
    attempts: GuessResult[];
  };
}) {
  const i18n = createI18n("en");
  return (
    <I18nextProvider i18n={i18n}>
      <StrictMode>
        <PuzzleView
          puzzle={puzzle}
          easyMode={false}
          revealed={false}
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

let root: ReactTestRenderer | null = null;

afterEach(() => {
  if (root) {
    act(() => root?.unmount());
    root = null;
  }
});

describe("PuzzleView persistence hydration", () => {
  it("does not overwrite loaded missing-word state on fresh hydration", () => {
    const calls: PersistPayload[] = [];
    const onPersist = (state: PersistPayload) => {
      calls.push(state);
    };

    act(() => {
      root = create(renderPuzzleView({ onPersist }));
    });

    expect(calls).toHaveLength(0);

    const hydratedInitial = {
      speaker: "the LORD",
      listener: "Abram",
      portion: "",
      bonus: "land",
      bookHintUsed: false,
      attempts: [coreSolvedAttempt],
    };

    act(() => {
      root?.update(renderPuzzleView({ onPersist, initial: hydratedInitial }));
    });

    expect(calls).toHaveLength(0);

    const bonusInput = root?.root.findByProps({ id: "inputBonus" });
    act(() => {
      bonusInput?.props.onChange({ target: { value: "earth" } });
    });

    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({
      speaker: "the LORD",
      listener: "Abram",
      bonus: "earth",
      attempts: [coreSolvedAttempt],
    });
  });
});
