import i18n from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import { initReactI18next } from "react-i18next";
import {
  DEFAULT_LANGUAGE,
  LANGUAGE_PREFERENCE_SET_KEY,
  LANGUAGE_STORAGE_KEY,
  normalizeLanguageTag,
} from "./lib/language";

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
        outOfTries: "No tries left.",
        shareShared: "Result shared.",
        shareCopied: "Result copied.",
        shareFailed: "Could not share result.",
      },
      puzzleCard: {
        clear: "Clear",
        hint: "Hint",
      },
      guessForm: {
        speaker: "Speaker",
        listener: "Listener",
        portion: "Portion",
        bonus: "Missing word (hard)",
        selectOption: "Choose an option",
        check: "Check",
        guesses: "Guesses: {{count}}",
        tries: "Tries: {{used}}/{{total}}",
        status: "Status: {{marks}}",
        share: "Share result",
      },
    },
  },
  he: {
    translation: {
      app: {
        kicker: "חִידוֹן צִיטּוּט יוֹמִי",
        title: "וַיֹּאמֶר",
        pageTitle: "וַיֹּאמֶר | חידון ציטוט יומי",
        subtitle: "נַחֲשׁוּ אֶת הַדּוֹבֵר, אֶת הַמַּאֲזִין, וְאֶת הַמִּלָּה הַחֲסֵרָה.",
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
        outOfTries: "נגמרו הניסיונות.",
        shareShared: "התוצאה שותפה.",
        shareCopied: "התוצאה הועתקה.",
        shareFailed: "לא הצלחנו לשתף את התוצאה.",
      },
      puzzleCard: {
        clear: "נקה",
        hint: "רמז",
      },
      guessForm: {
        speaker: "דובר",
        listener: "מאזין",
        portion: "פרשה",
        bonus: "מילה חסרה",
        selectOption: "בחרו אפשרות",
        check: "בדיקה",
        guesses: "ניחושים: {{count}}",
        tries: "ניסיונות: {{used}}/{{total}}",
        status: "מצב: {{marks}}",
        share: "שיתוף תוצאה",
      },
    },
  },
} as const;

function detectHeOrEnglish(language: string | readonly string[] | null | undefined): "he" | "en" {
  const candidates = Array.isArray(language) ? language : [language];
  for (const candidate of candidates) {
    if (!candidate) continue;
    const base = candidate.toLowerCase().split("-")[0];
    if (base === "he" || base === "iw") return "he";
  }
  return "en";
}

const languageDetector = new LanguageDetector();
languageDetector.addDetector({
  name: "navigatorHeFirst",
  lookup() {
    if (typeof navigator === "undefined") return undefined;
    const candidates = navigator.languages?.length ? navigator.languages : [navigator.language];
    return detectHeOrEnglish(candidates);
  },
});

void i18n.use(languageDetector).use(initReactI18next).init({
  resources,
  fallbackLng: DEFAULT_LANGUAGE,
  supportedLngs: ["en", "he"],
  load: "languageOnly",
  detection: {
    order: ["querystring", "localStorage", "navigatorHeFirst"],
    lookupLocalStorage: LANGUAGE_STORAGE_KEY,
    caches: [],
    convertDetectedLanguage: detectHeOrEnglish,
  },
  interpolation: { escapeValue: false },
});

let initializedLanguage = false;
i18n.on("languageChanged", (next) => {
  if (typeof window === "undefined") return;
  const normalized = normalizeLanguageTag(next);
  if (!initializedLanguage) {
    initializedLanguage = true;
    return;
  }
  try {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, normalized);
    window.localStorage.setItem(LANGUAGE_PREFERENCE_SET_KEY, "1");
  } catch {
    // Ignore storage access errors.
  }
});

export default i18n;
