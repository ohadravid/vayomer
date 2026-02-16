import { describe, expect, it } from "bun:test";
import { HARD_MODE_SUCCESS_MARKS, dayIndex, pickDailyHardModeSuccessMark, pickDailyItemIndex } from "./daily";

describe("dayIndex", () => {
  it("is deterministic for a given date", () => {
    const date = new Date(2026, 1, 15);
    expect(dayIndex(10, date)).toBe(dayIndex(10, date));
  });

  it("handles non-positive totals safely", () => {
    expect(dayIndex(0, new Date(2026, 1, 15))).toBe(0);
    expect(dayIndex(-5, new Date(2026, 1, 15))).toBe(0);
  });
});

describe("pickDailyItemIndex", () => {
  it("is deterministic for a given date", () => {
    const date = new Date(2030, 4, 10, 18, 22, 31);
    expect(pickDailyItemIndex(17, date)).toBe(pickDailyItemIndex(17, date));
  });

  it("supports dates before the epoch date", () => {
    const idx = pickDailyItemIndex(8, new Date(1901, 0, 1));
    expect(idx).toBeGreaterThanOrEqual(0);
    expect(idx).toBeLessThan(8);
  });
});

describe("pickDailyHardModeSuccessMark", () => {
  it("returns one of the allowed hard-mode marks", () => {
    const mark = pickDailyHardModeSuccessMark(new Date(2026, 1, 15));
    expect(HARD_MODE_SUCCESS_MARKS).toContain(mark);
  });

  it("is deterministic per day", () => {
    const date = new Date(2026, 1, 15, 9, 10, 0);
    const sameDay = new Date(2026, 1, 15, 23, 59, 59);
    expect(pickDailyHardModeSuccessMark(date)).toBe(pickDailyHardModeSuccessMark(sameDay));
  });
});
