import { useTranslation } from "react-i18next";
import type { EasyChoicePools, GuessEditState, GuessField, GuessResult, GuessValues } from "../types";

type Props = {
  easyMode: boolean;
  choiceOptions?: EasyChoicePools;
  values: GuessValues;
  result: GuessResult | null;
  editedSinceCheck: GuessEditState;
  onChange: (field: GuessField, value: string) => void;
  onSubmit: () => void;
  onShare: () => void;
  coreSolved: boolean;
  showBonusRow: boolean;
  extraChecked: boolean;
  bonusDisabled: boolean;
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
  onSubmit,
  onShare,
  coreSolved,
  showBonusRow,
  extraChecked,
  bonusDisabled,
  canShare,
  disabled,
  feedback,
  shareNotice,
  triesUsed,
  maxTries,
  statusMarks,
}: Props) {
  const { t } = useTranslation();
  const isEasyCorrect = (field: "speaker" | "listener"): boolean => {
    if (!easyMode || !result) return false;
    if (field === "speaker") return !editedSinceCheck.speaker && result.speakerOk;
    return !editedSinceCheck.listener && result.listenerOk;
  };
  const renderChoiceControl = (
    field: "speaker" | "listener",
    disabled: boolean,
    className: string
  ) => {
    if (!easyMode) {
      return (
        <input
          id={field === "speaker" ? "inputSpeaker" : field === "listener" ? "inputListener" : "inputPortion"}
          type="text"
          autoComplete="off"
          value={values[field]}
          onChange={(e) => onChange(field, e.target.value)}
          disabled={disabled}
          className={className}
        />
      );
    }

    const options = choiceOptions?.[field] ?? [];
    const activeValue = values[field].trim();
    const renderedOptions =
      activeValue && !options.includes(activeValue) ? [activeValue, ...options] : options;
    return (
      <div className={`select-shell ${className} ${disabled ? "disabled" : ""}`}>
        <select
          id={field === "speaker" ? "inputSpeaker" : field === "listener" ? "inputListener" : "inputPortion"}
          value={values[field]}
          onChange={(e) => onChange(field, e.target.value)}
          disabled={disabled}
          className="select-field"
        >
          <option value="">{t("guessForm.selectOption")}</option>
          {renderedOptions.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
        <span className="select-icon" aria-hidden="true">
          ▾
        </span>
      </div>
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
            <span id="labelSpeaker" className="field-label">
              {t("guessForm.speaker")}
              {isEasyCorrect("speaker") ? <span className="easy-correct" aria-hidden="true">❇️</span> : null}
            </span>
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
            <span id="labelListener" className="field-label">
              {t("guessForm.listener")}
              {isEasyCorrect("listener") ? <span className="easy-correct" aria-hidden="true">❇️</span> : null}
            </span>
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
        <div className={`form-row secondary no-portion ${showBonusRow ? "open" : "locked"}`}>
          <label>
            <span id="labelBonus">{t("guessForm.bonus")}</span>
            <input
              id="inputBonus"
              type="text"
              autoComplete="off"
              value={values.bonus}
              onChange={(e) => onChange("bonus", e.target.value)}
              disabled={!showBonusRow || bonusDisabled}
              className={
                result && extraChecked && values.bonus && !editedSinceCheck.bonus
                  ? result.bonusOk
                    ? "correct"
                    : "wrong"
                  : ""
              }
            />
          </label>
          <div className="form-actions">
            <button id="submitGuess" className="primary" type="submit" disabled={disabled}>
              {t("guessForm.check")}
            </button>
          </div>
        </div>
      </form>
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
