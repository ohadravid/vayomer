import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { resolveChoicePoolsForPuzzle } from "./lib/easyMode";
import { pickDailyItemIndex } from "./lib/daily";
import { getAlternateLanguage, getLanguageDirection, getLanguageFromI18n } from "./lib/language";
import { loadPuzzleItems } from "./lib/puzzleData";
import { buildPuzzleStorageKey } from "./lib/persistence";
import type { GuessResult, Lang, PuzzleItem } from "./types";
import { PuzzleView } from "./components/PuzzleView";
import { LanguageUrlSync } from "./components/LanguageUrlSync";
import packageMeta from "../package.json";

const EASY_MODE_STORAGE_KEY = "qs:easy-mode";
const EASY_MODE_QUERY_KEY = "easy";
const PUZZLE_QUERY_KEY = "puzzle";
const ABOUT_HASH = "#about";
const DEFAULT_EASY_MODE = true;
const DIFFICULTY_LOCK_STORAGE_PREFIX = "qs:difficulty-lock:";
const REPO_URL = "https://github.com/ohadravid/vayomer";
const APP_VERSION = packageMeta.version;

enum EasyModeQueryValue {
  On = "0",
  Off = "1",
}

enum EasyModeStorageValue {
  Off = "0",
  On = "1",
}

type PersistedState = {
  version: string;
  lang: Lang;
  speaker: string;
  listener: string;
  portion: string;
  bonus: string;
  bookHintUsed: boolean;
  hintRevealed: boolean;
  attempts: GuessResult[];
  revealed: boolean;
};

type PersistInput = Omit<PersistedState, "version" | "lang" | "revealed">;
type AppPage = "game" | "about";

const EMPTY_PERSIST_INPUT: PersistInput = {
  speaker: "",
  listener: "",
  portion: "",
  bonus: "",
  bookHintUsed: false,
  hintRevealed: false,
  attempts: [],
};

function toPersistInput(state: PersistedState): PersistInput {
  return {
    speaker: state.speaker,
    listener: state.listener,
    portion: state.portion,
    bonus: state.bonus,
    bookHintUsed: state.bookHintUsed,
    hintRevealed: state.hintRevealed,
    attempts: state.attempts,
  };
}

function isGuessResult(raw: unknown): raw is GuessResult {
  if (!raw || typeof raw !== "object") return false;
  const candidate = raw as Record<string, unknown>;
  return (
    typeof candidate.speakerOk === "boolean" &&
    typeof candidate.listenerOk === "boolean" &&
    typeof candidate.portionOk === "boolean" &&
    typeof candidate.bonusOk === "boolean"
  );
}

function parseAttempts(parsed: Partial<PersistedState> & { result?: unknown; guesses?: unknown }): GuessResult[] {
  if (Array.isArray(parsed.attempts)) {
    return parsed.attempts.filter((attempt): attempt is GuessResult => isGuessResult(attempt));
  }

  if (!isGuessResult(parsed.result)) return [];
  const tries =
    typeof parsed.guesses === "number" && Number.isFinite(parsed.guesses) && parsed.guesses > 0
      ? Math.floor(parsed.guesses)
      : 1;
  const legacyResult: GuessResult = parsed.result;
  return Array.from({ length: tries }, () => ({ ...legacyResult }));
}

export function buildDifficultyLockStorageKey(puzzleId: string): string {
  return `${DIFFICULTY_LOCK_STORAGE_PREFIX}${puzzleId}`;
}

export function parseDifficultyLockFromStorageValue(raw: string | null): boolean | null {
  return parseEasyModeFromStorageValue(raw);
}

export function toDifficultyLockStorageValue(enabled: boolean): EasyModeStorageValue {
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
    const parsed = JSON.parse(raw) as Partial<PersistedState> & { result?: unknown; guesses?: unknown };
    if (parsed.version !== currentVersion) return null;
    if (parsed.lang !== lang) return null;
    const attempts = parseAttempts(parsed);
    const hasCoreSolvedAttempt = attempts.some((attempt) => attempt.speakerOk && attempt.listenerOk);
    const revealed = !!parsed.revealed && hasCoreSolvedAttempt;
    const bookHintUsed = !!parsed.bookHintUsed;
    const hintRevealed = !!parsed.hintRevealed || bookHintUsed;
    return {
      version: parsed.version ?? currentVersion,
      lang,
      speaker: parsed.speaker ?? "",
      listener: parsed.listener ?? "",
      portion: parsed.portion ?? "",
      bonus: parsed.bonus ?? "",
      bookHintUsed,
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

function parseEasyModeFromQueryValue(raw: string | null): boolean | null {
  if (raw === EasyModeQueryValue.On) return true;
  if (raw === EasyModeQueryValue.Off) return false;
  return null;
}

function parseEasyModeFromStorageValue(raw: string | null): boolean | null {
  if (raw === EasyModeStorageValue.On) return true;
  if (raw === EasyModeStorageValue.Off) return false;
  return null;
}

export function toEasyModeStorageValue(enabled: boolean): EasyModeStorageValue {
  return enabled ? EasyModeStorageValue.On : EasyModeStorageValue.Off;
}

function toEasyModeQueryValue(enabled: boolean): EasyModeQueryValue {
  return enabled ? EasyModeQueryValue.On : EasyModeQueryValue.Off;
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
  return parseEasyModeFromQueryValue(new URLSearchParams(search).get(EASY_MODE_QUERY_KEY));
}

export function parsePuzzleIdFromSearch(search: string): string | null {
  const raw = new URLSearchParams(search).get(PUZZLE_QUERY_KEY);
  if (typeof raw !== "string") return null;
  const trimmed = raw.trim();
  return trimmed.length > 0 ? trimmed : null;
}

export function pickPuzzleIndexForSearch(items: PuzzleItem[], search: string): number {
  if (items.length === 0) return 0;
  const requestedPuzzleId = parsePuzzleIdFromSearch(search);
  if (requestedPuzzleId) {
    const explicitIndex = items.findIndex((item) => item.id === requestedPuzzleId);
    if (explicitIndex >= 0) return explicitIndex;
  }
  return pickDailyItemIndex(items.length);
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
  if (easyModeEnabled === DEFAULT_EASY_MODE) {
    params.delete(EASY_MODE_QUERY_KEY);
  } else {
    params.set(EASY_MODE_QUERY_KEY, toEasyModeQueryValue(easyModeEnabled));
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

function pickPageFromHash(hash: string): AppPage {
  const normalized = hash.trim().replace(/^#/, "").toLowerCase();
  return normalized === "about" ? "about" : "game";
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
  const [initial, setInitial] = useState<PersistInput | null>(null);
  const [page, setPage] = useState<AppPage>(() => {
    if (typeof window === "undefined") return "game";
    return pickPageFromHash(window.location.hash);
  });

  useEffect(() => {
    if (typeof window === "undefined") return;
    const onHashChange = () => setPage(pickPageFromHash(window.location.hash));
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
      const todayPuzzle = list[pickDailyItemIndex(list.length)];
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
  const lockedEasyMode = puzzle && lockedEasyModeByPuzzle.puzzleId === puzzle.id ? lockedEasyModeByPuzzle.value : null;
  const easyModeToggleBlocked = isEasyModeToggleBlocked(lockedEasyMode, easyMode);
  const storageKey = puzzle ? buildPuzzleStorageKey(puzzle.id, lang) : "";
  const choicePools = useMemo(() => {
    if (!puzzle) return null;
    return resolveChoicePoolsForPuzzle({
      puzzle,
      items,
      lang,
    });
  }, [puzzle, items, lang]);

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
    setInitial(parsed ? toPersistInput(parsed) : { ...EMPTY_PERSIST_INPUT });
  }, [puzzle, storageKey, lang]);

  useEffect(() => {
    const direction = getLanguageDirection(lang);
    document.documentElement.lang = lang;
    document.documentElement.dir = direction;
    document.body.dir = direction;
    document.title = page === "about" ? t("about.title") : t("app.pageTitle");
  }, [lang, page, t]);

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

  if (!puzzle && page === "game") return null;

  const persist = (state: PersistInput) => {
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
    setInitial({ ...EMPTY_PERSIST_INPUT });
  };

  const reveal = () => {
    if (!puzzle) return;
    setRevealed(true);
    const existing = parsePersistedState(localStorage.getItem(storageKey), lang, APP_VERSION);
    localStorage.setItem(
      storageKey,
      JSON.stringify({
        ...(existing ?? { version: APP_VERSION, lang, ...EMPTY_PERSIST_INPUT, revealed: false }),
        revealed: true,
      })
    );
  };

  return (
    <div className="app" id="app">
      <LanguageUrlSync i18n={i18n} lang={lang} />

      <header className="header">
        <div className="header-copy">
          <div className="kicker">{page === "about" ? t("about.kicker") : t("app.kicker")}</div>
          <h1>{page === "about" ? t("about.title") : t("app.title")}</h1>
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
          {page === "game" ? (
            <button
              className={`chip ${easyMode ? "active" : ""}`}
              type="button"
              onClick={toggleEasyMode}
              disabled={easyModeToggleBlocked}
              aria-pressed={easyMode}
              aria-label={t("app.toggleEasyMode")}
              title={easyModeToggleBlocked ? t("app.easyModeLockedTooltip") : t("app.easyModeTooltip")}
            >
              🐑
            </button>
          ) : null}
        </div>
        <p className="subtitle header-subtitle">{page === "about" ? t("about.subtitle") : t("app.subtitle")}</p>
      </header>

      {page === "about" ? (
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
      ) : puzzle ? (
        <PuzzleView
          puzzle={puzzle}
          easyMode={easyMode}
          choicePools={choicePools ?? undefined}
          onChoiceInteracted={lockDifficultyForPuzzle}
          revealed={revealed}
          onReveal={reveal}
          onClear={clearResult}
          onPersist={persist}
          initial={initial ?? undefined}
        />
      ) : null}

      <footer className="footer-note">
        <div>
          <a className="footer-link" href={page === "about" ? "#" : ABOUT_HASH}>
            {page === "about" ? t("about.backToGame") : t("about.link")}
          </a>
        </div>
        <div>
          <a className="footer-link footer-version-link" href={REPO_URL} target="_blank" rel="noreferrer">
            {t("footer.version", { version: APP_VERSION })}
          </a>
        </div>
      </footer>
    </div>
  );
}
