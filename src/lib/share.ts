import type { GuessResult } from "../types";
import { doesAttemptCountAsTry } from "./gameState";

type BuildShareTextArgs = {
  title: string;
  attempts: GuessResult[];
  solved: boolean;
  bonusRequired: boolean;
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

function attemptRow(attempt: GuessResult, bonusRequired: boolean): string {
  const speaker = attempt.speakerOk ? "✅" : "❌";
  const listener = attempt.listenerOk ? "✅" : "❌";
  if (!bonusRequired) return `${speaker}${listener}`;
  const coreSolved = attempt.speakerOk && attempt.listenerOk;
  const bonus = coreSolved ? (attempt.bonusOk ? "✳️" : "✡️") : "⬜";
  return `${speaker}${listener}${bonus}`;
}

export function buildShareText(args: BuildShareTextArgs): string {
  const { title, attempts, solved, bonusRequired, maxTries, date, gameUrl } = args;
  const countedAttempts = attempts.filter(doesAttemptCountAsTry);
  const score = solved ? `${Math.min(countedAttempts.length, maxTries)}/${maxTries}` : `X/${maxTries}`;
  const header = `${title} ${formatShareDate(date)} ${score}`;
  const fallbackRow = bonusRequired ? "⬜⬜⬜" : "⬜⬜";
  const rows = countedAttempts.length > 0 ? countedAttempts.map((attempt) => attemptRow(attempt, bonusRequired)) : [fallbackRow];
  const lines = [header, "", ...rows];
  if (gameUrl) lines.push(gameUrl);
  return lines.join("\n");
}
