import { normalize } from "./format";
import { canonicalizeDivineName } from "./divineAliases";
import type {
  DifficultyChoicePools,
  EasyChoiceField,
  EasyChoicePools,
  Lang,
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

function alphabeticalSort(values: string[], lang: Lang): string[] {
  const locale = lang === "he" ? "he" : "en";
  return [...values].sort((a, b) => a.localeCompare(b, locale, { sensitivity: "base" }));
}

function canonicalizeChoiceLabel(value: string, lang: Lang): string {
  const trimmed = value.trim();
  if (!trimmed) return "";
  return canonicalizeDivineName(trimmed, lang) ?? trimmed;
}

function dedupeByNormalized(values: string[], lang: Lang): string[] {
  const seen = new Set<string>();
  const next: string[] = [];

  for (const value of values) {
    const canonical = canonicalizeChoiceLabel(value, lang);
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

  return alphabeticalSort(dedupeByNormalized(candidates, lang), lang);
}

function buildFallbackPools(items: PuzzleItem[], puzzle: PuzzleItem, lang: Lang): EasyChoicePools {
  const sameBook = items.filter((item) => item[lang].book === puzzle[lang].book);
  return {
    speaker: dedupeByNormalized(sameBook.map((item) => item[lang].speaker), lang),
    listener: dedupeByNormalized(sameBook.map((item) => item[lang].listener), lang),
  };
}

export function resolveChoicePoolsForPuzzle(params: {
  puzzle: PuzzleItem;
  items: PuzzleItem[];
  lang: Lang;
}): EasyChoicePools {
  const { puzzle, items, lang } = params;
  return buildFallbackPools(items, puzzle, lang);
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
}): EasyChoicePools {
  const { puzzle, lang, easyMode } = params;
  const easyOverrides = normalizeDifficultyChoicePools(puzzle[lang].options);
  const hardOverrides = normalizeDifficultyChoicePools(puzzle[lang].hard_difficulty_options);
  const selectedOverrides = easyMode ? easyOverrides : hardOverrides;

  return {
    speaker: dedupeByNormalized([...(selectedOverrides.speaker ?? [])], lang),
    listener: dedupeByNormalized([...(selectedOverrides.listener ?? [])], lang),
  };
}
