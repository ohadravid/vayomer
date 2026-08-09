import type { Lang } from "../types";
import { normalize } from "./format";

export function answersMatch(guess: string, answer: string, lang: Lang): boolean {
  return normalize(guess, lang) === normalize(answer, lang);
}
