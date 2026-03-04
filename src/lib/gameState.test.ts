import { describe, expect, it } from "vitest";
import { deriveGameState } from "./gameState";
import { GameState, type GuessResult } from "../types";

const CORE_SOLVED_BONUS_MISS: GuessResult = {
  speakerOk: true,
  listenerOk: true,
  portionOk: true,
  bonusOk: false,
};

describe("deriveGameState", () => {
  it("fails when tries are exhausted even if core is solved", () => {
    const state = deriveGameState({
      revealed: false,
      result: CORE_SOLVED_BONUS_MISS,
      guesses: 5,
      maxGuesses: 5,
      bonusRequired: true,
    });
    expect(state).toBe(GameState.Failed);
  });

  it("stays in extra-guess while tries remain", () => {
    const state = deriveGameState({
      revealed: false,
      result: CORE_SOLVED_BONUS_MISS,
      guesses: 4,
      maxGuesses: 5,
      bonusRequired: true,
    });
    expect(state).toBe(GameState.ExtraGuess);
  });

  it("remains solved when final guess includes bonus", () => {
    const state = deriveGameState({
      revealed: false,
      result: { ...CORE_SOLVED_BONUS_MISS, bonusOk: true },
      guesses: 5,
      maxGuesses: 5,
      bonusRequired: true,
    });
    expect(state).toBe(GameState.Solved);
  });
});
