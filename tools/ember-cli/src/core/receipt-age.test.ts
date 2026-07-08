import { describe, it, expect } from "bun:test";
import { formatReceiptAge, isReceiptStale } from "./receipt-age.ts";

describe("formatReceiptAge", () => {
  it("should format receipts produced just now", () => {
    const now = Date.now();
    const boardTs = new Date(now).toISOString();
    expect(formatReceiptAge(boardTs, now)).toBe("just now");
  });

  it("should format receipts from minutes ago", () => {
    const now = Date.now();
    const fiveMinutesAgo = now - 5 * 60 * 1000;
    const boardTs = new Date(fiveMinutesAgo).toISOString();
    expect(formatReceiptAge(boardTs, now)).toBe("5m ago");
  });

  it("should format receipts from hours and minutes ago", () => {
    const now = Date.now();
    const twoHoursFifteenMinutesAgo = now - (2 * 60 * 60 * 1000 + 15 * 60 * 1000);
    const boardTs = new Date(twoHoursFifteenMinutesAgo).toISOString();
    expect(formatReceiptAge(boardTs, now)).toBe("2h15m ago");
  });

  it("should return false for a receipt inside the 2h cadence window (not a wolf-cry)", () => {
    const now = Date.now();
    const oneHourAgo = now - 60 * 60 * 1000;
    const boardTs = new Date(oneHourAgo).toISOString();
    expect(isReceiptStale(boardTs, now)).toBe(false);
  });

  it("should return true for stale receipts (>2h)", () => {
    const now = Date.now();
    const threeHoursAgo = now - 3 * 60 * 60 * 1000;
    const boardTs = new Date(threeHoursAgo).toISOString();
    expect(isReceiptStale(boardTs, now)).toBe(true);
  });
});
