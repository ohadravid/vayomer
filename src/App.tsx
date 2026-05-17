import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Temporal } from "@js-temporal/polyfill";
import { BrowserRouter, Link, Navigate, Outlet, useLocation, useNavigate, useRoutes, type RouteObject } from "react-router-dom";
import { answersMatch } from "./lib/answerMatcher";
import { pickDailyItemIndexWithOverrides } from "./lib/daily";
import { maskHardWord, pickHardWordPlaceholderForId } from "./lib/format";
import { getAlternateLanguage, getLanguageDirection, getLanguageFromI18n, getSearchWithLanguage } from "./lib/language";
import { PUZZLE_MANIFEST, loadPuzzleItemById } from "./lib/puzzleData";
import { buildPuzzleStorageKey } from "./lib/persistence";
import type { GuessResult, Lang, PersistedGameFields, PuzzleItem } from "./types";
import { PuzzleView } from "./components/PuzzleView";
import { LanguageUrlSync } from "./components/LanguageUrlSync";
import { hasSeenExample, markExampleSeen, pickExamplePuzzle } from "./lib/examplePuzzles";
import { ReadBookPage, ReadBooksPage, ReadChapterPage } from "./components/SourceReader";
import packageMeta from "../package.json";

const PUZZLE_QUERY_KEY = "puzzle";
const LEGACY_DIFFICULTY_QUERY_KEYS = ["hard", "easy"] as const;
const REPO_URL = "https://github.com/ohadravid/vayomer";
const APP_VERSION = packageMeta.version;

type PersistedDraft = Pick<PersistedGameFields, "speaker" | "listener" | "portion" | "bonus">;

type PersistedState = {
  version: string;
  drafts: Partial<Record<Lang, PersistedDraft>>;
  attempts: GuessResult[];
  hintRevealed: boolean;
  revealed: boolean;
};

type AppSection = "game" | "about" | "example" | "reader";

const EMPTY_PERSISTED_GAME_FIELDS: PersistedGameFields = {
  speaker: "",
  listener: "",
  portion: "",
  bonus: "",
  hintRevealed: false,
  attempts: [],
};
const EMPTY_PERSISTED_DRAFT: PersistedDraft = {
  speaker: "",
  listener: "",
  portion: "",
  bonus: "",
};

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

function toPersistedDraft(state: PersistedGameFields): PersistedDraft {
  return {
    speaker: state.speaker,
    listener: state.listener,
    portion: state.portion,
    bonus: state.bonus,
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
  if (!Array.isArray(parsed.attempts)) return [];
  return parsed.attempts
    .map((attempt) => toGuessResult(attempt))
    .filter((attempt): attempt is GuessResult => attempt !== null);
}

function parsePersistedDraft(raw: unknown): PersistedDraft | null {
  if (!raw || typeof raw !== "object") return null;
  const parsed = raw as Record<string, unknown>;
  return {
    speaker: typeof parsed.speaker === "string" ? parsed.speaker : "",
    listener: typeof parsed.listener === "string" ? parsed.listener : "",
    portion: typeof parsed.portion === "string" ? parsed.portion : "",
    bonus: typeof parsed.bonus === "string" ? parsed.bonus : "",
  };
}

function parsePersistedDrafts(raw: unknown): Partial<Record<Lang, PersistedDraft>> | null {
  if (!raw || typeof raw !== "object") return null;
  const parsed = raw as Record<string, unknown>;
  const drafts: Partial<Record<Lang, PersistedDraft>> = {};

  for (const language of ["en", "he"] as const) {
    const draft = parsePersistedDraft(parsed[language]);
    if (draft) drafts[language] = draft;
  }

  return drafts;
}

export function parsePersistedState(raw: string | null, currentVersion: string): PersistedState | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    if (parsed.version !== currentVersion) return null;
    if (!Array.isArray(parsed.attempts)) return null;
    const drafts = parsePersistedDrafts(parsed.drafts);
    if (!drafts) return null;
    const attempts = parseAttempts(parsed);
    const hasCoreSolvedAttempt = attempts.some((attempt) => attempt.speakerOk && attempt.listenerOk);
    const revealed = !!parsed.revealed && hasCoreSolvedAttempt;
    return {
      version: currentVersion,
      drafts,
      attempts,
      hintRevealed: !!parsed.hintRevealed,
      revealed,
    };
  } catch {
    return null;
  }
}

export function resolvePersistedGameFields(state: PersistedState, puzzle: PuzzleItem, lang: Lang): PersistedGameFields {
  const langDraft = state.drafts[lang];
  const hasCoreSolvedAttempt = state.attempts.some((attempt) => attempt.speakerOk && attempt.listenerOk);
  const draft: PersistedDraft = {
    ...EMPTY_PERSISTED_DRAFT,
    ...(langDraft ?? {}),
  };

  if (hasCoreSolvedAttempt) {
    if (!langDraft?.speaker) draft.speaker = puzzle[lang].speaker;
    if (!langDraft?.listener) draft.listener = puzzle[lang].listener;
  }

  if (state.revealed && !langDraft?.bonus) {
    draft.bonus = puzzle[lang].bonus ?? "";
  }

  return {
    ...draft,
    hintRevealed: state.hintRevealed,
    attempts: state.attempts,
  };
}

export function parsePuzzleIdFromSearch(search: string): string | null {
  const raw = new URLSearchParams(search).get(PUZZLE_QUERY_KEY);
  if (typeof raw !== "string") return null;
  const trimmed = raw.trim();
  return trimmed.length > 0 ? trimmed : null;
}

export function getSearchWithoutPuzzleId(search: string): string {
  const params = new URLSearchParams(search);
  params.delete(PUZZLE_QUERY_KEY);
  const serialized = params.toString();
  return serialized ? `?${serialized}` : "";
}

export function getSearchWithPuzzleId(search: string, puzzleId: string): string {
  const params = new URLSearchParams(search);
  params.set(PUZZLE_QUERY_KEY, puzzleId);
  const serialized = params.toString();
  return serialized ? `?${serialized}` : "";
}

export function resolvePuzzleSelectionForSearch(
  items: readonly { id: string }[],
  search: string,
  date: Temporal.PlainDate = Temporal.Now.plainDateISO()
): { index: number; dailyIndex: number; requestedPuzzleId: string | null; isArchive: boolean } {
  if (items.length === 0) {
    return { index: 0, dailyIndex: 0, requestedPuzzleId: null, isArchive: false };
  }

  const dailyIndex = pickDailyItemIndexWithOverrides(items, date);
  const requestedPuzzleId = parsePuzzleIdFromSearch(search);
  if (requestedPuzzleId) {
    const explicitIndex = items.findIndex((item) => item.id === requestedPuzzleId);
    if (explicitIndex >= 0) {
      return {
        index: explicitIndex,
        dailyIndex,
        requestedPuzzleId,
        isArchive: explicitIndex !== dailyIndex,
      };
    }
  }

  return { index: dailyIndex, dailyIndex, requestedPuzzleId: null, isArchive: false };
}

export function pickPuzzleIndexForSearch(
  items: readonly { id: string }[],
  search: string,
  date: Temporal.PlainDate = Temporal.Now.plainDateISO()
): number {
  return resolvePuzzleSelectionForSearch(items, search, date).index;
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

function getAppSection(pathname: string): AppSection {
  if (pathname === "/about") return "about";
  if (pathname === "/example") return "example";
  if (pathname === "/read" || pathname.startsWith("/read/")) return "reader";
  return "game";
}

function buildAppHref(pathname: string, lang: Lang, search: string): string {
  return `${pathname}${getSearchWithLanguage(search, lang)}`;
}

function buildAbsoluteAppHref(pathname: string, search: string): string {
  const href = `${pathname}${search}`;
  if (typeof window === "undefined" || !window.location.origin) return href;
  return `${window.location.origin}${href}`;
}

function usePageLanguage(): Lang {
  const { i18n } = useTranslation();
  return getLanguageFromI18n(i18n);
}

function GamePage() {
  const lang = usePageLanguage();
  const location = useLocation();
  const manifestEntries = PUZZLE_MANIFEST;
  const selection = useMemo(
    () => resolvePuzzleSelectionForSearch(manifestEntries, location.search),
    [location.search, manifestEntries]
  );
  const index = selection.index;
  const [puzzle, setPuzzle] = useState<PuzzleItem | null>(null);
  const [revealed, setRevealed] = useState(false);
  const [initial, setInitial] = useState<PersistedGameFields | null>(null);

  useEffect(() => {
    const selectedId = manifestEntries[index]?.id;
    if (!selectedId) {
      setPuzzle(null);
      return;
    }

    let cancelled = false;
    setPuzzle(null);

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
  }, [index, manifestEntries]);

  const storageKey = puzzle ? buildPuzzleStorageKey(puzzle.id) : "";

  useEffect(() => {
    if (!puzzle) return;
    const rawPersisted = localStorage.getItem(storageKey);
    const parsed = parsePersistedState(rawPersisted, APP_VERSION);
    if (rawPersisted && !parsed) {
      localStorage.removeItem(storageKey);
    }
    setRevealed(parsed?.revealed ?? false);
    setInitial(parsed ? resolvePersistedGameFields(parsed, puzzle, lang) : { ...EMPTY_PERSISTED_GAME_FIELDS });
  }, [lang, puzzle, storageKey]);

  if (!puzzle) return null;

  const todaySearch = getSearchWithoutPuzzleId(location.search);
  const archiveTodayHref = selection.isArchive ? `${location.pathname}${todaySearch}` : undefined;

  const persist = (state: PersistedGameFields) => {
    const existing = parsePersistedState(localStorage.getItem(storageKey), APP_VERSION);
    const payload = {
      version: APP_VERSION,
      drafts: {
        ...(existing?.drafts ?? {}),
        [lang]: toPersistedDraft(state),
      },
      attempts: state.attempts,
      hintRevealed: state.hintRevealed,
      revealed: existing?.revealed ?? revealed,
    };
    localStorage.setItem(storageKey, JSON.stringify(payload));
  };

  const clearResult = () => {
    localStorage.removeItem(storageKey);
    setRevealed(false);
    setInitial({ ...EMPTY_PERSISTED_GAME_FIELDS });
  };

  const reveal = () => {
    setRevealed(true);
    const existing = parsePersistedState(localStorage.getItem(storageKey), APP_VERSION);
    localStorage.setItem(
      storageKey,
      JSON.stringify({
        ...(existing ?? {
          version: APP_VERSION,
          drafts: {},
          attempts: [],
          hintRevealed: false,
          revealed: false,
        }),
        revealed: true,
      })
    );
  };

  return (
    <PuzzleView
      puzzle={puzzle}
      revealed={revealed}
      onReveal={reveal}
      onClear={clearResult}
      onPersist={persist}
      initial={initial ?? undefined}
      archiveTodayHref={archiveTodayHref}
    />
  );
}

function ExamplePage() {
  const { t } = useTranslation();
  const lang = usePageLanguage();
  const location = useLocation();
  const requestedId = parsePuzzleIdFromSearch(location.search);
  const [exampleBasePuzzle, setExampleBasePuzzle] = useState<PuzzleItem | null>(null);
  const [exampleRevealed, setExampleRevealed] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") {
      setExampleBasePuzzle(pickExamplePuzzle(requestedId, false));
      return;
    }

    setExampleBasePuzzle(pickExamplePuzzle(requestedId, hasSeenExample(window.localStorage)));
    setExampleRevealed(false);
    markExampleSeen(window.localStorage);
  }, [requestedId]);

  const exampleMaskedPuzzle = useMemo(
    () => (exampleBasePuzzle ? buildExamplePuzzleWithMaskedBonusWord(exampleBasePuzzle) : null),
    [exampleBasePuzzle]
  );
  const examplePuzzle = exampleRevealed ? exampleBasePuzzle : exampleMaskedPuzzle;
  const exampleInitial = useMemo(
    () => (exampleBasePuzzle ? buildExampleInitialState(exampleBasePuzzle, lang) : null),
    [exampleBasePuzzle, lang]
  );

  if (!examplePuzzle) return null;

  return (
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
  );
}

function AboutPage() {
  const { t } = useTranslation();

  return (
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
  );
}

function AppLayout() {
  const { t, i18n } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const lang = getLanguageFromI18n(i18n);
  const nextLanguage = getAlternateLanguage(lang);
  const section = getAppSection(location.pathname);
  const cleanedSearch = useMemo(() => getSearchWithoutLegacyDifficultyParams(location.search), [location.search]);
  const homeHref = useMemo(() => buildAppHref("/", lang, cleanedSearch), [cleanedSearch, lang]);
  const aboutHref = useMemo(() => buildAppHref("/about", lang, cleanedSearch), [cleanedSearch, lang]);
  const exampleHref = useMemo(() => buildAppHref("/example", lang, cleanedSearch), [cleanedSearch, lang]);
  const specificRiddleHref = useMemo(() => {
    if (section !== "game") return undefined;
    const selection = resolvePuzzleSelectionForSearch(PUZZLE_MANIFEST, cleanedSearch);
    const puzzleId = PUZZLE_MANIFEST[selection.index]?.id;
    if (!puzzleId) return undefined;
    return buildAbsoluteAppHref(location.pathname, getSearchWithPuzzleId(getSearchWithoutPuzzleId(cleanedSearch), puzzleId));
  }, [cleanedSearch, location.pathname, section]);

  useEffect(() => {
    if (cleanedSearch === location.search) return;
    void navigate(`${location.pathname}${cleanedSearch}${location.hash}`, { replace: true });
  }, [cleanedSearch, location.hash, location.pathname, location.search, navigate]);

  useEffect(() => {
    const direction = getLanguageDirection(lang);
    document.documentElement.lang = lang;
    document.documentElement.dir = direction;
    document.body.dir = direction;
    document.title =
      section === "reader"
        ? t("reader.pageTitle")
        : section === "about"
          ? t("about.title")
          : section === "example"
            ? t("example.title")
            : t("app.pageTitle");
  }, [lang, section, t]);

  return (
    <div className="app" id="app">
      <LanguageUrlSync i18n={i18n} lang={lang} />

      <header className="header">
        <div className="header-copy">
          <div className="kicker">
            {section === "reader"
              ? t("reader.kicker")
              : section === "about"
                ? t("about.kicker")
                : section === "example"
                  ? t("example.kicker")
                  : t("app.kicker")}
          </div>
          <h1>{section === "reader" ? t("reader.title") : section === "about" ? t("about.title") : section === "example" ? t("example.title") : t("app.title")}</h1>
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
          {section === "game" ? (
            <Link className="chip" to={exampleHref} aria-label={t("app.openExample")} title={t("app.openExample")}>
              ❓
            </Link>
          ) : (
            <Link id="topBackButton" className="chip back-chip" to={homeHref}>
              ⬅️
            </Link>
          )}
        </div>
        <p className="subtitle header-subtitle">
          {section === "reader"
            ? t("reader.subtitle")
            : section === "about"
              ? t("about.subtitle")
              : section === "example"
                ? t("example.subtitle")
                : t("app.subtitle")}
        </p>
      </header>

      <Outlet />

      <footer className="footer-note">
        {section === "game" ? (
          <>
            {specificRiddleHref ? (
              <div>
                <a className="footer-link" href={specificRiddleHref}>
                  {t("guessForm.shareSpecificRiddle")}
                </a>
              </div>
            ) : null}
            <div>
              <Link className="footer-link" to={aboutHref}>
                {t("about.link")}
              </Link>
            </div>
          </>
        ) : null}
        <div>
          <a className="footer-link footer-version-link" href={REPO_URL} target="_blank" rel="noreferrer">
            {t("footer.version", { version: APP_VERSION })}
          </a>
          <span className="footer-separator" aria-hidden="true">
            {" - "}
          </span>
          <a className="footer-link" href="mailto:mashov@vayomer.io">
            {t("footer.feedback")}
          </a>
        </div>
      </footer>
    </div>
  );
}

export const APP_ROUTE_OBJECTS: RouteObject[] = [
  {
    element: <AppLayout />,
    children: [
      { index: true, element: <GamePage /> },
      { path: "about", element: <AboutPage /> },
      { path: "example", element: <ExamplePage /> },
      { path: "read", element: <ReadBooksPage /> },
      { path: "read/:bookSlug", element: <ReadBookPage /> },
      { path: "read/:bookSlug/:chapter", element: <ReadChapterPage /> },
      { path: "*", element: <Navigate to="/" replace /> },
    ],
  },
];

export function AppRoutes() {
  return useRoutes(APP_ROUTE_OBJECTS);
}

export function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  );
}
