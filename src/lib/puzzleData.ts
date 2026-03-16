import type { PuzzleItem } from "../types";
import manifest from "./puzzleManifest.json";

export type PuzzleManifestEntry = {
  id: string;
  file: string;
};

type ChapterPayload = {
  items: PuzzleItem[];
};

const QUOTES_BASE_URL = "/quotes";
const chapterCache = new Map<string, Promise<PuzzleItem[]>>();

export const PUZZLE_MANIFEST = manifest as PuzzleManifestEntry[];

export async function loadPuzzleChapter(file: string): Promise<PuzzleItem[]> {
  const cached = chapterCache.get(file);
  if (cached) return cached;

  const promise = (async () => {
    const res = await fetch(`${QUOTES_BASE_URL}/${file}`);

    if (!res.ok) {
      throw new Error(`Failed to fetch ${file}: ${res.status} ${res.statusText}`);
    }

    const payload = (await res.json()) as ChapterPayload;
    return payload.items ?? [];
  })();

  chapterCache.set(file, promise);
  return promise;
}

export async function loadPuzzleItemById(id: string): Promise<PuzzleItem | null> {
  const match = PUZZLE_MANIFEST.find((entry) => entry.id === id);
  if (!match) return null;
  const chapterItems = await loadPuzzleChapter(match.file);
  return chapterItems.find((item) => item.id === id) ?? null;
}
