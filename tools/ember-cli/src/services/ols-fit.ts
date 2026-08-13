// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// ols-fit.ts — ordinary least squares slope over (x, y) points. Same method used to verify
// every regression claim across the #1455 investigation's soak legs (by hand, outside this
// codebase); factored out here so the closing regression test uses the identical formula rather
// than a re-derivation that could quietly diverge from what was actually verified.

export interface LinearFit {
  /** dy/dx in the same units as the input y values per unit x. */
  slope: number;
  intercept: number;
  /** Coefficient of determination. 1.0 = perfect fit, ~0 = no linear relationship (noise). */
  r2: number;
}

export function linearFit(points: ReadonlyArray<{ x: number; y: number }>): LinearFit {
  const n = points.length;
  if (n < 2) throw new Error(`linearFit requires at least 2 points, got ${n}`);
  const meanX = points.reduce((sum, p) => sum + p.x, 0) / n;
  const meanY = points.reduce((sum, p) => sum + p.y, 0) / n;
  const sxx = points.reduce((sum, p) => sum + (p.x - meanX) ** 2, 0);
  const sxy = points.reduce((sum, p) => sum + (p.x - meanX) * (p.y - meanY), 0);
  if (sxx === 0) throw new Error("linearFit requires at least two distinct x values");
  const slope = sxy / sxx;
  const intercept = meanY - slope * meanX;
  const ssTot = points.reduce((sum, p) => sum + (p.y - meanY) ** 2, 0);
  const ssRes = points.reduce((sum, p) => sum + (p.y - (intercept + slope * p.x)) ** 2, 0);
  const r2 = ssTot === 0 ? 1 : 1 - ssRes / ssTot;
  return { slope, intercept, r2 };
}
