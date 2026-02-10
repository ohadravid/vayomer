import type { i18n as I18nInstance } from "i18next";
import type { Lang } from "../types";

export const LANGUAGE_STORAGE_KEY = "qs:lang";
export const LANGUAGE_PREFERENCE_SET_KEY = "qs:lang:manual";
export const DEFAULT_LANGUAGE: Lang = "en";
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

export function normalizeLanguageTag(value: string | null | undefined): Lang {
  if (!value) return DEFAULT_LANGUAGE;
  const base = value.toLowerCase().split("-")[0];
  return isSupportedLanguage(base) ? base : DEFAULT_LANGUAGE;
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
