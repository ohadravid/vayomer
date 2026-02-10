import { useEffect, useMemo, useState, type ComponentProps } from "react";
import { createInstance } from "i18next";
import { I18nextProvider, initReactI18next } from "react-i18next";
import { GuessForm } from "./components/GuessForm";
import { PuzzleCard } from "./components/PuzzleCard";
import { PuzzleView } from "./components/PuzzleView";
import { resources } from "./i18n";
import { getLanguageDirection } from "./lib/language";
import type { EasyChoicePools, GuessEditState, GuessResult, GuessValues, Lang, PuzzleItem } from "./types";

const samplePuzzle: PuzzleItem = {
  id: "genesis-12-01-01",
  en: {
    book: "Genesis",
    quote: "1 Now the LORD said unto Abram: 'Get thee out of thy country, and from thy kindred, and from thy father's house, unto the land that I will show thee.'",
    riddle: "Get thee out of thy country, and from thy kindred, and from thy father's house",
    speaker: "the LORD",
    listener: "Abram",
    bonus: "land",
  },
  he: {
    book: "בראשית",
    quote: "א וַיֹּאמֶר אֲדֹנָי אֶל-אַבְרָם, לֶךְ-לְךָ מֵאַרְצְךָ וּמִמּוֹלַדְתְּךָ וּמִבֵּית אָבִיךָ, אֶל-הָאָרֶץ, אֲשֶׁר אַרְאֶךָּ.",
    riddle: "לֶךְ-לְךָ מֵאַרְצְךָ וּמִמּוֹלַדְתְּךָ וּמִבֵּית אָבִיךָ",
    speaker: "אֲדֹנָי",
    listener: "אַבְרָם",
    bonus: "הָאָרֶץ",
  },
  portion: { en: "Lech-Lecha", he: "לך-לך" },
  source: { ref_start: "Genesis 12:1", ref_end: "Genesis 12:1" },
};

const sampleChoicesEn: EasyChoicePools = {
  speaker: ["the LORD", "Moses", "Isaac", "Pharaoh"],
  listener: ["Abram", "Sarah", "Pharaoh", "Jacob"],
};

const sampleChoicesHe: EasyChoicePools = {
  speaker: ["אֲדֹנָי", "משה", "יצחק", "פרעה"],
  listener: ["אַבְרָם", "שָׂרָה", "יַעֲקֹב", "פרעה"],
};

const EMPTY_EDITED: GuessEditState = {
  speaker: false,
  listener: false,
  portion: false,
  bonus: false,
};

type PuzzleInitial = ComponentProps<typeof PuzzleView>["initial"];

function localize(lang: Lang, english: string, hebrew: string): string {
  return lang === "he" ? hebrew : english;
}

function buildInitial(lang: Lang, state: "core-solved" | "stage-two-missing" | "stage-two-revealed" | "solved" | "failed"): PuzzleInitial {
  if (state === "core-solved") {
    return {
      speaker: localize(lang, "the LORD", "אֲדֹנָי"),
      listener: localize(lang, "Abram", "אַבְרָם"),
      portion: "",
      bonus: "",
      result: { speakerOk: true, listenerOk: true, portionOk: false, bonusOk: false },
      guesses: 1,
    };
  }

  if (state === "stage-two-missing") {
    return {
      speaker: localize(lang, "the LORD", "אֲדֹנָי"),
      listener: localize(lang, "Abram", "אַבְרָם"),
      portion: "",
      bonus: localize(lang, "field", "שָׂדֶה"),
      result: { speakerOk: true, listenerOk: true, portionOk: false, bonusOk: false },
      guesses: 2,
    };
  }

  if (state === "stage-two-revealed") {
    return {
      speaker: localize(lang, "the LORD", "אֲדֹנָי"),
      listener: localize(lang, "Abram", "אַבְרָם"),
      portion: "",
      bonus: "",
      result: { speakerOk: true, listenerOk: true, portionOk: false, bonusOk: false },
      guesses: 2,
    };
  }

  if (state === "solved") {
    return {
      speaker: localize(lang, "the LORD", "אֲדֹנָי"),
      listener: localize(lang, "Abram", "אַבְרָם"),
      portion: localize(lang, "Lech-Lecha", "לך-לך"),
      bonus: localize(lang, "land", "הָאָרֶץ"),
      result: { speakerOk: true, listenerOk: true, portionOk: true, bonusOk: true },
      guesses: 2,
    };
  }

  return {
    speaker: localize(lang, "Moses", "משה"),
    listener: localize(lang, "Pharaoh", "פרעה"),
    portion: localize(lang, "Tzav", "צַו"),
    bonus: localize(lang, "house", "בֵּית אָבִיךָ"),
    result: { speakerOk: false, listenerOk: false, portionOk: false, bonusOk: false },
    guesses: 3,
  };
}

function buildGuessValues(lang: Lang): GuessValues {
  return {
    speaker: localize(lang, "Moses", "משה"),
    listener: localize(lang, "Abram", "אַבְרָם"),
    portion: "",
    bonus: localize(lang, "field", "שָׂדֶה"),
  };
}

function RevealTransitionDemo({ lang, choicePools }: { lang: Lang; choicePools: EasyChoicePools }) {
  const [revealed, setRevealed] = useState(false);

  useEffect(() => {
    setRevealed(false);
    const timer = window.setTimeout(() => setRevealed(true), 600);
    return () => window.clearTimeout(timer);
  }, [lang]);

  return (
    <PuzzleView
      puzzle={samplePuzzle}
      easyMode
      choicePools={choicePools}
      revealed={revealed}
      onReveal={() => setRevealed(true)}
      onClear={() => setRevealed(false)}
      syncDocumentDirection={false}
    />
  );
}

function makeDebugI18n(lang: Lang) {
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

function LanguageSuite({ lang, title, anchorId }: { lang: Lang; title: string; anchorId?: string }) {
  const direction = getLanguageDirection(lang);
  const [guessValues, setGuessValues] = useState<GuessValues>(() => buildGuessValues(lang));
  const i18n = useMemo(() => makeDebugI18n(lang), [lang]);
  const choicePools = lang === "he" ? sampleChoicesHe : sampleChoicesEn;
  const dateLabel = useMemo(
    () =>
      new Intl.DateTimeFormat(lang === "he" ? "he-IL" : "en-US", {
        year: "numeric",
        month: "long",
        day: "numeric",
        weekday: "long",
      }).format(new Date()),
    [lang]
  );
  const guessResult: GuessResult = {
    speakerOk: false,
    listenerOk: true,
    portionOk: false,
    bonusOk: false,
  };

  return (
    <I18nextProvider i18n={i18n}>
      <section className={`debug-suite ${direction === "rtl" ? "rtl" : ""}`} dir={direction}>
        <h2 className="debug-suite-title" id={anchorId}>
          {anchorId ? <a href={`#${anchorId}`}>{title}</a> : title}
        </h2>

        <section className="debug-grid">
          <article className="debug-panel">
            <h2>PuzzleView Fresh</h2>
            <PuzzleView
              puzzle={samplePuzzle}
              easyMode={false}
              revealed={false}
              onReveal={() => undefined}
              onClear={() => undefined}
              syncDocumentDirection={false}
            />
          </article>

          <article className="debug-panel">
            <h2>PuzzleView Easy Mode</h2>
            <PuzzleView
              puzzle={samplePuzzle}
              easyMode
              choicePools={choicePools}
              revealed={false}
              onReveal={() => undefined}
              onClear={() => undefined}
              syncDocumentDirection={false}
            />
          </article>

          <article className="debug-panel">
            <h2>PuzzleView Core Solved</h2>
            <PuzzleView
              puzzle={samplePuzzle}
              easyMode={false}
              initial={buildInitial(lang, "core-solved")}
              revealed={false}
              onReveal={() => undefined}
              onClear={() => undefined}
              syncDocumentDirection={false}
            />
          </article>

          <article className="debug-panel">
            <h2>PuzzleView Stage Two Missing</h2>
            <PuzzleView
              puzzle={samplePuzzle}
              easyMode={false}
              initial={buildInitial(lang, "stage-two-missing")}
              revealed={false}
              onReveal={() => undefined}
              onClear={() => undefined}
              syncDocumentDirection={false}
            />
          </article>

          <article className="debug-panel">
            <h2>PuzzleView Stage Two Revealed</h2>
            <PuzzleView
              puzzle={samplePuzzle}
              easyMode={false}
              initial={buildInitial(lang, "stage-two-revealed")}
              revealed
              onReveal={() => undefined}
              onClear={() => undefined}
              syncDocumentDirection={false}
            />
          </article>

          <article className="debug-panel">
            <h2>PuzzleView Solved</h2>
            <PuzzleView
              puzzle={samplePuzzle}
              easyMode={false}
              initial={buildInitial(lang, "solved")}
              revealed
              onReveal={() => undefined}
              onClear={() => undefined}
              syncDocumentDirection={false}
            />
          </article>

          <article className="debug-panel">
            <h2>PuzzleView Failed</h2>
            <PuzzleView
              puzzle={samplePuzzle}
              easyMode={false}
              initial={buildInitial(lang, "failed")}
              revealed={false}
              onReveal={() => undefined}
              onClear={() => undefined}
              syncDocumentDirection={false}
            />
          </article>

          <article className="debug-panel">
            <h2>PuzzleView Reveal Transition</h2>
            <RevealTransitionDemo lang={lang} choicePools={choicePools} />
          </article>
        </section>

        <section className="debug-grid">
          <article className="debug-panel">
            <h2>PuzzleCard Standalone</h2>
            <PuzzleCard
              puzzle={samplePuzzle}
              revealed={false}
              quoteRevealed={false}
              dateLabel={dateLabel}
              onClear={() => undefined}
            />
          </article>

          <article className="debug-panel">
            <h2>PuzzleCard Revealed</h2>
            <PuzzleCard
              puzzle={samplePuzzle}
              revealed
              quoteRevealed
              dateLabel={dateLabel}
              onClear={() => undefined}
            />
          </article>

          <article className="debug-panel">
            <h2>GuessForm Standalone</h2>
            <section className="card">
              <GuessForm
                easyMode
                choiceOptions={choicePools}
                values={guessValues}
                result={guessResult}
                editedSinceCheck={EMPTY_EDITED}
                onChange={(field, value) => setGuessValues((prev) => ({ ...prev, [field]: value }))}
                onSubmit={() => undefined}
                coreSolved={false}
                showBonusRow
                extraChecked
                bonusDisabled={false}
                disabled={false}
                feedback={localize(lang, "Try another speaker.", "נסו דובר אחר.")}
                wrongGuesses={1}
                statusMarks="❌✅⬜"
              />
            </section>
          </article>
        </section>
      </section>
    </I18nextProvider>
  );
}

export function DebugPage() {
  return (
    <div className="app debug-page">
      <header className="header">
        <div>
          <div className="kicker">Bun Debug Surface</div>
          <h1>Vayomer Debug</h1>
          <p className="subtitle">English and Hebrew puzzle states without Storybook.</p>
        </div>
      </header>

      <LanguageSuite lang="en" title="English Puzzle Scenarios" />
      <LanguageSuite lang="he" title="תרחישי חידה בעברית" anchorId="hebrew-puzzles" />
    </div>
  );
}
