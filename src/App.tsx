import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Temporal } from "@js-temporal/polyfill";
import { answersMatch } from "./lib/answerMatcher";
import { pickDailyItemIndexWithOverrides } from "./lib/daily";
import { maskHardWord, pickHardWordPlaceholderForId } from "./lib/format";
import { getAlternateLanguage, getLanguageDirection, getLanguageFromI18n } from "./lib/language";
import { loadPuzzleItems } from "./lib/puzzleData";
import { buildPuzzleStorageKey } from "./lib/persistence";
import type { GuessResult, Lang, PersistedGameFields, PuzzleItem } from "./types";
import { PuzzleView } from "./components/PuzzleView";
import { LanguageUrlSync } from "./components/LanguageUrlSync";
import packageMeta from "../package.json";
import exampleQuoteData from "./lib/exampleQuote.json";

const EASY_MODE_STORAGE_KEY = "qs:easy-mode";
const HARD_MODE_QUERY_KEY = "hard";
const LEGACY_EASY_MODE_QUERY_KEY = "easy";
const PUZZLE_QUERY_KEY = "puzzle";
const ABOUT_HASH = "#about";
const EXAMPLE_HASH = "#example";
const DEFAULT_EASY_MODE = true;
const DIFFICULTY_LOCK_STORAGE_PREFIX = "qs:difficulty-lock:";
const REPO_URL = "https://github.com/ohadravid/vayomer";
const APP_VERSION = packageMeta.version;
const ENCODED_TRUE = "1";
const ENCODED_FALSE = "0";
const STORAGE_TRUE_VALUE = ENCODED_TRUE;

type EncodedBoolean = typeof ENCODED_TRUE | typeof ENCODED_FALSE;

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

export function buildDifficultyLockStorageKey(puzzleId: string): string {
  return `${DIFFICULTY_LOCK_STORAGE_PREFIX}${puzzleId}`;
}

export function parseDifficultyLockFromStorageValue(raw: string | null): boolean | null {
  return parseEasyModeFromStorageValue(raw);
}

export function toDifficultyLockStorageValue(enabled: boolean): EncodedBoolean {
  return toEasyModeStorageValue(enabled);
}

export function isEasyModeToggleBlocked(lockedEasyMode: boolean | null, easyMode: boolean): boolean {
  // A locked puzzle can always move from hard -> easy, but never back to hard.
  const togglingToHard = easyMode;
  return togglingToHard && lockedEasyMode !== null;
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

function parseEncodedBoolean(raw: string | null, trueValue: EncodedBoolean): boolean | null {
  if (raw !== ENCODED_TRUE && raw !== ENCODED_FALSE) return null;
  return raw === trueValue;
}

function toEncodedBoolean(value: boolean, trueValue: EncodedBoolean): EncodedBoolean {
  if (value) return trueValue;
  return trueValue === ENCODED_TRUE ? ENCODED_FALSE : ENCODED_TRUE;
}

function parseHardModeFromQueryValue(raw: string | null): boolean | null {
  return parseEncodedBoolean(raw, ENCODED_TRUE);
}

function parseEasyModeFromStorageValue(raw: string | null): boolean | null {
  return parseEncodedBoolean(raw, STORAGE_TRUE_VALUE);
}

export function toEasyModeStorageValue(enabled: boolean): EncodedBoolean {
  return toEncodedBoolean(enabled, STORAGE_TRUE_VALUE);
}

function toHardModeQueryValue(enabled: boolean): EncodedBoolean {
  return toEncodedBoolean(enabled, ENCODED_TRUE);
}

function pickEasyModeFromStorage(): boolean {
  if (typeof window === "undefined") return DEFAULT_EASY_MODE;
  try {
    return parseEasyModeFromStorageValue(window.localStorage.getItem(EASY_MODE_STORAGE_KEY)) ?? DEFAULT_EASY_MODE;
  } catch {
    return DEFAULT_EASY_MODE;
  }
}

export function parseEasyModeFromSearch(search: string): boolean | null {
  const hardMode = parseHardModeFromQueryValue(new URLSearchParams(search).get(HARD_MODE_QUERY_KEY));
  if (hardMode === null) return null;
  return !hardMode;
}

export function parsePuzzleIdFromSearch(search: string): string | null {
  const raw = new URLSearchParams(search).get(PUZZLE_QUERY_KEY);
  if (typeof raw !== "string") return null;
  const trimmed = raw.trim();
  return trimmed.length > 0 ? trimmed : null;
}

export function pickPuzzleIndexForSearch(
  items: PuzzleItem[],
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

function pickEasyMode(): boolean {
  if (typeof window === "undefined") return DEFAULT_EASY_MODE;
  const fromUrl = parseEasyModeFromSearch(window.location.search);
  if (fromUrl !== null) return fromUrl;
  return pickEasyModeFromStorage();
}

export function pickEasyModeForNavigation(search: string): boolean {
  const fromUrl = parseEasyModeFromSearch(search);
  return fromUrl ?? DEFAULT_EASY_MODE;
}

export function getSearchWithEasyMode(search: string, easyModeEnabled: boolean): string {
  const params = new URLSearchParams(search);
  params.delete(LEGACY_EASY_MODE_QUERY_KEY);
  const hardModeEnabled = !easyModeEnabled;
  if (easyModeEnabled === DEFAULT_EASY_MODE) {
    params.delete(HARD_MODE_QUERY_KEY);
  } else {
    params.set(HARD_MODE_QUERY_KEY, toHardModeQueryValue(hardModeEnabled));
  }
  const serialized = params.toString();
  return serialized ? `?${serialized}` : "";
}

type BrowserForEasyModeHistory = {
  location: Pick<Location, "pathname" | "search" | "hash">;
  history: Pick<History, "state" | "replaceState">;
};

type StorageKeyAccess = Pick<Storage, "length" | "key" | "removeItem">;

export function buildLocationWithEasyMode(pathname: string, search: string, hash: string, easyModeEnabled: boolean): string {
  return `${pathname}${getSearchWithEasyMode(search, easyModeEnabled)}${hash}`;
}

export function syncEasyModeInUrl(browser: BrowserForEasyModeHistory, easyModeEnabled: boolean): void {
  const current = `${browser.location.pathname}${browser.location.search}${browser.location.hash}`;
  const next = buildLocationWithEasyMode(
    browser.location.pathname,
    browser.location.search,
    browser.location.hash,
    easyModeEnabled
  );
  if (current === next) return;
  browser.history.replaceState(browser.history.state, "", next);
}

export function pruneDifficultyLockKeys(storage: StorageKeyAccess, keepPuzzleId: string): void {
  const keepKey = buildDifficultyLockStorageKey(keepPuzzleId);
  for (let idx = storage.length - 1; idx >= 0; idx -= 1) {
    const key = storage.key(idx);
    if (!key || !key.startsWith(DIFFICULTY_LOCK_STORAGE_PREFIX) || key === keepKey) continue;
    storage.removeItem(key);
  }
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
  const [items, setItems] = useState<PuzzleItem[]>([]);
  const [index, setIndex] = useState(0);
  const [easyMode, setEasyMode] = useState<boolean>(() => pickEasyMode());
  const [lockedEasyModeByPuzzle, setLockedEasyModeByPuzzle] = useState<{ puzzleId: string; value: boolean | null }>({
    puzzleId: "",
    value: null,
  });
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
    const syncEasyModeFromLocation = () => {
      const next = pickEasyModeForNavigation(window.location.search);
      const currentPuzzleId = items[index]?.id;
      if (!currentPuzzleId) {
        setEasyMode(next);
        return;
      }
      let locked: boolean | null = null;
      try {
        locked = parseDifficultyLockFromStorageValue(
          window.localStorage.getItem(buildDifficultyLockStorageKey(currentPuzzleId))
        );
      } catch {
        locked = null;
      }
      setEasyMode(locked ?? next);
    };
    window.addEventListener("popstate", syncEasyModeFromLocation);
    return () => window.removeEventListener("popstate", syncEasyModeFromLocation);
  }, [items, index]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    syncEasyModeInUrl(window, easyMode);
    try {
      localStorage.setItem(EASY_MODE_STORAGE_KEY, toEasyModeStorageValue(easyMode));
    } catch {
      // Ignore storage access errors.
    }
  }, [easyMode]);

  useEffect(() => {
    const list = loadPuzzleItems();
    if (list.length === 0) {
      setItems([]);
      return;
    }

    if (typeof window !== "undefined") {
      const todayPuzzle = list[pickDailyItemIndexWithOverrides(list)];
      if (todayPuzzle) {
        try {
          pruneDifficultyLockKeys(window.localStorage, todayPuzzle.id);
        } catch {
          // Ignore storage access errors.
        }
      }
    }

    setItems(list);
    const search = typeof window === "undefined" ? "" : window.location.search;
    setIndex(pickPuzzleIndexForSearch(list, search));
  }, []);

  const puzzle = useMemo(() => items[index], [items, index]);
  const exampleMaskedPuzzle = useMemo(
    () => (EXAMPLE_PUZZLE ? buildExamplePuzzleWithMaskedBonusWord(EXAMPLE_PUZZLE) : null),
    []
  );
  const examplePuzzle = exampleRevealed ? EXAMPLE_PUZZLE : exampleMaskedPuzzle;
  const exampleInitial = useMemo(
    () => (EXAMPLE_PUZZLE ? buildExampleInitialState(EXAMPLE_PUZZLE, lang) : null),
    [lang]
  );
  const lockedEasyMode = puzzle && lockedEasyModeByPuzzle.puzzleId === puzzle.id ? lockedEasyModeByPuzzle.value : null;
  const easyModeToggleBlocked = isEasyModeToggleBlocked(lockedEasyMode, easyMode);
  const storageKey = puzzle ? buildPuzzleStorageKey(puzzle.id, lang) : "";

  useEffect(() => {
    if (!puzzle) return;
    let difficultyLock: boolean | null = null;
    try {
      difficultyLock = parseDifficultyLockFromStorageValue(
        localStorage.getItem(buildDifficultyLockStorageKey(puzzle.id))
      );
    } catch {
      difficultyLock = null;
    }
    setLockedEasyModeByPuzzle({ puzzleId: puzzle.id, value: difficultyLock });
    if (difficultyLock !== null) {
      setEasyMode(difficultyLock);
    }
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

  const toggleEasyMode = () => {
    if (easyModeToggleBlocked) return;
    setEasyMode((previous) => !previous);
  };

  const lockDifficultyForPuzzle = () => {
    if (!puzzle || typeof window === "undefined") return;
    const lockKey = buildDifficultyLockStorageKey(puzzle.id);
    let existing: boolean | null = null;
    try {
      existing = parseDifficultyLockFromStorageValue(window.localStorage.getItem(lockKey));
    } catch {
      existing = null;
    }
    const nextLock = existing ?? easyMode;
    if (existing === null) {
      try {
        window.localStorage.setItem(lockKey, toDifficultyLockStorageValue(nextLock));
      } catch {
        // Ignore storage access errors.
      }
    }
    setLockedEasyModeByPuzzle({ puzzleId: puzzle.id, value: nextLock });
    if (easyMode !== nextLock) {
      setEasyMode(nextLock);
    }
  };

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
                className={`chip difficulty ${easyMode ? "active" : ""}`}
                type="button"
                onClick={toggleEasyMode}
                disabled={easyModeToggleBlocked}
                aria-pressed={easyMode}
                aria-label={t("app.toggleEasyMode")}
                title={easyModeToggleBlocked ? t("app.easyModeLockedTooltip") : t("app.easyModeTooltip")}
              >
                🐑
              </button>
              <button
                className="chip difficulty"
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
            easyMode
            revealed={exampleRevealed}
            onReveal={() => {
              setExampleRevealed(true);
            }}
            onClear={() => {}}
            initial={exampleInitial ?? undefined}
            shareEnabled={false}
          />
        </>
      ) : puzzle ? (
        <PuzzleView
          puzzle={puzzle}
          easyMode={easyMode}
          onChoiceInteracted={lockDifficultyForPuzzle}
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
