import type { GuessResult } from "../types";

type BuildShareTextArgs = {
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

function cellMark(ok: boolean): string {
  return ok ? "🟩" : "⬛";
}

function attemptRow(attempt: GuessResult, bonusRequired: boolean): string {
  const speaker = cellMark(attempt.speakerOk);
  const listener = cellMark(attempt.listenerOk);
  if (!bonusRequired) return `${speaker}${listener}`;
  const coreSolved = attempt.speakerOk && attempt.listenerOk;
  const bonus = coreSolved ? cellMark(attempt.bonusOk) : "⬜";
  return `${speaker}${listener}${bonus}`;
}

export function buildShareText(args: BuildShareTextArgs): string {
  const { attempts, solved, bonusRequired, maxTries, date, gameUrl } = args;
  const score = solved ? `${Math.min(attempts.length, maxTries)}/${maxTries}` : `X/${maxTries}`;
  const title = `Vayomer ${formatShareDate(date)} ${score}`;
  const fallbackRow = bonusRequired ? "⬜⬜⬜" : "⬜⬜";
  const rows = attempts.length > 0 ? attempts.map((attempt) => attemptRow(attempt, bonusRequired)) : [fallbackRow];
  const lines = [title, "", ...rows];
  if (gameUrl) lines.push(gameUrl);
  return lines.join("\n");
}
