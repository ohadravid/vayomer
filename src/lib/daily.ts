import { Temporal } from "@js-temporal/polyfill";

export const DAILY_EPOCH_DATE = Temporal.PlainDate.from("2026-03-16");
export const DAILY_ORDER_SEED = 20220805;
export const HARD_MODE_SUCCESS_MARKS = ["🔥", "⚔️", "👑"] as const;
export type DailyDateInput = Temporal.PlainDate;

// Override keys are parsed with Temporal:
// - Full-date overrides: Temporal.PlainDate RFC 9557 strings (e.g. "2026-03-16", "2025-09-23[u-ca=hebrew]")
// - Recurring month/day overrides: Temporal.PlainMonthDay strings (e.g. "03-16", "1972-09-09[u-ca=hebrew]")
export const DAILY_QUOTE_ID_OVERRIDES: Readonly<Record<string, string>> = {
  "2026-02-19": "manual-genesis-03-09-09-d094f0f4",
  "2026-02-21": "exodus-24-03-04",
  "2026-02-22": "manual-genesis-37-07-09-69be8e9c",
  "2026-02-23": "exodus-20-22-23",
  "2026-02-24": "manual-genesis-24-16-18-10363c00",
  "2026-02-25": "exodus-33-17-17",
  "2026-02-26": "manual-genesis-47-08-09-17ff6fd8",
  "2026-03-04": "exodus-07-14-15",
  "2026-03-10": "exodus-32-09-12",
  "2026-03-11": "genesis-16-08-10",
  "2026-03-15": "genesis-18-05-06",
  "2026-03-16": "genesis-42-07-07",
  "2026-03-17": "1-samuel-23-09-11",
  "2026-03-19": "manual-jeremiah-33-10-11-4f49ab70",
  "2026-03-24": "genesis-44-14-15",
  "2026-03-25": "genesis-22-04-05",
};

function toLocalPlainDate(date: DailyDateInput): Temporal.PlainDate {
  return date.withCalendar("iso8601");
}

function dayOffsetFromEpoch(date: DailyDateInput, epochDate: DailyDateInput): number {
  const localDate = toLocalPlainDate(date);
  const localEpoch = toLocalPlainDate(epochDate);
  return localEpoch.until(localDate, { largestUnit: "days" }).days;
}

export function dayIndex(
  total: number,
  date: DailyDateInput = Temporal.Now.plainDateISO(),
  epochDate: DailyDateInput = DAILY_EPOCH_DATE
): number {
  if (total <= 0) return 0;
  const offset = dayOffsetFromEpoch(date, epochDate);
  return ((offset % total) + total) % total;
}

export function seededRandom(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let mixed = Math.imul(state ^ (state >>> 15), state | 1);
    mixed ^= mixed + Math.imul(mixed ^ (mixed >>> 7), mixed | 61);
    return ((mixed ^ (mixed >>> 14)) >>> 0) / 4294967296;
  };
}

function buildDailyOrder(total: number): number[] {
  const order = Array.from({ length: total }, (_, idx) => idx);
  const rand = seededRandom(DAILY_ORDER_SEED);

  for (let idx = order.length - 1; idx > 0; idx -= 1) {
    const swapIdx = Math.floor(rand() * (idx + 1));
    [order[idx], order[swapIdx]] = [order[swapIdx], order[idx]];
  }

  return order;
}

export function pickDailyItemIndex(total: number, date: DailyDateInput = Temporal.Now.plainDateISO()): number {
  if (total <= 0) return 0;
  const day = dayIndex(total, date);
  const order = buildDailyOrder(total);
  return order[day] ?? 0;
}

export function dateOverrideKey(date: DailyDateInput = Temporal.Now.plainDateISO()): string {
  return toLocalPlainDate(date).toString();
}

function parseOverridePlainDate(value: string): Temporal.PlainDate | null {
  try {
    return Temporal.PlainDate.from(value);
  } catch {
    return null;
  }
}

function parseOverridePlainMonthDay(value: string): Temporal.PlainMonthDay | null {
  try {
    return Temporal.PlainMonthDay.from(value);
  } catch {
    return null;
  }
}

function resolveOverrideId(overrides: Readonly<Record<string, string>>, date: DailyDateInput): string | null {
  const localDate = toLocalPlainDate(date);

  for (const [rawKey, rawId] of Object.entries(overrides)) {
    const key = rawKey.trim();
    const id = rawId.trim();
    if (!key || !id) continue;

    const dateOverride = parseOverridePlainDate(key);
    const monthDayOverride = parseOverridePlainMonthDay(key);

    // Some month-day strings (notably non-ISO calendar ones) include a reference year and
    // are parseable as both PlainDate and PlainMonthDay. Treat canonical PlainMonthDay text
    // as recurring; otherwise, treat parseable PlainDate text as an exact date.
    const preferMonthDay =
      monthDayOverride !== null &&
      (dateOverride === null || key === monthDayOverride.toString() || key.startsWith("--"));

    if (preferMonthDay && monthDayOverride) {
      const localMonthDayInCalendar = localDate.withCalendar(monthDayOverride.calendarId).toPlainMonthDay();
      if (monthDayOverride.equals(localMonthDayInCalendar)) {
        return id;
      }
      continue;
    }

    if (dateOverride && dateOverride.equals(localDate.withCalendar(dateOverride.calendarId))) {
      return id;
    }
  }

  return null;
}

export function pickDailyItemIndexWithOverrides(
  items: readonly { id: string }[],
  date: DailyDateInput = Temporal.Now.plainDateISO(),
  overrides: Readonly<Record<string, string>> = DAILY_QUOTE_ID_OVERRIDES
): number {
  if (items.length <= 0) return 0;
  const overrideId = resolveOverrideId(overrides, date);
  if (overrideId) {
    const overrideIndex = items.findIndex((item) => item.id === overrideId);
    if (overrideIndex >= 0) return overrideIndex;
  }
  return pickDailyItemIndex(items.length, date);
}

export function pickDailyHardModeSuccessMark(
  date: DailyDateInput = Temporal.Now.plainDateISO()
): (typeof HARD_MODE_SUCCESS_MARKS)[number] {
  const day = dayOffsetFromEpoch(date, DAILY_EPOCH_DATE);
  const rand = seededRandom(DAILY_ORDER_SEED + day);
  const idx = Math.floor(rand() * HARD_MODE_SUCCESS_MARKS.length);
  return HARD_MODE_SUCCESS_MARKS[idx] ?? HARD_MODE_SUCCESS_MARKS[0];
}
