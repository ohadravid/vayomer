import { expect, test, type Locator, type Page } from "@playwright/test";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import { normalize } from "../src/lib/format";
import type { Lang } from "../src/types";

type PuzzleItem = {
  id: string;
  en: {
    speaker: string;
    listener: string;
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
    speaker: string;
    listener: string;
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
const dailyJsonPath = fileURLToPath(new URL("../data/daily.json", import.meta.url));
const parsedDailyJson = JSON.parse(fs.readFileSync(dailyJsonPath, "utf8")) as { items?: PuzzleItem[] } | PuzzleItem[];
const dailyItems = Array.isArray(parsedDailyJson) ? parsedDailyJson : (parsedDailyJson.items ?? []);

function hasEasyModeDistractors(item: PuzzleItem): boolean {
  const sameBook = dailyItems.filter((candidate) => candidate.en.book === item.en.book && candidate.he.book === item.he.book);
  const normalizedSpeaker = normalize(item.en.speaker, "en");
  const normalizedListener = normalize(item.en.listener, "en");
  const hasSpeakerAlternative = sameBook.some((candidate) => normalize(candidate.en.speaker, "en") !== normalizedSpeaker);
  const hasListenerAlternative = sameBook.some((candidate) => normalize(candidate.en.listener, "en") !== normalizedListener);
  return hasSpeakerAlternative && hasListenerAlternative;
}

const testPuzzle = dailyItems.find(
  (item) => !!item.en.bonus?.trim() && !!item.he.bonus?.trim() && hasEasyModeDistractors(item)
);

if (!testPuzzle) {
  throw new Error("Expected a puzzle with EN/HE bonus answers and easy-mode distractors in data/daily.json.");
}

const puzzleId = testPuzzle.id;
const enAnswer = {
  speaker: testPuzzle.en.speaker,
  listener: testPuzzle.en.listener,
  bonus: testPuzzle.en.bonus!.trim(),
};
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
  throw new Error("Expected at least one puzzle with EN/HE bonus_hint quotes in data/daily.json.");
}

const hintPuzzleId = hintPuzzle.id;
const hintEnAnswer = {
  speaker: hintPuzzle.en.speaker,
  listener: hintPuzzle.en.listener,
  bonus: hintPuzzle.en.bonus!.trim(),
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

  if (options.easyMode === true) {
    params.set("easy", "0");
  } else if (options.easyMode === false) {
    params.set("easy", "1");
  }

  await page.goto(`/?${params.toString()}`);
  await expect(page.locator("#guessForm")).toBeVisible();
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

test("easy mode is default and easy=0 is canonicalized away", async ({ page }) => {
  await openGame(page);
  await expect(page.locator("#guessForm")).toBeVisible();

  const defaultTagName = await page.locator("#inputSpeaker").evaluate((node) => node.tagName);
  expect(defaultTagName).toBe("SELECT");
  expect(new URL(page.url()).searchParams.get("easy")).toBeNull();

  const legacyParams = new URLSearchParams({
    puzzle: puzzleId,
    lng: "en",
    easy: "0",
  });
  await page.goto(`/?${legacyParams.toString()}`);
  await expect(page.locator("#guessForm")).toBeVisible();
  await expect
    .poll(() => new URL(page.url()).searchParams.get("easy"))
    .toBeNull();

  const legacyTagName = await page.locator("#inputSpeaker").evaluate((node) => node.tagName);
  expect(legacyTagName).toBe("SELECT");
  expect(new URL(page.url()).searchParams.get("puzzle")).toBe(puzzleId);

  await openGame(page, { easyMode: false });
  const hardTagName = await page.locator("#inputSpeaker").evaluate((node) => node.tagName);
  expect(hardTagName).toBe("SELECT");
});

test("full game: clear win (reload persists state)", async ({ page }) => {
  await openGame(page, { easyMode: false });
  await expect(page.locator("#bonusHint")).toHaveCount(0);
  await expect(page.locator("#refLine")).toHaveText("");

  await selectAnswerOption(page.locator("#inputSpeaker"), enAnswer.speaker, "en");
  await selectAnswerOption(page.locator("#inputListener"), enAnswer.listener, "en");
  await page.click("#submitGuess");

  await expect(page.locator("#feedback")).toHaveText("Nice! Now find the missing word.");
  await expect(page.locator("#refLine")).not.toHaveText("");
  await expect(page.getByText("Tries: 0/5")).toBeVisible();

  await page.reload();
  await expect(page.locator("#guessForm")).toBeVisible();
  const persistedSpeaker = await page.locator("#inputSpeaker").inputValue();
  const persistedListener = await page.locator("#inputListener").inputValue();
  expect(normalize(persistedSpeaker, "en")).toBe(normalize(enAnswer.speaker, "en"));
  expect(normalize(persistedListener, "en")).toBe(normalize(enAnswer.listener, "en"));
  await expect(page.locator("#feedback")).toHaveText("Nice! Now find the missing word.");
  await expect(page.locator("#refLine")).not.toHaveText("");
  await expect(page.getByText("Tries: 0/5")).toBeVisible();

  await page.fill("#inputBonus", enAnswer.bonus);
  await page.click("#submitGuess");

  await expect(page.locator("#feedback")).toHaveText("Solved.");
  await expect(page.locator("#bonusHint")).toHaveCount(0);
  await expect(page.getByText("Tries: 1/5")).toBeVisible();
  await expect(page.locator("#submitGuess")).toBeDisabled();
});

test("bonus hint in stage two reveals hint, stays visible after solve, and is reflected in share", async ({ page }) => {
  await openGame(page, { easyMode: false, puzzleId: hintPuzzleId, lang: "en", captureClipboard: true });
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

test("full game: mistakes and win", async ({ page }) => {
  await openGame(page, { easyMode: false });

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

test("full game: lose", async ({ page }) => {
  await openGame(page, { easyMode: false });

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

  const wrongSpeaker = await pickWrongOption(page.locator("#inputSpeaker"), enAnswer.speaker, "en");
  const wrongListener = await pickWrongOption(page.locator("#inputListener"), enAnswer.listener, "en");
  await page.selectOption("#inputSpeaker", wrongSpeaker);
  await page.selectOption("#inputListener", wrongListener);
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

  await page.getByRole("link", { name: "Back to puzzle" }).click();
  await expect(page.locator("#puzzleCard")).toBeVisible();
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
