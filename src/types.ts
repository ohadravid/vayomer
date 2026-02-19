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

export type DifficultyChoicePools = Partial<Record<EasyChoiceField, string[]>>;

export type HintSourceRef = {
  book?: string;
  chapter?: number;
  start?: number;
  end?: number;
};

export type BonusHint = {
  quote: string;
  source?: HintSourceRef;
};

export type LangText = {
  book?: string;
  quote: string;
  riddle: string;
  speaker: string;
  listener: string;
  bonus?: string | null;
  bonus_hint?: BonusHint | null;
  options?: DifficultyChoicePools | null;
};

export type Portion = {
  en: string;
  he: string;
} | null;

export type SourceMethod = "llm" | "manual";

export type SourceRef = {
  method?: SourceMethod;
  ref_start?: string;
  ref_end?: string;
  book?: string;
  book_he?: string;
  chapter?: number;
  quote_verse_start?: number;
  quote_verse_end?: number;
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
  hintUsed?: boolean;
  countsAsTry?: boolean;
};

export type PersistedGameFields = {
  speaker: string;
  listener: string;
  portion: string;
  bonus: string;
  hintRevealed: boolean;
  attempts: GuessResult[];
};
