import { useEffect, useRef, useState } from "react";
import type { i18n as I18nInstance } from "i18next";
import { useLocation, useNavigate } from "react-router-dom";
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

export function LanguageUrlSync({ i18n, lang }: { i18n: UrlSyncI18n; lang: Lang }) {
  const location = useLocation();
  const navigate = useNavigate();
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
    const targetLang = resolveLanguageFromExternalState(location.search, readLanguageFromStorage(window));
    const finishBoot = () => {
      if (!cancelled) setIsBootstrapped(true);
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
    if (lang !== getLanguageFromI18n(i18nRef.current)) return;

    const current = `${location.pathname}${location.search}${location.hash}`;
    const next = buildLocationWithLanguage(location.pathname, location.search, location.hash, lang);
    if (next !== current) {
      void navigate(next, { replace: true });
    }

    if (typeof window === "undefined") return;
    try {
      window.localStorage.setItem(LANGUAGE_STORAGE_KEY, lang);
    } catch {
      // Ignore storage access errors.
    }
  }, [isBootstrapped, lang, location.hash, location.pathname, location.search, navigate]);

  useEffect(() => {
    if (!isBootstrapped) return;
    const fromUrl = parseLanguageFromSearch(location.search) ?? DEFAULT_LANGUAGE;
    if (fromUrl === getLanguageFromI18n(i18nRef.current)) return;
    void i18nRef.current.changeLanguage(fromUrl);
  }, [isBootstrapped, location.search]);

  useEffect(() => {
    if (typeof window === "undefined") return;

    const onStorage = (event: StorageEvent) => {
      if (event.storageArea && event.storageArea !== window.localStorage) return;
      if (event.key && event.key !== LANGUAGE_STORAGE_KEY) return;
      if (!event.newValue) return;
      const fromStorage = normalizeLanguageTag(event.newValue);
      if (fromStorage === getLanguageFromI18n(i18nRef.current)) return;
      void i18nRef.current.changeLanguage(fromStorage);
    };

    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  return null;
}

type BrowserForStorage = Pick<Window, "localStorage">;

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
