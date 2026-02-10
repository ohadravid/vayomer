import { useTranslation } from "react-i18next";
import { getLanguageFromI18n } from "../lib/language";
import type { PuzzleItem } from "../types";
import { highlightQuote, maskHardWord, pickHardWordPlaceholderForId } from "../lib/format";

type Props = {
  puzzle: PuzzleItem;
  revealed: boolean;
  quoteRevealed: boolean;
  dateLabel: string;
  onClear: () => void;
};

export function PuzzleCard({ puzzle, revealed, quoteRevealed, dateLabel, onClear }: Props) {
  const { t, i18n } = useTranslation();
  const lang = getLanguageFromI18n(i18n);
  const riddleText = puzzle[lang].riddle;
  const quote = puzzle[lang].quote;
  const bonus = puzzle[lang].bonus ?? "";
  const placeholder = pickHardWordPlaceholderForId(puzzle.id);
  const renderedQuote = revealed ? quote : maskHardWord(quote, bonus, placeholder);

  const refStart = puzzle.source?.ref_start || "";
  const refEnd = puzzle.source?.ref_end || "";
  const ref = refStart === refEnd ? refStart : `${refStart}–${refEnd}`;
  const refNumber = ref.replace(/^[^0-9]*/, "");
  const refLine = refNumber ? `${puzzle[lang].book} ${refNumber}` : "";

  return (
    <section
      className={`card reveal ${quoteRevealed ? "quote-revealed" : ""} ${revealed ? "revealed" : ""}`}
      id="puzzleCard"
    >
      <div className="meta">
        <div className="meta-left">
          <span id="puzzleDate" className="meta-item">
            {dateLabel}
          </span>
        </div>
        <div className="meta-actions">
          <button className="ghost small" type="button" onClick={onClear}>
            {t("puzzleCard.clear")}
          </button>
        </div>
      </div>
      <div
        id="fullQuote"
        className="full-quote"
        dangerouslySetInnerHTML={{ __html: highlightQuote(renderedQuote, riddleText) }}
      />
      <div id="refLine" className="ref-line">
        {refLine}
      </div>
    </section>
  );
}
