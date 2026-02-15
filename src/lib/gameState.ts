import { GameState, type GuessResult } from "../types";

type DeriveGameStateArgs = {
  revealed: boolean;
  result: GuessResult | null;
  guesses: number;
  maxGuesses: number;
  bonusRequired: boolean;
};

const STAGE_TWO_STATES = new Set<GameState>([GameState.ExtraGuess, GameState.Solved, GameState.Revealed]);

export function doesAttemptCountAsTry(attempt: GuessResult): boolean {
  return attempt.countsAsTry !== false;
}

export function countTryAttempts(attempts: GuessResult[]): number {
  return attempts.reduce((count, attempt) => count + (doesAttemptCountAsTry(attempt) ? 1 : 0), 0);
}

export function isCoreSolved(result: GuessResult | null): boolean {
  return !!(result?.speakerOk && result?.listenerOk);
}

export function isFullySolved(result: GuessResult | null, bonusRequired: boolean): boolean {
  if (!result) return false;
  const bonusOk = bonusRequired ? result.bonusOk : true;
  return result.speakerOk && result.listenerOk && bonusOk;
}

export function deriveGameState(args: DeriveGameStateArgs): GameState {
  const { revealed, result, guesses, maxGuesses, bonusRequired } = args;

  if (isFullySolved(result, bonusRequired)) return GameState.Solved;
  if (revealed) return GameState.Revealed;
  if (guesses >= maxGuesses) return GameState.Failed;
  if (isCoreSolved(result)) return GameState.ExtraGuess;
  return GameState.CoreGuess;
}

export function isStageTwoOpen(state: GameState): boolean {
  return STAGE_TWO_STATES.has(state);
}
