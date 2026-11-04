// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// extensions/scheduler.test.ts — issue #2376 acceptance, at unit level:
//   * a job scheduled 1 minute ahead fires once (and only while the TUI is idle)
//   * /loop <interval> <prompt> runs the prompt now and again each interval, and Esc stops it
//   * cron expressions compute their next fire time correctly

import { afterEach, beforeEach, describe, expect, it } from "bun:test";
import type { ToolUseContext } from "../core/tool-interface.ts";
import {
  CronCreateTool,
  CronListTool,
  _resetCronStore,
  cronJobCount,
  takeNextDueCronJob,
} from "../tools/schedule-cron.ts";
import { nextCronTime, parseCron } from "./cron-time.ts";
import {
  SchedulerTicker,
  _resetSchedulerForTests,
  formatInterval,
  hasActiveLoops,
  listLoops,
  parseInterval,
} from "./scheduler.ts";
import type { DuePrompt } from "./scheduler.ts";
import { createExtensionCommands } from "./commands.ts";
import { stopLoopsOnEscape } from "./repl-seam.ts";

const lead = {} as ToolUseContext;

beforeEach(() => {
  _resetCronStore();
  _resetSchedulerForTests();
});
afterEach(() => {
  _resetCronStore();
  _resetSchedulerForTests();
});

/** Local-time epoch ms for Y-M-D h:m. */
const at = (y: number, mo: number, d: number, h: number, mi: number): number => new Date(y, mo - 1, d, h, mi, 0, 0).getTime();

describe("cron next-fire time", () => {
  it("steps, lists, ranges and fixed times", () => {
    expect(nextCronTime("*/5 * * * *", at(2026, 11, 3, 10, 2))).toBe(at(2026, 11, 3, 10, 5));
    expect(nextCronTime("*/5 * * * *", at(2026, 11, 3, 10, 5))).toBe(at(2026, 11, 3, 10, 10)); // strictly after
    expect(nextCronTime("30 14 * * *", at(2026, 11, 3, 15, 0))).toBe(at(2026, 11, 4, 14, 30));
    expect(nextCronTime("0,15,45 9 * * *", at(2026, 11, 3, 9, 20))).toBe(at(2026, 11, 3, 9, 45));
    expect(nextCronTime("10-12 * * * *", at(2026, 11, 3, 9, 20))).toBe(at(2026, 11, 3, 10, 10));
    expect(nextCronTime("0 9 5 12 *", at(2026, 11, 3, 9, 0))).toBe(at(2026, 12, 5, 9, 0));
  });

  it("day-of-week (7 is Sunday) and the dom/dow OR rule", () => {
    // 2026-11-03 is a Tuesday
    expect(nextCronTime("0 9 * * 1", at(2026, 11, 3, 8, 0))).toBe(at(2026, 11, 9, 9, 0));
    expect(nextCronTime("0 9 * * 7", at(2026, 11, 3, 8, 0))).toBe(at(2026, 11, 8, 9, 0));
    expect(nextCronTime("0 9 * * 1-5", at(2026, 11, 7, 10, 0))).toBe(at(2026, 11, 9, 9, 0)); // Sat -> Mon
    // both restricted: the 10th OR any Friday -> next is Fri 2026-11-06
    expect(nextCronTime("0 9 10 * 5", at(2026, 11, 3, 8, 0))).toBe(at(2026, 11, 6, 9, 0));
  });

  it("rejects bad expressions and ones that never fire", () => {
    expect(parseCron("* * * *")).toBeNull();
    expect(parseCron("61 * * * *")).toBeNull();
    expect(parseCron("*/0 * * * *")).toBeNull();
    expect(nextCronTime("0 0 30 2 *", at(2026, 1, 1, 0, 0))).toBeNull();
  });
});

describe("CronCreate jobs actually fire", () => {
  async function schedule(cron: string, prompt: string, recurring: boolean): Promise<string> {
    const r = (await CronCreateTool.call({ cron, prompt, recurring } as never, lead, undefined as never, undefined as never)) as { data: { id: string } };
    return r.data.id;
  }

  it("a one-shot job scheduled for the next minute fires exactly once", async () => {
    const now = Date.now();
    const next = new Date(now + 60_000);
    const cron = `${next.getMinutes()} ${next.getHours()} ${next.getDate()} ${next.getMonth() + 1} *`;
    const id = await schedule(cron, "ping the build", false);

    const fireTime = nextCronTime(cron, now)!;
    expect(fireTime).toBeGreaterThan(now);
    expect(fireTime - now).toBeLessThanOrEqual(120_000);

    const fired: DuePrompt[] = [];
    let clock = now;
    let idle = true;
    const ticker = new SchedulerTicker({ isIdle: () => idle, fire: (d) => fired.push(d), now: () => clock });

    ticker.tick();
    expect(fired).toEqual([]); // not yet due
    clock = fireTime - 1;
    ticker.tick();
    expect(fired).toEqual([]);
    clock = fireTime;
    ticker.tick();
    expect(fired).toEqual([{ source: "cron", id, prompt: "ping the build" }]);
    clock = fireTime + 10 * 60_000;
    ticker.tick();
    ticker.tick();
    expect(fired).toHaveLength(1); // once, ever
    expect(cronJobCount()).toBe(0);
  });

  it("only fires while idle; a job that came due while busy fires once, late", async () => {
    const id = await schedule("*/1 * * * *", "tick", true);
    const job = (await CronListTool.call({} as never, lead, undefined as never, undefined as never)) as { data: { jobs: Array<{ id: string; nextFire: string }> } };
    const due = Date.parse(job.data.jobs[0]!.nextFire);

    const fired: DuePrompt[] = [];
    let idle = false;
    let clock = due + 5 * 60_000; // five minutes overdue, but the TUI is busy
    const ticker = new SchedulerTicker({ isIdle: () => idle, fire: (d) => fired.push(d), now: () => clock });
    ticker.tick();
    ticker.tick();
    expect(fired).toEqual([]);
    idle = true;
    ticker.tick();
    expect(fired.map((f) => f.id)).toEqual([id]);
    ticker.tick(); // rescheduled from `now`: no burst of five missed runs
    expect(fired).toHaveLength(1);
    clock += 61_000;
    ticker.tick();
    expect(fired).toHaveLength(2); // a recurring job keeps going
    expect(cronJobCount()).toBe(1);
  });

  it("takeNextDueCronJob hands out one job per call", async () => {
    const a = await schedule("* * * * *", "a", false);
    const b = await schedule("* * * * *", "b", false);
    const later = Date.now() + 5 * 60_000;
    expect(takeNextDueCronJob(later)?.id).toBe(a);
    expect(takeNextDueCronJob(later)?.id).toBe(b);
    expect(takeNextDueCronJob(later)).toBeNull();
  });

  it("CronCreate refuses an expression that never fires", async () => {
    let msg = "";
    try {
      await schedule("0 0 30 2 *", "never", false);
    } catch (e) {
      msg = (e as Error).message;
    }
    expect(msg).toContain("never fires");
  });
});

describe("/loop", () => {
  const loop = createExtensionCommands().find((c) => c.name === "loop")!;
  const ctx = { sessionId: "s", mode: "regular", cwd: process.cwd() };

  it("parses intervals", () => {
    expect(parseInterval("30s")).toBe(30_000);
    expect(parseInterval("1m")).toBe(60_000);
    expect(parseInterval("2h")).toBe(7_200_000);
    expect(parseInterval("1d")).toBe(86_400_000);
    expect(parseInterval("soon")).toBeNull();
    expect(formatInterval(60_000)).toBe("1m");
    expect(formatInterval(90_000)).toBe("90s");
  });

  it("/loop 1m <prompt> runs now, runs again after a minute (twice in all), and Esc stops it", async () => {
    const t0 = Date.now();
    const started = await loop.execute("1m check the build", ctx);
    expect(started).toMatchObject({ prompt: "check the build" }); // run #1 happens now, via the REPL turn
    expect(hasActiveLoops()).toBe(true);
    expect(listLoops()[0]!.nextFireAt).toBeGreaterThanOrEqual(t0 + 60_000);

    const fired: DuePrompt[] = [];
    let clock = t0 + 30_000;
    const ticker = new SchedulerTicker({ isIdle: () => true, fire: (d) => fired.push(d), now: () => clock });
    ticker.tick();
    expect(fired).toEqual([]); // 30 s in: not yet
    clock = t0 + 61_000;
    ticker.tick();
    expect(fired.map((f) => f.prompt)).toEqual(["check the build"]); // run #2
    expect(fired[0]!.source).toBe("loop");

    expect(stopLoopsOnEscape()).toBe("Stopped 1 loop.");
    expect(hasActiveLoops()).toBe(false);
    clock = t0 + 10 * 60_000;
    ticker.tick();
    expect(fired).toHaveLength(1); // stopped: no third run
    expect(stopLoopsOnEscape()).toBeNull(); // nothing left to stop
  });

  it("a loop does not fire while the TUI is busy or being typed in", async () => {
    await loop.execute("1m again", ctx);
    const fired: DuePrompt[] = [];
    let idle = false;
    const clock = Date.now() + 5 * 60_000;
    const ticker = new SchedulerTicker({ isIdle: () => idle, fire: (d) => fired.push(d), now: () => clock });
    ticker.tick();
    expect(fired).toEqual([]);
    idle = true;
    ticker.tick();
    expect(fired).toHaveLength(1);
  });

  it("explains itself when misused, and /loop stop stops everything", async () => {
    expect((await loop.execute("", ctx))?.message).toContain("Usage: /loop");
    expect((await loop.execute("banana do it", ctx))?.message).toContain("Could not read an interval");
    expect((await loop.execute("1s too fast", ctx))?.message).toContain("shortest loop interval");
    expect(hasActiveLoops()).toBe(false);
    await loop.execute("5m one", ctx);
    await loop.execute("10m two", ctx);
    expect((await loop.execute("stop", ctx))?.message).toBe("Stopped 2 loop(s).");
    expect(hasActiveLoops()).toBe(false);
  });
});
