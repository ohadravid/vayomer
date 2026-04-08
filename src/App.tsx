import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Temporal } from "@js-temporal/polyfill";
import { answersMatch } from "./lib/answerMatcher";
import { pickDailyItemIndexWithOverrides } from "./lib/daily";
import { maskHardWord, pickHardWordPlaceholderForId } from "./lib/format";
import { getAlternateLanguage, getLanguageDirection, getLanguageFromI18n } from "./lib/language";
import { PUZZLE_MANIFEST, loadPuzzleItemById } from "./lib/puzzleData";
import { buildPuzzleStorageKey } from "./lib/persistence";
import type { GuessResult, Lang, PersistedGameFields, PuzzleItem } from "./types";
import { PuzzleView } from "./components/PuzzleView";
import { LanguageUrlSync } from "./components/LanguageUrlSync";
import packageMeta from "../package.json";
import exampleQuoteData from "./lib/exampleQuote.json";

const PUZZLE_QUERY_KEY = "puzzle";
const ABOUT_HASH = "#about";
const LEGACY_DIFFICULTY_QUERY_KEYS = ["hard", "easy"] as const;
const REPO_URL = "https://github.com/ohadravid/vayomer";
const APP_VERSION = packageMeta.version;

type PersistedState = PersistedGameFields & {
  version: string;
  lang: Lang;
  revealed: boolean;
};

enum AppPage {
  Game = "game",
  About = "about",
  Example = "example",
}

const EMPTY_PERSISTED_GAME_FIELDS: PersistedGameFields = {
  speaker: "",
  listener: "",
  portion: "",
  bonus: "",
  hintRevealed: false,
  attempts: [],
};
const EXAMPLE_PUZZLE: PuzzleItem | null = ((exampleQuoteData as { items?: PuzzleItem[] }).items ?? [])[0] ?? null;

function buildExamplePuzzleWithMaskedBonusWord(puzzle: PuzzleItem): PuzzleItem {
  const placeholder = pickHardWordPlaceholderForId(puzzle.id);
  const enBonus = puzzle.en.bonus ?? "";
  const heBonus = puzzle.he.bonus ?? "";

  return {
    ...puzzle,
    en: {
      ...puzzle.en,
      quote: maskHardWord(puzzle.en.quote, enBonus, placeholder, "en"),
    },
    he: {
      ...puzzle.he,
      quote: maskHardWord(puzzle.he.quote, heBonus, placeholder, "he"),
    },
  };
}

function pickExampleWrongSpeaker(puzzle: PuzzleItem, lang: Lang): string {
  const answer = puzzle[lang].speaker;
  const options = puzzle[lang].options?.speaker ?? [];
  const candidate = options.find((option) => !answersMatch(option, answer, lang));
  if (candidate) return candidate;
  return "";
}

function buildExampleInitialState(puzzle: PuzzleItem, lang: Lang): PersistedGameFields {
  const wrongSpeaker = pickExampleWrongSpeaker(puzzle, lang);
  const listener = puzzle[lang].listener;
  const speakerOk = answersMatch(wrongSpeaker, puzzle[lang].speaker, lang);
  const listenerOk = answersMatch(listener, puzzle[lang].listener, lang);

  return {
    speaker: wrongSpeaker,
    listener,
    portion: "",
    bonus: "",
    hintRevealed: false,
    attempts: [
      {
        speakerOk,
        listenerOk,
        portionOk: true,
        bonusOk: false,
      },
    ],
  };
}

function toPersistedGameFields(state: PersistedState): PersistedGameFields {
  return {
    speaker: state.speaker,
    listener: state.listener,
    portion: state.portion,
    bonus: state.bonus,
    hintRevealed: state.hintRevealed,
    attempts: state.attempts,
  };
}

function toGuessResult(raw: unknown): GuessResult | null {
  if (!raw || typeof raw !== "object") return null;
  const candidate = raw as Record<string, unknown>;
  if (
    typeof candidate.speakerOk !== "boolean" ||
    typeof candidate.listenerOk !== "boolean" ||
    typeof candidate.portionOk !== "boolean" ||
    typeof candidate.bonusOk !== "boolean"
  ) {
    return null;
  }
  return {
    speakerOk: candidate.speakerOk,
    listenerOk: candidate.listenerOk,
    portionOk: candidate.portionOk,
    bonusOk: candidate.bonusOk,
    hintUsed: typeof candidate.hintUsed === "boolean" ? candidate.hintUsed : undefined,
    countsAsTry: typeof candidate.countsAsTry === "boolean" ? candidate.countsAsTry : undefined,
  };
}

function parseAttempts(parsed: Record<string, unknown>): GuessResult[] {
  if (Array.isArray(parsed.attempts)) {
    return parsed.attempts
      .map((attempt) => toGuessResult(attempt))
      .filter((attempt): attempt is GuessResult => attempt !== null);
  }

  const legacyResult = toGuessResult(parsed.result);
  if (!legacyResult) return [];
  const tries =
    typeof parsed.guesses === "number" && Number.isFinite(parsed.guesses) && parsed.guesses > 0
      ? Math.floor(parsed.guesses)
      : 1;
  return Array.from({ length: tries }, () => ({ ...legacyResult }));
}

export function parsePersistedState(raw: string | null, lang: Lang, currentVersion: string): PersistedState | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    if (parsed.version !== currentVersion) return null;
    if (parsed.lang !== lang) return null;
    const attempts = parseAttempts(parsed);
    const hasCoreSolvedAttempt = attempts.some((attempt) => attempt.speakerOk && attempt.listenerOk);
    const revealed = !!parsed.revealed && hasCoreSolvedAttempt;
    const hintRevealed = !!parsed.hintRevealed || !!parsed.bookHintUsed;
    return {
      version: currentVersion,
      lang,
      speaker: typeof parsed.speaker === "string" ? parsed.speaker : "",
      listener: typeof parsed.listener === "string" ? parsed.listener : "",
      portion: typeof parsed.portion === "string" ? parsed.portion : "",
      bonus: typeof parsed.bonus === "string" ? parsed.bonus : "",
      hintRevealed,
      attempts,
      // Old/corrupted payloads can end up with `revealed: true` and no solved attempt.
      // Treat those as not revealed so the form remains playable on load.
      revealed,
    };
  } catch {
    return null;
  }
}

export function parsePuzzleIdFromSearch(search: string): string | null {
  const raw = new URLSearchParams(search).get(PUZZLE_QUERY_KEY);
  if (typeof raw !== "string") return null;
  const trimmed = raw.trim();
  return trimmed.length > 0 ? trimmed : null;
}

export function pickPuzzleIndexForSearch(
  items: readonly { id: string }[],
  search: string,
  date: Temporal.PlainDate = Temporal.Now.plainDateISO()
): number {
  if (items.length === 0) return 0;
  const requestedPuzzleId = parsePuzzleIdFromSearch(search);
  if (requestedPuzzleId) {
    const explicitIndex = items.findIndex((item) => item.id === requestedPuzzleId);
    if (explicitIndex >= 0) return explicitIndex;
  }
  return pickDailyItemIndexWithOverrides(items, date);
}

function pickInitialPuzzleIndex(items: readonly { id: string }[]): number {
  if (items.length === 0) return 0;
  const search = typeof window === "undefined" ? "" : window.location.search;
  return pickPuzzleIndexForSearch(items, search);
}

function getSearchWithoutLegacyDifficultyParams(search: string): string {
  const params = new URLSearchParams(search);
  let changed = false;

  for (const key of LEGACY_DIFFICULTY_QUERY_KEYS) {
    if (!params.has(key)) continue;
    params.delete(key);
    changed = true;
  }

  if (!changed) return search;
  const serialized = params.toString();
  return serialized ? `?${serialized}` : "";
}

type BrowserForHistorySync = {
  location: Pick<Location, "pathname" | "search" | "hash">;
  history: Pick<History, "state" | "replaceState">;
};

function syncLegacyDifficultyParamsInUrl(browser: BrowserForHistorySync): void {
  const current = `${browser.location.pathname}${browser.location.search}${browser.location.hash}`;
  const next = `${browser.location.pathname}${getSearchWithoutLegacyDifficultyParams(browser.location.search)}${browser.location.hash}`;
  if (current === next) return;
  browser.history.replaceState(browser.history.state, "", next);
}

function pickPageFromLocationHash(): AppPage {
  if (typeof window === "undefined") return AppPage.Game;
  const hash = window.location.hash.trim().replace(/^#/, "").toLowerCase();
  if (hash === AppPage.About) return AppPage.About;
  if (hash === AppPage.Example) return AppPage.Example;
  return AppPage.Game;
}

export function App() {
  const { t, i18n } = useTranslation();
  const lang = getLanguageFromI18n(i18n);
  const nextLanguage = getAlternateLanguage(lang);
  const manifestEntries = PUZZLE_MANIFEST;
  const [index] = useState(() => pickInitialPuzzleIndex(manifestEntries));
  const [puzzle, setPuzzle] = useState<PuzzleItem | null>(null);
  const [revealed, setRevealed] = useState(false);
  const [exampleRevealed, setExampleRevealed] = useState(false);
  const [initial, setInitial] = useState<PersistedGameFields | null>(null);
  const [page, setPage] = useState<AppPage>(() => pickPageFromLocationHash());

  useEffect(() => {
    if (typeof window === "undefined") return;
    const onHashChange = () => setPage(pickPageFromLocationHash());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const syncFromLocation = () => syncLegacyDifficultyParamsInUrl(window);
    syncFromLocation();
    window.addEventListener("popstate", syncFromLocation);
    return () => window.removeEventListener("popstate", syncFromLocation);
  }, []);

  useEffect(() => {
    const selectedId = manifestEntries[index]?.id;
    if (!selectedId) {
      setPuzzle(null);
      return;
    }

    let cancelled = false;
    void (async () => {
      try {
        const loadedPuzzle = await loadPuzzleItemById(selectedId);
        if (cancelled) return;
        setPuzzle(loadedPuzzle);
      } catch {
        if (cancelled) return;
        setPuzzle(null);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [manifestEntries, index]);

  const exampleMaskedPuzzle = useMemo(
    () => (EXAMPLE_PUZZLE ? buildExamplePuzzleWithMaskedBonusWord(EXAMPLE_PUZZLE) : null),
    []
  );
  const examplePuzzle = exampleRevealed ? EXAMPLE_PUZZLE : exampleMaskedPuzzle;
  const exampleInitial = useMemo(
    () => (EXAMPLE_PUZZLE ? buildExampleInitialState(EXAMPLE_PUZZLE, lang) : null),
    [lang]
  );
  const storageKey = puzzle ? buildPuzzleStorageKey(puzzle.id, lang) : "";

  useEffect(() => {
    if (!puzzle) return;
    const rawPersisted = localStorage.getItem(storageKey);
    const parsed = parsePersistedState(rawPersisted, lang, APP_VERSION);
    if (rawPersisted && !parsed) {
      localStorage.removeItem(storageKey);
    }
    setRevealed(parsed?.revealed ?? false);
    setInitial(parsed ? toPersistedGameFields(parsed) : { ...EMPTY_PERSISTED_GAME_FIELDS });
  }, [puzzle, storageKey, lang]);

  useEffect(() => {
    const direction = getLanguageDirection(lang);
    document.documentElement.lang = lang;
    document.documentElement.dir = direction;
    document.body.dir = direction;
    document.title = page === AppPage.About ? t("about.title") : page === AppPage.Example ? t("example.title") : t("app.pageTitle");
  }, [lang, page, t]);

  useEffect(() => {
    if (page === AppPage.Example) return;
    if (exampleRevealed) setExampleRevealed(false);
  }, [page, exampleRevealed]);

  if (!puzzle && page === AppPage.Game) return null;

  const persist = (state: PersistedGameFields) => {
    if (!puzzle) return;
    const existing = parsePersistedState(localStorage.getItem(storageKey), lang, APP_VERSION);
    const payload = {
      version: APP_VERSION,
      lang,
      ...state,
      revealed: existing?.revealed ?? revealed,
    };
    localStorage.setItem(storageKey, JSON.stringify(payload));
  };

  const clearResult = () => {
    if (!puzzle) return;
    localStorage.removeItem(storageKey);
    setRevealed(false);
    setInitial({ ...EMPTY_PERSISTED_GAME_FIELDS });
  };

  const reveal = () => {
    if (!puzzle) return;
    setRevealed(true);
    const existing = parsePersistedState(localStorage.getItem(storageKey), lang, APP_VERSION);
    localStorage.setItem(
      storageKey,
      JSON.stringify({
        ...(existing ?? { version: APP_VERSION, lang, ...EMPTY_PERSISTED_GAME_FIELDS, revealed: false }),
        revealed: true,
      })
    );
  };

  return (
    <div className="app" id="app">
      <LanguageUrlSync i18n={i18n} lang={lang} />

      <header className="header">
        <div className="header-copy">
          <div className="kicker">
            {page === AppPage.About ? t("about.kicker") : page === AppPage.Example ? t("example.kicker") : t("app.kicker")}
          </div>
          <h1>{page === AppPage.About ? t("about.title") : page === AppPage.Example ? t("example.title") : t("app.title")}</h1>
        </div>
        <div className="controls">
          <button
            className="chip"
            type="button"
            onClick={() => void i18n.changeLanguage(nextLanguage)}
            aria-label={t("app.switchLanguage", { language: nextLanguage.toUpperCase() })}
          >
            {nextLanguage.toUpperCase()}
          </button>
          {page === AppPage.Game ? (
            <>
              <button
                className="chip"
                type="button"
                onClick={() => {
                  window.location.hash = AppPage.Example;
                }}
                aria-label={t("app.openExample")}
                title={t("app.openExample")}
              >
                ❓
              </button>
            </>
          ) : (
            <a id="topBackButton" className="chip back-chip" href="#">⬅️</a>
          )}
        </div>
        <p className="subtitle header-subtitle">
          {page === AppPage.About ? t("about.subtitle") : page === AppPage.Example ? t("example.subtitle") : t("app.subtitle")}
        </p>
      </header>

      {page === AppPage.About ? (
        <section className="card about-card">
          <p>{t("about.gameDescription")}</p>
          <h2 className="about-heading">{t("about.sourceHeading")}</h2>
          <ul className="about-list">
            <li>
              <strong>{t("about.hebrewLabel")}</strong>{" "}
              <a href="https://tanach.us/" target="_blank" rel="noreferrer">
                {t("about.hebrewSourceName")}
              </a>
            </li>
            <li>
              <strong>{t("about.englishLabel")}</strong>{" "}
              <a href="https://hdl.handle.net/21.11113/0000-0016-9447-1" target="_blank" rel="noreferrer">
                {t("about.englishSourceName")}
              </a>
            </li>
            <li>
              <strong>{t("about.fontLabel")}</strong>{" "}
              <a href="https://opensiddur.org/help/fonts/#t'amim-with-niqqud" target="_blank" rel="noreferrer">
                {t("about.fontSourceName")}
              </a>
              <p>({t("about.fontLicenseNote")})</p>
            </li>
          </ul>
          <p className="about-note">{t("about.modelNote")}</p>
          <p className="about-note">
            <a href="https://icons8.com/icon/112712/scroll" target="_blank" rel="noreferrer">
              Scroll
            </a>{" "}
            icon by{" "}
            <a href="https://icons8.com" target="_blank" rel="noreferrer">
              Icons8
            </a>
          </p>
        </section>
      ) : page === AppPage.Example && examplePuzzle ? (
        <>
          <PuzzleView
            puzzle={examplePuzzle}
            revealed={exampleRevealed}
            onReveal={() => {
              setExampleRevealed(true);
            }}
            onClear={() => {}}
            initial={exampleInitial ?? undefined}
            shareEnabled={false}
            upperCornerLabel={t("example.upperCornerLabel")}
          />
        </>
      ) : puzzle ? (
        <PuzzleView
          puzzle={puzzle}
          revealed={revealed}
          onReveal={reveal}
          onClear={clearResult}
          onPersist={persist}
          initial={initial ?? undefined}
        />
      ) : null}

      <footer className="footer-note">
        {page === AppPage.Game ? (
          <div>
            <a className="footer-link" href={ABOUT_HASH}>
              {t("about.link")}
            </a>
          </div>
        ) : null}
        <div>
          <a className="footer-link footer-version-link" href={REPO_URL} target="_blank" rel="noreferrer">
            {t("footer.version", { version: APP_VERSION })}
          </a>
        </div>
      </footer>
    </div>
  );
}
