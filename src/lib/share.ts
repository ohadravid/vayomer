import type { GuessResult } from "../types";
import { doesAttemptCountAsTry } from "./gameState";

type BuildShareTextArgs = {
  title: string;
  attempts: GuessResult[];
  solved: boolean;
  bonusRequired: boolean;
  hintUsed?: boolean;
  successMark?: string;
  maxTries: number;
  date: Date;
  gameUrl?: string;
};

function formatShareDate(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function attemptRow(attempt: GuessResult, bonusRequired: boolean, hintUsed: boolean, successMark: string): string {
  const speaker = attempt.speakerOk ? successMark : "❌";
  const listener = attempt.listenerOk ? successMark : "❌";
  if (!bonusRequired) return `${speaker}${listener}`;
  const coreSolved = attempt.speakerOk && attempt.listenerOk;
  const bonus = coreSolved ? (attempt.bonusOk ? "✳️" : "✴️") : "⬜";
  const hint = hintUsed ? "💡" : "⬜";
  return `${speaker}${listener}${bonus}${hint}`;
}

export function buildShareText(args: BuildShareTextArgs): string {
  const { title, attempts, solved, bonusRequired, hintUsed = false, successMark = "✅", maxTries, date, gameUrl } = args;
  const countedAttempts = attempts.filter(doesAttemptCountAsTry);
  const score = solved ? `${Math.min(countedAttempts.length, maxTries)}/${maxTries}` : `X/${maxTries}`;
  const header = `${title} ${formatShareDate(date)} ${score}`;
  const fallbackRow = bonusRequired ? `⬜⬜⬜${hintUsed ? "💡" : "⬜"}` : "⬜⬜";
  const rows =
    countedAttempts.length > 0
      ? countedAttempts.map((attempt) => attemptRow(attempt, bonusRequired, hintUsed, successMark))
      : [fallbackRow];
  const lines = [header, "", ...rows];
  if (gameUrl) lines.push(gameUrl);
  return lines.join("\n");
}
