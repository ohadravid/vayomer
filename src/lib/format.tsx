import type { ReactNode } from "react";
import type { Lang } from "../types";
import { normalizeDivineAlias } from "./divineAliases";

export const HARD_WORD_PLACEHOLDERS = ["🪧", "🚧", "💬", "🔎"] as const;

const DATE_LOCALE_BY_LANG: Record<Lang, string> = {
  en: "en-US",
  he: "he-IL",
};

function normalizeEnglish(text: string): string {
  let s = text.toLowerCase();
  s = s.replace(/[^\w\u0590-\u05FF]+/g, " ");
  s = s.replace(/\s+/g, " ").trim();
  s = s.replace(/^the\s+/, "");
  const divine = normalizeDivineAlias(s, "en");
  if (divine) return divine;
  return s;
}

function normalizeHebrew(text: string): string {
  let s = text.toLowerCase();
  // Treat maqaf as a word separator so `X־Y` and `X Y` normalize identically.
  s = s.replace(/\u05be/g, " ");
  s = s.replace(/[\u0591-\u05C7]/g, "");
  s = s.replace(/ה['׳]/g, "השם");
  s = s.replace(/[^\w\u0590-\u05FF]+/g, " ");
  s = s.replace(/\s+/g, " ").trim();
  const divine = normalizeDivineAlias(s, "he");
  if (divine) return divine;
  return s;
}

const NORMALIZER_BY_LANG: Record<Lang, (text: string) => string> = {
  en: normalizeEnglish,
  he: normalizeHebrew,
};

export function normalize(text: string, lang: Lang): string {
  if (!text) return "";
  return NORMALIZER_BY_LANG[lang](text);
}

export function pickHardWordPlaceholderForId(quoteId: string): string {
  if (!quoteId) return HARD_WORD_PLACEHOLDERS[0];
  let hash = 0;
  for (const char of quoteId) {
    hash = (hash * 31 + (char.codePointAt(0) ?? 0)) >>> 0;
  }
  return HARD_WORD_PLACEHOLDERS[hash % HARD_WORD_PLACEHOLDERS.length];
}

function escapeRegex(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}``

function maskTokenCharacters(value: string, placeholder: string): string {
  return Array.from(value)
    .map((char) => {
      if (/\s/u.test(char)) return char;
      if (/[\u0591-\u05C7]/u.test(char)) return "";
      return placeholder;
    })
    .join("");
}

function containsHebrew(value: string): boolean {
  return /[\u0590-\u05FF]/u.test(value);
}

function normalizeHebrewForMaskMatch(text: string): string {
  return normalizeHebrew(text).replace(/[יו]/gu, "");
}

const HEBREW_MASK_WORD_REGEX = /[\u0590-\u05BD\u05BF-\u05FF]+/gu;

function maskTokenSubstring(token: string, normalizedLengthToMask: number, placeholder: string): string {
  let consumed = 0;

  return Array.from(token)
    .map((char) => {
      // Drop niqqud from output, like maskTokenCharacters currently does.
      if (/[\u0591-\u05C7]/u.test(char)) return "";

      // Keep spaces untouched, probably irrelevant inside token.
      if (/\s/u.test(char)) return char;

      const normalizedChar = normalizeHebrewForMaskMatch(char);

      if (consumed < normalizedLengthToMask) {
        consumed += normalizedChar.length;
        return placeholder;
      }

      return char;
    })
    .join("");
}

export function maskHardWord(quote: string, hardWord: string, placeholder: string, lang?: Lang): string {
  if (!quote || !hardWord) return quote;
  const trimmedHardWord = hardWord.trim();
  if (!trimmedHardWord) return quote;

  const pattern = escapeRegex(trimmedHardWord);
  if (!pattern) return quote;
  const exactRegex = new RegExp(pattern, "gu");
  const exactMasked = quote.replace(exactRegex, (match) => maskTokenCharacters(match, placeholder));

  if (exactMasked !== quote) return exactMasked;

  const resolvedLang = lang ?? (containsHebrew(trimmedHardWord) ? "he" : "en");
  if (resolvedLang !== "he") return exactMasked;

  const normalizedTarget = normalizeHebrewForMaskMatch(trimmedHardWord);
  if (!normalizedTarget || /\s/u.test(normalizedTarget)) return exactMasked;

  let replaced = false;
  const fuzzyMasked = quote.replace(HEBREW_MASK_WORD_REGEX, (token) => {
    const normalizedTarget = normalizeHebrewForMaskMatch(trimmedHardWord);
    const normalizedToken = normalizeHebrewForMaskMatch(token);

    const matchIndex = normalizedToken.indexOf(normalizedTarget);
    if (matchIndex === -1) return token;

    replaced = true;
    return maskTokenSubstring(token, normalizedTarget.length, placeholder);
  });

  return replaced ? fuzzyMasked : exactMasked;
}

function renderTextWithVerseNumbers(text: string, keyPrefix: string): ReactNode[] {
  if (!text) return [text];

  const verseRegex = /(^|\s)(\d{1,3})(\s)/g;
  const nodes: ReactNode[] = [];
  let cursor = 0;
  let verseIndex = 0;

  for (const match of text.matchAll(verseRegex)) {
    const full = match[0] ?? "";
    const leading = match[1] ?? "";
    const verse = match[2] ?? "";
    const trailing = match[3] ?? "";
    const index = match.index ?? 0;

    if (index > cursor) nodes.push(text.slice(cursor, index));
    if (leading) nodes.push(leading);
    nodes.push(
      <span className="verse-num" key={`${keyPrefix}-verse-${verseIndex}`}>
        v{verse}
      </span>
    );
    if (trailing) nodes.push(trailing);

    cursor = index + full.length;
    verseIndex += 1;
  }

  if (cursor < text.length) nodes.push(text.slice(cursor));
  if (nodes.length === 0) nodes.push(text);
  return nodes;
}

export function renderQuoteText(text: string, placeholder = "", keyPrefix = "quote"): ReactNode {
  if (!text) return text;
  if (!placeholder) return renderTextWithVerseNumbers(text, keyPrefix);

  const pattern = escapeRegex(placeholder);
  if (!pattern) return renderTextWithVerseNumbers(text, keyPrefix);

  const placeholderRuns = new RegExp(`(?:${pattern})+`, "gu");
  const nodes: ReactNode[] = [];
  let cursor = 0;
  let segmentIndex = 0;

  for (const match of text.matchAll(placeholderRuns)) {
    const run = match[0] ?? "";
    const index = match.index ?? 0;

    if (index > cursor) {
      nodes.push(...renderTextWithVerseNumbers(text.slice(cursor, index), `${keyPrefix}-segment-${segmentIndex}`));
      segmentIndex += 1;
    }

    nodes.push(
      <span className="quote-emoji" key={`${keyPrefix}-emoji-${segmentIndex}`}>
        {run}
      </span>
    );
    segmentIndex += 1;
    cursor = index + run.length;
  }

  if (cursor < text.length) {
    nodes.push(...renderTextWithVerseNumbers(text.slice(cursor), `${keyPrefix}-segment-${segmentIndex}`));
  }

  return nodes.length > 0 ? nodes : renderTextWithVerseNumbers(text, keyPrefix);
}

export function highlightQuote(quote: string, riddle: string, placeholder = ""): ReactNode {
  if (!quote || !riddle) return quote;
  const idx = quote.indexOf(riddle);
  if (idx === -1) return renderQuoteText(quote, placeholder, "full");

  const before = quote.slice(0, idx);
  const after = quote.slice(idx + riddle.length);
  const cleanBefore = renderQuoteText(before, placeholder, "before");
  const cleanRiddle = renderQuoteText(riddle, placeholder, "riddle");
  const cleanAfter = renderQuoteText(after, placeholder, "after");

  return (
    <>
      <span className="quote-hidden veil">{cleanBefore}</span>
      <span className="highlight">{cleanRiddle}</span>
      <span className="quote-hidden veil">{cleanAfter}</span>
    </>
  );
}

export function formatDate(date: Date, lang: Lang): string {
  return date.toLocaleDateString(DATE_LOCALE_BY_LANG[lang], {
    weekday: "long",
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}
