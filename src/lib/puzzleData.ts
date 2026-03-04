import type { PuzzleItem } from "../types";

type ChapterPayload = {
  items?: unknown;
};

function sortedPayloadsFromGlob(modules: Record<string, unknown>): ChapterPayload[] {
  return Object.entries(modules)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([, payload]) => payload as ChapterPayload);
}

const CHAPTER_PAYLOADS = [
  ...sortedPayloadsFromGlob(
    import.meta.glob("/data/quotes_options/*.json", {
      eager: true,
      import: "default",
    })
  ),
  ...sortedPayloadsFromGlob(
    import.meta.glob("/data/manual_quotes/*.json", {
      eager: true,
      import: "default",
    })
  ),
];

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
