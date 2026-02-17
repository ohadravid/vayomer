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
  chapter?: number | string;
  start?: number | string;
  end?: number | string;
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
  hard_difficulty_options?: DifficultyChoicePools | null;
};

export type Portion = {
  en: string;
  he: string;
} | null;

export type SourceRef = {
  ref_start?: string;
  ref_end?: string;
  book?: string;
  book_he?: string;
  chapter?: number | string;
  quote_verse_start?: number | string;
  quote_verse_end?: number | string;
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
