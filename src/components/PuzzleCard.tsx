import { useTranslation } from "react-i18next";
import { getLanguageFromI18n } from "../lib/language";
import type { PuzzleItem, SourceMethod } from "../types";
import { highlightQuote, maskHardWord, pickHardWordPlaceholderForId } from "../lib/format";

type Props = {
  puzzle: PuzzleItem;
  revealed: boolean;
  quoteRevealed: boolean;
  sourceRevealed: boolean;
  dateLabel: string;
  onClear: () => void;
};

function toInt(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return Math.floor(value);
  if (typeof value === "string") {
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function trimmedString(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function stripLeadingBook(ref: string): string {
  return ref.replace(/^[^\d]*/, "").trim();
}

function formatRefRange(refStart: string, refEnd: string): string {
  const start = stripLeadingBook(refStart);
  const end = stripLeadingBook(refEnd);
  if (start && end) return start === end ? start : `${start}–${end}`;
  return start || end;
}

function formatChapterRange(chapterValue: unknown, startValue: unknown, endValue: unknown): string {
  const chapter = toInt(chapterValue);
  const start = toInt(startValue);
  const end = toInt(endValue);

  if (chapter !== null && start !== null) {
    if (end !== null && end !== start) return `${chapter}:${start}-${end}`;
    return `${chapter}:${start}`;
  }

  if (start !== null) {
    if (end !== null && end !== start) return `${start}-${end}`;
    return `${start}`;
  }

  return "";
}

function getBookLabel(puzzle: PuzzleItem, lang: "en" | "he"): string {
  const fromLang = trimmedString(puzzle[lang].book);
  if (fromLang) return fromLang;
  const source = puzzle.source;
  if (!source) return "";
  if (lang === "he") return trimmedString(source.book_he) || trimmedString(source.book);
  return trimmedString(source.book);
}

function getMainSourceRange(puzzle: PuzzleItem): string {
  const source = puzzle.source;
  if (!source) return "";

  const refStart = trimmedString(source.ref_start);
  const refEnd = trimmedString(source.ref_end);
  if (refStart || refEnd) {
    return formatRefRange(refStart, refEnd);
  }

  return formatChapterRange(source.chapter, source.quote_verse_start, source.quote_verse_end);
}

function sourceMethodFromPuzzle(puzzle: PuzzleItem): SourceMethod {
  return puzzle.source?.method === "manual" ? "manual" : "llm";
}

function sourceMethodEmoji(method: SourceMethod): string {
  return method === "manual" ? "👵" : "";
}

export function PuzzleCard({
  puzzle,
  revealed,
  quoteRevealed,
  sourceRevealed,
  dateLabel,
  onClear,
}: Props) {
  const { t, i18n } = useTranslation();
  const lang = getLanguageFromI18n(i18n);
  const riddleText = puzzle[lang].riddle;
  const quote = puzzle[lang].quote;
  const bonus = puzzle[lang].bonus ?? "";
  const placeholder = pickHardWordPlaceholderForId(puzzle.id);
  const renderedQuote = revealed ? quote : maskHardWord(quote, bonus, placeholder);

  const book = getBookLabel(puzzle, lang);
  const mainSourceRange = getMainSourceRange(puzzle);
  const sourceLine = [book, mainSourceRange].filter(Boolean).join(" ");
  const sourceLineWithMethod = sourceLine ? `${sourceMethodEmoji(sourceMethodFromPuzzle(puzzle))} ${sourceLine}` : "";

  return (
    <section
      className={`card reveal ${quoteRevealed ? "quote-revealed" : ""} ${revealed ? "revealed" : ""} ${
        sourceRevealed ? "source-revealed" : ""
      }`}
      id="puzzleCard"
    >
      <div className="meta">
        <div className="meta-left">
          <span id="puzzleDate" className="meta-item">
            {dateLabel}
          </span>
        </div>
        {import.meta.hot ? (
          <div className="meta-actions">
            <button className="ghost small icon-btn" type="button" onClick={onClear}>
              🧹 {t("puzzleCard.clear")}
            </button>
          </div>
        ) : null}
      </div>
      <div
        id="fullQuote"
        className="full-quote"
        dangerouslySetInnerHTML={{ __html: highlightQuote(renderedQuote, riddleText) }}
      />
      <div id="refLine" className="ref-line">
        {sourceRevealed ? sourceLineWithMethod : ""}
      </div>
    </section>
  );
}
