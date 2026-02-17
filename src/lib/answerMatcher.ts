import type { Lang } from "../types";
import { normalize } from "./format";

export function normalizeForAnswerMatch(value: string, lang: Lang): string {
  return normalize(value, lang);
}

export function answersMatch(guess: string, answer: string, lang: Lang): boolean {
  return normalizeForAnswerMatch(guess, lang) === normalizeForAnswerMatch(answer, lang);
}
