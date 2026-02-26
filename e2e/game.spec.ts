import { expect, test, type Locator, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { pickDailyHardModeSuccessMark, pickDailyItemIndex } from "../src/lib/daily";
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

type GameOpenOptions = {
  easyMode?: boolean;
  captureClipboard?: boolean;
  lang?: "en" | "he";
  puzzleId?: string;
};

const WRONG_TEXT = "not-the-answer";
const quotesOptionsDirPath = fileURLToPath(new URL("../data/quotes_options", import.meta.url));
const exampleQuotePath = fileURLToPath(new URL("../src/lib/exampleQuote.json", import.meta.url));

function loadPuzzleItemsFromQuotesOptions(dirPath: string): PuzzleItem[] {
  const files = fs
    .readdirSync(dirPath)
    .filter((name) => name.endsWith(".json"))
    .sort();

  return files.flatMap((name) => {
    const raw = fs.readFileSync(path.join(dirPath, name), "utf8");
    const parsed = JSON.parse(raw) as { items?: PuzzleItem[] } | PuzzleItem[];
    return Array.isArray(parsed) ? parsed : (parsed.items ?? []);
  });
}

const dailyItems = loadPuzzleItemsFromQuotesOptions(quotesOptionsDirPath);
const examplePayload = JSON.parse(fs.readFileSync(exampleQuotePath, "utf8")) as { items?: PuzzleItem[] };
const examplePuzzle = examplePayload.items?.[0];
const todayPuzzle = dailyItems[pickDailyItemIndex(dailyItems.length)];

if (!todayPuzzle) {
  throw new Error("Expected at least one puzzle to resolve today's puzzle id.");
}

if (!examplePuzzle) {
  throw new Error("Expected one example puzzle in src/lib/exampleQuote.json.");
}

const exampleEnAnswer = {
  speaker: examplePuzzle.en.speaker,
  listener: examplePuzzle.en.listener,
  bonus: examplePuzzle.en.bonus?.trim() ?? "",
  riddle: examplePuzzle.en.riddle?.trim() ?? "",
  quote: examplePuzzle.en.quote,
};
const exampleWrongSpeaker = examplePuzzle.en.options?.speaker?.[0]?.trim() ?? "";

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
  throw new Error("Expected a puzzle with EN/HE bonus answers and easy-mode distractors in data/quotes_options/*.json.");
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
  throw new Error("Expected at least one puzzle with EN/HE bonus_hint quotes in data/quotes_options/*.json.");
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
const hardSuccessMark = pickDailyHardModeSuccessMark(new Date());
const difficultyLockStoragePrefix = "qs:difficulty-lock:";

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

  if (options.easyMode === false) {
    params.set("hard", "1");
  }

  await page.goto(`/?${params.toString()}`);
  await expect(page.locator("#guessForm")).toBeVisible();
}

async function getDifficultyLockValue(page: Page, id: string): Promise<string | null> {
  return page.evaluate(
    ({ puzzleId, prefix }) => localStorage.getItem(`${prefix}${puzzleId}`),
    { puzzleId: id, prefix: difficultyLockStoragePrefix }
  );
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

function buildEnglishArticleVariant(answer: string): string {
  const trimmed = answer.trim();
  if (!trimmed) return trimmed;
  if (/^the\s+/iu.test(trimmed)) {
    return trimmed.replace(/^the\s+/iu, "");
  }
  return `the ${trimmed}`;
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

if (!enVisibleContextToken) {
  throw new Error(`Could not pick a visible non-bonus token from puzzle ${puzzleId}.`);
}

if (!exampleVisibleContextToken) {
  throw new Error("Could not pick a visible non-bonus token from example puzzle.");
}

test("toggling the sheep to hard mode writes hard=1 in the URL", async ({ page }) => {
  await openGame(page, { puzzleId: todayPuzzleId });
  await expect(page.locator("#guessForm")).toBeVisible();
  const difficultyToggle = page.getByRole("button", { name: "Toggle easy mode" });

  const defaultTagName = await page.locator("#inputSpeaker").evaluate((node) => node.tagName);
  expect(defaultTagName).toBe("SELECT");
  expect(new URL(page.url()).searchParams.get("hard")).toBeNull();
  await expect(difficultyToggle).toBeEnabled();
  expect(await getDifficultyLockValue(page, todayPuzzleId)).toBeNull();

  await difficultyToggle.click();
  await expect(difficultyToggle).toBeEnabled();
  await expect(difficultyToggle).toHaveAttribute("aria-pressed", "false");
  await expect.poll(() => new URL(page.url()).searchParams.get("hard")).toBe("1");
});

test("difficulty lock keeps hard mode when revisiting regular URL", async ({ page }) => {
  await openGame(page, { easyMode: false, puzzleId: todayPuzzleId });
  const difficultyToggle = page.getByRole("button", { name: "Toggle easy mode" });

  await expect(difficultyToggle).toBeEnabled();
  await expect(difficultyToggle).toHaveAttribute("aria-pressed", "false");
  expect(await getDifficultyLockValue(page, todayPuzzleId)).toBeNull();
  await expect.poll(() => new URL(page.url()).searchParams.get("hard")).toBe("1");

  await page.click("#inputSpeaker");
  await expect(difficultyToggle).toBeEnabled();
  await expect(difficultyToggle).toHaveAttribute("aria-pressed", "false");
  expect(await getDifficultyLockValue(page, todayPuzzleId)).toBe("0");
  await expect.poll(() => new URL(page.url()).searchParams.get("hard")).toBe("1");

  const regularParams = new URLSearchParams({
    puzzle: todayPuzzleId,
    lng: "en",
  });
  await page.goto(`/?${regularParams.toString()}`);
  await expect(page.locator("#guessForm")).toBeVisible();

  // The hard lock still applies across navigation even when URL has no explicit mode.
  await expect(difficultyToggle).toBeEnabled();
  await expect(difficultyToggle).toHaveAttribute("aria-pressed", "false");
  await expect.poll(() => new URL(page.url()).searchParams.get("hard")).toBe("1");
});

test("hard mode accepts fuzzy free-text answers", async ({ page }) => {
  await openGame(page, { easyMode: false });

  await page.fill("#inputSpeaker", buildEnglishArticleVariant(enAnswer.speaker));
  await page.fill("#inputListener", `${enAnswer.listener}!!!`);
  await page.click("#submitGuess");

  await expect(page.locator("#feedback")).toHaveText("Nice! Now find the missing word.");
  await expect(page.locator("#labelSpeaker")).toContainText("✅");
  await expect(page.locator("#labelListener")).toContainText("✅");
  await expect(page.locator("#labelBonus")).not.toContainText("❌");
  await expect(page.locator("#labelBonus")).not.toContainText("✅");
  await expect(page.locator("#inputBonus")).not.toHaveClass(/wrong|correct/);
  await expect(page.locator("#bonusHint")).toHaveCount(testPuzzleHasBonusHint ? 1 : 0);
});

test("full game: clear win (reload persists state)", async ({ page }) => {
  await openGame(page, { easyMode: false });
  await expect(page.locator("#bonusHint")).toHaveCount(0);
  await expect(page.locator("#refLine")).toHaveText("");

  await page.fill("#inputSpeaker", enAnswer.speaker);
  await page.fill("#inputListener", enAnswer.listener);
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

test("bonus hint in stage two reveals hint, stays visible after solve, and is reflected in share", async ({ page }) => {
  await openGame(page, { easyMode: false, puzzleId: hintPuzzleId, lang: "en", captureClipboard: true });
  await expect(page.locator("#bonusHint")).toHaveCount(0);
  await expect(page.locator("#refLine")).toHaveText("");

  await page.fill("#inputSpeaker", hintEnAnswer.speaker);
  await page.fill("#inputListener", hintEnAnswer.listener);
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

test("full game: mistakes and win", async ({ page }) => {
  await openGame(page, { easyMode: false });

  await page.fill("#inputSpeaker", WRONG_TEXT);
  await page.fill("#inputListener", WRONG_TEXT);
  await page.click("#submitGuess");
  await expect(page.locator("#feedback")).toHaveText("Not quite. Try again.");

  await page.fill("#inputSpeaker", enAnswer.speaker);
  await page.fill("#inputListener", enAnswer.listener);
  await page.click("#submitGuess");
  await expect(page.locator("#feedback")).toHaveText("Nice! Now find the missing word.");

  await page.fill("#inputBonus", WRONG_TEXT);
  await page.click("#submitGuess");
  await expect(page.locator("#feedback")).toHaveText("Nice! Now find the missing word.");
  await expect(page.getByText(`Status: ${hardSuccessMark}${hardSuccessMark}✴️⬜`)).toBeVisible();
  await expect(page.locator("#inputBonus")).toHaveClass(/wrong/);
  await expect(page.locator("#labelBonus")).toContainText("❌");

  await page.fill("#inputBonus", enAnswer.bonus);
  await page.click("#submitGuess");

  await expect(page.locator("#feedback")).toHaveText("Solved.");
  await expect(page.getByText("Tries: 3/5")).toBeVisible();
});

test("full game: lose", async ({ page }) => {
  await openGame(page, { easyMode: false });

  await page.fill("#inputSpeaker", WRONG_TEXT);
  await page.fill("#inputListener", WRONG_TEXT);
  const quoteBeforeLose = await page.locator("#fullQuote").innerText();
  expect(normalize(quoteBeforeLose, "en")).not.toContain(normalize(enAnswer.bonus, "en"));
  for (let idx = 0; idx < 5; idx += 1) {
    await page.click("#submitGuess");
  }

  await expect(page.locator("#feedback")).toHaveText("No tries left.");
  await expect(page.getByText("Tries: 5/5")).toBeVisible();
  const quoteAfterLose = await page.locator("#fullQuote").innerText();
  expect(normalize(quoteAfterLose, "en")).toContain(normalize(enAnswer.bonus, "en"));
  await expect(page.locator("#submitGuess")).toBeDisabled();
});

test("easy mode: clear win", async ({ page }) => {
  await openGame(page);

  await selectAnswerOption(page.locator("#inputSpeaker"), enAnswer.speaker, "en");
  await selectAnswerOption(page.locator("#inputListener"), enAnswer.listener, "en");
  await page.click("#submitGuess");
  await expect(page.locator("#feedback")).toHaveText("Nice! Now find the missing word.");

  await page.fill("#inputBonus", enAnswer.bonus);
  await page.click("#submitGuess");

  await expect(page.locator("#feedback")).toHaveText("Solved.");
  await expect(page.getByText("Tries: 1/5")).toBeVisible();
  await expect(page.locator("#submitGuess")).toBeDisabled();
});

test("easy mode canonicalizes divine speaker options to God and accepts them", async ({ page }) => {
  await openGame(page, { puzzleId: divinePuzzleId, easyMode: true, lang: "en" });

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

test("hebrew easy mode canonicalizes divine speaker options to אֱלֹהִים and accepts them", async ({ page }) => {
  await openGame(page, { puzzleId: divineHePuzzleId, easyMode: true, lang: "he" });

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

test("easy mode: mistakes and win", async ({ page }) => {
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

  await page.fill("#inputBonus", enAnswer.bonus);
  await page.click("#submitGuess");

  await expect(page.locator("#feedback")).toHaveText("Solved.");
  await expect(page.getByText("Tries: 3/5")).toBeVisible();
});

test("easy mode: lose", async ({ page }) => {
  await openGame(page);

  const wrongSpeaker = await pickWrongOption(page.locator("#inputSpeaker"), enAnswer.speaker, "en");
  const wrongListener = await pickWrongOption(page.locator("#inputListener"), enAnswer.listener, "en");

  await page.selectOption("#inputSpeaker", wrongSpeaker);
  await page.selectOption("#inputListener", wrongListener);

  for (let idx = 0; idx < 5; idx += 1) {
    await page.click("#submitGuess");
  }

  await expect(page.locator("#feedback")).toHaveText("No tries left.");
  await expect(page.getByText("Tries: 5/5")).toBeVisible();
  await expect(page.locator("#submitGuess")).toBeDisabled();
});

test("share copies result text", async ({ page }) => {
  await openGame(page, { easyMode: false, captureClipboard: true });

  await page.fill("#inputSpeaker", WRONG_TEXT);
  await page.fill("#inputListener", WRONG_TEXT);
  await page.click("#submitGuess");

  await page.getByRole("button", { name: "Share result" }).click();
  await expect(page.locator(".share-note")).toHaveText("Result copied.");

  const copiedText = await page.evaluate(() => (globalThis as { __copiedText?: string }).__copiedText ?? "");
  expect(copiedText).toContain("Vayomer");
  expect(copiedText).toContain("http://localhost:4173/");
});

test("about page opens and returns to puzzle", async ({ page }) => {
  await openGame(page);

  await page.getByRole("link", { name: "About & sources" }).click();
  await expect(page).toHaveURL(/#about$/);
  await expect(page.getByRole("heading", { name: "About Vayomer" })).toBeVisible();
  await expect(page.getByText("Source Material")).toBeVisible();

  await page.locator("#topBackButton").click();
  await expect(page.locator("#puzzleCard")).toBeVisible();
});

test("how-to example opens from ❓, starts with partial correctness, and can be solved", async ({ page }) => {
  await openGame(page, { lang: "en" });

  await page.getByRole("button", { name: "Open how to play example" }).click();
  await expect(page).toHaveURL(/#example$/);
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

test("language switch updates UI and keeps selected puzzle", async ({ page }) => {
  await openGame(page, { lang: "en" });

  await page.getByRole("button", { name: "Switch language to HE" }).click();

  await expect(page.locator("html")).toHaveAttribute("lang", "he");
  await expect(page.locator("#submitGuess")).toHaveText("בדיקה");

  const searchParams = new URL(page.url()).searchParams;
  expect(searchParams.get("puzzle")).toBe(puzzleId);
});

test("hebrew full game flow", async ({ page }) => {
  await openGame(page, { lang: "he", easyMode: false });

  await page.fill("#inputSpeaker", heAnswer.speaker);
  await page.fill("#inputListener", `${heAnswer.listener}!!!`);
  await page.click("#submitGuess");
  await expect(page.locator("#feedback")).toHaveText("יפה! עכשיו מצאו את המילה החסרה.");

  await page.fill("#inputBonus", heAnswer.bonus);
  await page.click("#submitGuess");

  await expect(page.locator("#feedback")).toHaveText("נכון.");
  await expect(page.getByText("ניסיונות: 1/5")).toBeVisible();
  await expect(page.locator("#submitGuess")).toBeDisabled();
});
