import type { Lang } from "../types";

export type BonusCharacterState = "correct" | "present" | "absent";

const BONUS_CHARACTER_PATTERN = /[\p{L}'’]/u;

export function splitBonusCharacters(value: string): string[] {
  return Array.from(value.normalize("NFD"))
    .filter((character) => BONUS_CHARACTER_PATTERN.test(character))
    .map((character) => (character === "’" ? "'" : character));
}

export function bonusWordLength(value: string): number {
  return splitBonusCharacters(value).length;
}

export function sanitizeBonusGuess(value: string, answer: string): string {
  return splitBonusCharacters(value).slice(0, bonusWordLength(answer)).join("");
}

export function isBonusGuessComplete(guess: string, answer: string): boolean {
  const expectedLength = bonusWordLength(answer);
  return expectedLength > 0 && bonusWordLength(guess) === expectedLength;
}

function comparableCharacter(character: string, lang: Lang): string {
  return character.toLocaleLowerCase(lang === "he" ? "he-IL" : "en-US");
}

export function scoreBonusGuess(guess: string, answer: string, lang: Lang): BonusCharacterState[] {
  const guessCharacters = splitBonusCharacters(guess);
  const answerCharacters = splitBonusCharacters(answer);
  const states = Array.from<BonusCharacterState>({ length: answerCharacters.length }).fill("absent");
  const remaining = new Map<string, number>();

  for (let index = 0; index < answerCharacters.length; index += 1) {
    const guessCharacter = guessCharacters[index];
    const answerCharacter = comparableCharacter(answerCharacters[index], lang);

    if (guessCharacter && comparableCharacter(guessCharacter, lang) === answerCharacter) {
      states[index] = "correct";
      continue;
    }

    remaining.set(answerCharacter, (remaining.get(answerCharacter) ?? 0) + 1);
  }

  for (let index = 0; index < answerCharacters.length; index += 1) {
    if (states[index] === "correct") continue;
    const guessCharacter = guessCharacters[index];
    if (!guessCharacter) continue;

    const comparableGuess = comparableCharacter(guessCharacter, lang);
    const available = remaining.get(comparableGuess) ?? 0;
    if (available === 0) continue;

    states[index] = "present";
    remaining.set(comparableGuess, available - 1);
  }

  return states;
}

export function bonusGuessMatches(guess: string, answer: string, lang: Lang): boolean {
  return isBonusGuessComplete(guess, answer) && scoreBonusGuess(guess, answer, lang).every((state) => state === "correct");
}
