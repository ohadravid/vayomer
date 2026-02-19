import { useEffect, useMemo, useState, type ComponentProps } from "react";
import { createInstance } from "i18next";
import { I18nextProvider, initReactI18next } from "react-i18next";
import { GuessForm } from "./components/GuessForm";
import { PuzzleCard } from "./components/PuzzleCard";
import { PuzzleView } from "./components/PuzzleView";
import { resources } from "./i18n";
import { formatDate } from "./lib/format";
import { getLanguageDirection } from "./lib/language";
import { loadPuzzleItems } from "./lib/puzzleData";
import { dayIndex, pickDailyItemIndexWithOverrides } from "./lib/daily";
import type {
  BonusHint,
  DifficultyChoicePools,
  EasyChoiceField,
  EasyChoicePools,
  GuessEditState,
  GuessResult,
  GuessValues,
  Lang,
  PuzzleItem,
} from "./types";

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
const CHOICE_FIELDS: EasyChoiceField[] = ["speaker", "listener"];

const debugQuoteItems = loadPuzzleItems();

function localize(lang: Lang, english: string, hebrew: string): string {
  return lang === "he" ? hebrew : english;
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

function toInt(value: number | undefined): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return Math.floor(value);
  return null;
}

function formatBonusHintSourceLine(hint: BonusHint | null | undefined): string {
  if (!hint?.source) return "";
  const book = typeof hint.source.book === "string" ? hint.source.book.trim() : "";
  const chapter = toInt(hint.source.chapter);
  const start = toInt(hint.source.start);
  const end = toInt(hint.source.end);
  const range =
    chapter !== null && start !== null
      ? `${chapter}:${end !== null && end !== start ? `${start}-${end}` : start}`
      : "";
  return [book, range].filter(Boolean).join(" ");
}

function normalizeChoicePool(pools: DifficultyChoicePools | null | undefined, field: EasyChoiceField): string[] {
  const raw = pools?.[field];
  if (!Array.isArray(raw)) return [];
  const values: string[] = [];
  const seen = new Set<string>();

  for (const value of raw) {
    if (typeof value !== "string") continue;
    const trimmed = value.trim();
    if (!trimmed || seen.has(trimmed)) continue;
    values.push(trimmed);
    seen.add(trimmed);
  }

  return values;
}

function renderChoicePoolValues(lang: Lang, pools: DifficultyChoicePools | null | undefined) {
  const entries = CHOICE_FIELDS.map((field) => ({
    field,
    values: normalizeChoicePool(pools, field),
  })).filter((entry) => entry.values.length > 0);

  if (entries.length === 0) {
    return <span className="debug-choice-pool-empty">{localize(lang, "Not set", "לא הוגדר")}</span>;
  }

  return (
    <div className="debug-choice-pools">
      {entries.map((entry) => (
        <div className="debug-choice-pool-row" key={entry.field}>
          <span className="debug-choice-pool-field">{entry.field === "speaker" ? localize(lang, "Speaker", "דובר") : localize(lang, "Listener", "מאזין")}</span>
          <span className="debug-choice-pool-values">{entry.values.join(", ")}</span>
        </div>
      ))}
    </div>
  );
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
      easyMode={false}
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

export function QuoteBrowser({ lang, items = debugQuoteItems }: { lang: Lang; items?: PuzzleItem[] }) {
  const total = items.length;
  const [showFullQuote, setShowFullQuote] = useState(true);
  const [selectedDate, setSelectedDate] = useState(() => new Date());

  if (total === 0) {
    return <section className="card">{localize(lang, "No quotes available.", "אין ציטוטים זמינים.")}</section>;
  }

  const daySlotIndex = dayIndex(total, selectedDate);
  const selectedItemIndex = pickDailyItemIndexWithOverrides(items, selectedDate);
  const displayOrderIndex = daySlotIndex + 1;
  const selectedItem = items[selectedItemIndex] ?? items[0];
  const dateInputValue = toDateInputValue(selectedDate);
  const sourceStart = selectedItem.source?.ref_start ?? "";
  const sourceEnd = selectedItem.source?.ref_end ?? "";
  const sourceLabel = sourceStart && sourceEnd && sourceStart !== sourceEnd ? `${sourceStart} - ${sourceEnd}` : sourceStart || sourceEnd;
  const selectedText = selectedItem[lang];
  const portion = selectedItem.portion?.[lang] ?? "";
  const bonus = selectedText.bonus ?? "";
  const bonusHintQuote = selectedText.bonus_hint?.quote?.trim() ?? "";
  const bonusHintSourceLine = formatBonusHintSourceLine(selectedText.bonus_hint);
  const displayItem = showFullQuote
    ? selectedItem
    : lang === "he"
      ? {
          ...selectedItem,
          he: {
            ...selectedItem.he,
            quote: selectedItem.he.riddle,
          },
        }
      : {
          ...selectedItem,
          en: {
            ...selectedItem.en,
            quote: selectedItem.en.riddle,
          },
        };

  return (
    <section className="debug-quote-browser">
      <div className="debug-quote-browser-controls">
        <button
          className="debug-quote-nav-btn"
          type="button"
          onClick={() =>
            setSelectedDate((prev) => {
              const next = new Date(prev);
              next.setDate(next.getDate() - 1);
              return next;
            })
          }
        >
          {localize(lang, "< Prev", "< הקודם")}
        </button>
        <input
          className="debug-quote-date-input"
          type="date"
          aria-label={localize(lang, "Pick quote date", "בחרו תאריך ציטוט")}
          value={dateInputValue}
          onChange={(event) => {
            const parsed = parseDateInputValue(event.target.value);
            if (!parsed) return;
            setSelectedDate(parsed);
          }}
        />
        <button
          className="debug-quote-nav-btn"
          type="button"
          onClick={() =>
            setSelectedDate((prev) => {
              const next = new Date(prev);
              next.setDate(next.getDate() + 1);
              return next;
            })
          }
        >
          {localize(lang, "Next >", "הבא >")}
        </button>
      </div>
      <div className="debug-quote-browser-toggles">
        <button className={`chip debug-quote-toggle-btn ${showFullQuote ? "active" : ""}`} type="button" onClick={() => setShowFullQuote(true)}>
          {localize(lang, "Full", "מלא")}
        </button>
        <button className={`chip debug-quote-toggle-btn ${!showFullQuote ? "active" : ""}`} type="button" onClick={() => setShowFullQuote(false)}>
          {localize(lang, "Riddle only", "חידה בלבד")}
        </button>
      </div>

      <div className="debug-quote-browser-status">
        {localize(lang, `Quote ${displayOrderIndex} of ${total}`, `ציטוט ${displayOrderIndex} מתוך ${total}`)} | {selectedItem.id}
      </div>
      {sourceLabel ? <div className="debug-quote-browser-source">{sourceLabel}</div> : null}
      <div className="debug-quote-browser-card">
        <PuzzleCard
          puzzle={displayItem}
          revealed
          quoteRevealed={showFullQuote}
          sourceRevealed
          dateLabel={formatDate(selectedDate, lang)}
          onClear={() => undefined}
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
        <div className="debug-answer-row">
          <span className="debug-answer-label">{localize(lang, "Bonus hint", "רמז בונוס")}</span>
          <div className="debug-answer-value">
            {bonusHintQuote || bonusHintSourceLine ? (
              <div className="debug-bonus-hint">
                {bonusHintQuote ? <div className="debug-bonus-hint-quote">{bonusHintQuote}</div> : null}
                {bonusHintSourceLine ? <div className="debug-bonus-hint-source">{bonusHintSourceLine}</div> : null}
              </div>
            ) : (
              <span className="debug-choice-pool-empty">{localize(lang, "Not set", "לא הוגדר")}</span>
            )}
          </div>
        </div>
        <div className="debug-answer-row">
          <span className="debug-answer-label">{localize(lang, "Options", "אפשרויות")}</span>
          <div className="debug-answer-value">{renderChoicePoolValues(lang, selectedText.options)}</div>
        </div>
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
              choicePools={choicePools}
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
              choicePools={choicePools}
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
              choicePools={choicePools}
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
              choicePools={choicePools}
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
              choicePools={choicePools}
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
              sourceRevealed={false}
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
              sourceRevealed
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
                onShare={() => undefined}
                coreSolved={false}
                showBonusRow
                extraChecked
                bonusDisabled={false}
                bonusHintUsed={false}
                showBonusHint
                showHintQuote
                hintQuoteHtml="hint"
                hintSourceLine={localize(lang, "Genesis 12:1", "בראשית 12:1")}
                canShare
                disabled={false}
                feedback={localize(lang, "Try another speaker.", "נסו דובר אחר.")}
                shareNotice={localize(lang, "Copied results.", "התוצאות הועתקו.")}
                triesUsed={2}
                maxTries={5}
                statusMarks="❌✅⬜⬜"
                onRevealBonusHint={() => undefined}
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
