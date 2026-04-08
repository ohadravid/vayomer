const STORAGE_PREFIX = "qs";

export function buildPuzzleStorageKey(puzzleId: string): string {
  return `${STORAGE_PREFIX}:${puzzleId}`;
}
