// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, expect, test } from "bun:test";
import { linearFit } from "./ols-fit.ts";

describe("linearFit", () => {
  test("recovers exact slope and intercept on a perfect line", () => {
    const points = Array.from({ length: 10 }, (_, i) => ({ x: i, y: 3 * i + 7 }));
    const fit = linearFit(points);
    expect(fit.slope).toBeCloseTo(3, 10);
    expect(fit.intercept).toBeCloseTo(7, 10);
    expect(fit.r2).toBeCloseTo(1, 10);
  });

  test("reports near-zero R2 for pure noise around a flat mean", () => {
    const noise = [5, -4, 6, -5, 4, -6, 5, -4];
    const points = noise.map((y, i) => ({ x: i, y }));
    const fit = linearFit(points);
    expect(Math.abs(fit.slope)).toBeLessThan(1);
    expect(fit.r2).toBeLessThan(0.2);
  });

  test("matches a hand-computed regression", () => {
    // y = 2x + 1 plus a small perturbation on one point
    const points = [
      { x: 0, y: 1 },
      { x: 1, y: 3 },
      { x: 2, y: 4 }, // would be 5 on the exact line
      { x: 3, y: 7 },
    ];
    const fit = linearFit(points);
    expect(fit.slope).toBeCloseTo(1.9, 5);
    expect(fit.intercept).toBeCloseTo(0.9, 5);
  });

  test("throws on fewer than 2 points", () => {
    expect(() => linearFit([])).toThrow();
    expect(() => linearFit([{ x: 0, y: 1 }])).toThrow();
  });

  test("throws when every point shares the same x", () => {
    expect(() => linearFit([{ x: 5, y: 1 }, { x: 5, y: 2 }])).toThrow();
  });
});
