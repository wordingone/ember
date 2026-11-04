// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// extensions/cron-time.ts — when does a 5-field cron expression next fire (local time)?
//
// Fields: minute hour day-of-month month day-of-week. Each field is a comma list of
// `*`, `n`, `a-b`, with an optional `/step` (`*/5`, `10-30/5`). Day-of-week 7 is Sunday.
// When both day-of-month and day-of-week are restricted, either matching fires (cron rule).

const RANGES: Array<[number, number]> = [
  [0, 59],
  [0, 23],
  [1, 31],
  [1, 12],
  [0, 7],
];

export interface CronSpec {
  minutes: Set<number>;
  hours: Set<number>;
  doms: Set<number>;
  months: Set<number>;
  dows: Set<number>;
  domRestricted: boolean;
  dowRestricted: boolean;
}

function parseField(field: string, min: number, max: number): Set<number> | null {
  const out = new Set<number>();
  for (const part of field.split(",")) {
    const m = /^(\*|\d+(?:-\d+)?)(?:\/(\d+))?$/.exec(part);
    if (!m) return null;
    const step = m[2] === undefined ? 1 : parseInt(m[2], 10);
    if (step < 1) return null;
    let lo: number;
    let hi: number;
    if (m[1] === "*") {
      lo = min;
      hi = max;
    } else if (m[1]!.includes("-")) {
      const [a, b] = m[1]!.split("-").map((x) => parseInt(x, 10));
      lo = a!;
      hi = b!;
    } else {
      lo = parseInt(m[1]!, 10);
      hi = m[2] === undefined ? lo : max; // "5/10" means from 5 to the end, every 10
    }
    if (lo < min || hi > max || lo > hi) return null;
    for (let v = lo; v <= hi; v += step) out.add(v);
  }
  return out.size > 0 ? out : null;
}

/** Parses a cron expression; null when it is not a valid 5-field expression. */
export function parseCron(expr: string): CronSpec | null {
  const fields = expr.trim().split(/\s+/);
  if (fields.length !== 5) return null;
  const sets = fields.map((f, i) => parseField(f, RANGES[i]![0], RANGES[i]![1]));
  if (sets.some((s) => s === null)) return null;
  const [minutes, hours, doms, months, dows] = sets as Set<number>[];
  if (dows!.has(7)) dows!.add(0);
  return {
    minutes: minutes!,
    hours: hours!,
    doms: doms!,
    months: months!,
    dows: dows!,
    domRestricted: fields[2] !== "*",
    dowRestricted: fields[4] !== "*",
  };
}

function dayMatches(spec: CronSpec, d: Date): boolean {
  const domOk = spec.doms.has(d.getDate());
  const dowOk = spec.dows.has(d.getDay());
  if (spec.domRestricted && spec.dowRestricted) return domOk || dowOk;
  return domOk && dowOk;
}

/**
 * The first fire time strictly after `afterMs` (epoch ms, local time rules), or null when the
 * expression is invalid or never fires within the next ~5 years (e.g. Feb 30).
 */
export function nextCronTime(expr: string, afterMs: number): number | null {
  const spec = parseCron(expr);
  if (!spec) return null;
  const d = new Date(afterMs);
  d.setSeconds(0, 0);
  d.setMinutes(d.getMinutes() + 1);
  const limit = afterMs + 5 * 366 * 24 * 3600 * 1000;
  while (d.getTime() <= limit) {
    if (!spec.months.has(d.getMonth() + 1)) {
      d.setMonth(d.getMonth() + 1, 1);
      d.setHours(0, 0, 0, 0);
      continue;
    }
    if (!dayMatches(spec, d)) {
      d.setDate(d.getDate() + 1);
      d.setHours(0, 0, 0, 0);
      continue;
    }
    if (!spec.hours.has(d.getHours())) {
      d.setHours(d.getHours() + 1, 0, 0, 0);
      continue;
    }
    if (!spec.minutes.has(d.getMinutes())) {
      d.setMinutes(d.getMinutes() + 1, 0, 0);
      continue;
    }
    return d.getTime();
  }
  return null;
}
