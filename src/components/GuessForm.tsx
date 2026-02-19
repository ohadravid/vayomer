import { useTranslation } from "react-i18next";
import type { ReactNode } from "react";
import type { EasyChoicePools, GuessEditState, GuessField, GuessResult, GuessValues } from "../types";

type Props = {
  easyMode: boolean;
  choiceOptions?: EasyChoicePools;
  values: GuessValues;
  result: GuessResult | null;
  editedSinceCheck: GuessEditState;
  onChange: (field: GuessField, value: string) => void;
  onChoiceInteracted?: () => void;
  onSubmit: () => void;
  onShare: () => void;
  onRevealBonusHint: () => void;
  showBonusHint: boolean;
  showHintQuote: boolean;
  hintQuoteContent?: ReactNode;
  hintSourceLine?: string;
  coreSolved: boolean;
  showBonusRow: boolean;
  extraChecked: boolean;
  bonusDisabled: boolean;
  bonusHintUsed: boolean;
  canShare: boolean;
  disabled: boolean;
  feedback?: string;
  shareNotice?: string;
  triesUsed: number;
  maxTries: number;
  statusMarks: string;
};

export function GuessForm({
  easyMode,
  choiceOptions,
  values,
  result,
  editedSinceCheck,
  onChange,
  onChoiceInteracted,
  onSubmit,
  onShare,
  onRevealBonusHint,
  showBonusHint,
  showHintQuote,
  hintQuoteContent,
  hintSourceLine,
  coreSolved,
  showBonusRow,
  extraChecked,
  bonusDisabled,
  bonusHintUsed,
  canShare,
  disabled,
  feedback,
  shareNotice,
  triesUsed,
  maxTries,
  statusMarks,
}: Props) {
  const { t } = useTranslation();
  const collator = new Intl.Collator(undefined, { sensitivity: "base" });
  const coreFieldState = (field: "speaker" | "listener"): "correct" | "wrong" | "" => {
    if (!result || editedSinceCheck[field]) return "";
    return result[field === "speaker" ? "speakerOk" : "listenerOk"] ? "correct" : "wrong";
  };
  const coreFieldMark = (field: "speaker" | "listener"): string => {
    const state = coreFieldState(field);
    if (state === "correct") return "✅";
    if (state === "wrong") return "❌";
    return "";
  };
  const bonusFeedbackVisible =
    showBonusRow && !!result && extraChecked && !editedSinceCheck.bonus && result.countsAsTry !== false;
  const bonusState: "correct" | "wrong" | "" = bonusFeedbackVisible ? (result!.bonusOk ? "correct" : "wrong") : "";
  const bonusMark = bonusState === "correct" ? "✅" : bonusState === "wrong" ? "❌" : "";

  const renderEasyChoiceControl = (
    field: "speaker" | "listener",
    disabled: boolean
  ) => {
    const inputId = field === "speaker" ? "inputSpeaker" : "inputListener";
    const options = choiceOptions?.[field] ?? [];
    const activeValue = values[field].trim();
    const renderedOptions = (activeValue && !options.includes(activeValue) ? [activeValue, ...options] : options).sort(
      (a, b) => collator.compare(a, b)
    );
    const className = coreFieldState(field);
    return (
      <select
        id={inputId}
        value={values[field]}
        onChange={(e) => onChange(field, e.target.value)}
        onClick={onChoiceInteracted}
        disabled={disabled}
        className={className}
      >
        <option value="">{t("guessForm.selectOption")}</option>
        {renderedOptions.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    );
  };

  const renderHardInputControl = (
    field: "speaker" | "listener",
    disabled: boolean
  ) => {
    const inputId = field === "speaker" ? "inputSpeaker" : "inputListener";
    const className = coreFieldState(field);
    return (
      <input
        id={inputId}
        type="text"
        autoComplete="off"
        value={values[field]}
        onChange={(e) => onChange(field, e.target.value)}
        onClick={onChoiceInteracted}
        disabled={disabled}
        className={className}
      />
    );
  };

  const renderChoiceControl = (
    field: "speaker" | "listener",
    disabled: boolean
  ) => {
    if (easyMode) return renderEasyChoiceControl(field, disabled);
    return renderHardInputControl(field, disabled);
  };

  return (
    <section className="card">
      <form
        id="guessForm"
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          onSubmit();
        }}
      >
        <div className="form-row primary">
          <label>
            <span id="labelSpeaker" className="field-label">
              {t("guessForm.speaker")}
              {coreFieldMark("speaker") ? <span aria-hidden="true">{coreFieldMark("speaker")}</span> : null}
            </span>
            {renderChoiceControl("speaker", coreSolved)}
          </label>
          <label>
            <span id="labelListener" className="field-label">
              {t("guessForm.listener")}
              {coreFieldMark("listener") ? <span aria-hidden="true">{coreFieldMark("listener")}</span> : null}
            </span>
            {renderChoiceControl("listener", coreSolved)}
          </label>
        </div>
        <div
          className={`form-row secondary ${showBonusRow ? "bonus-visible" : "bonus-hidden"} ${
            showBonusHint ? "with-bonus-hint" : ""
          }`}
        >
          <div className="bonus-cell" aria-hidden={!showBonusRow}>
            <label>
              <span id="labelBonus" className="field-label">
                {t("guessForm.bonus")}
                {bonusMark ? <span aria-hidden="true">{bonusMark}</span> : null}
              </span>
              <input
                id="inputBonus"
                type="text"
                autoComplete="off"
                value={values.bonus}
                onChange={(e) => onChange("bonus", e.target.value)}
                disabled={bonusDisabled || !showBonusRow}
                tabIndex={showBonusRow ? 0 : -1}
                className={bonusState}
              />
            </label>
          </div>
          {showBonusHint ? (
            <button
              id="bonusHint"
              className="ghost small bonus-hint-btn"
              type="button"
              onClick={onRevealBonusHint}
              disabled={bonusHintUsed}
            >
              💡 {t("guessForm.bonusHint")}
            </button>
          ) : null}
          <button id="submitGuess" className="primary submit-cell" type="submit" disabled={disabled}>
            {t("guessForm.check")}
          </button>
        </div>
      </form>
      {showHintQuote ? (
        <div id="hintReveal" className={`bonus-hint-reveal ${showHintQuote ? "revealed" : ""}`}>
          <div id="hintQuote" className="bonus-hint-quote">
            {hintQuoteContent ?? ""}
          </div>
          <div id="hintRefLine" className="bonus-hint-ref-line">
            {hintSourceLine ?? ""}
          </div>
        </div>
      ) : null}
      <div id="feedback" className="feedback">
        {feedback}
      </div>
      <div className="status-line">
        <span>{t("guessForm.tries", { used: triesUsed, total: maxTries })}</span>
        <span>{t("guessForm.status", { marks: statusMarks })}</span>
        <button className="ghost small share-btn" type="button" disabled={!canShare} onClick={onShare}>
          {t("guessForm.share")}
        </button>
      </div>
      <div className="share-note">{shareNotice}</div>
    </section>
  );
}
