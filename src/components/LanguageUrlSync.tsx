import { useEffect, useRef, useState } from "react";
import type { i18n as I18nInstance } from "i18next";
import {
  DEFAULT_LANGUAGE,
  LANGUAGE_STORAGE_KEY,
  getLanguageFromI18n,
  getSearchWithLanguage,
  normalizeLanguageTag,
  parseLanguageFromSearch,
} from "../lib/language";
import type { Lang } from "../types";

export type UrlSyncI18n = Pick<I18nInstance, "resolvedLanguage" | "language" | "changeLanguage">;

/**
 * Keeps language state synchronized between i18n, URL, and local storage.
 *
 * Behavior:
 * - Hebrew is the canonical default URL and removes the `lng` query parameter.
 * - Non-default language (`en`) writes `lng=en` so links are shareable.
 * - Boot uses URL first, then storage, and waits for initial language sync
 *   before i18n writes back to the URL.
 * - `popstate` trusts only the URL (no storage fallback) so Back/Forward works.
 * - Cross-tab storage changes can still drive i18n updates.
 *
 * Implementation:
 * - One effect reflects current i18n language into `history.replaceState`.
 * - A second effect subscribes to `popstate` and `storage` and applies external
 *   language values back into i18n when they differ.
 */
export function LanguageUrlSync({ i18n, lang }: { i18n: UrlSyncI18n; lang: Lang }) {
  const i18nRef = useRef(i18n);
  const [isBootstrapped, setIsBootstrapped] = useState(false);

  useEffect(() => {
    i18nRef.current = i18n;
  }, [i18n]);

  useEffect(() => {
    if (typeof window === "undefined") {
      setIsBootstrapped(true);
      return;
    }
    const instance = i18nRef.current;
    let cancelled = false;
    const targetLang = resolveLanguageFromExternalState(window.location.search, readLanguageFromStorage(window));
    const finishBoot = () => {
      if (cancelled) return;
      setIsBootstrapped(true);
    };

    if (!targetLang || targetLang === getLanguageFromI18n(instance)) {
      finishBoot();
      return () => {
        cancelled = true;
      };
    }

    void instance.changeLanguage(targetLang).finally(finishBoot);
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!isBootstrapped) return;
    if (typeof window === "undefined") return;
    if (lang !== getLanguageFromI18n(i18nRef.current)) return;
    syncLanguageInUrl(window, lang);
    try {
      window.localStorage.setItem(LANGUAGE_STORAGE_KEY, lang);
    } catch {
      // Ignore storage access errors.
    }
  }, [lang, isBootstrapped]);

  useEffect(() => {
    if (typeof window === "undefined") return;

    const onPopState = () => {
      const fromUrl = parseLanguageFromSearch(window.location.search);
      const nextLang = fromUrl ?? DEFAULT_LANGUAGE;
      if (nextLang === getLanguageFromI18n(i18nRef.current)) return;
      void i18nRef.current.changeLanguage(nextLang);
    };

    const onStorage = (event: StorageEvent) => {
      if (event.storageArea && event.storageArea !== window.localStorage) return;
      if (event.key && event.key !== LANGUAGE_STORAGE_KEY) return;
      if (!event.newValue) return;
      const fromStorage = normalizeLanguageTag(event.newValue);
      if (fromStorage === getLanguageFromI18n(i18nRef.current)) return;
      void i18nRef.current.changeLanguage(fromStorage);
    };

    window.addEventListener("popstate", onPopState);
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener("popstate", onPopState);
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  return null;
}

type BrowserForStorage = Pick<Window, "localStorage">;
type BrowserForHistory = {
  location: Pick<Location, "pathname" | "search" | "hash">;
  history: Pick<History, "state" | "replaceState">;
};

function readLanguageFromStorage(browser: BrowserForStorage): Lang | null {
  try {
    const stored = browser.localStorage.getItem(LANGUAGE_STORAGE_KEY);
    if (stored === null) return null;
    return normalizeLanguageTag(stored);
  } catch {
    return null;
  }
}

export function resolveLanguageFromExternalState(search: string, storedLanguage: string | null): Lang | null {
  const fromUrl = parseLanguageFromSearch(search);
  if (fromUrl) return fromUrl;
  if (storedLanguage === null) return null;
  return normalizeLanguageTag(storedLanguage);
}

export function buildLocationWithLanguage(pathname: string, search: string, hash: string, lang: Lang): string {
  return `${pathname}${getSearchWithLanguage(search, lang)}${hash}`;
}

export function syncLanguageInUrl(browser: BrowserForHistory, lang: Lang): void {
  const current = `${browser.location.pathname}${browser.location.search}${browser.location.hash}`;
  const next = buildLocationWithLanguage(browser.location.pathname, browser.location.search, browser.location.hash, lang);
  if (next === current) return;
  browser.history.replaceState(browser.history.state, "", next);
}
