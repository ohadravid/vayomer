export const DAILY_EPOCH_DATE = new Date(2026, 2, 16);
export const DAILY_ORDER_SEED = 20220805;
export const HARD_MODE_SUCCESS_MARKS = ["🔥", "⚔️", "👑"] as const;

function utcDayNumber(date: Date): number {
  return Math.floor(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) / (24 * 60 * 60 * 1000));
}

function dayOffsetFromEpoch(date: Date, epochDate: Date): number {
  return utcDayNumber(date) - utcDayNumber(epochDate);
}

export function dayIndex(total: number, date: Date = new Date(), epochDate: Date = DAILY_EPOCH_DATE): number {
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

export function pickDailyItemIndex(total: number, date: Date = new Date()): number {
  if (total <= 0) return 0;
  const day = dayIndex(total, date);
  const order = buildDailyOrder(total);
  return order[day] ?? 0;
}

export function pickDailyHardModeSuccessMark(date: Date = new Date()): (typeof HARD_MODE_SUCCESS_MARKS)[number] {
  const day = dayOffsetFromEpoch(date, DAILY_EPOCH_DATE);
  const rand = seededRandom(DAILY_ORDER_SEED + day);
  const idx = Math.floor(rand() * HARD_MODE_SUCCESS_MARKS.length);
  return HARD_MODE_SUCCESS_MARKS[idx] ?? HARD_MODE_SUCCESS_MARKS[0];
}
