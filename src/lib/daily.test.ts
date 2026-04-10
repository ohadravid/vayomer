import { describe, expect, it } from "vitest";
import { Temporal } from "@js-temporal/polyfill";
import {
  dateOverrideKey,
  dayIndex,
  pickDailyItemIndex,
  pickDailyItemIndexWithOverrides,
} from "./daily";

describe("dayIndex", () => {
  it("is deterministic for a given date", () => {
    const date = Temporal.PlainDate.from("2026-02-15");
    expect(dayIndex(10, date)).toBe(dayIndex(10, date));
  });

  it("handles non-positive totals safely", () => {
    const date = Temporal.PlainDate.from("2026-02-15");
    expect(dayIndex(0, date)).toBe(0);
    expect(dayIndex(-5, date)).toBe(0);
  });
});

describe("pickDailyItemIndex", () => {
  it("is deterministic for a given date", () => {
    const date = Temporal.PlainDate.from("2030-05-10");
    const items = [{ id: "a" }, { id: "b" }, { id: "c" }];
    expect(pickDailyItemIndex(items, date)).toBe(pickDailyItemIndex(items, date));
  });

  it("supports dates before the epoch date", () => {
    const items = Array.from({ length: 8 }, (_, idx) => ({ id: `item-${idx}` }));
    const idx = pickDailyItemIndex(items, Temporal.PlainDate.from("1901-01-01"));
    expect(idx).toBeGreaterThanOrEqual(0);
    expect(idx).toBeLessThan(items.length);
  });

  it("keeps the remaining order stable when an item is removed", () => {
    const start = Temporal.PlainDate.from("2026-03-16");
    const orderedItems = [{ id: "alpha" }, { id: "beta" }, { id: "gamma" }, { id: "delta" }];
    const filteredItems = orderedItems.filter((item) => item.id !== "gamma");

    const originalCycle = orderedItems.map((_, offset) => {
      const date = start.add({ days: offset });
      return orderedItems[pickDailyItemIndex(orderedItems, date)]?.id;
    });
    const filteredCycle = filteredItems.map((_, offset) => {
      const date = start.add({ days: offset });
      return filteredItems[pickDailyItemIndex(filteredItems, date)]?.id;
    });

    expect(originalCycle.filter((id) => id !== "gamma")).toEqual(filteredCycle);
  });
});

describe("date override selection", () => {
  it("formats override keys as local YYYY-MM-DD", () => {
    expect(dateOverrideKey(Temporal.PlainDate.from("2026-03-16"))).toBe("2026-03-16");
  });

  it("uses override id when present for that date", () => {
    const items = [{ id: "a" }, { id: "b" }, { id: "c" }];
    const date = Temporal.PlainDate.from("2026-03-16");
    const overrides = { "2026-03-16": "b" };
    expect(pickDailyItemIndexWithOverrides(items, date, overrides)).toBe(1);
  });

  it("falls back to regular daily selection when override id is missing", () => {
    const items = [{ id: "a" }, { id: "b" }, { id: "c" }];
    const date = Temporal.PlainDate.from("2026-03-16");
    const overrides = { "2026-03-16": "missing-id" };
    expect(pickDailyItemIndexWithOverrides(items, date, overrides)).toBe(pickDailyItemIndex(items, date));
  });

  it("supports recurring Gregorian month-day keys", () => {
    const items = [{ id: "a" }, { id: "b" }, { id: "c" }];
    const date = Temporal.PlainDate.from("2031-03-16");
    const overrides = { "03-16": "c" };
    expect(pickDailyItemIndexWithOverrides(items, date, overrides)).toBe(2);
  });

  it("uses the first matching override key", () => {
    const items = [{ id: "a" }, { id: "b" }, { id: "c" }];
    const date = Temporal.PlainDate.from("2026-03-16");
    const overrides = {
      "03-16": "a",
      "2026-03-16": "b",
    };
    expect(pickDailyItemIndexWithOverrides(items, date, overrides)).toBe(0);
  });

  it("supports recurring Hebrew month-day keys via PlainMonthDay strings", () => {
    const items = [{ id: "a" }, { id: "b" }, { id: "c" }];

    const hebrewA = Temporal.PlainDate.from({ calendar: "hebrew", year: 5786, monthCode: "M01", day: 1 });
    const hebrewB = Temporal.PlainDate.from({ calendar: "hebrew", year: 5787, monthCode: "M01", day: 1 });
    const isoA = hebrewA.withCalendar("iso8601");
    const isoB = hebrewB.withCalendar("iso8601");
    // Build an RFC 9557-compatible recurring key directly from Temporal.
    const recurringHebrewKey = hebrewA.toPlainMonthDay().toString();
    const overrides = { [recurringHebrewKey]: "c" };

    expect(pickDailyItemIndexWithOverrides(items, isoA, overrides)).toBe(2);
    expect(pickDailyItemIndexWithOverrides(items, isoB, overrides)).toBe(2);
  });

  it("supports full Hebrew dates via PlainDate RFC 9557 strings and keeps them year-specific", () => {
    const items = [{ id: "a" }, { id: "b" }, { id: "c" }];

    const hebrewA = Temporal.PlainDate.from({ calendar: "hebrew", year: 5786, monthCode: "M01", day: 1 });
    const hebrewB = Temporal.PlainDate.from({ calendar: "hebrew", year: 5787, monthCode: "M01", day: 1 });
    const isoA = hebrewA.withCalendar("iso8601");
    const isoB = hebrewB.withCalendar("iso8601");
    const fullHebrewKey = hebrewA.toString();
    const overrides = { [fullHebrewKey]: "b" };

    expect(pickDailyItemIndexWithOverrides(items, isoA, overrides)).toBe(1);
    expect(pickDailyItemIndexWithOverrides(items, isoB, overrides)).toBe(pickDailyItemIndex(items, isoB));
  });
});
