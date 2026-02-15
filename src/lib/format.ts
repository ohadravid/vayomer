import type { Lang } from "../types";

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
  return s;
}

function normalizeHebrew(text: string): string {
  let s = text.toLowerCase();
  s = s.replace(/[\u0591-\u05C7]/g, "");
  s = s.replace(/ה['׳]/g, "השם");
  s = s.replace(/[^\w\u0590-\u05FF]+/g, " ");
  s = s.replace(/\s+/g, " ").trim();
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

export function markVerseNumbers(text: string): string {
  return text.replace(/(^|\s)(\d{1,3})(\s)/g, '$1<span class="verse-num">v$2</span>$3');
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
}

export function maskHardWord(quote: string, hardWord: string, placeholder: string): string {
  if (!quote || !hardWord) return quote;
  const pattern = escapeRegex(hardWord.trim());
  if (!pattern) return quote;
  const regex = new RegExp(pattern, "gu");
  return quote.replace(regex, (match) =>
    Array.from(match)
      .map((char) => {
        if (/\s/u.test(char)) return char;
        if (/[\u0591-\u05C7]/u.test(char)) return "";
        return placeholder;
      })
      .join("")
  );
}

export function highlightQuote(quote: string, riddle: string): string {
  if (!quote || !riddle) return quote;
  const idx = quote.indexOf(riddle);
  if (idx === -1) return quote;
  const before = quote.slice(0, idx);
  const after = quote.slice(idx + riddle.length);
  const cleanBefore = markVerseNumbers(before);
  const cleanRiddle = markVerseNumbers(riddle);
  const cleanAfter = markVerseNumbers(after);
  return `\n    <span class="veil">${cleanBefore}</span><span class="highlight">${cleanRiddle}</span><span class="veil">${cleanAfter}</span>`;
}

export function formatDate(date: Date, lang: Lang): string {
  return date.toLocaleDateString(DATE_LOCALE_BY_LANG[lang], {
    weekday: "long",
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}
