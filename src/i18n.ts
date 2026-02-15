import i18n from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import { initReactI18next } from "react-i18next";
import {
  DEFAULT_LANGUAGE,
  LANGUAGE_QUERY_KEY,
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
        easyModeLockedTooltip: "Difficulty is locked for this puzzle.",
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
        shareCopied: "Result copied.",
        shareFailed: "Could not share result.",
      },
      puzzleCard: {
        clear: "",
      },
      guessForm: {
        speaker: "Speaker",
        listener: "Listener",
        portion: "Portion",
        bonus: "Missing word (hard)",
        bonusHint: "Bonus hint",
        selectOption: "Choose an option",
        check: "Check",
        guesses: "Guesses: {{count}}",
        tries: "Tries: {{used}}/{{total}}",
        status: "Status: {{marks}}",
        share: "Share result",
      },
      footer: {
        version: "Version {{version}} (beta)",
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
        easyModeLockedTooltip: "רמת הקושי נעולה עבור החידה הזו.",
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
        shareCopied: "התוצאה הועתקה.",
        shareFailed: "לא הצלחנו לשתף את התוצאה.",
      },
      puzzleCard: {
        clear: "",
      },
      guessForm: {
        speaker: "דובר",
        listener: "מאזין",
        portion: "פרשה",
        bonus: "מילה חסרה",
        bonusHint: "רמז",
        selectOption: "בחרו אפשרות",
        check: "בדיקה",
        guesses: "ניחושים: {{count}}",
        tries: "ניסיונות: {{used}}/{{total}}",
        status: "מצב: {{marks}}",
        share: "שיתוף תוצאה",
      },
      footer: {
        version: "גרסת הרצה ({{version}})",
      },
    },
  },
} as const;

void i18n.use(LanguageDetector).use(initReactI18next).init({
  resources,
  fallbackLng: DEFAULT_LANGUAGE,
  supportedLngs: ["en", "he"],
  load: "languageOnly",
  detection: {
    order: ["querystring", "localStorage"],
    lookupQuerystring: LANGUAGE_QUERY_KEY,
    lookupLocalStorage: LANGUAGE_STORAGE_KEY,
    caches: [],
    convertDetectedLanguage: normalizeLanguageTag,
  },
  interpolation: { escapeValue: false },
});

export default i18n;
