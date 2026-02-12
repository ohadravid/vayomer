import { useEffect, useMemo, useState, type ComponentProps } from "react";
import { createInstance } from "i18next";
import { I18nextProvider, initReactI18next } from "react-i18next";
import { GuessForm } from "./components/GuessForm";
import { PuzzleCard } from "./components/PuzzleCard";
import { PuzzleView } from "./components/PuzzleView";
import { resources } from "./i18n";
import { formatDate } from "./lib/format";
import { getLanguageDirection } from "./lib/language";
import type { EasyChoicePools, GuessEditState, GuessResult, GuessValues, Lang, PuzzleItem } from "./types";
import dailyData from "../data/daily.json";

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
const DAY_IN_MS = 24 * 60 * 60 * 1000;
const DEBUG_EPOCH_DATE = new Date(2026, 1, 6);
const DEBUG_DAILY_ORDER_SEED = 20260805;

function parsePuzzleItems(data: unknown): PuzzleItem[] {
  const payload = (data as { items?: unknown }).items ?? data;
  return Array.isArray(payload) ? (payload as PuzzleItem[]) : [];
}

const debugQuoteItems = parsePuzzleItems(dailyData as unknown);

function localize(lang: Lang, english: string, hebrew: string): string {
  return lang === "he" ? hebrew : english;
}

function seededRandom(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let mixed = Math.imul(state ^ (state >>> 15), state | 1);
    mixed ^= mixed + Math.imul(mixed ^ (mixed >>> 7), mixed | 61);
    return ((mixed ^ (mixed >>> 14)) >>> 0) / 4294967296;
  };
}

function buildDailyOrder(total: number): number[] {
  const order = Array.from({ length: total }, (_, idx) => idx);
  const rand = seededRandom(DEBUG_DAILY_ORDER_SEED);

  for (let idx = order.length - 1; idx > 0; idx -= 1) {
    const swapIdx = Math.floor(rand() * (idx + 1));
    [order[idx], order[swapIdx]] = [order[swapIdx], order[idx]];
  }

  return order;
}

function utcDayNumber(date: Date): number {
  return Math.floor(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) / DAY_IN_MS);
}

function dayOffsetFromEpoch(date: Date): number {
  return utcDayNumber(date) - utcDayNumber(DEBUG_EPOCH_DATE);
}

function dateForDayOffset(dayOffset: number): Date {
  const date = new Date(DEBUG_EPOCH_DATE);
  date.setDate(date.getDate() + dayOffset);
  return date;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function toDateInputValue(date: Date): string {
  const year = String(date.getFullYear()).padStart(4, "0");
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function parseDateInputValue(value: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const parsed = new Date(year, month - 1, day);

  if (
    Number.isNaN(parsed.getTime()) ||
    parsed.getFullYear() !== year ||
    parsed.getMonth() !== month - 1 ||
    parsed.getDate() !== day
  ) {
    return null;
  }
  return parsed;
}

function buildInitial(lang: Lang, state: "core-solved" | "stage-two-missing" | "stage-two-revealed" | "solved" | "failed"): PuzzleInitial {
  const coreSolvedAttempt: GuessResult = { speakerOk: true, listenerOk: true, portionOk: false, bonusOk: false };
  const solvedAttempt: GuessResult = { speakerOk: true, listenerOk: true, portionOk: true, bonusOk: true };
  const failedAttempt: GuessResult = { speakerOk: false, listenerOk: false, portionOk: false, bonusOk: false };

  if (state === "core-solved") {
    return {
      speaker: localize(lang, "the LORD", "אֲדֹנָי"),
      listener: localize(lang, "Abram", "אַבְרָם"),
      portion: "",
      bonus: "",
      attempts: [coreSolvedAttempt],
    };
  }

  if (state === "stage-two-missing") {
    return {
      speaker: localize(lang, "the LORD", "אֲדֹנָי"),
      listener: localize(lang, "Abram", "אַבְרָם"),
      portion: "",
      bonus: localize(lang, "field", "שָׂדֶה"),
      attempts: [coreSolvedAttempt, coreSolvedAttempt],
    };
  }

  if (state === "stage-two-revealed") {
    return {
      speaker: localize(lang, "the LORD", "אֲדֹנָי"),
      listener: localize(lang, "Abram", "אַבְרָם"),
      portion: "",
      bonus: "",
      attempts: [coreSolvedAttempt, coreSolvedAttempt],
    };
  }

  if (state === "solved") {
    return {
      speaker: localize(lang, "the LORD", "אֲדֹנָי"),
      listener: localize(lang, "Abram", "אַבְרָם"),
      portion: localize(lang, "Lech-Lecha", "לך-לך"),
      bonus: localize(lang, "land", "הָאָרֶץ"),
      attempts: [failedAttempt, coreSolvedAttempt, solvedAttempt],
    };
  }

  return {
    speaker: localize(lang, "Moses", "משה"),
    listener: localize(lang, "Pharaoh", "פרעה"),
    portion: localize(lang, "Tzav", "צַו"),
    bonus: localize(lang, "house", "בֵּית אָבִיךָ"),
    attempts: [failedAttempt, failedAttempt, failedAttempt, failedAttempt, failedAttempt],
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

function QuoteBrowser({ lang }: { lang: Lang }) {
  const total = debugQuoteItems.length;
  const order = useMemo(() => buildDailyOrder(total), [total]);
  const maxDayOffset = Math.max(0, total - 1);
  const [dayOffset, setDayOffset] = useState(() => {
    if (total === 0) return 0;
    return clamp(dayOffsetFromEpoch(new Date()), 0, maxDayOffset);
  });

  useEffect(() => {
    setDayOffset((prev) => clamp(prev, 0, maxDayOffset));
  }, [maxDayOffset]);

  if (total === 0) {
    return <section className="card">{localize(lang, "No quotes available.", "אין ציטוטים זמינים.")}</section>;
  }

  const selectedDate = dateForDayOffset(dayOffset);
  const selectedItem = debugQuoteItems[order[dayOffset] ?? 0] ?? debugQuoteItems[0];
  const dateInputValue = toDateInputValue(selectedDate);
  const minDate = toDateInputValue(DEBUG_EPOCH_DATE);
  const maxDate = toDateInputValue(dateForDayOffset(maxDayOffset));
  const sourceStart = selectedItem.source?.ref_start ?? "";
  const sourceEnd = selectedItem.source?.ref_end ?? "";
  const sourceLabel = sourceStart && sourceEnd && sourceStart !== sourceEnd ? `${sourceStart} - ${sourceEnd}` : sourceStart || sourceEnd;
  const selectedText = selectedItem[lang];
  const portion = selectedItem.portion?.[lang] ?? "";
  const bonus = selectedText.bonus ?? "";

  return (
    <section className="debug-quote-browser">
      <div className="debug-quote-browser-controls">
        <button className="debug-quote-nav-btn" type="button" onClick={() => setDayOffset((prev) => clamp(prev - 1, 0, maxDayOffset))} disabled={dayOffset === 0}>
          {localize(lang, "< Prev", "< הקודם")}
        </button>
        <input
          className="debug-quote-date-input"
          type="date"
          aria-label={localize(lang, "Pick quote date", "בחרו תאריך ציטוט")}
          value={dateInputValue}
          min={minDate}
          max={maxDate}
          onChange={(event) => {
            const parsed = parseDateInputValue(event.target.value);
            if (!parsed) return;
            setDayOffset(clamp(dayOffsetFromEpoch(parsed), 0, maxDayOffset));
          }}
        />
        <button className="debug-quote-nav-btn" type="button" onClick={() => setDayOffset((prev) => clamp(prev + 1, 0, maxDayOffset))} disabled={dayOffset === maxDayOffset}>
          {localize(lang, "Next >", "הבא >")}
        </button>
      </div>

      <div className="debug-quote-browser-status">
        {localize(lang, `Quote ${dayOffset + 1} of ${total}`, `ציטוט ${dayOffset + 1} מתוך ${total}`)} | {selectedItem.id}
      </div>
      {sourceLabel ? <div className="debug-quote-browser-source">{sourceLabel}</div> : null}
      <div className="debug-quote-browser-card">
        <PuzzleCard
          puzzle={selectedItem}
          revealed
          quoteRevealed
          bookHintUsed={false}
          dateLabel={formatDate(selectedDate, lang)}
          onClear={() => undefined}
          onRevealBookHint={() => undefined}
        />
      </div>
      <section className="debug-quote-browser-answers card">
        <h3>{localize(lang, "Answers", "תשובות")}</h3>
        <div className="debug-answer-row">
          <span className="debug-answer-label">{localize(lang, "Speaker", "דובר")}</span>
          <span className="debug-answer-value">{selectedText.speaker}</span>
        </div>
        <div className="debug-answer-row">
          <span className="debug-answer-label">{localize(lang, "Listener", "מאזין")}</span>
          <span className="debug-answer-value">{selectedText.listener}</span>
        </div>
        {portion ? (
          <div className="debug-answer-row">
            <span className="debug-answer-label">{localize(lang, "Portion", "פרשה")}</span>
            <span className="debug-answer-value">{portion}</span>
          </div>
        ) : null}
        {bonus ? (
          <div className="debug-answer-row">
            <span className="debug-answer-label">{localize(lang, "Bonus", "בונוס")}</span>
            <span className="debug-answer-value">{bonus}</span>
          </div>
        ) : null}
      </section>
    </section>
  );
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
            <h2>{localize(lang, "All Quotes Browser", "דפדפן כל הציטוטים")}</h2>
            <QuoteBrowser lang={lang} />
          </article>
        </section>

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
              bookHintUsed={false}
              dateLabel={dateLabel}
              onClear={() => undefined}
              onRevealBookHint={() => undefined}
            />
          </article>

          <article className="debug-panel">
            <h2>PuzzleCard Revealed</h2>
            <PuzzleCard
              puzzle={samplePuzzle}
              revealed
              quoteRevealed
              bookHintUsed
              dateLabel={dateLabel}
              onClear={() => undefined}
              onRevealBookHint={() => undefined}
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
                onShare={() => undefined}
                coreSolved={false}
                showBonusRow
                extraChecked
                bonusDisabled={false}
                canShare
                disabled={false}
                feedback={localize(lang, "Try another speaker.", "נסו דובר אחר.")}
                shareNotice={localize(lang, "Copied results.", "התוצאות הועתקו.")}
                triesUsed={2}
                maxTries={5}
                statusMarks="❌✅⬜⬜"
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
