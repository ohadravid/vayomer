import { useEffect } from "react";
import { PuzzleCard } from "./components/PuzzleCard";
import type { PuzzleItem } from "./types";

const PREVIEW_PUZZLE: PuzzleItem = {
  id: "preview-og-image",
  en: {
    book: "",
    quote: "חִידוֹן צִיטּוּט יוֹמִי",
    riddle: "צִיטּוּט",
    speaker: "",
    listener: "",
    bonus: "",
  },
  he: {
    book: "",
    quote: "חִידוֹן צִיטּוּט יוֹמִי",
    riddle: "צִיטּוּט",
    speaker: "",
    listener: "",
    bonus: "",
  },
  source: {
    book: "",
    ref_start: "",
    ref_end: "",
  },
};

export function PreviewPage() {
  useEffect(() => {
    document.documentElement.lang = "he";
    document.documentElement.dir = "rtl";
    document.body.dir = "rtl";
    document.title = "וַיֹּאמֶר | Preview";
  }, []);

  return (
    <main className="preview-root">
      <div className="preview-canvas">
        <h1 className="preview-title">וַיֹּאמֶר</h1>
        <div className="preview-quote-wrap" dir="rtl">
          <PuzzleCard
            puzzle={PREVIEW_PUZZLE}
            revealed
            quoteRevealed
            sourceRevealed={false}
            dateLabel=""
            onClear={() => undefined}
          />
        </div>
        <p className="preview-subtitle">נַחֲשׁוּ אֶת הַדּוֹבֵר, אֶת הַמַּאֲזִין, וְאֶת הַמִּלָּה הַחֲסֵרָה.</p>
      </div>
    </main>
  );
}
