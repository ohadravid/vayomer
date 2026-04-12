import { expect, test, type Locator, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { pickDailyItemIndex, pickDailyItemIndexWithOverrides } from "../src/lib/daily";
import { normalize } from "../src/lib/format";
import type { Lang } from "../src/types";

type PuzzleItem = {
  id: string;
  en: {
    book: string;
    quote: string;
    riddle?: string;
    speaker: string;
    listener: string;
    options?: {
      speaker?: string[];
      listener?: string[];
    };
    bonus?: string | null;
    bonus_hint?: {
      quote?: string | null;
      source?: {
        book?: string;
        chapter?: number;
        start?: number;
        end?: number;
      };
    } | null;
  };
  he: {
    book: string;
    quote: string;
    riddle?: string;
    speaker: string;
    listener: string;
    options?: {
      speaker?: string[];
      listener?: string[];
    };
    bonus?: string | null;
    bonus_hint?: {
      quote?: string | null;
      source?: {
        book?: string;
        chapter?: number;
        start?: number;
        end?: number;
      };
    } | null;
  };
};

type HintSource = {
  book?: string;
  chapter?: number;
  start?: number;
  end?: number;
};

type PuzzleManifestEntry = {
  id: string;
  file: string;
};

type GameOpenOptions = {
  captureClipboard?: boolean;
  lang?: "en" | "he";
  puzzleId?: string;
};

const WRONG_TEXT = "not-the-answer";
const EN_BONUS_DRAFT = "draft-word";
const HE_BONUS_DRAFT = "טיוטה";
const EXAMPLE_SEEN_STORAGE_KEY = "qs:example-seen";
const generatedOptionsDirPath = fileURLToPath(new URL("../data/processed/generated_options", import.meta.url));
const manualQuotesDirPath = fileURLToPath(new URL("../data/manual_quotes", import.meta.url));
const puzzleManifestPath = fileURLToPath(new URL("../src/lib/puzzleManifest.json", import.meta.url));
const exampleQuotesDirPath = fileURLToPath(new URL("../src/lib", import.meta.url));

function parsePuzzleItems(raw: string): PuzzleItem[] {
  const parsed = JSON.parse(raw) as { items?: PuzzleItem[] } | PuzzleItem[];
  return Array.isArray(parsed) ? parsed : (parsed.items ?? []);
}

function loadPuzzleItemsFromDir(dirPath: string): PuzzleItem[] {
  const files = fs
    .readdirSync(dirPath)
    .filter((name) => name.endsWith(".json"))
    .sort();

  return files.flatMap((name) => {
    const raw = fs.readFileSync(path.join(dirPath, name), "utf8");
    return parsePuzzleItems(raw);
  });
}

function loadManifestEntries(filePath: string): PuzzleManifestEntry[] {
  const raw = fs.readFileSync(filePath, "utf8");
  const parsed = JSON.parse(raw) as PuzzleManifestEntry[];
  return Array.isArray(parsed) ? parsed : [];
}

function loadPuzzleItemsFromManifest(manifestPath: string): PuzzleItem[] {
  const itemsById = new Map(
    [...loadPuzzleItemsFromDir(generatedOptionsDirPath), ...loadPuzzleItemsFromDir(manualQuotesDirPath)].map((item) => [item.id, item])
  );

  return loadManifestEntries(manifestPath).map((entry) => {
    const item = itemsById.get(entry.id);
    if (!item) {
      throw new Error(`Expected manifest puzzle ${entry.id} (${entry.file}) to exist in source data.`);
    }
    return item;
  });
}

function loadExamplePuzzleItems(dirPath: string): PuzzleItem[] {
  const files = fs
    .readdirSync(dirPath)
    .filter((name) => /^exampleQuote.*\.json$/u.test(name))
    .sort();

  return files.flatMap((name) => {
    const raw = fs.readFileSync(path.join(dirPath, name), "utf8");
    return parsePuzzleItems(raw);
  }).sort((left, right) => left.id.localeCompare(right.id));
}

const dailyItems = loadPuzzleItemsFromManifest(puzzleManifestPath);
const exampleItems = loadExamplePuzzleItems(exampleQuotesDirPath);
const examplePuzzle = exampleItems.find((item) => item.id === "exodus-03-04-04-example");
const dailyExamplePuzzle = exampleItems[pickDailyItemIndex(exampleItems)];
const hpExamplePuzzle = exampleItems.find((item) => item.id === "hp-example-1");
const todayPuzzle = dailyItems[pickDailyItemIndexWithOverrides(dailyItems)];

if (!todayPuzzle) {
  throw new Error("Expected at least one puzzle to resolve today's puzzle id.");
}

if (!examplePuzzle) {
  throw new Error("Expected exodus-03-04-04-example in src/lib/exampleQuote*.json.");
}

if (!dailyExamplePuzzle) {
  throw new Error("Expected at least one daily example puzzle in src/lib/exampleQuote*.json.");
}

if (!hpExamplePuzzle) {
  throw new Error("Expected hp-example-1 in src/lib/exampleQuote*.json.");
}

const exampleEnAnswer = {
  speaker: examplePuzzle.en.speaker,
  listener: examplePuzzle.en.listener,
  bonus: examplePuzzle.en.bonus?.trim() ?? "",
  riddle: examplePuzzle.en.riddle?.trim() ?? "",
  quote: examplePuzzle.en.quote,
};
const exampleWrongSpeaker = examplePuzzle.en.options?.speaker?.[0]?.trim() ?? "";
const hpExampleEnAnswer = {
  speaker: hpExamplePuzzle.en.speaker,
  listener: hpExamplePuzzle.en.listener,
  bonus: hpExamplePuzzle.en.bonus?.trim() ?? "",
  riddle: hpExamplePuzzle.en.riddle?.trim() ?? "",
  quote: hpExamplePuzzle.en.quote,
};
const hpExampleWrongSpeaker = hpExamplePuzzle.en.options?.speaker?.[0]?.trim() ?? "";
const dailyExampleEnAnswer = {
  speaker: dailyExamplePuzzle.en.speaker,
  listener: dailyExamplePuzzle.en.listener,
};
const dailyExampleWrongSpeaker = dailyExamplePuzzle.en.options?.speaker?.[0]?.trim() ?? "";

if (
  !exampleEnAnswer.speaker ||
  !exampleEnAnswer.listener ||
  !exampleEnAnswer.bonus ||
  !exampleEnAnswer.riddle ||
  !exampleEnAnswer.quote ||
  !exampleWrongSpeaker
) {
  throw new Error("Example puzzle must contain EN speaker/listener/quote/riddle/bonus and one wrong speaker option.");
}

if (
  !hpExampleEnAnswer.speaker ||
  !hpExampleEnAnswer.listener ||
  !hpExampleEnAnswer.bonus ||
  !hpExampleEnAnswer.riddle ||
  !hpExampleEnAnswer.quote ||
  !hpExampleWrongSpeaker
) {
  throw new Error("HP example puzzle must contain EN speaker/listener/quote/riddle/bonus and one wrong speaker option.");
}

if (!dailyExampleEnAnswer.speaker || !dailyExampleEnAnswer.listener || !dailyExampleWrongSpeaker) {
  throw new Error("Daily example puzzle must contain EN speaker/listener and one wrong speaker option.");
}

const todayPuzzleId = todayPuzzle.id;

function hasEasyModeDistractors(item: PuzzleItem): boolean {
  const sameBook = dailyItems.filter((candidate) => candidate.en.book === item.en.book && candidate.he.book === item.he.book);
  const normalizedSpeaker = normalize(item.en.speaker, "en");
  const normalizedListener = normalize(item.en.listener, "en");
  const hasSpeakerAlternative = sameBook.some((candidate) => normalize(candidate.en.speaker, "en") !== normalizedSpeaker);
  const hasListenerAlternative = sameBook.some((candidate) => normalize(candidate.en.listener, "en") !== normalizedListener);
  return hasSpeakerAlternative && hasListenerAlternative;
}

function hasRawEnglishDivineAlias(value: string): boolean {
  const trimmed = value.trim();
  if (!trimmed) return false;
  return normalize(trimmed, "en") === normalize("God", "en") && trimmed.toLowerCase() !== "god";
}

function hasRawHebrewDivineAlias(value: string): boolean {
  const trimmed = value.trim();
  if (!trimmed) return false;
  return normalize(trimmed, "he") === normalize("אֱלֹהִים", "he") && trimmed !== "אֱלֹהִים";
}

const testPuzzle = dailyItems.find(
  (item) => !!item.en.bonus?.trim() && !!item.he.bonus?.trim() && hasEasyModeDistractors(item)
);

if (!testPuzzle) {
  throw new Error("Expected a puzzle with EN/HE bonus answers and easy-mode distractors in the generated puzzle data.");
}

const puzzleId = testPuzzle.id;
const enAnswer = {
  speaker: testPuzzle.en.speaker,
  listener: testPuzzle.en.listener,
  bonus: testPuzzle.en.bonus!.trim(),
};
const testPuzzleHasBonusHint = !!testPuzzle.en.bonus_hint?.quote?.trim();
const heAnswer = {
  speaker: testPuzzle.he.speaker,
  listener: testPuzzle.he.listener,
  bonus: testPuzzle.he.bonus!.trim(),
};

const hintPuzzle = dailyItems.find(
  (item) =>
    !!item.en.bonus?.trim() &&
    !!item.en.bonus_hint?.quote?.trim() &&
    !!item.he.bonus?.trim() &&
    !!item.he.bonus_hint?.quote?.trim()
);

if (!hintPuzzle) {
  throw new Error("Expected at least one puzzle with EN/HE bonus_hint quotes in the generated puzzle data.");
}

const hintPuzzleId = hintPuzzle.id;
const hintEnAnswer = {
  speaker: hintPuzzle.en.speaker,
  listener: hintPuzzle.en.listener,
  bonus: hintPuzzle.en.bonus!.trim(),
};

const divineAliasPuzzle = dailyItems.find(
  (item) =>
    !!item.en.bonus?.trim() &&
    !!item.he.bonus?.trim() &&
    hasEasyModeDistractors(item) &&
    hasRawEnglishDivineAlias(item.en.speaker)
);

if (!divineAliasPuzzle) {
  throw new Error("Expected a puzzle with a raw English divine-name alias speaker and easy-mode distractors.");
}

const divinePuzzleId = divineAliasPuzzle.id;
const divineEnAnswer = {
  speaker: divineAliasPuzzle.en.speaker,
  listener: divineAliasPuzzle.en.listener,
  bonus: divineAliasPuzzle.en.bonus!.trim(),
};

const divineAliasPuzzleHe = dailyItems.find(
  (item) =>
    !!item.en.bonus?.trim() &&
    !!item.he.bonus?.trim() &&
    hasEasyModeDistractors(item) &&
    hasRawHebrewDivineAlias(item.he.speaker)
);

if (!divineAliasPuzzleHe) {
  throw new Error("Expected a puzzle with a raw Hebrew divine-name alias speaker and easy-mode distractors.");
}

const divineHePuzzleId = divineAliasPuzzleHe.id;
const divineHeAnswer = {
  speaker: divineAliasPuzzleHe.he.speaker,
  listener: divineAliasPuzzleHe.he.listener,
  bonus: divineAliasPuzzleHe.he.bonus!.trim(),
};

function formatHintSource(source: HintSource | undefined): string {
  if (!source) return "";
  const book = source.book?.trim() ?? "";
  const chapter = Number.isFinite(source.chapter) ? source.chapter : null;
  const start = Number.isFinite(source.start) ? source.start : null;
  const end = Number.isFinite(source.end) ? source.end : null;
  const verse = chapter !== null && start !== null ? `${chapter}:${end !== null && end !== start ? `${start}-${end}` : start}` : "";
  return [book, verse].filter(Boolean).join(" ");
}

const hintSourceLabel = formatHintSource(hintPuzzle.en.bonus_hint?.source);

if (!enAnswer.speaker || !enAnswer.listener || !enAnswer.bonus) {
  throw new Error(`Missing EN answers in puzzle ${puzzleId}.`);
}

if (!heAnswer.speaker || !heAnswer.listener || !heAnswer.bonus) {
  throw new Error(`Missing HE answers in puzzle ${puzzleId}.`);
}

async function installClipboardCapture(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const setCopiedText = (text: string) => {
      (globalThis as { __copiedText?: string }).__copiedText = text;
    };

    setCopiedText("");

    try {
      Object.defineProperty(navigator, "clipboard", {
        configurable: true,
        value: {
          writeText: async (text: string) => setCopiedText(text),
        },
      });
    } catch {
      // Keep execCommand fallback below.
    }

    const originalExecCommand = document.execCommand?.bind(document);
    document.execCommand = ((commandId: string): boolean => {
      if (commandId.toLowerCase() === "copy") {
        const active = document.activeElement as HTMLTextAreaElement | null;
        if (active && typeof active.value === "string") {
          setCopiedText(active.value);
        }
        return true;
      }
      if (!originalExecCommand) return false;
      return originalExecCommand(commandId);
    }) as typeof document.execCommand;
  });
}

async function openGame(page: Page, options: GameOpenOptions = {}): Promise<void> {
  if (options.captureClipboard) {
    await installClipboardCapture(page);
  }

  const params = new URLSearchParams();
  params.set("puzzle", options.puzzleId ?? puzzleId);
  params.set("lng", options.lang ?? "en");

  await page.goto(`/?${params.toString()}`);
  await expect(page.locator("#guessForm")).toBeVisible();
}

async function expectSolvedState(
  page: Page,
  args: { lang: Lang; bonus: string; feedback: string; triesLabel: string }
): Promise<void> {
  await expect(page.locator("#feedback")).toHaveText(args.feedback);
  await expect(page.getByText(args.triesLabel)).toBeVisible();
  await expect(page.locator("#submitGuess")).toBeDisabled();
  const quoteText = await page.locator("#fullQuote").innerText();
  expect(normalize(quoteText, args.lang)).toContain(normalize(args.bonus, args.lang));
}

function findMatchingOption(options: string[], answer: string, lang: Lang): string {
  const exact = options.find((option) => option === answer);
  if (exact) return exact;

  const normalizedAnswer = normalize(answer, lang);
  const equivalent = options.find((option) => !!option && normalize(option, lang) === normalizedAnswer);
  if (equivalent) return equivalent;

  throw new Error(`Expected a matching option. Answer: ${answer}. Options: ${options.join(", ")}`);
}

async function selectAnswerOption(select: Locator, answer: string, lang: Lang): Promise<void> {
  const options = await select.locator("option").evaluateAll((nodes) =>
    nodes.map((node) => (node as HTMLOptionElement).value)
  );
  const match = findMatchingOption(options, answer, lang);
  await select.selectOption(match);
}

async function pickWrongOption(select: Locator, correctAnswer: string, lang: Lang): Promise<string> {
  const options = await select.locator("option").evaluateAll((nodes) =>
    nodes.map((node) => (node as HTMLOptionElement).value)
  );
  const normalizedCorrect = normalize(correctAnswer, lang);
  const wrong = options.find((option) => option && normalize(option, lang) !== normalizedCorrect);
  if (!wrong) {
    throw new Error(`Expected a wrong option. Correct answer: ${correctAnswer}.`);
  }
  return wrong;
}

function pickVisibleContextTokenFromQuote(quote: string, riddle: string, bonus: string, lang: Lang): string {
  const quoteTokens = quote.match(/\p{L}+/gu) ?? [];
  const bonusNormalized = normalize(bonus, lang);
  const riddleTokens = new Set((riddle.match(/\p{L}+/gu) ?? []).map((token) => normalize(token, lang)));
  const candidate = quoteTokens.find((token) => {
    const normalizedToken = normalize(token, lang);
    if (!normalizedToken) return false;
    if (normalizedToken === bonusNormalized) return false;
    return !riddleTokens.has(normalizedToken);
  });
  return candidate ?? "";
}

const enVisibleContextToken = pickVisibleContextTokenFromQuote(
  testPuzzle.en.quote,
  testPuzzle.en.riddle ?? "",
  enAnswer.bonus,
  "en"
);
const exampleVisibleContextToken = pickVisibleContextTokenFromQuote(
  exampleEnAnswer.quote,
  exampleEnAnswer.riddle,
  exampleEnAnswer.bonus,
  "en"
);
const hpExampleVisibleContextToken = pickVisibleContextTokenFromQuote(
  hpExampleEnAnswer.quote,
  hpExampleEnAnswer.riddle,
  hpExampleEnAnswer.bonus,
  "en"
);

if (!enVisibleContextToken) {
  throw new Error(`Could not pick a visible non-bonus token from puzzle ${puzzleId}.`);
}

if (!exampleVisibleContextToken) {
  throw new Error("Could not pick a visible non-bonus token from example puzzle.");
}

if (!hpExampleVisibleContextToken) {
  throw new Error("Could not pick a visible non-bonus token from HP example puzzle.");
}

test("legacy difficulty params are removed from the URL on load", async ({ page }) => {
  const params = new URLSearchParams({
    puzzle: todayPuzzleId,
    lng: "en",
    hard: "1",
    easy: "0",
  });

  await page.goto(`/?${params.toString()}`);
  await expect(page.locator("#guessForm")).toBeVisible();
  await expect.poll(() => new URL(page.url()).searchParams.get("hard")).toBeNull();
  await expect.poll(() => new URL(page.url()).searchParams.get("easy")).toBeNull();
  expect(new URL(page.url()).searchParams.get("puzzle")).toBe(todayPuzzleId);
});

test("full game: clear win (double reload persists stage-two state)", async ({ page }) => {
  await openGame(page);
  await expect(page.locator("#bonusHint")).toHaveCount(0);
  await expect(page.locator("#refLine")).toHaveText("");

  await selectAnswerOption(page.locator("#inputSpeaker"), enAnswer.speaker, "en");
  await selectAnswerOption(page.locator("#inputListener"), enAnswer.listener, "en");
  await page.click("#submitGuess");

  await expect(page.locator("#feedback")).toHaveText("Nice! Now find the missing word.");
  const quoteAfterCoreSolve = await page.locator("#fullQuote").innerText();
  expect(normalize(quoteAfterCoreSolve, "en")).toContain(normalize(enVisibleContextToken, "en"));
  expect(normalize(quoteAfterCoreSolve, "en")).not.toContain(normalize(enAnswer.bonus, "en"));
  await expect(page.locator("#refLine")).not.toHaveText("");
  await expect(page.getByText("Tries: 0/5")).toBeVisible();

  await page.reload();
  await expect(page.locator("#guessForm")).toBeVisible();
  const persistedSpeaker = await page.locator("#inputSpeaker").inputValue();
  const persistedListener = await page.locator("#inputListener").inputValue();
  expect(normalize(persistedSpeaker, "en")).toBe(normalize(enAnswer.speaker, "en"));
  expect(normalize(persistedListener, "en")).toBe(normalize(enAnswer.listener, "en"));
  await expect(page.locator("#feedback")).toHaveText("Nice! Now find the missing word.");
  const quoteAfterReload = await page.locator("#fullQuote").innerText();
  expect(normalize(quoteAfterReload, "en")).toContain(normalize(enVisibleContextToken, "en"));
  expect(normalize(quoteAfterReload, "en")).not.toContain(normalize(enAnswer.bonus, "en"));
  await expect(page.locator("#refLine")).not.toHaveText("");
  await expect(page.getByText("Tries: 0/5")).toBeVisible();

  await page.reload();
  await expect(page.locator("#guessForm")).toBeVisible();
  const persistedSpeakerAfterSecondReload = await page.locator("#inputSpeaker").inputValue();
  const persistedListenerAfterSecondReload = await page.locator("#inputListener").inputValue();
  expect(normalize(persistedSpeakerAfterSecondReload, "en")).toBe(normalize(enAnswer.speaker, "en"));
  expect(normalize(persistedListenerAfterSecondReload, "en")).toBe(normalize(enAnswer.listener, "en"));
  await expect(page.locator("#feedback")).toHaveText("Nice! Now find the missing word.");
  const quoteAfterSecondReload = await page.locator("#fullQuote").innerText();
  expect(normalize(quoteAfterSecondReload, "en")).toContain(normalize(enVisibleContextToken, "en"));
  expect(normalize(quoteAfterSecondReload, "en")).not.toContain(normalize(enAnswer.bonus, "en"));
  await expect(page.locator("#refLine")).not.toHaveText("");
  await expect(page.getByText("Tries: 0/5")).toBeVisible();

  await page.fill("#inputBonus", enAnswer.bonus);
  await page.click("#submitGuess");

  await expect(page.locator("#feedback")).toHaveText("Solved.");
  const quoteAfterSolve = await page.locator("#fullQuote").innerText();
  expect(normalize(quoteAfterSolve, "en")).toContain(normalize(enAnswer.bonus, "en"));
  if (testPuzzleHasBonusHint) {
    await expect(page.locator("#bonusHint")).toBeVisible();
  } else {
    await expect(page.locator("#bonusHint")).toHaveCount(0);
  }
  await expect(page.getByText("Tries: 1/5")).toBeVisible();
  await expect(page.locator("#submitGuess")).toBeDisabled();
});

test("language switch keeps shared progress and separate drafts", async ({ page }) => {
  await openGame(page, { lang: "he" });

  await selectAnswerOption(page.locator("#inputSpeaker"), heAnswer.speaker, "he");
  await selectAnswerOption(page.locator("#inputListener"), heAnswer.listener, "he");
  await page.click("#submitGuess");

  await expect(page.locator("#feedback")).toHaveText("יפה! עכשיו מצאו את המילה החסרה.");
  await expect(page.getByText("ניסיונות: 0/5")).toBeVisible();
  await expect(page.locator("#inputBonus")).toBeEnabled();
  await page.fill("#inputBonus", HE_BONUS_DRAFT);
  await expect(page.locator("#inputBonus")).toHaveValue(HE_BONUS_DRAFT);

  await page.getByRole("button", { name: "החלפת שפה ל-EN" }).click();

  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.locator("#feedback")).toHaveText("Nice! Now find the missing word.");
  await expect(page.getByText("Tries: 0/5")).toBeVisible();
  const enSpeakerAfterSwitch = await page.locator("#inputSpeaker").inputValue();
  expect(normalize(enSpeakerAfterSwitch, "en")).toBe(normalize(enAnswer.speaker, "en"));
  await expect(page.locator("#inputListener")).toHaveValue(enAnswer.listener);
  await expect(page.locator("#inputBonus")).toHaveValue("");
  expect(new URL(page.url()).searchParams.get("puzzle")).toBe(puzzleId);

  await page.fill("#inputBonus", EN_BONUS_DRAFT);
  await expect(page.locator("#inputBonus")).toHaveValue(EN_BONUS_DRAFT);

  await page.getByRole("button", { name: "Switch language to HE" }).click();

  await expect(page.locator("html")).toHaveAttribute("lang", "he");
  await expect(page.locator("#feedback")).toHaveText("יפה! עכשיו מצאו את המילה החסרה.");
  await expect(page.getByText("ניסיונות: 0/5")).toBeVisible();
  const heSpeakerAfterReturn = await page.locator("#inputSpeaker").inputValue();
  expect(normalize(heSpeakerAfterReturn, "he")).toBe(normalize(heAnswer.speaker, "he"));
  await expect(page.locator("#inputListener")).toHaveValue(heAnswer.listener);
  await expect(page.locator("#inputBonus")).toHaveValue(HE_BONUS_DRAFT);
});

test("bonus hint in stage two reveals hint, stays visible after solve, and is reflected in share", async ({ page }) => {
  await openGame(page, { puzzleId: hintPuzzleId, lang: "en", captureClipboard: true });
  await expect(page.locator("#bonusHint")).toHaveCount(0);
  await expect(page.locator("#refLine")).toHaveText("");

  await selectAnswerOption(page.locator("#inputSpeaker"), hintEnAnswer.speaker, "en");
  await selectAnswerOption(page.locator("#inputListener"), hintEnAnswer.listener, "en");
  await page.click("#submitGuess");

  await expect(page.locator("#feedback")).toHaveText("Nice! Now find the missing word.");
  await expect(page.locator("#bonusHint")).toBeVisible();
  await expect(page.locator("#refLine")).not.toHaveText("");
  await expect(page.locator("#hintQuote")).toHaveCount(0);

  await page.click("#bonusHint");

  await expect(page.locator("#hintQuote")).toBeVisible();
  const hintQuoteText = await page.locator("#hintQuote").innerText();
  expect(normalize(hintQuoteText, "en")).not.toContain(normalize(hintEnAnswer.bonus, "en"));
  if (hintSourceLabel) {
    await expect(page.locator("#hintRefLine")).toHaveText(hintSourceLabel);
  } else {
    await expect(page.locator("#hintRefLine")).toBeVisible();
  }
  await expect(page.locator("#bonusHint")).toBeDisabled();

  await page.reload();
  await expect(page.locator("#guessForm")).toBeVisible();
  await expect(page.locator("#hintQuote")).toBeVisible();
  await expect(page.locator("#bonusHint")).toBeDisabled();

  await page.fill("#inputBonus", hintEnAnswer.bonus);
  await page.click("#submitGuess");
  await expect(page.locator("#feedback")).toHaveText("Solved.");
  await expect(page.locator("#bonusHint")).toBeVisible();
  const solvedHintQuoteText = await page.locator("#hintQuote").innerText();
  expect(normalize(solvedHintQuoteText, "en")).toContain(normalize(hintEnAnswer.bonus, "en"));

  await page.getByRole("button", { name: "Share result" }).click();
  await expect(page.locator(".share-note")).toHaveText("Result copied.");
  const copiedText = await page.evaluate(() => (globalThis as { __copiedText?: string }).__copiedText ?? "");
  expect(copiedText).toContain("💡");
});

test("stage-two failure reveals the bonus in quote and hint but preserves the typed bonus input", async ({ page }) => {
  await openGame(page, { puzzleId: hintPuzzleId, lang: "en" });

  await selectAnswerOption(page.locator("#inputSpeaker"), hintEnAnswer.speaker, "en");
  await selectAnswerOption(page.locator("#inputListener"), hintEnAnswer.listener, "en");
  await page.click("#submitGuess");

  await expect(page.locator("#feedback")).toHaveText("Nice! Now find the missing word.");
  await page.click("#bonusHint");
  await expect(page.locator("#hintQuote")).toBeVisible();

  await page.fill("#inputBonus", WRONG_TEXT);
  for (let idx = 0; idx < 5; idx += 1) {
    await page.click("#submitGuess");
  }

  await expect(page.locator("#feedback")).toHaveText("No tries left.");
  await expect(page.getByText("Tries: 5/5")).toBeVisible();
  const quoteAfterLose = await page.locator("#fullQuote").innerText();
  const hintQuoteAfterLose = await page.locator("#hintQuote").innerText();
  expect(normalize(quoteAfterLose, "en")).toContain(normalize(hintEnAnswer.bonus, "en"));
  expect(normalize(hintQuoteAfterLose, "en")).toContain(normalize(hintEnAnswer.bonus, "en"));
  await expect(page.locator("#inputBonus")).toHaveValue(WRONG_TEXT);
  await expect(page.locator("#inputBonus")).toBeDisabled();
  await expect(page.locator("#inputBonus")).toHaveClass(/wrong/);
  await expect(page.locator("#labelBonus")).toContainText("❌");
});

test("full game: mistakes and win", async ({ page }) => {
  await openGame(page);

  const wrongSpeaker = await pickWrongOption(page.locator("#inputSpeaker"), enAnswer.speaker, "en");
  const wrongListener = await pickWrongOption(page.locator("#inputListener"), enAnswer.listener, "en");

  await page.selectOption("#inputSpeaker", wrongSpeaker);
  await page.selectOption("#inputListener", wrongListener);
  await page.click("#submitGuess");
  await expect(page.locator("#feedback")).toHaveText("Not quite. Try again.");

  await selectAnswerOption(page.locator("#inputSpeaker"), enAnswer.speaker, "en");
  await selectAnswerOption(page.locator("#inputListener"), enAnswer.listener, "en");
  await page.click("#submitGuess");
  await expect(page.locator("#feedback")).toHaveText("Nice! Now find the missing word.");

  await page.fill("#inputBonus", WRONG_TEXT);
  await page.click("#submitGuess");
  await expect(page.locator("#feedback")).toHaveText("Nice! Now find the missing word.");
  await expect(page.getByText("Status: ✅✅✴️⬜")).toBeVisible();
  await expect(page.locator("#inputBonus")).toHaveClass(/wrong/);
  await expect(page.locator("#labelBonus")).toContainText("❌");

  await page.fill("#inputBonus", enAnswer.bonus);
  await page.click("#submitGuess");

  await expect(page.locator("#feedback")).toHaveText("Solved.");
  await expect(page.getByText("Tries: 3/5")).toBeVisible();
});

test("solved state survives two reloads", async ({ page }) => {
  await openGame(page, { lang: "en" });

  await selectAnswerOption(page.locator("#inputSpeaker"), enAnswer.speaker, "en");
  await selectAnswerOption(page.locator("#inputListener"), enAnswer.listener, "en");
  await page.click("#submitGuess");
  await page.fill("#inputBonus", enAnswer.bonus);
  await page.click("#submitGuess");

  await expectSolvedState(page, {
    lang: "en",
    bonus: enAnswer.bonus,
    feedback: "Solved.",
    triesLabel: "Tries: 1/5",
  });

  await page.reload();
  await expect(page.locator("#guessForm")).toBeVisible();
  await expectSolvedState(page, {
    lang: "en",
    bonus: enAnswer.bonus,
    feedback: "Solved.",
    triesLabel: "Tries: 1/5",
  });

  await page.reload();
  await expect(page.locator("#guessForm")).toBeVisible();
  await expectSolvedState(page, {
    lang: "en",
    bonus: enAnswer.bonus,
    feedback: "Solved.",
    triesLabel: "Tries: 1/5",
  });
});

test("full game: lose", async ({ page }) => {
  await openGame(page);

  const wrongSpeaker = await pickWrongOption(page.locator("#inputSpeaker"), enAnswer.speaker, "en");
  const wrongListener = await pickWrongOption(page.locator("#inputListener"), enAnswer.listener, "en");

  await page.selectOption("#inputSpeaker", wrongSpeaker);
  await page.selectOption("#inputListener", wrongListener);
  const quoteBeforeLose = await page.locator("#fullQuote").innerText();
  expect(normalize(quoteBeforeLose, "en")).not.toContain(normalize(enAnswer.bonus, "en"));
  for (let idx = 0; idx < 5; idx += 1) {
    await page.click("#submitGuess");
  }

  await expect(page.locator("#feedback")).toHaveText("No tries left.");
  await expect(page.getByText("Tries: 5/5")).toBeVisible();
  const quoteAfterLose = await page.locator("#fullQuote").innerText();
  expect(normalize(quoteAfterLose, "en")).toContain(normalize(enAnswer.bonus, "en"));
  const revealedSpeaker = await page.locator("#inputSpeaker").inputValue();
  const revealedListener = await page.locator("#inputListener").inputValue();
  const revealedBonus = await page.locator("#inputBonus").inputValue();
  expect(normalize(revealedSpeaker, "en")).toBe(normalize(enAnswer.speaker, "en"));
  expect(normalize(revealedListener, "en")).toBe(normalize(enAnswer.listener, "en"));
  expect(revealedBonus).toBe("");
  await expect(page.locator("#inputSpeaker")).toBeDisabled();
  await expect(page.locator("#inputListener")).toBeDisabled();
  await expect(page.locator("#inputBonus")).toBeDisabled();
  await expect(page.locator("#inputBonus")).toHaveClass(/wrong/);
  await expect(page.locator("#labelSpeaker")).toContainText("✅");
  await expect(page.locator("#labelListener")).toContainText("✅");
  await expect(page.locator("#labelBonus")).toContainText("❌");
  await expect(page.locator("#submitGuess")).toBeDisabled();
});

test("canonicalizes divine speaker options to God and accepts them", async ({ page }) => {
  await openGame(page, { puzzleId: divinePuzzleId, lang: "en" });

  const speakerSelect = page.locator("#inputSpeaker");
  const speakerOptions = await speakerSelect
    .locator("option")
    .evaluateAll((nodes) => nodes.map((node) => (node as HTMLOptionElement).value).filter(Boolean));

  expect(speakerOptions).toContain("God");
  expect(
    speakerOptions.some((option) => {
      const trimmed = option.trim();
      return normalize(trimmed, "en") === normalize("God", "en") && trimmed.toLowerCase() !== "god";
    })
  ).toBe(false);

  await selectAnswerOption(speakerSelect, divineEnAnswer.speaker, "en");
  expect(await speakerSelect.inputValue()).toBe("God");
  await selectAnswerOption(page.locator("#inputListener"), divineEnAnswer.listener, "en");
  await page.click("#submitGuess");
  await expect(page.locator("#feedback")).toHaveText("Nice! Now find the missing word.");
});

test("hebrew canonicalizes divine speaker options to אֱלֹהִים and accepts them", async ({ page }) => {
  await openGame(page, { puzzleId: divineHePuzzleId, lang: "he" });

  const speakerSelect = page.locator("#inputSpeaker");
  const speakerOptions = await speakerSelect
    .locator("option")
    .evaluateAll((nodes) => nodes.map((node) => (node as HTMLOptionElement).value).filter(Boolean));

  expect(speakerOptions).toContain("אֱלֹהִים");
  expect(
    speakerOptions.some((option) => {
      const trimmed = option.trim();
      return normalize(trimmed, "he") === normalize("אֱלֹהִים", "he") && trimmed !== "אֱלֹהִים";
    })
  ).toBe(false);

  await selectAnswerOption(speakerSelect, divineHeAnswer.speaker, "he");
  expect(await speakerSelect.inputValue()).toBe("אֱלֹהִים");
  await selectAnswerOption(page.locator("#inputListener"), divineHeAnswer.listener, "he");
  await page.click("#submitGuess");
  await expect(page.locator("#feedback")).toHaveText("יפה! עכשיו מצאו את המילה החסרה.");
});

test("share copies result text", async ({ page }) => {
  await openGame(page, { captureClipboard: true });

  const wrongSpeaker = await pickWrongOption(page.locator("#inputSpeaker"), enAnswer.speaker, "en");
  const wrongListener = await pickWrongOption(page.locator("#inputListener"), enAnswer.listener, "en");

  await page.selectOption("#inputSpeaker", wrongSpeaker);
  await page.selectOption("#inputListener", wrongListener);
  await page.click("#submitGuess");

  await page.getByRole("button", { name: "Share result" }).click();
  await expect(page.locator(".share-note")).toHaveText("Result copied.");

  const copiedText = await page.evaluate(() => (globalThis as { __copiedText?: string }).__copiedText ?? "");
  const origin = new URL(page.url()).origin;
  expect(copiedText).toContain("Vayomer");
  expect(copiedText).toContain(`${origin}/`);
});

test("about page opens and returns to puzzle", async ({ page }) => {
  await openGame(page);

  await page.getByRole("link", { name: "About & sources" }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe("/about");
  await expect.poll(() => new URL(page.url()).searchParams.get("lng")).toBe("en");
  await expect(page.getByRole("heading", { name: "About Vayomer" })).toBeVisible();
  await expect(page.getByText("Source Material")).toBeVisible();

  await page.locator("#topBackButton").click();
  await expect(page.locator("#puzzleCard")).toBeVisible();
});

test("how-to example opens from ❓, starts with partial correctness, and can be solved", async ({ page }) => {
  await openGame(page, { lang: "en" });

  await page.getByRole("link", { name: "Open how to play example" }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe("/example");
  await expect.poll(() => new URL(page.url()).searchParams.get("lng")).toBe("en");
  await expect(page.locator("#guessForm")).toBeVisible();
  await expect(page.getByRole("button", { name: "Share result" })).toHaveCount(0);

  await expect(page.locator("#inputSpeaker")).toHaveValue(exampleWrongSpeaker);
  await expect(page.locator("#inputListener")).toHaveValue(exampleEnAnswer.listener);
  await expect(page.locator("#labelSpeaker")).toContainText("❌");
  await expect(page.locator("#labelListener")).toContainText("✅");
  await expect(page.locator("#feedback")).toHaveText("Not quite. Try again.");
  const quoteBeforeCoreSolve = await page.locator("#fullQuote").innerText();
  expect(normalize(quoteBeforeCoreSolve, "en")).not.toContain(normalize(exampleEnAnswer.bonus, "en"));

  await selectAnswerOption(page.locator("#inputSpeaker"), exampleEnAnswer.speaker, "en");
  await selectAnswerOption(page.locator("#inputListener"), exampleEnAnswer.listener, "en");
  await page.click("#submitGuess");

  await expect(page.locator("#feedback")).toHaveText("Nice! Now find the missing word.");
  await expect(page.locator("#inputBonus")).toBeEnabled();
  const quoteAfterCoreSolve = await page.locator("#fullQuote").innerText();
  expect(normalize(quoteAfterCoreSolve, "en")).toContain(normalize(exampleVisibleContextToken, "en"));
  expect(normalize(quoteAfterCoreSolve, "en")).not.toContain(normalize(exampleEnAnswer.bonus, "en"));

  await page.fill("#inputBonus", exampleEnAnswer.bonus);
  await page.click("#submitGuess");
  await expect(page.locator("#feedback")).toHaveText("Solved.");
  const quoteAfterSolve = await page.locator("#fullQuote").innerText();
  expect(normalize(quoteAfterSolve, "en")).toContain(normalize(exampleEnAnswer.riddle, "en"));
  expect(normalize(quoteAfterSolve, "en")).toContain(normalize(exampleEnAnswer.bonus, "en"));
});

test("first example view uses the bible example, then later views use the daily example and persist a marker", async ({ page }) => {
  await openGame(page, { lang: "en" });

  await page.getByRole("link", { name: "Open how to play example" }).click();
  await expect(page.locator("#inputSpeaker")).toHaveValue(exampleWrongSpeaker);
  await expect(page.locator("#inputListener")).toHaveValue(exampleEnAnswer.listener);
  expect(await page.evaluate((key) => localStorage.getItem(key), EXAMPLE_SEEN_STORAGE_KEY)).toBe("1");

  await page.locator("#topBackButton").click();
  await expect(page.locator("#puzzleCard")).toBeVisible();

  await page.getByRole("link", { name: "Open how to play example" }).click();
  await expect(page.locator("#inputSpeaker")).toHaveValue(dailyExampleWrongSpeaker);
  await expect(page.locator("#inputListener")).toHaveValue(dailyExampleEnAnswer.listener);
});

test("example page can resolve the HP example by id from the URL", async ({ page }) => {
  await page.addInitScript((storageKey) => {
    window.localStorage.setItem(storageKey, "1");
  }, EXAMPLE_SEEN_STORAGE_KEY);

  const params = new URLSearchParams({
    puzzle: hpExamplePuzzle.id,
    lng: "en",
  });

  await page.goto(`/example?${params.toString()}`);
  await expect(page.locator("#guessForm")).toBeVisible();
  await expect(page.locator("#inputSpeaker")).toHaveValue(hpExampleWrongSpeaker);
  await expect(page.locator("#inputListener")).toHaveValue(hpExampleEnAnswer.listener);
  await expect(page.locator("#feedback")).toHaveText("Not quite. Try again.");

  const quoteBeforeCoreSolve = await page.locator("#fullQuote").innerText();
  expect(normalize(quoteBeforeCoreSolve, "en")).toContain(normalize(hpExampleVisibleContextToken, "en"));
  expect(normalize(quoteBeforeCoreSolve, "en")).not.toContain(normalize(hpExampleEnAnswer.bonus, "en"));

  await selectAnswerOption(page.locator("#inputSpeaker"), hpExampleEnAnswer.speaker, "en");
  await selectAnswerOption(page.locator("#inputListener"), hpExampleEnAnswer.listener, "en");
  await page.click("#submitGuess");

  await expect(page.locator("#feedback")).toHaveText("Nice! Now find the missing word.");
  await page.fill("#inputBonus", hpExampleEnAnswer.bonus);
  await page.click("#submitGuess");

  await expect(page.locator("#feedback")).toHaveText("Solved.");
  const quoteAfterSolve = await page.locator("#fullQuote").innerText();
  expect(normalize(quoteAfterSolve, "en")).toContain(normalize(hpExampleEnAnswer.riddle, "en"));
  expect(normalize(quoteAfterSolve, "en")).toContain(normalize(hpExampleEnAnswer.bonus, "en"));
});

test("language switch updates UI and keeps selected puzzle", async ({ page }) => {
  await openGame(page, { lang: "en" });

  await page.getByRole("button", { name: "Switch language to HE" }).click();

  await expect(page.locator("html")).toHaveAttribute("lang", "he");
  await expect(page.locator("#submitGuess")).toHaveText("בדיקה");

  const searchParams = new URL(page.url()).searchParams;
  expect(searchParams.get("puzzle")).toBe(puzzleId);
});

test("hebrew full game flow", async ({ page }) => {
  await openGame(page, { lang: "he" });

  await selectAnswerOption(page.locator("#inputSpeaker"), heAnswer.speaker, "he");
  await selectAnswerOption(page.locator("#inputListener"), heAnswer.listener, "he");
  await page.click("#submitGuess");
  await expect(page.locator("#feedback")).toHaveText("יפה! עכשיו מצאו את המילה החסרה.");

  await page.fill("#inputBonus", heAnswer.bonus);
  await page.click("#submitGuess");

  await expect(page.locator("#feedback")).toHaveText("נכון.");
  await expect(page.getByText("ניסיונות: 1/5")).toBeVisible();
  await expect(page.locator("#submitGuess")).toBeDisabled();
});
