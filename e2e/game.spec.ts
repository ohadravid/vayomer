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
  };
  he: {
    speaker: string;
    listener: string;
    bonus?: string | null;
  };
};

type GameOpenOptions = {
  easyMode?: boolean;
  captureClipboard?: boolean;
  lang?: "en" | "he";
};

const WRONG_TEXT = "not-the-answer";
const dailyJsonPath = fileURLToPath(new URL("../data/daily.json", import.meta.url));
const parsedDailyJson = JSON.parse(fs.readFileSync(dailyJsonPath, "utf8")) as { items?: PuzzleItem[] } | PuzzleItem[];
const dailyItems = Array.isArray(parsedDailyJson) ? parsedDailyJson : (parsedDailyJson.items ?? []);
const testPuzzle = dailyItems.find((item) => !!item.en.bonus?.trim() && !!item.he.bonus?.trim());

if (!testPuzzle) {
  throw new Error("Expected a puzzle with both EN and HE bonus answers in data/daily.json.");
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
  params.set("puzzle", puzzleId);
  params.set("lng", options.lang ?? "en");

  if (options.easyMode) {
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

test("full game: clear win (reload persists state)", async ({ page }) => {
  await openGame(page);

  await page.fill("#inputSpeaker", enAnswer.speaker);
  await page.fill("#inputListener", enAnswer.listener);
  await page.click("#submitGuess");

  await expect(page.locator("#feedback")).toHaveText("Nice! Now find the missing word.");
  await expect(page.getByText("Tries: 1/5")).toBeVisible();

  await page.reload();
  await expect(page.locator("#guessForm")).toBeVisible();
  await expect(page.locator("#inputSpeaker")).toHaveValue(enAnswer.speaker);
  await expect(page.locator("#inputListener")).toHaveValue(enAnswer.listener);
  await expect(page.locator("#feedback")).toHaveText("Nice! Now find the missing word.");
  await expect(page.getByText("Tries: 1/5")).toBeVisible();

  await page.fill("#inputBonus", enAnswer.bonus);
  await page.click("#submitGuess");

  await expect(page.locator("#feedback")).toHaveText("Solved.");
  await expect(page.getByText("Tries: 2/5")).toBeVisible();
  await expect(page.locator("#submitGuess")).toBeDisabled();
});

test("full game: mistakes and win", async ({ page }) => {
  await openGame(page);

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

  await page.fill("#inputBonus", enAnswer.bonus);
  await page.click("#submitGuess");

  await expect(page.locator("#feedback")).toHaveText("Solved.");
  await expect(page.getByText("Tries: 4/5")).toBeVisible();
});

test("full game: lose", async ({ page }) => {
  await openGame(page);

  await page.fill("#inputSpeaker", WRONG_TEXT);
  await page.fill("#inputListener", WRONG_TEXT);
  for (let idx = 0; idx < 5; idx += 1) {
    await page.click("#submitGuess");
  }

  await expect(page.locator("#feedback")).toHaveText("No tries left.");
  await expect(page.getByText("Tries: 5/5")).toBeVisible();
  await expect(page.locator("#submitGuess")).toBeDisabled();
});

test("easy mode: clear win", async ({ page }) => {
  await openGame(page, { easyMode: true });

  await selectAnswerOption(page.locator("#inputSpeaker"), enAnswer.speaker, "en");
  await selectAnswerOption(page.locator("#inputListener"), enAnswer.listener, "en");
  await page.click("#submitGuess");
  await expect(page.locator("#feedback")).toHaveText("Nice! Now find the missing word.");

  await page.fill("#inputBonus", enAnswer.bonus);
  await page.click("#submitGuess");

  await expect(page.locator("#feedback")).toHaveText("Solved.");
  await expect(page.getByText("Tries: 2/5")).toBeVisible();
  await expect(page.locator("#submitGuess")).toBeDisabled();
});

test("easy mode: mistakes and win", async ({ page }) => {
  await openGame(page, { easyMode: true });

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

  await page.fill("#inputBonus", enAnswer.bonus);
  await page.click("#submitGuess");

  await expect(page.locator("#feedback")).toHaveText("Solved.");
  await expect(page.getByText("Tries: 4/5")).toBeVisible();
});

test("easy mode: lose", async ({ page }) => {
  await openGame(page, { easyMode: true });

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
  await openGame(page, { captureClipboard: true });

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
  await openGame(page, { lang: "he" });

  await page.fill("#inputSpeaker", heAnswer.speaker);
  await page.fill("#inputListener", heAnswer.listener);
  await page.click("#submitGuess");
  await expect(page.locator("#feedback")).toHaveText("יפה! עכשיו מצאו את המילה החסרה.");

  await page.fill("#inputBonus", heAnswer.bonus);
  await page.click("#submitGuess");

  await expect(page.locator("#feedback")).toHaveText("נכון.");
  await expect(page.getByText("ניסיונות: 2/5")).toBeVisible();
  await expect(page.locator("#submitGuess")).toBeDisabled();
});
