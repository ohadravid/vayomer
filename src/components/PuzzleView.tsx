import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { buildMultipleChoiceOptions } from "../lib/easyMode";
import { countTryAttempts, deriveGameState, isCoreSolved, isFullySolved, isStageTwoOpen } from "../lib/gameState";
import { normalize, formatDate, markVerseNumbers, maskHardWord, pickHardWordPlaceholderForId } from "../lib/format";
import { getLanguageDirection, getLanguageFromI18n } from "../lib/language";
import { MAX_TOTAL_TRIES } from "../lib/gameRules";
import { buildShareText } from "../lib/share";
import { PuzzleCard } from "./PuzzleCard";
import { GuessForm } from "./GuessForm";
import { GameState, type EasyChoicePools, type GuessEditState, type GuessField, type GuessResult, type GuessValues, type PuzzleItem } from "../types";

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
    // Kept as-is to stay compatible with existing persisted payloads.
    bookHintUsed: boolean;
    hintRevealed: boolean;
    attempts: GuessResult[];
  }) => void;
  initial?: {
    speaker: string;
    listener: string;
    portion: string;
    bonus: string;
    bookHintUsed?: boolean;
    hintRevealed?: boolean;
    attempts: GuessResult[];
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

function signatureFromInitial(initial?: Props["initial"]): string {
  return JSON.stringify({
    speaker: initial?.speaker ?? "",
    listener: initial?.listener ?? "",
    portion: initial?.portion ?? "",
    bonus: initial?.bonus ?? "",
    bookHintUsed: initial?.bookHintUsed ?? false,
    hintRevealed: initial?.hintRevealed ?? false,
    attempts: initial?.attempts ?? [],
  });
}

function signatureFromState(state: {
  speaker: string;
  listener: string;
  portion: string;
  bonus: string;
  bookHintUsed: boolean;
  hintRevealed: boolean;
  attempts: GuessResult[];
}): string {
  return JSON.stringify(state);
}

function toInt(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return Math.floor(value);
  if (typeof value === "string") {
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function formatHintSourceLine(
  source:
    | {
        book?: string;
        chapter?: number | string;
        start?: number | string;
        end?: number | string;
      }
    | null
    | undefined
): string {
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
  const [bonusHintUsed, setBonusHintUsed] = useState(initial?.bookHintUsed ?? false);
  const [hintRevealed, setHintRevealed] = useState(initial?.hintRevealed ?? false);
  const [attempts, setAttempts] = useState<GuessResult[]>(initial?.attempts ?? []);
  const [editedSinceCheck, setEditedSinceCheck] = useState<GuessEditState>(() => emptyEditedState());
  const [shareNotice, setShareNotice] = useState("");
  const persistRef = useRef<Props["onPersist"]>(onPersist);
  const hasPersistedHydratedStateRef = useRef(false);
  const initialSignature = signatureFromInitial(initial);

  const dateLabel = useMemo(() => formatDate(new Date(), lang), [lang]);
  const bonusAnswer = puzzle[lang].bonus ?? "";
  const hintQuote = puzzle[lang].bonus_hint?.quote?.trim() ?? "";
  const hasBonusHint = hintQuote.length > 0;
  const placeholder = pickHardWordPlaceholderForId(puzzle.id);
  const maskedHintQuote = hasBonusHint ? maskHardWord(hintQuote, bonusAnswer, placeholder) : "";
  const hintQuoteHtml = hasBonusHint ? `<span class="veil">${markVerseNumbers(maskedHintQuote)}</span>` : "";
  const hintSourceLine = formatHintSourceLine(puzzle[lang].bonus_hint?.source);
  const bonusRequired = !!bonusAnswer;
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
  const stageTwoOpen = isStageTwoOpen(gameState) || coreSolved;
  const quoteRevealed = stageTwoOpen;
  const sourceRevealed = stageTwoOpen;
  const fullySolved = gameState === GameState.Solved;
  const canShare = attempts.length > 0;
  const submitDisabled = gameState === GameState.Solved || gameState === GameState.Revealed || gameState === GameState.Failed;
  const feedback = useMemo(() => {
    if (!result) return "";
    if (isFullySolved(result, bonusRequired)) return t("puzzleView.solved");
    if (gameState === GameState.Failed) return t("puzzleView.outOfTries");
    if (isCoreSolved(result)) return t("puzzleView.keepGoing");
    return t("puzzleView.retry");
  }, [result, bonusRequired, gameState, t]);
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
    const nextAttempts = initial?.attempts ?? [];
    setSpeaker(nextValues.speaker);
    setListener(nextValues.listener);
    setPortion(nextValues.portion);
    setBonus(nextValues.bonus);
    setBonusHintUsed(initial?.bookHintUsed ?? false);
    setHintRevealed(initial?.hintRevealed ?? false);
    setAttempts(nextAttempts);
    setEditedSinceCheck(emptyEditedState());
    setShareNotice("");
  }, [
    initial?.speaker,
    initial?.listener,
    initial?.portion,
    initial?.bonus,
    initial?.bookHintUsed,
    initial?.hintRevealed,
    initial?.attempts,
    puzzle,
  ]);

  useEffect(() => {
    persistRef.current = onPersist;
  }, [onPersist]);

  useEffect(() => {
    hasPersistedHydratedStateRef.current = false;
  }, [initialSignature, puzzle]);

  useEffect(() => {
    if (!persistRef.current) return;
    const stateSignature = signatureFromState({
      speaker,
      listener,
      portion,
      bonus,
      bookHintUsed: bonusHintUsed,
      hintRevealed,
      attempts,
    });
    if (!hasPersistedHydratedStateRef.current && stateSignature === initialSignature) {
      return;
    }
    hasPersistedHydratedStateRef.current = true;
    persistRef.current({
      speaker,
      listener,
      portion,
      bonus,
      bookHintUsed: bonusHintUsed,
      hintRevealed,
      attempts,
    });
  }, [speaker, listener, portion, bonus, bonusHintUsed, hintRevealed, attempts]);

  useEffect(() => {
    if (!syncDocumentDirection) return;
    const direction = getLanguageDirection(lang);
    document.documentElement.dir = direction;
    document.body.dir = direction;
  }, [lang, syncDocumentDirection]);

  const statusMarks = (() => {
    const hintMark = bonusHintUsed ? "💡" : "⬜";

    if (fullySolved) return `✅✅✳️${hintMark}`;
    if (revealed && coreSolved) return `✅✅✴️${hintMark}`;
    if (coreSolved) return `✅✅✡️${hintMark}`;
    if (!result) return `⬜⬜⬜${hintMark}`;
    const speakerMark = result.speakerOk ? "✅" : "❌";
    const listenerMark = result.listenerOk ? "✅" : "❌";
    return `${speakerMark}${listenerMark}⬜${hintMark}`;
  })();

  const shareUrl = buildShareUrl();
  const shareText = useMemo(() => {
    return buildShareText({
      title: t("app.title"),
      attempts,
      solved: fullySolved,
      bonusRequired,
      hintUsed: bonusHintUsed,
      maxTries: MAX_TOTAL_TRIES,
      date: new Date(),
      gameUrl: shareUrl,
    });
  }, [attempts, fullySolved, bonusRequired, bonusHintUsed, shareUrl, t, lang]);

  const checkGuess = () => {
    if (submitDisabled) return;
    setEditedSinceCheck(emptyEditedState());
    setShareNotice("");
    const speakerAnswer = puzzle[lang].speaker;
    const listenerAnswer = puzzle[lang].listener;

    const speakerOk = normalize(speaker, lang) === normalize(speakerAnswer, lang);
    const listenerOk = normalize(listener, lang) === normalize(listenerAnswer, lang);
    const bonusOk = bonusRequired ? normalize(bonus, lang) === normalize(bonusAnswer, lang) : true;
    const transitioningToMissingWord = bonusRequired && !stageTwoOpen && speakerOk && listenerOk && !bonusOk;

    const next = { speakerOk, listenerOk, portionOk: true, bonusOk, countsAsTry: !transitioningToMissingWord };
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
        extraChecked={coreSolved}
        bonusDisabled={revealed || !bonusRequired}
        bonusHintUsed={bonusHintUsed}
        showBonusHint={stageTwoOpen && hasBonusHint}
        showHintQuote={hintRevealed && hasBonusHint}
        hintQuoteHtml={hintQuoteHtml}
        hintSourceLine={hintSourceLine}
        onChange={handleChange}
        onSubmit={checkGuess}
        onShare={shareResult}
        onRevealBonusHint={revealBonusHint}
        canShare={canShare}
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
