import type { Lang } from "../types";
import { normalize } from "./format";

export function normalizeForAnswerMatch(value: string, lang: Lang): string {
  const normalized = normalize(value, lang);
  if (lang !== "he") return normalized;
  // Allow ketiv-haser/male style variants by ignoring י/ו in Hebrew checks.
  return normalized.replace(/[יו]/gu, "");
}

export function answersMatch(guess: string, answer: string, lang: Lang): boolean {
  return normalizeForAnswerMatch(guess, lang) === normalizeForAnswerMatch(answer, lang);
}
