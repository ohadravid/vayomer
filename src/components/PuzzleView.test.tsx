import { afterEach, describe, expect, it } from "bun:test";
import React, { StrictMode } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { createInstance } from "i18next";
import { I18nextProvider, initReactI18next } from "react-i18next";
import { PuzzleView } from "./PuzzleView";
import { GuessForm } from "./GuessForm";
import { resources } from "../i18n";
import { pickDailyHardModeSuccessMark, HARD_MODE_SUCCESS_MARKS } from "../lib/daily";
import { pickHardWordPlaceholderForId } from "../lib/format";
import type { EasyChoicePools, GuessResult, Lang, PuzzleItem } from "../types";

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

function renderPuzzleView(props: {
  onPersist: (state: PersistPayload) => void;
  onChoiceInteracted?: () => void;
  puzzle?: PuzzleItem;
  revealed?: boolean;
  easyMode?: boolean;
  choicePools?: EasyChoicePools;
  initial?: {
    speaker: string;
    listener: string;
    portion: string;
    bonus: string;
    bookHintUsed?: boolean;
    hintRevealed?: boolean;
    attempts: GuessResult[];
  };
}) {
  const i18n = createI18n("en");
  return (
    <I18nextProvider i18n={i18n}>
      <StrictMode>
        <PuzzleView
          puzzle={props.puzzle ?? puzzle}
          easyMode={props.easyMode ?? false}
          choicePools={props.choicePools}
          revealed={props.revealed ?? false}
          onReveal={() => {}}
          onClear={() => {}}
          onChoiceInteracted={props.onChoiceInteracted}
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
  it("does not lock difficulty until a choice select is clicked", () => {
    const onPersist = () => {};
    let interactions = 0;
    const onChoiceInteracted = () => {
      interactions += 1;
    };

    act(() => {
      root = create(renderPuzzleView({ onPersist, onChoiceInteracted }));
    });

    expect(interactions).toBe(0);

    const speakerSelect = root?.root.findByProps({ id: "inputSpeaker" });
    const listenerSelect = root?.root.findByProps({ id: "inputListener" });

    act(() => {
      speakerSelect?.props.onClick();
    });
    expect(interactions).toBe(1);

    act(() => {
      listenerSelect?.props.onClick();
    });
    expect(interactions).toBe(1);
  });

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
      bookHintUsed: false,
      hintRevealed: false,
      attempts: [coreSolvedAttempt],
    };

    act(() => {
      root = create(renderPuzzleView({ onPersist, initial }));
    });

    expect(calls).toHaveLength(0);

    act(() => {
      root?.update(
        renderPuzzleView({
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

  it("does not persist on rehydration but resumes persisting after user edits", () => {
    const calls: PersistPayload[] = [];
    const onPersist = (state: PersistPayload) => {
      calls.push(state);
    };
    const initialA = {
      speaker: "the LORD",
      listener: "Abram",
      portion: "",
      bonus: "land",
      bookHintUsed: false,
      hintRevealed: false,
      attempts: [coreSolvedAttempt],
    };
    const initialB = {
      ...initialA,
      attempts: [coreSolvedAttempt, coreSolvedAttempt],
    };

    act(() => {
      root = create(renderPuzzleView({ onPersist, initial: initialA }));
    });

    const bonusInputBeforeRehydrate = root?.root.findByProps({ id: "inputBonus" });
    act(() => {
      bonusInputBeforeRehydrate?.props.onChange({ target: { value: "earth" } });
    });

    expect(calls).toHaveLength(1);
    expect(calls[0]?.bonus).toBe("earth");

    act(() => {
      root?.update(renderPuzzleView({ onPersist, initial: initialB }));
    });

    expect(calls).toHaveLength(1);

    const bonusInputAfterRehydrate = root?.root.findByProps({ id: "inputBonus" });
    act(() => {
      bonusInputAfterRehydrate?.props.onChange({ target: { value: "sand" } });
    });

    expect(calls).toHaveLength(2);
    expect(calls[1]).toMatchObject({
      bonus: "sand",
      attempts: initialB.attempts,
    });
  });

  it("uses hard_difficulty_options in hard mode when present", () => {
    const onPersist = () => {};
    const puzzleWithDifficultyOptions: PuzzleItem = {
      ...puzzle,
      en: {
        ...puzzle.en,
        options: {
          speaker: ["Easy Speaker"],
          listener: ["Easy Listener"],
        },
        hard_difficulty_options: {
          speaker: ["Hard Speaker"],
          listener: ["Hard Listener"],
        },
      },
    };

    act(() => {
      root = create(renderPuzzleView({ onPersist, puzzle: puzzleWithDifficultyOptions, easyMode: false }));
    });

    const form = root?.root.findByType(GuessForm);
    expect(form?.props.choiceOptions.speaker).toContain("Hard Speaker");
    expect(form?.props.choiceOptions.listener).toContain("Hard Listener");
    expect(form?.props.choiceOptions.speaker).not.toContain("Easy Speaker");
    expect(form?.props.choiceOptions.listener).not.toContain("Easy Listener");
  });

  it("uses options in easy mode when hard_difficulty_options are present", () => {
    const onPersist = () => {};
    const puzzleWithDifficultyOptions: PuzzleItem = {
      ...puzzle,
      en: {
        ...puzzle.en,
        options: {
          speaker: ["Easy Speaker"],
          listener: ["Easy Listener"],
        },
        hard_difficulty_options: {
          speaker: ["Hard Speaker"],
          listener: ["Hard Listener"],
        },
      },
    };

    act(() => {
      root = create(renderPuzzleView({ onPersist, puzzle: puzzleWithDifficultyOptions, easyMode: true }));
    });

    const form = root?.root.findByType(GuessForm);
    expect(form?.props.choiceOptions.speaker).toContain("Easy Speaker");
    expect(form?.props.choiceOptions.listener).toContain("Easy Listener");
    expect(form?.props.choiceOptions.speaker).not.toContain("Hard Speaker");
    expect(form?.props.choiceOptions.listener).not.toContain("Hard Listener");
  });

  it("does not overwrite loaded missing-word state on fresh hydration", () => {
    const calls: PersistPayload[] = [];
    const onPersist = (state: PersistPayload) => {
      calls.push(state);
    };

    act(() => {
      root = create(renderPuzzleView({ onPersist }));
    });

    expect(calls).toHaveLength(0);
    expect(root?.root.findAllByProps({ id: "bonusHint" })).toHaveLength(0);

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
    expect(root?.root.findAllByProps({ id: "bonusHint" })).toHaveLength(0);
    expect(root?.root.findByProps({ id: "refLine" }).children.join("")).toBe("Genesis 12:1");

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

  it("reveals a masked bonus hint quote in stage two and unmasks it after solve", () => {
    const calls: PersistPayload[] = [];
    const onPersist = (state: PersistPayload) => {
      calls.push(state);
    };

    act(() => {
      root = create(
        renderPuzzleView({
          onPersist,
          puzzle: puzzleWithHint,
          revealed: false,
          initial: {
            speaker: "the LORD",
            listener: "Abram",
            portion: "",
            bonus: "",
            bookHintUsed: false,
            hintRevealed: false,
            attempts: [coreSolvedAttempt],
          },
        })
      );
    });

    expect(calls).toHaveLength(0);
    expect(root?.root.findAllByProps({ id: "hintQuote" })).toHaveLength(0);

    const revealHint = root?.root.findByProps({ id: "bonusHint" });
    act(() => {
      revealHint?.props.onClick();
    });

    const hintQuoteNode = root?.root.findByProps({ id: "hintQuote" });
    const hintQuoteHtml = String(hintQuoteNode?.props?.dangerouslySetInnerHTML?.__html ?? "");
    const placeholder = pickHardWordPlaceholderForId(puzzleWithHint.id);

    expect(hintQuoteHtml.includes("land")).toBe(false);
    expect(hintQuoteHtml.includes(placeholder)).toBe(true);
    expect(root?.root.findByProps({ id: "hintRefLine" }).children.join("")).toBe("Genesis 12:1");
    expect(calls).toHaveLength(1);
    expect(calls[0]?.bookHintUsed).toBe(true);
    expect(calls[0]?.hintRevealed).toBe(true);

    const formWithHint = root?.root.findByType(GuessForm);
    act(() => {
      formWithHint?.props.onChange("bonus", "land");
    });
    const formAfterBonusInput = root?.root.findByType(GuessForm);
    act(() => {
      formAfterBonusInput?.props.onSubmit();
    });

    const solvedHintQuoteNode = root?.root.findByProps({ id: "hintQuote" });
    const solvedHintQuoteHtml = String(solvedHintQuoteNode?.props?.dangerouslySetInnerHTML?.__html ?? "");
    expect(solvedHintQuoteHtml.includes("land")).toBe(true);
    expect(solvedHintQuoteHtml.includes(placeholder)).toBe(false);
  });

  it("restores the bonus hint quote on load when hint was already used", () => {
    const calls: PersistPayload[] = [];
    const onPersist = (state: PersistPayload) => {
      calls.push(state);
    };

    act(() => {
      root = create(
        renderPuzzleView({
          onPersist,
          puzzle: puzzleWithHint,
          revealed: false,
          initial: {
            speaker: "the LORD",
            listener: "Abram",
            portion: "",
            bonus: "",
            bookHintUsed: true,
            hintRevealed: false,
            attempts: [coreSolvedAttempt],
          },
        })
      );
    });

    expect(calls).toHaveLength(0);
    expect(root?.root.findAllByProps({ id: "hintQuote" })).toHaveLength(1);
    expect(root?.root.findByProps({ id: "hintRefLine" }).children.join("")).toBe("Genesis 12:1");
    expect(root?.root.findByProps({ id: "bonusHint" }).props.disabled).toBe(true);
  });

  it("hides bonus hint control until stage two opens", () => {
    const onPersist = () => {};
    act(() => {
      root = create(
        renderPuzzleView({
          onPersist,
          puzzle: puzzleWithHint,
          revealed: false,
          initial: {
            speaker: "the LORD",
            listener: "Abram",
            portion: "",
            bonus: "",
            bookHintUsed: false,
            hintRevealed: false,
            attempts: [],
          },
        })
      );
    });

    expect(root?.root.findAllByProps({ id: "bonusHint" })).toHaveLength(0);
  });

  it("shows the failed-bonus marker after a wrong bonus guess", () => {
    const onPersist = () => {};
    const successMark = pickDailyHardModeSuccessMark(new Date());
    expect(HARD_MODE_SUCCESS_MARKS).toContain(successMark);
    const stageTwoOpenAttempt: GuessResult = {
      speakerOk: true,
      listenerOk: true,
      portionOk: true,
      bonusOk: false,
      countsAsTry: false,
    };
    act(() => {
      root = create(
        renderPuzzleView({
          onPersist,
          puzzle: puzzleWithHint,
          revealed: false,
          initial: {
            speaker: "the LORD",
            listener: "Abram",
            portion: "",
            bonus: "",
            bookHintUsed: false,
            hintRevealed: false,
            attempts: [stageTwoOpenAttempt],
          },
        })
      );
    });

    const formBeforeGuess = root?.root.findByType(GuessForm);
    expect(formBeforeGuess?.props.statusMarks).toBe(`${successMark}${successMark}✡️⬜`);

    act(() => {
      formBeforeGuess?.props.onChange("bonus", "earth");
      formBeforeGuess?.props.onSubmit();
    });

    const formAfterGuess = root?.root.findByType(GuessForm);
    expect(formAfterGuess?.props.statusMarks).toBe(`${successMark}${successMark}✴️⬜`);
  });
});
