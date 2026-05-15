import { Temporal } from "@js-temporal/polyfill";

export const DAILY_EPOCH_DATE = Temporal.PlainDate.from("2026-03-16");
export type DailyDateInput = Temporal.PlainDate;

// Override keys are parsed with Temporal:
// - Full-date overrides: Temporal.PlainDate RFC 9557 strings (e.g. "2026-03-16", "2025-09-23[u-ca=hebrew]")
// - Recurring month/day overrides: Temporal.PlainMonthDay strings (e.g. "03-16", "1972-09-09[u-ca=hebrew]")
export const DAILY_QUOTE_ID_OVERRIDES: Readonly<Record<string, string>> = {
  "02-19": "manual-genesis-03-09-09-d094f0f4",
  "02-22": "manual-genesis-37-07-09-69be8e9c",
  "02-24": "manual-genesis-24-16-18-10363c00",
  "02-26": "manual-genesis-47-08-09-17ff6fd8",
  "03-19": "manual-jeremiah-33-10-11-4f49ab70",
  "1972-05-13[u-ca=hebrew]": "manual-numbers-10-29-29-d5882096",
  "04-11": "exodus-33-05-05",
  "04-13": "1-samuel-12-03-03",
  "04-14": "2-samuel-17-20-20",
  "04-15": "2-kings-20-15-15",
  "04-17": "genesis-30-34-34",
  "04-18": "genesis-19-17-17",
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

export function pickDailyItemIndex(
  items: readonly { id: string }[],
  date: DailyDateInput = Temporal.Now.plainDateISO()
): number {
  if (items.length <= 0) return 0;
  return dayIndex(items.length, date);
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
  return pickDailyItemIndex(items, date);
}
