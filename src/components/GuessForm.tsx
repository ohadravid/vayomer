import { useTranslation } from "react-i18next";
import type { EasyChoicePools, GuessEditState, GuessField, GuessResult, GuessValues } from "../types";

type Props = {
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
  hintQuoteHtml?: string;
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
  hintQuoteHtml,
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
  const renderChoiceControl = (
    field: "speaker" | "listener",
    disabled: boolean,
    className: string
  ) => {
    const inputId = field === "speaker" ? "inputSpeaker" : "inputListener";
    const options = choiceOptions?.[field] ?? [];
    const activeValue = values[field].trim();
    const renderedOptions =
      activeValue && !options.includes(activeValue) ? [activeValue, ...options] : options;
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
            <span id="labelSpeaker" className="field-label">{t("guessForm.speaker")}</span>
            {renderChoiceControl(
              "speaker",
              coreSolved,
              result && !editedSinceCheck.speaker
                ? result.speakerOk
                  ? "correct"
                  : "wrong"
                : ""
            )}
          </label>
          <label>
            <span id="labelListener" className="field-label">{t("guessForm.listener")}</span>
            {renderChoiceControl(
              "listener",
              coreSolved,
              result && !editedSinceCheck.listener
                ? result.listenerOk
                  ? "correct"
                  : "wrong"
                : ""
            )}
          </label>
        </div>
        <div
          className={`form-row secondary ${showBonusRow ? "bonus-visible" : "bonus-hidden"} ${
            showBonusHint ? "with-bonus-hint" : ""
          }`}
        >
          <div className="bonus-cell" aria-hidden={!showBonusRow}>
            <label>
              <span id="labelBonus">{t("guessForm.bonus")}</span>
              <input
                id="inputBonus"
                type="text"
                autoComplete="off"
                value={values.bonus}
                onChange={(e) => onChange("bonus", e.target.value)}
                disabled={bonusDisabled || !showBonusRow}
                tabIndex={showBonusRow ? 0 : -1}
                className={
                  showBonusRow && result && extraChecked && values.bonus && !editedSinceCheck.bonus
                    ? result.bonusOk
                      ? "correct"
                      : "wrong"
                    : ""
                }
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
          <div id="hintQuote" className="bonus-hint-quote" dangerouslySetInnerHTML={{ __html: hintQuoteHtml ?? "" }} />
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
