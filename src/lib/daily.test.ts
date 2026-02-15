import { describe, expect, it } from "bun:test";
import { HARD_MODE_SUCCESS_MARKS, dayIndex, pickDailyHardModeSuccessMark } from "./daily";

describe("dayIndex", () => {
  it("is deterministic for a given date", () => {
    const date = new Date(2026, 1, 15);
    expect(dayIndex(10, date)).toBe(dayIndex(10, date));
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
