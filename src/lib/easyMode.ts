import { normalize } from "./format";
import type {
  BookOptionSet,
  DifficultyChoicePools,
  EasyChoiceField,
  EasyChoicePools,
  Lang,
  OptionsDataset,
  PuzzleItem,
} from "../types";

const DEFAULT_CHOICE_COUNT = 4;

function hashText(text: string): number {
  let hash = 2166136261;
  for (const char of text) {
    hash ^= char.codePointAt(0) ?? 0;
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function stableSeedSort(values: string[], seed: string): string[] {
  return [...values].sort((a, b) => {
    const diff = hashText(`${seed}:${a}`) - hashText(`${seed}:${b}`);
    if (diff !== 0) return diff;
    return a.localeCompare(b);
  });
}

function canonicalizeChoiceLabel(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return "";
  return trimmed;
}

function dedupeByNormalized(values: string[], lang: Lang): string[] {
  const seen = new Set<string>();
  const next: string[] = [];

  for (const value of values) {
    const canonical = canonicalizeChoiceLabel(value);
    if (!canonical) continue;
    const key = normalize(canonical, lang);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    next.push(canonical);
  }
  return next;
}

export function buildMultipleChoiceOptions(params: {
  answer: string;
  pool: string[];
  lang: Lang;
  seed: string;
  maxChoices?: number;
}): string[] {
  const { answer, pool, lang, seed, maxChoices = DEFAULT_CHOICE_COUNT } = params;
  const cleanAnswer = answer.trim();
  const normalizedAnswer = normalize(cleanAnswer, lang);
  const mergedPool = dedupeByNormalized(
    cleanAnswer ? [...pool, cleanAnswer] : [...pool],
    lang
  );

  const distractors = mergedPool.filter((option) => normalize(option, lang) !== normalizedAnswer);
  const orderedDistractors = stableSeedSort(distractors, `${seed}:distractors`);
  const distractorCount = cleanAnswer ? Math.max(maxChoices - 1, 0) : maxChoices;
  const pickedDistractors = orderedDistractors.slice(0, distractorCount);
  const candidates = cleanAnswer ? [cleanAnswer, ...pickedDistractors] : pickedDistractors;

  return stableSeedSort(dedupeByNormalized(candidates, lang), `${seed}:choices`);
}

function buildFallbackPools(items: PuzzleItem[], puzzle: PuzzleItem, lang: Lang): EasyChoicePools {
  const sameBook = items.filter((item) => item[lang].book === puzzle[lang].book);
  return {
    speaker: dedupeByNormalized(sameBook.map((item) => item[lang].speaker), lang),
    listener: dedupeByNormalized(sameBook.map((item) => item[lang].listener), lang),
  };
}

function findBookOptionSet(puzzle: PuzzleItem, optionSets: BookOptionSet[]): BookOptionSet | null {
  return (
    optionSets.find(
      (set) => set.book.en === puzzle.en.book || set.book.he === puzzle.he.book
    ) ?? null
  );
}

export function resolveChoicePoolsForPuzzle(params: {
  puzzle: PuzzleItem;
  items: PuzzleItem[];
  optionSets: BookOptionSet[];
  lang: Lang;
}): EasyChoicePools {
  const { puzzle, items, optionSets, lang } = params;
  const fallback = buildFallbackPools(items, puzzle, lang);
  const fromStatic = findBookOptionSet(puzzle, optionSets);
  if (!fromStatic) return fallback;

  return {
    speaker: dedupeByNormalized([...fromStatic.speaker[lang], ...fallback.speaker], lang),
    listener: dedupeByNormalized([...fromStatic.listener[lang], ...fallback.listener], lang),
  };
}

function normalizeDifficultyChoicePools(raw: unknown): DifficultyChoicePools {
  if (!raw || typeof raw !== "object") return {};
  const candidate = raw as Record<EasyChoiceField, unknown>;
  const toStringList = (value: unknown): string[] => {
    if (!Array.isArray(value)) return [];
    return value.filter((entry): entry is string => typeof entry === "string");
  };
  return {
    speaker: toStringList(candidate.speaker),
    listener: toStringList(candidate.listener),
  };
}

export function resolveChoicePoolsForDifficulty(params: {
  puzzle: PuzzleItem;
  lang: Lang;
  easyMode: boolean;
  fallbackPools?: EasyChoicePools;
}): EasyChoicePools {
  const { puzzle, lang, easyMode, fallbackPools } = params;
  const easyOverrides = normalizeDifficultyChoicePools(puzzle[lang].options);
  // TODO(data): hard_difficulty_options will be added to daily.json.
  // Until then, hard mode falls back to the existing `options` payload.
  const hardOverrides = normalizeDifficultyChoicePools(
    puzzle[lang].hard_difficulty_options ?? puzzle[lang].options
  );
  const selectedOverrides = easyMode ? easyOverrides : hardOverrides;

  return {
    speaker: dedupeByNormalized(
      [...(selectedOverrides.speaker ?? []), ...(fallbackPools?.speaker ?? [])],
      lang
    ),
    listener: dedupeByNormalized(
      [...(selectedOverrides.listener ?? []), ...(fallbackPools?.listener ?? [])],
      lang
    ),
  };
}

export function parseOptionsDataset(raw: unknown): BookOptionSet[] {
  if (!raw || typeof raw !== "object") return [];
  const books = (raw as OptionsDataset).books;
  if (!Array.isArray(books)) return [];
  return books.filter((entry) => {
    if (!entry || typeof entry !== "object") return false;
    if (!entry.book || typeof entry.book !== "object") return false;
    if (!entry.speaker || typeof entry.speaker !== "object") return false;
    if (!entry.listener || typeof entry.listener !== "object") return false;
    if (!entry.portion || typeof entry.portion !== "object") return false;
    return true;
  });
}
