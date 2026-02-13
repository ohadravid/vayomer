import type { i18n as I18nInstance } from "i18next";
import type { Lang } from "../types";

export const LANGUAGE_STORAGE_KEY = "qs:lang";
export const LANGUAGE_PREFERENCE_SET_KEY = "qs:lang:manual";
export const LANGUAGE_QUERY_KEY = "lng";
export const DEFAULT_LANGUAGE: Lang = "he";
export const SUPPORTED_LANGUAGES: readonly Lang[] = ["en", "he"] as const;

const NEXT_LANGUAGE: Record<Lang, Lang> = {
  en: "he",
  he: "en",
};

const LANGUAGE_DIRECTION: Record<Lang, "ltr" | "rtl"> = {
  en: "ltr",
  he: "rtl",
};

export function isSupportedLanguage(value: string | null | undefined): value is Lang {
  if (!value) return false;
  return (SUPPORTED_LANGUAGES as readonly string[]).includes(value);
}

function toLanguageBase(value: string): string {
  const base = value.toLowerCase().split("-")[0];
  return base === "iw" ? "he" : base;
}

export function parseLanguageTag(value: string | null | undefined): Lang | null {
  if (!value) return null;
  const base = toLanguageBase(value);
  return isSupportedLanguage(base) ? base : null;
}

export function normalizeLanguageTag(value: string | null | undefined): Lang {
  return parseLanguageTag(value) ?? DEFAULT_LANGUAGE;
}

export function parseLanguageFromSearch(search: string): Lang | null {
  const language = new URLSearchParams(search).get(LANGUAGE_QUERY_KEY);
  if (language === null) return null;
  return normalizeLanguageTag(language);
}

export function getSearchWithLanguage(search: string, lang: Lang): string {
  const params = new URLSearchParams(search);
  if (lang === DEFAULT_LANGUAGE) {
    params.delete(LANGUAGE_QUERY_KEY);
  } else {
    params.set(LANGUAGE_QUERY_KEY, lang);
  }

  const serialized = params.toString();
  return serialized ? `?${serialized}` : "";
}

export function getLanguageFromI18n(i18n: Pick<I18nInstance, "resolvedLanguage" | "language">): Lang {
  return normalizeLanguageTag(i18n.resolvedLanguage ?? i18n.language);
}

export function getAlternateLanguage(lang: Lang): Lang {
  return NEXT_LANGUAGE[lang];
}

export function getLanguageDirection(lang: Lang): "ltr" | "rtl" {
  return LANGUAGE_DIRECTION[lang];
}
