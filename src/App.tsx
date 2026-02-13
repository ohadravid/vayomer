import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { parseOptionsDataset, resolveChoicePoolsForPuzzle } from "./lib/easyMode";
import { getAlternateLanguage, getLanguageDirection, getLanguageFromI18n } from "./lib/language";
import { buildPuzzleStorageKey } from "./lib/persistence";
import type { BookOptionSet, GuessResult, Lang, PuzzleItem } from "./types";
import { PuzzleView } from "./components/PuzzleView";
import { LanguageUrlSync } from "./components/LanguageUrlSync";
import dailyData from "../data/daily.json";
import optionsData from "../data/options.json";
const EPOCH_DATE = new Date(2026, 1, 6);
const DAILY_ORDER_SEED = 20260805;
const EASY_MODE_STORAGE_KEY = "qs:easy-mode";
const EASY_MODE_QUERY_KEY = "easy";
const ABOUT_HASH = "#about";

enum EasyModeValue {
  Off = "0",
  On = "1",
}

type PersistedState = {
  lang: Lang;
  speaker: string;
  listener: string;
  portion: string;
  bonus: string;
  bookHintUsed: boolean;
  attempts: GuessResult[];
  revealed: boolean;
};

type PersistInput = Omit<PersistedState, "lang" | "revealed">;
type AppPage = "game" | "about";

const EMPTY_PERSIST_INPUT: PersistInput = {
  speaker: "",
  listener: "",
  portion: "",
  bonus: "",
  bookHintUsed: false,
  attempts: [],
};

function toPersistInput(state: PersistedState): PersistInput {
  return {
    speaker: state.speaker,
    listener: state.listener,
    portion: state.portion,
    bonus: state.bonus,
    bookHintUsed: state.bookHintUsed,
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

function dayIndex(total: number): number {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const base = new Date(EPOCH_DATE.getFullYear(), EPOCH_DATE.getMonth(), EPOCH_DATE.getDate());
  const diff = Math.floor((today.getTime() - base.getTime()) / (24 * 60 * 60 * 1000));
  const idx = ((diff % total) + total) % total;
  return idx;
}

function seededRandom(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = Math.imul(state ^ (state >>> 15), state | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function pickDailyItemIndex(total: number): number {
  const day = dayIndex(total);
  const order = Array.from({ length: total }, (_, idx) => idx);
  const rand = seededRandom(DAILY_ORDER_SEED);

  for (let idx = order.length - 1; idx > 0; idx -= 1) {
    const swapIdx = Math.floor(rand() * (idx + 1));
    [order[idx], order[swapIdx]] = [order[swapIdx], order[idx]];
  }

  return order[day] ?? 0;
}

function parsePersistedState(raw: string | null, lang: Lang): PersistedState | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<PersistedState> & { result?: unknown; guesses?: unknown };
    if (parsed.lang !== lang) return null;
    return {
      lang,
      speaker: parsed.speaker ?? "",
      listener: parsed.listener ?? "",
      portion: parsed.portion ?? "",
      bonus: parsed.bonus ?? "",
      bookHintUsed: !!parsed.bookHintUsed,
      attempts: parseAttempts(parsed),
      revealed: !!parsed.revealed,
    };
  } catch {
    return null;
  }
}

function parseEasyModeValue(raw: string | null): boolean | null {
  if (raw === EasyModeValue.On) return true;
  if (raw === EasyModeValue.Off) return false;
  return null;
}

export function toEasyModeValue(enabled: boolean): EasyModeValue {
  return enabled ? EasyModeValue.On : EasyModeValue.Off;
}

function pickEasyModeFromStorage(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return parseEasyModeValue(window.localStorage.getItem(EASY_MODE_STORAGE_KEY)) ?? false;
  } catch {
    return false;
  }
}

export function parseEasyModeFromSearch(search: string): boolean | null {
  return parseEasyModeValue(new URLSearchParams(search).get(EASY_MODE_QUERY_KEY));
}

function pickEasyMode(): boolean {
  if (typeof window === "undefined") return false;
  const fromUrl = parseEasyModeFromSearch(window.location.search);
  if (fromUrl !== null) return fromUrl;
  return pickEasyModeFromStorage();
}

export function pickEasyModeForNavigation(search: string): boolean {
  const fromUrl = parseEasyModeFromSearch(search);
  return fromUrl ?? false;
}

export function getSearchWithEasyMode(search: string, easyModeEnabled: boolean): string {
  const params = new URLSearchParams(search);
  params.set(EASY_MODE_QUERY_KEY, toEasyModeValue(easyModeEnabled));
  const serialized = params.toString();
  return serialized ? `?${serialized}` : "";
}

function pickPageFromHash(hash: string): AppPage {
  const normalized = hash.trim().replace(/^#/, "").toLowerCase();
  return normalized === "about" ? "about" : "game";
}

function parsePuzzleItems(data: unknown): PuzzleItem[] {
  const payload = (data as { items?: unknown }).items ?? data;
  return Array.isArray(payload) ? (payload as PuzzleItem[]) : [];
}

export function App() {
  const { t, i18n } = useTranslation();
  const lang = getLanguageFromI18n(i18n);
  const nextLanguage = getAlternateLanguage(lang);
  const [items, setItems] = useState<PuzzleItem[]>([]);
  const [optionSets, setOptionSets] = useState<BookOptionSet[]>([]);
  const [index, setIndex] = useState(0);
  const [easyMode, setEasyMode] = useState<boolean>(() => pickEasyMode());
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
      setEasyMode(next);
      try {
        localStorage.setItem(EASY_MODE_STORAGE_KEY, toEasyModeValue(next));
      } catch {
        // Ignore storage access errors.
      }
    };
    window.addEventListener("popstate", syncEasyModeFromLocation);
    return () => window.removeEventListener("popstate", syncEasyModeFromLocation);
  }, []);

  useEffect(() => {
    const list = parsePuzzleItems(dailyData as unknown);
    if (list.length === 0) {
      setItems([]);
      setOptionSets([]);
      return;
    }

    setItems(list);
    setIndex(pickDailyItemIndex(list.length));
    setOptionSets(parseOptionsDataset(optionsData as unknown));
  }, []);

  const puzzle = useMemo(() => items[index], [items, index]);
  const storageKey = puzzle ? buildPuzzleStorageKey(puzzle.id, lang) : "";
  const choicePools = useMemo(() => {
    if (!puzzle) return null;
    return resolveChoicePoolsForPuzzle({
      puzzle,
      items,
      optionSets,
      lang,
    });
  }, [puzzle, items, optionSets, lang]);

  useEffect(() => {
    if (!puzzle) return;
    const parsed = parsePersistedState(localStorage.getItem(storageKey), lang);
    setRevealed(parsed?.revealed ?? false);
    setInitial(parsed ? toPersistInput(parsed) : { ...EMPTY_PERSIST_INPUT });
  }, [puzzle, storageKey, lang]);

  useEffect(() => {
    const direction = getLanguageDirection(lang);
    document.documentElement.lang = lang;
    document.documentElement.dir = direction;
    document.body.classList.toggle("rtl", direction === "rtl");
    document.title = page === "about" ? t("about.title") : t("app.pageTitle");
  }, [lang, page, t]);

  const toggleEasyMode = () => {
    setEasyMode((previous) => {
      const next = !previous;
      const nextValue = toEasyModeValue(next);
      if (typeof window !== "undefined") {
        const url = new URL(window.location.href);
        const nextSearch = getSearchWithEasyMode(url.search, next);
        if (nextSearch !== url.search) {
          window.history.replaceState(window.history.state, "", `${url.pathname}${nextSearch}${url.hash}`);
        }
      }
      try {
        localStorage.setItem(EASY_MODE_STORAGE_KEY, nextValue);
      } catch {
        // Ignore storage access errors.
      }
      return next;
    });
  };

  if (!puzzle && page === "game") return null;

  const persist = (state: PersistInput) => {
    if (!puzzle) return;
    const existing = parsePersistedState(localStorage.getItem(storageKey), lang);
    const payload = {
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
    const existing = parsePersistedState(localStorage.getItem(storageKey), lang);
    localStorage.setItem(
      storageKey,
      JSON.stringify({
        ...(existing ?? { lang, ...EMPTY_PERSIST_INPUT, revealed: false }),
        revealed: true,
      })
    );
  };

  return (
    <div className="app" id="app">
      <LanguageUrlSync i18n={i18n} lang={lang} />

      <header className="header">
        <div>
          <div className="kicker">{page === "about" ? t("about.kicker") : t("app.kicker")}</div>
          <h1>{page === "about" ? t("about.title") : t("app.title")}</h1>
          <p className="subtitle">{page === "about" ? t("about.subtitle") : t("app.subtitle")}</p>
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
              aria-pressed={easyMode}
              aria-label={t("app.toggleEasyMode")}
              title={t("app.easyModeTooltip")}
            >
              🐑
            </button>
          ) : null}
        </div>
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
          revealed={revealed}
          onReveal={reveal}
          onClear={clearResult}
          onPersist={persist}
          initial={initial ?? undefined}
        />
      ) : null}

      <footer className="footer-note">
        <a className="footer-link" href={page === "about" ? "#" : ABOUT_HASH}>
          {page === "about" ? t("about.backToGame") : t("about.link")}
        </a>
      </footer>
    </div>
  );
}
