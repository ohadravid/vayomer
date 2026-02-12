import type { Lang } from "../types";

const STORAGE_PREFIX = "qs";

export function buildPuzzleStorageKey(puzzleId: string, lang: Lang): string {
  return `${STORAGE_PREFIX}:${puzzleId}:${lang}`;
}
