import { Temporal } from "@js-temporal/polyfill";
import { pickDailyItemIndex } from "./daily";
import type { PuzzleItem } from "../types";

type ExamplePayload = {
  items?: PuzzleItem[];
};
type ExampleStorage = Pick<Storage, "getItem" | "setItem">;

const exampleModules = import.meta.glob("./exampleQuote*.json", {
  eager: true,
  import: "default",
}) as Record<string, ExamplePayload>;
const defaultExampleItems = exampleModules["./exampleQuote.json"]?.items ?? [];

export const EXAMPLE_SEEN_STORAGE_KEY = "qs:example-seen";
export const DEFAULT_EXAMPLE_PUZZLE: PuzzleItem | null = defaultExampleItems[0] ?? null;

export const EXAMPLE_PUZZLES: PuzzleItem[] = Object.entries(exampleModules)
  .sort(([leftPath], [rightPath]) => leftPath.localeCompare(rightPath))
  .flatMap(([, payload]) => (Array.isArray(payload.items) ? payload.items : []))
  .sort((left, right) => left.id.localeCompare(right.id));

export function findExamplePuzzleById(id: string | null | undefined): PuzzleItem | null {
  const trimmedId = typeof id === "string" ? id.trim() : "";
  if (trimmedId) {
    const matchingPuzzle = EXAMPLE_PUZZLES.find((item) => item.id === trimmedId);
    if (matchingPuzzle) return matchingPuzzle;
  }

  return null;
}

export function hasSeenExample(storage: ExampleStorage): boolean {
  try {
    return storage.getItem(EXAMPLE_SEEN_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

export function markExampleSeen(storage: ExampleStorage): void {
  try {
    storage.setItem(EXAMPLE_SEEN_STORAGE_KEY, "1");
  } catch {
    // Ignore storage access errors.
  }
}

export function pickDailyExamplePuzzle(date: Temporal.PlainDate = Temporal.Now.plainDateISO()): PuzzleItem | null {
  if (EXAMPLE_PUZZLES.length === 0) return DEFAULT_EXAMPLE_PUZZLE;
  const dailyIndex = pickDailyItemIndex(EXAMPLE_PUZZLES, date);
  return EXAMPLE_PUZZLES[dailyIndex] ?? DEFAULT_EXAMPLE_PUZZLE;
}

export function pickExamplePuzzle(
  id: string | null | undefined,
  hasSeenMarker: boolean,
  date: Temporal.PlainDate = Temporal.Now.plainDateISO()
): PuzzleItem | null {
  if (!hasSeenMarker) {
    return DEFAULT_EXAMPLE_PUZZLE ?? EXAMPLE_PUZZLES[0] ?? null;
  }

  const explicitExample = findExamplePuzzleById(id);
  if (explicitExample) return explicitExample;

  const dailyExample = pickDailyExamplePuzzle(date);
  if (dailyExample) return dailyExample;

  return EXAMPLE_PUZZLES[0] ?? null;
}
