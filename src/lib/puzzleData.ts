import { loadPuzzleChapterPayloadsJson } from "./puzzleDataMacro" with { type: "macro" };
import type { PuzzleItem } from "../types";

type ChapterPayload = {
  items?: unknown;
};

const CHAPTER_PAYLOADS = JSON.parse(
  loadPuzzleChapterPayloadsJson(["data/quotes_options", "data/manual_quotes"])
) as ChapterPayload[];

function normalizeSourceMethod(item: PuzzleItem): PuzzleItem {
  if (!item.source) return item;
  const sourceMethod = item.source.method === "manual" ? "manual" : "llm";
  if (item.source.method === sourceMethod) return item;
  return {
    ...item,
    source: {
      ...item.source,
      method: sourceMethod,
    },
  };
}

function parsePuzzleItems(data: unknown): PuzzleItem[] {
  const payload = (data as { items?: unknown }).items ?? data;
  if (!Array.isArray(payload)) return [];
  return payload
    .filter((item): item is PuzzleItem => !!item && typeof item === "object")
    .map((item) => normalizeSourceMethod(item));
}

export function loadPuzzleItems(): PuzzleItem[] {
  return CHAPTER_PAYLOADS.flatMap((chapter) => parsePuzzleItems(chapter));
}
