import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import { DEFAULT_LANGUAGE, LANGUAGE_STORAGE_KEY, isSupportedLanguage, normalizeLanguageTag } from "./lib/language";

export const resources = {
  en: {
    translation: {
      app: {
        kicker: "Daily Quote Puzzle",
        title: "Vayomer",
        pageTitle: "Vayomer | Daily Quote Puzzle",
        subtitle: "Guess the speaker, the listener, and the missing word.",
        switchLanguage: "Switch language to {{language}}",
        easyModeOn: "Easy mode: on",
        easyModeOff: "Easy mode: off",
        easyModeTooltip: "Easy mode",
        toggleEasyMode: "Toggle easy mode",
      },
      about: {
        kicker: "About",
        title: "About Vayomer",
        subtitle: "Notes on the game and source texts.",
        link: "About & sources",
        backToGame: "Back to puzzle",
        gameDescription:
          "Vayomer is a daily quote puzzle built from aligned Hebrew and English Bible texts. Each day, you identify the speaker, listener, and context.",
        sourceHeading: "Source Material",
        hebrewLabel: "Hebrew text:",
        hebrewSourceName: "Unicode/XML Leningrad Codex (UXLC) via tanach.us",
        englishLabel: "English text:",
        englishSourceName:
          "TextGrid Repository (2025), English Collection, Multilingual Parallel Bible Corpus",
        modelNote: "Quote candidates were selected with Gemma3:27b.",
      },
      puzzleView: {
        solved: "Solved.",
        keepGoing: "Nice! Now find the missing word.",
        retry: "Not quite. Try again.",
      },
      puzzleCard: {
        clear: "Clear",
      },
      guessForm: {
        speaker: "Speaker",
        listener: "Listener",
        portion: "Portion",
        bonus: "Missing word (hard)",
        selectOption: "Choose an option",
        check: "Check",
        guesses: "Guesses: {{count}}",
        status: "Status: {{marks}}",
      },
    },
  },
  he: {
    translation: {
      app: {
        kicker: "חִידוֹן צִיטּוּט יוֹמִי",
        title: "וַיֹּאמֶר",
        pageTitle: "וַיֹּאמֶר | חידון ציטוט יומי",
        subtitle: "נַחֲשׁוּ אֶת הַדּוֹבֵר, אֶת הַמַּאֲזִין, וְאֶת מִלַּת הגְּמוּל הנוֹסָף.",
        switchLanguage: "החלפת שפה ל-{{language}}",
        easyModeOn: "מצב קל: פעיל",
        easyModeOff: "מצב קל: כבוי",
        easyModeTooltip: "מצב קל",
        toggleEasyMode: "החלפת מצב קל",
      },
      about: {
        kicker: "אודות",
        title: "אודות ויאמר",
        subtitle: "מידע על המשחק ועל מקורות הטקסט.",
        link: "אודות ומקורות",
        backToGame: "חזרה לחידה",
        gameDescription:
          "ויאמר הוא חידון ציטוט יומי שנבנה מטקסטים מקבילים של התנ\"ך בעברית ובאנגלית. בכל יום מזהים את הדובר, המאזין וההקשר.",
        sourceHeading: "מקורות",
        hebrewLabel: "טקסט עברי:",
        hebrewSourceName: "מהדורת Unicode/XML של קודקס לנינגרד (UXLC), דרך tanach.us",
        englishLabel: "טקסט אנגלי:",
        englishSourceName: "מאגר TextGrid ‏(2025), English Collection, Multilingual Parallel Bible Corpus",
        modelNote: "בחירת הציטוטים נעשתה באמצעות Gemma3:27b.",
      },
      puzzleView: {
        solved: "נכון.",
        keepGoing: "יפה! עכשיו מצאו את המילה החסרה.",
        retry: "לא בדיוק. נסו שוב.",
      },
      puzzleCard: {
        clear: "נקה",
      },
      guessForm: {
        speaker: "דובר",
        listener: "מאזין",
        portion: "פרשה",
        bonus: "מילה חסרה (קשה)",
        selectOption: "בחרו אפשרות",
        check: "בדיקה",
        guesses: "ניחושים: {{count}}",
        status: "מצב: {{marks}}",
      },
    },
  },
} as const;

function detectInitialLanguage(): string {
  if (typeof window === "undefined") return DEFAULT_LANGUAGE;
  try {
    const saved = window.localStorage.getItem(LANGUAGE_STORAGE_KEY);
    if (isSupportedLanguage(saved)) return saved;
  } catch {
    // Ignore storage access errors.
  }
  return normalizeLanguageTag(window.navigator?.language);
}

void i18n.use(initReactI18next).init({
  resources,
  lng: detectInitialLanguage(),
  fallbackLng: DEFAULT_LANGUAGE,
  supportedLngs: ["en", "he"],
  load: "languageOnly",
  interpolation: { escapeValue: false },
});

i18n.on("languageChanged", (next) => {
  if (typeof window === "undefined") return;
  const normalized = normalizeLanguageTag(next);
  try {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, normalized);
  } catch {
    // Ignore storage access errors.
  }
});

export default i18n;
