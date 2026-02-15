export type Lang = "en" | "he";

export enum GameState {
  CoreGuess = "core-guess",
  ExtraGuess = "extra-guess",
  Solved = "solved",
  Revealed = "revealed",
  Failed = "failed",
}

export type GuessField = "speaker" | "listener" | "portion" | "bonus";

export type GuessValues = Record<GuessField, string>;

export type GuessEditState = Record<GuessField, boolean>;

export type EasyChoiceField = "speaker" | "listener";

export type EasyChoicePools = Record<EasyChoiceField, string[]>;

export type LangText = {
  book: string;
  quote: string;
  riddle: string;
  speaker: string;
  listener: string;
  bonus?: string | null;
};

export type Portion = {
  en: string;
  he: string;
} | null;

export type SourceRef = {
  ref_start?: string;
  ref_end?: string;
};

export type PuzzleItem = {
  id: string;
  en: LangText;
  he: LangText;
  portion?: Portion;
  source?: SourceRef;
};

export type GuessResult = {
  speakerOk: boolean;
  listenerOk: boolean;
  portionOk: boolean;
  bonusOk: boolean;
  countsAsTry?: boolean;
};

export type BookOptionSet = {
  book: {
    en: string;
    he: string;
  };
  speaker: {
    en: string[];
    he: string[];
  };
  listener: {
    en: string[];
    he: string[];
  };
  portion: {
    en: string[];
    he: string[];
  };
};

export type OptionsDataset = {
  books: BookOptionSet[];
};
