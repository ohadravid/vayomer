import type { CSSProperties } from "react";
import { useTranslation } from "react-i18next";
import {
  bonusWordLength,
  sanitizeBonusGuess,
  scoreBonusGuess,
  splitBonusCharacters,
  type BonusCharacterState,
} from "../lib/bonusWord";
import type { Lang } from "../types";

type FeedbackState = "correct" | "wrong" | "";

type Props = {
  id: string;
  value: string;
  answer: string;
  lang: Lang;
  disabled: boolean;
  feedbackState: FeedbackState;
  onChange: (value: string) => void;
};

export function BonusWordInput({ id, value, answer, lang, disabled, feedbackState, onChange }: Props) {
  const { t } = useTranslation();
  const answerLength = bonusWordLength(answer);
  const displayValue = sanitizeBonusGuess(value, answer);
  const characters = splitBonusCharacters(displayValue);
  const scoredCharacters: BonusCharacterState[] =
    feedbackState === "correct"
      ? Array.from<BonusCharacterState>({ length: answerLength }).fill("correct")
      : feedbackState === "wrong"
        ? scoreBonusGuess(displayValue, answer, lang)
        : Array.from<BonusCharacterState>({ length: answerLength }).fill("absent");
  const feedbackCounts = scoredCharacters.reduce(
    (counts, state, index) => {
      if (!characters[index] || feedbackState === "") return counts;
      if (state === "correct") counts.correct += 1;
      if (state === "present") counts.present += 1;
      return counts;
    },
    { correct: 0, present: 0 }
  );
  const helpText =
    feedbackState === "correct"
      ? t("guessForm.bonusCorrect")
      : feedbackState === "wrong"
        ? t("guessForm.bonusCharacterFeedback", feedbackCounts)
        : t("guessForm.bonusLengthHint", { count: answerLength });
  const maximumRowWidth = answerLength * 2.75 + Math.max(0, answerLength - 1) * 0.25;
  const style = {
    "--bonus-character-count": answerLength,
    "--bonus-row-max-width": `${maximumRowWidth}rem`,
  } as CSSProperties;

  return (
    <div
      className={["bonus-word-control", feedbackState ? `is-${feedbackState}` : ""].filter(Boolean).join(" ")}
      style={style}
      dir={lang === "he" ? "rtl" : "ltr"}
    >
      <div className="bonus-character-grid" aria-hidden="true">
        {Array.from({ length: answerLength }, (_, index) => {
          const state = feedbackState ? scoredCharacters[index] : "";
          return (
            <span className={["bonus-character-tile", state].filter(Boolean).join(" ")} key={index}>
              {characters[index] ?? ""}
            </span>
          );
        })}
      </div>
      <input
        id={id}
        className={["bonus-native-input", feedbackState].filter(Boolean).join(" ")}
        type="text"
        inputMode="text"
        enterKeyHint="done"
        autoComplete="off"
        autoCapitalize="none"
        autoCorrect="off"
        spellCheck={false}
        value={displayValue}
        disabled={disabled}
        aria-describedby={`${id}Help`}
        aria-invalid={feedbackState === "wrong"}
        onChange={(event) => onChange(sanitizeBonusGuess(event.target.value, answer))}
      />
      <span id={`${id}Help`} className="sr-only" aria-live="polite">
        {helpText}
      </span>
    </div>
  );
}
