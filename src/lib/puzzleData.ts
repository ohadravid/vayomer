import { loadPuzzleChapterPayloadsJson } from "./puzzleDataMacro" with { type: "macro" };
import type { PuzzleItem } from "../types";

type ChapterPayload = {
  items?: unknown;
};

const CHAPTER_PAYLOADS = JSON.parse(
  loadPuzzleChapterPayloadsJson("data/quotes_options")
) as ChapterPayload[];

function parsePuzzleItems(data: unknown): PuzzleItem[] {
  const payload = (data as { items?: unknown }).items ?? data;
  return Array.isArray(payload) ? (payload as PuzzleItem[]) : [];
}

export function loadPuzzleItems(): PuzzleItem[] {
  return CHAPTER_PAYLOADS.flatMap((chapter) => parsePuzzleItems(chapter));
}
