import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { buildMultipleChoiceOptions, resolveChoicePoolsForDifficulty } from "../lib/easyMode";
import { answersMatch } from "../lib/answerMatcher";
import { bonusGuessMatches, isBonusGuessComplete } from "../lib/bonusWord";
import {
  countTryAttempts,
  deriveGameState,
  doesAttemptCountAsTry,
  isCoreSolved,
  isFullySolved,
  isStageTwoOpen,
} from "../lib/gameState";
import {
  formatDate,
  maskHardWord,
  pickHardWordPlaceholderForId,
  renderQuoteText,
} from "../lib/format";
import { getLanguageDirection, getLanguageFromI18n } from "../lib/language";
import { MAX_TOTAL_TRIES } from "../lib/gameRules";
import { buildShareText } from "../lib/share";
import { PuzzleCard, sourceEmojiFromPuzzle } from "./PuzzleCard";
import { GuessForm } from "./GuessForm";
import {
  GameState,
  type GuessEditState,
  type GuessField,
  type GuessResult,
  type GuessValues,
  type HintSourceRef,
  type PersistedGameFields,
  type PuzzleItem,
} from "../types";

type Props = {
  puzzle: PuzzleItem;
  onReveal: () => void;
  onClear: () => void;
  revealed: boolean;
  onPersist?: (state: PersistedGameFields) => void;
  initial?: Omit<PersistedGameFields, "hintRevealed"> & { hintRevealed?: boolean };
  syncDocumentDirection?: boolean;
  shareEnabled?: boolean;
  upperCornerLabel?: string;
  archiveTodayHref?: string;
};

type PersistableState = PersistedGameFields;

const EMPTY_GUESS_VALUES: GuessValues = {
  speaker: "",
  listener: "",
  portion: "",
  bonus: "",
};
const ALL_CORRECT_RESULT: GuessResult = {
  speakerOk: true,
  listenerOk: true,
  portionOk: true,
  bonusOk: true,
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

function buildPersistableState(initial?: Props["initial"]): PersistableState {
  return {
    speaker: initial?.speaker ?? "",
    listener: initial?.listener ?? "",
    portion: initial?.portion ?? "",
    bonus: initial?.bonus ?? "",
    hintRevealed: initial?.hintRevealed ?? false,
    attempts: initial?.attempts ?? [],
  };
}

function signatureFromState(state: PersistableState): string {
  return JSON.stringify(state);
}

function toInt(value: number | undefined): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return Math.floor(value);
  return null;
}

function formatHintSourceLine(source: HintSourceRef | null | undefined): string {
  if (!source) return "";
  const book = typeof source.book === "string" ? source.book.trim() : "";
  const chapter = toInt(source.chapter);
  const start = toInt(source.start);
  const end = toInt(source.end);

  const range =
    chapter !== null && start !== null
      ? `${chapter}:${end !== null && end !== start ? `${start}-${end}` : start}`
      : "";

  return [book, range].filter(Boolean).join(" ");
}

function buildShareUrl(): string | undefined {
  if (typeof window === "undefined") return undefined;
  if (window.location.protocol !== "http:" && window.location.protocol !== "https:") return undefined;
  const { origin, pathname, search, hash } = window.location;
  return `${origin}${pathname}${search}${hash}`;
}

async function copyToClipboard(text: string): Promise<boolean> {
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Fall through to execCommand fallback.
    }
  }

  if (typeof document === "undefined") return false;
  try {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "true");
    textarea.style.position = "fixed";
    textarea.style.top = "-9999px";
    textarea.style.left = "-9999px";
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    textarea.setSelectionRange(0, textarea.value.length);
    const copied = document.execCommand("copy");
    document.body.removeChild(textarea);
    return copied;
  } catch {
    return false;
  }
}

export function PuzzleView({
  puzzle,
  revealed,
  onReveal,
  onClear,
  onPersist,
  initial,
  syncDocumentDirection = true,
  shareEnabled = true,
  upperCornerLabel = "",
  archiveTodayHref,
}: Props) {
  const { t, i18n } = useTranslation();
  const lang = getLanguageFromI18n(i18n);
  const [speaker, setSpeaker] = useState(initial?.speaker ?? EMPTY_GUESS_VALUES.speaker);
  const [listener, setListener] = useState(initial?.listener ?? EMPTY_GUESS_VALUES.listener);
  const [portion, setPortion] = useState(initial?.portion ?? EMPTY_GUESS_VALUES.portion);
  const [bonus, setBonus] = useState(initial?.bonus ?? EMPTY_GUESS_VALUES.bonus);
  const [bonusHintUsed, setBonusHintUsed] = useState(initial?.hintRevealed ?? false);
  const [hintRevealed, setHintRevealed] = useState(initial?.hintRevealed ?? false);
  const [attempts, setAttempts] = useState<GuessResult[]>(initial?.attempts ?? []);
  const [editedSinceCheck, setEditedSinceCheck] = useState<GuessEditState>(() => emptyEditedState());
  const [shareNotice, setShareNotice] = useState("");
  const persistRef = useRef<Props["onPersist"]>(onPersist);
  const hydratedStateSignatureRef = useRef(signatureFromState(buildPersistableState(initial)));
  const isHydratingRef = useRef(false);

  const dateLabel = useMemo(
    () => (archiveTodayHref ? t("puzzleView.archiveRiddle") : upperCornerLabel ? upperCornerLabel : formatDate(new Date(), lang)),
    [archiveTodayHref, lang, t, upperCornerLabel]
  );
  const bonusAnswer = puzzle[lang].bonus ?? "";
  const hintQuote = puzzle[lang].bonus_hint?.quote?.trim() ?? "";
  const hasBonusHint = hintQuote.length > 0;
  const placeholder = pickHardWordPlaceholderForId(puzzle.id);
  const maskedHintQuote = hasBonusHint ? maskHardWord(hintQuote, bonusAnswer, placeholder, lang) : "";
  const hintSourceLine = formatHintSourceLine(puzzle[lang].bonus_hint?.source);
  const bonusRequired = !!bonusAnswer;
  const bonusGuessComplete = isBonusGuessComplete(bonus, bonusAnswer);
  const result = attempts.length > 0 ? attempts[attempts.length - 1] : null;
  const triesUsed = countTryAttempts(attempts);
  const coreSolved = isCoreSolved(result);
  const gameState = deriveGameState({
    revealed,
    result,
    guesses: triesUsed,
    maxGuesses: MAX_TOTAL_TRIES,
    bonusRequired,
  });
  const answersRevealed = gameState === GameState.Failed;
  const stageTwoOpen = isStageTwoOpen(gameState) || coreSolved;
  const fullySolved = gameState === GameState.Solved;
  const bonusRevealed = fullySolved || answersRevealed;
  const quoteRevealed =
    stageTwoOpen || gameState === GameState.Failed;
  const sourceRevealed = stageTwoOpen;
  const displayValues: GuessValues = answersRevealed
    ? {
        speaker: puzzle[lang].speaker,
        listener: puzzle[lang].listener,
        portion,
        bonus,
      }
    : { speaker, listener, portion, bonus };
  const displayResult = answersRevealed ? ALL_CORRECT_RESULT : result;
  const coreFieldsLocked = stageTwoOpen || answersRevealed;
  const bonusRowVisible = stageTwoOpen || answersRevealed;
  const extraChecked = coreSolved || answersRevealed;
  const successMark = "✅";
  const failedBonusTry = bonusRequired
    ? attempts.some((attempt) => doesAttemptCountAsTry(attempt) && attempt.speakerOk && attempt.listenerOk && !attempt.bonusOk)
    : false;
  const hintQuoteContent = (() => {
    if (!hasBonusHint) return null;
    const quoteBody = renderQuoteText(bonusRevealed ? hintQuote : maskedHintQuote, bonusRevealed ? "" : placeholder, "hint");
    return bonusRevealed ? quoteBody : <span className="quote-hidden veil">{quoteBody}</span>;
  })();
  const showHintQuote = stageTwoOpen && hasBonusHint && (hintRevealed || bonusHintUsed);
  const canShare = shareEnabled && attempts.length > 0;
  const sourceEmoji = sourceEmojiFromPuzzle(puzzle);
  const gameFinished = gameState === GameState.Solved || gameState === GameState.Revealed || gameState === GameState.Failed;
  const bonusSubmissionBlocked = stageTwoOpen && bonusRequired && !bonusGuessComplete;
  const submitDisabled = gameFinished || bonusSubmissionBlocked;
  const feedback = useMemo(() => {
    if (!result) return "";
    if (isFullySolved(result, bonusRequired)) return t("puzzleView.solved");
    if (gameState === GameState.Failed) return t("puzzleView.outOfTries");
    if (isCoreSolved(result)) return t("puzzleView.keepGoing");
    return t("puzzleView.retry");
  }, [result, bonusRequired, gameState, t]);
  const multipleChoiceOptions = useMemo(() => {
    const pools = resolveChoicePoolsForDifficulty({
      puzzle,
      lang,
    });
    return {
      speaker: buildMultipleChoiceOptions({
        answer: puzzle[lang].speaker,
        pool: pools.speaker,
        lang,
        seed: `${puzzle.id}:speaker`,
      }),
      listener: buildMultipleChoiceOptions({
        answer: puzzle[lang].listener,
        pool: pools.listener,
        lang,
        seed: `${puzzle.id}:listener`,
      }),
    };
  }, [puzzle, lang]);

  useEffect(() => {
    const nextValues = initialValues(initial);
    const nextAttempts = initial?.attempts ?? [];
    hydratedStateSignatureRef.current = signatureFromState(buildPersistableState(initial));
    isHydratingRef.current = true;
    setSpeaker(nextValues.speaker);
    setListener(nextValues.listener);
    setPortion(nextValues.portion);
    setBonus(nextValues.bonus);
    setBonusHintUsed(initial?.hintRevealed ?? false);
    setHintRevealed(initial?.hintRevealed ?? false);
    setAttempts(nextAttempts);
    setEditedSinceCheck(emptyEditedState());
    setShareNotice("");
  }, [
    initial?.speaker,
    initial?.listener,
    initial?.portion,
    initial?.bonus,
    initial?.hintRevealed,
    initial?.attempts,
    puzzle.id,
  ]);

  useEffect(() => {
    persistRef.current = onPersist;
  }, [onPersist]);

  useEffect(() => {
    if (!persistRef.current) return;
    const nextState: PersistableState = {
      speaker,
      listener,
      portion,
      bonus,
      hintRevealed,
      attempts,
    };
    const nextSignature = signatureFromState(nextState);
    if (isHydratingRef.current) {
      if (nextSignature === hydratedStateSignatureRef.current) {
        isHydratingRef.current = false;
      }
      return;
    }
    if (nextSignature === hydratedStateSignatureRef.current) return;
    persistRef.current(nextState);
  }, [speaker, listener, portion, bonus, bonusHintUsed, hintRevealed, attempts]);

  useEffect(() => {
    if (!syncDocumentDirection) return;
    const direction = getLanguageDirection(lang);
    document.documentElement.dir = direction;
    document.body.dir = direction;
  }, [lang, syncDocumentDirection]);

  const statusMarks = (() => {
    const hintMark = bonusHintUsed ? "💡" : "⬜";

    if (fullySolved) return `${successMark}${successMark}✳️${hintMark}`;
    if (failedBonusTry) return `${successMark}${successMark}✴️${hintMark}`;
    if (coreSolved) return `${successMark}${successMark}✡️${hintMark}`;
    if (!result) return `⬜⬜⬜${hintMark}`;
    const speakerMark = result.speakerOk ? successMark : "❌";
    const listenerMark = result.listenerOk ? successMark : "❌";
    return `${speakerMark}${listenerMark}⬜${hintMark}`;
  })();

  const shareUrl = buildShareUrl();
  const shareText = useMemo(() => {
    return buildShareText({
      title: t("app.title"),
      attempts,
      solved: fullySolved,
      bonusRequired,
      sourceEmoji,
      hintUsed: bonusHintUsed,
      successMark,
      maxTries: MAX_TOTAL_TRIES,
      date: new Date(),
      gameUrl: shareUrl,
    });
  }, [attempts, fullySolved, bonusRequired, sourceEmoji, bonusHintUsed, successMark, shareUrl, t, lang]);

  const checkGuess = () => {
    if (gameFinished || (stageTwoOpen && bonusRequired && !bonusGuessComplete)) return;
    setEditedSinceCheck(emptyEditedState());
    setShareNotice("");
    const speakerAnswer = puzzle[lang].speaker;
    const listenerAnswer = puzzle[lang].listener;

    const speakerOk = answersMatch(speaker, speakerAnswer, lang);
    const listenerOk = answersMatch(listener, listenerAnswer, lang);
    const bonusOk = bonusRequired ? bonusGuessMatches(bonus, bonusAnswer, lang) : true;
    const transitioningToMissingWord = bonusRequired && !stageTwoOpen && speakerOk && listenerOk && !bonusOk;

    const next = {
      speakerOk,
      listenerOk,
      portionOk: true,
      bonusOk,
      hintUsed: bonusHintUsed,
      countsAsTry: !transitioningToMissingWord,
    };
    setAttempts((prev) => [...prev, next]);

    if (isFullySolved(next, bonusRequired)) {
      onReveal();
    }
  };

  const clearLocal = () => {
    setSpeaker(EMPTY_GUESS_VALUES.speaker);
    setListener(EMPTY_GUESS_VALUES.listener);
    setPortion(EMPTY_GUESS_VALUES.portion);
    setBonus(EMPTY_GUESS_VALUES.bonus);
    setBonusHintUsed(false);
    setHintRevealed(false);
    setAttempts([]);
    setEditedSinceCheck(emptyEditedState());
    setShareNotice("");
    onClear();
  };

  const revealBonusHint = () => {
    if (!hasBonusHint) return;
    setBonusHintUsed(true);
    setHintRevealed(true);
  };

  const shareResult = async () => {
    if (!canShare) return;

    const copied = await copyToClipboard(shareText);
    if (copied) {
      setShareNotice(t("puzzleView.shareCopied"));
      return;
    }

    const sharePayload: ShareData = {
      title: t("app.title"),
      text: shareText,
    };
    if (shareUrl) sharePayload.url = shareUrl;

    if (typeof navigator !== "undefined" && typeof navigator.share === "function") {
      try {
        let payloadToShare: ShareData = sharePayload;
        if (typeof navigator.canShare === "function") {
          const candidates: ShareData[] = [sharePayload];
          if (shareUrl) candidates.push({ title: t("app.title"), text: shareText });
          candidates.push({ text: shareText });
          const supported = candidates.find((candidate) => navigator.canShare(candidate));
          if (!supported) {
            throw new Error("Share payload is not supported on this platform.");
          }
          payloadToShare = supported;
        }
        await navigator.share(payloadToShare);
        setShareNotice("");
        return;
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
      }
    }

    setShareNotice(t("puzzleView.shareFailed"));
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
        sourceRevealed={sourceRevealed}
        bonusRevealed={bonusRevealed}
        dateLabel={dateLabel}
        archiveTodayHref={archiveTodayHref}
        archiveTodayLabel={t("puzzleView.todayRiddle")}
        onClear={clearLocal}
      />
      <GuessForm
        choiceOptions={multipleChoiceOptions}
        values={displayValues}
        result={displayResult}
        editedSinceCheck={editedSinceCheck}
        coreSolved={coreFieldsLocked}
        showBonusRow={bonusRowVisible}
        extraChecked={extraChecked}
        bonusDisabled={revealed || answersRevealed || !bonusRequired}
        bonusAnswer={bonusAnswer}
        lang={lang}
        bonusStateOverride={gameState === GameState.Failed && bonusRequired ? "wrong" : undefined}
        bonusHintUsed={bonusHintUsed}
        showBonusHint={stageTwoOpen && hasBonusHint}
        showHintQuote={showHintQuote}
        hintQuoteContent={hintQuoteContent}
        hintSourceLine={hintSourceLine}
        onChange={handleChange}
        onSubmit={checkGuess}
        onShare={shareResult}
        onRevealBonusHint={revealBonusHint}
        canShare={canShare}
        showShare={shareEnabled}
        disabled={submitDisabled}
        feedback={feedback}
        shareNotice={shareNotice}
        triesUsed={triesUsed}
        maxTries={MAX_TOTAL_TRIES}
        statusMarks={statusMarks}
      />
    </>
  );
}
