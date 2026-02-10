import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { buildMultipleChoiceOptions } from "../lib/easyMode";
import { deriveGameState, isCoreSolved, isFullySolved, isStageTwoOpen } from "../lib/gameState";
import { normalize, formatDate } from "../lib/format";
import { getLanguageDirection, getLanguageFromI18n } from "../lib/language";
import { PuzzleCard } from "./PuzzleCard";
import { GuessForm } from "./GuessForm";
import { GameState, type EasyChoicePools, type GuessEditState, type GuessField, type GuessResult, type GuessValues, type PuzzleItem } from "../types";

const MAX_GUESSES = 3;

type Props = {
  puzzle: PuzzleItem;
  easyMode: boolean;
  choicePools?: EasyChoicePools;
  onReveal: () => void;
  onClear: () => void;
  revealed: boolean;
  onPersist?: (state: {
    speaker: string;
    listener: string;
    portion: string;
    bonus: string;
    result: GuessResult | null;
    guesses: number;
  }) => void;
  initial?: {
    speaker: string;
    listener: string;
    portion: string;
    bonus: string;
    result: GuessResult | null;
    guesses: number;
  };
  syncDocumentDirection?: boolean;
};

const EMPTY_GUESS_VALUES: GuessValues = {
  speaker: "",
  listener: "",
  portion: "",
  bonus: "",
};

function emptyEditedState(): GuessEditState {
  return {
    speaker: false,
    listener: false,
    portion: false,
    bonus: false,
  };
}

function initialValues(initial?: Props["initial"]): GuessValues {
  return {
    speaker: initial?.speaker ?? "",
    listener: initial?.listener ?? "",
    portion: initial?.portion ?? "",
    bonus: initial?.bonus ?? "",
  };
}

export function PuzzleView({
  puzzle,
  easyMode,
  choicePools,
  revealed,
  onReveal,
  onClear,
  onPersist,
  initial,
  syncDocumentDirection = true,
}: Props) {
  const { t, i18n } = useTranslation();
  const lang = getLanguageFromI18n(i18n);
  const [speaker, setSpeaker] = useState(initial?.speaker ?? EMPTY_GUESS_VALUES.speaker);
  const [listener, setListener] = useState(initial?.listener ?? EMPTY_GUESS_VALUES.listener);
  const [portion, setPortion] = useState(initial?.portion ?? EMPTY_GUESS_VALUES.portion);
  const [bonus, setBonus] = useState(initial?.bonus ?? EMPTY_GUESS_VALUES.bonus);
  const [result, setResult] = useState<GuessResult | null>(initial?.result ?? null);
  const [guesses, setGuesses] = useState(initial?.guesses ?? 0);
  const [extraChecked, setExtraChecked] = useState(false);
  const [editedSinceCheck, setEditedSinceCheck] = useState<GuessEditState>(() => emptyEditedState());
  const [feedback, setFeedback] = useState("");

  const dateLabel = useMemo(() => formatDate(new Date(), lang), [lang]);
  const bonusAnswer = puzzle[lang].bonus ?? "";
  const bonusRequired = !!bonusAnswer;
  const coreSolved = isCoreSolved(result);
  const gameState = deriveGameState({
    revealed,
    result,
    guesses,
    maxGuesses: MAX_GUESSES,
    bonusRequired,
  });
  const stageTwoOpen = isStageTwoOpen(gameState);
  const quoteRevealed = stageTwoOpen;
  const fullySolved = gameState === GameState.Solved;
  const submitDisabled = gameState === GameState.Solved || gameState === GameState.Revealed || gameState === GameState.Failed;
  const multipleChoiceOptions = useMemo(() => {
    if (!easyMode) return null;
    return {
      speaker: buildMultipleChoiceOptions({
        answer: puzzle[lang].speaker,
        pool: choicePools?.speaker ?? [],
        lang,
        seed: `${puzzle.id}:speaker`,
      }),
      listener: buildMultipleChoiceOptions({
        answer: puzzle[lang].listener,
        pool: choicePools?.listener ?? [],
        lang,
        seed: `${puzzle.id}:listener`,
      }),
    };
  }, [easyMode, puzzle, choicePools, lang]);

  useEffect(() => {
    const nextValues = initialValues(initial);
    const nextResult = initial?.result ?? null;
    const nextGuesses = initial?.guesses ?? 0;
    setSpeaker(nextValues.speaker);
    setListener(nextValues.listener);
    setPortion(nextValues.portion);
    setBonus(nextValues.bonus);
    setResult(nextResult);
    setGuesses(nextGuesses);
    setEditedSinceCheck(emptyEditedState());
    const attemptedExtras = !!nextValues.bonus.trim() || !!nextResult?.bonusOk;
    const nextCoreSolved = isCoreSolved(nextResult);
    setExtraChecked(nextCoreSolved && attemptedExtras);
    if (isFullySolved(nextResult, bonusRequired)) {
      setFeedback(t("puzzleView.solved"));
    } else if (nextCoreSolved) {
      setFeedback(t("puzzleView.keepGoing"));
    } else if (nextGuesses > 0) {
      setFeedback(t("puzzleView.retry"));
    } else {
      setFeedback("");
    }
  }, [
    initial?.speaker,
    initial?.listener,
    initial?.portion,
    initial?.bonus,
    initial?.result,
    initial?.guesses,
    puzzle,
    bonusRequired,
    t,
  ]);

  useEffect(() => {
    if (!onPersist) return;
    onPersist({ speaker, listener, portion, bonus, result, guesses });
  }, [speaker, listener, portion, bonus, result, guesses, onPersist]);

  useEffect(() => {
    if (!syncDocumentDirection) return;
    const direction = getLanguageDirection(lang);
    document.body.classList.toggle("rtl", direction === "rtl");
  }, [lang, syncDocumentDirection]);

  const wrongGuesses = coreSolved ? Math.max(0, guesses - 1) : guesses;
  const statusMarks = (() => {
    if (fullySolved) return "✅✅✳️";
    if (revealed && coreSolved) return "✅✅✴️";
    if (coreSolved) return "✅✅✡️";
    if (!result) return "⬜⬜⬜";
    const speakerMark = result.speakerOk ? "✅" : "❌";
    const listenerMark = result.listenerOk ? "✅" : "❌";
    return `${speakerMark}${listenerMark}⬜`;
  })();

  const checkGuess = () => {
    if (submitDisabled) return;
    setEditedSinceCheck(emptyEditedState());
    const speakerAnswer = puzzle[lang].speaker;
    const listenerAnswer = puzzle[lang].listener;

    const speakerOk = normalize(speaker, lang) === normalize(speakerAnswer, lang);
    const listenerOk = normalize(listener, lang) === normalize(listenerAnswer, lang);
    const bonusOk = bonusRequired ? normalize(bonus, lang) === normalize(bonusAnswer, lang) : true;

    const next = { speakerOk, listenerOk, portionOk: true, bonusOk };
    setResult(next);
    const nextCoreSolved = isCoreSolved(next);
    setExtraChecked(nextCoreSolved);
    if (gameState === GameState.CoreGuess) {
      setGuesses((prev) => prev + 1);
    }

    if (isFullySolved(next, bonusRequired)) {
      setFeedback(t("puzzleView.solved"));
      onReveal();
      return;
    }
    if (nextCoreSolved) {
      setFeedback(t("puzzleView.keepGoing"));
      return;
    }
    setFeedback(t("puzzleView.retry"));
  };

  const clearLocal = () => {
    setSpeaker(EMPTY_GUESS_VALUES.speaker);
    setListener(EMPTY_GUESS_VALUES.listener);
    setPortion(EMPTY_GUESS_VALUES.portion);
    setBonus(EMPTY_GUESS_VALUES.bonus);
    setResult(null);
    setGuesses(0);
    setExtraChecked(false);
    setEditedSinceCheck(emptyEditedState());
    setFeedback("");
    onClear();
  };

  const handleChange = (field: GuessField, value: string) => {
    if (field === "speaker") setSpeaker(value);
    if (field === "listener") setListener(value);
    if (field === "portion") setPortion(value);
    if (field === "bonus") setBonus(value);
    setEditedSinceCheck((prev) => ({ ...prev, [field]: true }));
  };

  return (
    <>
      <PuzzleCard
        puzzle={puzzle}
        revealed={revealed}
        quoteRevealed={quoteRevealed}
        dateLabel={dateLabel}
        onClear={clearLocal}
      />
      <GuessForm
        easyMode={easyMode}
        choiceOptions={multipleChoiceOptions ?? undefined}
        values={{ speaker, listener, portion, bonus }}
        result={result}
        editedSinceCheck={editedSinceCheck}
        coreSolved={stageTwoOpen}
        showBonusRow={stageTwoOpen}
        extraChecked={extraChecked}
        bonusDisabled={revealed || !bonusRequired}
        onChange={handleChange}
        onSubmit={checkGuess}
        disabled={submitDisabled}
        feedback={feedback}
        wrongGuesses={wrongGuesses}
        statusMarks={statusMarks}
      />
    </>
  );
}
