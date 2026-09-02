// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// #1701: the #1700 dedup (services/poll-failure-dedup.ts) correctly stopped the raw-stdout
// bleed, but it republishes a NEW activity-feed/transcript entry every POLL_FAILURE_DEDUP_
// INTERVAL_MS (15s) window for as long as a failure class stays active. An idle OFFLINE
// cockpit accumulates ~4 entries/min forever across the interleaved failure classes, burying
// real operator activity. The steady state of a KNOWN, UNCHANGED failure class is STATUS, not
// news: it must render as one in-place, updating status element, and the transcript/ledger
// must gain at most one entry per failure class per TRANSITION (first-seen / message-changed /
// recovered) -- never one per dedup window.
//
// This test mounts the real ReplScreen (same technique as repl-offline-stdout-bleed.test.ts)
// with no EMBER_LAB_PIPE set (OFFLINE) and lets the real memory-footprint supervisor fail on
// its real ~1s poll cadence for long enough to cross three real POLL_FAILURE_DEDUP_INTERVAL_MS
// (15s) window boundaries. It reads the SAME activity-feed engine state the live render path
// consumes (services/activity-feed.ts's getActivityFeedState(), the exact source
// screens/repl.ts's own activity-poll effect and components/operator-surface-pane.ts's
// agentLines both read) -- never a reimplementation of the dedup/activity-feed mechanism.
import { afterEach, beforeEach, describe, expect, spyOn, test } from "bun:test";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../ink/rendering-pipeline.ts";
import { TerminalSizeContext } from "../ink/components.ts";
import { resetCommandRegistryForTests } from "../command-registry.ts";
import { getActivityFeedState } from "../services/activity-feed.ts";
import { ReplScreen } from "../screens/repl.ts";

async function wait(ms: number): Promise<void> {
  await new Promise<void>((resolve) => setTimeout(resolve, ms));
}

function renderedLines(raw: string, columns: number, rows: number): string[] {
  const frame = buildFrame(columns, rows);
  parseRenderedIntoFrame(raw, frame, new StylePool());
  return frame.cells.map((line) => line.map((cell) => cell?.char ?? " ").join(""));
}

// Three real POLL_FAILURE_DEDUP_INTERVAL_MS (15_000ms) windows, plus margin for the first-poll
// timing and tick jitter around each boundary. Deliberately real wall-clock: the defect this
// guards is a real-time steady-state ticker, and no fake-timer harness exists in this suite for
// screens/repl.ts's live setInterval-driven pollers -- compressing it would mean testing a
// reimplementation of the timing, not the real one.
const OBSERVE_MS = 47_000;

describe("cockpit OFFLINE idle: sticky per-class failure status, not a repeating ticker (regression #1701)", () => {
  let mounted: ReturnType<typeof mountInk> | null = null;
  let warnSpy: ReturnType<typeof spyOn>;
  let errorSpy: ReturnType<typeof spyOn>;
  const previousPipe = process.env.EMBER_LAB_PIPE;

  beforeEach(() => {
    delete process.env.EMBER_LAB_PIPE;
    warnSpy = spyOn(console, "warn").mockImplementation(() => {});
    errorSpy = spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    mounted?.unmount();
    mounted = null;
    warnSpy.mockRestore();
    errorSpy.mockRestore();
    if (previousPipe === undefined) delete process.env.EMBER_LAB_PIPE;
    else process.env.EMBER_LAB_PIPE = previousPipe;
  });

  test(
    "an unchanged OFFLINE failure class gains at most one activity-feed entry across 3 dedup windows, and renders as one updating in-place status line",
    async () => {
      resetCommandRegistryForTests();
      let raw = "";
      const config = { model: "ember", permissionMode: "bypass" as const, baseSystemPrompt: "" };
      const columns = 120, rows = 44;
      const element = React.createElement(
        TerminalSizeContext.Provider,
        { value: { columns, rows } },
        React.createElement(ReplScreen, {
          config,
          cwd: process.cwd(),
          env: { EMBER_DISABLE_TERMINAL_TITLE: "1", EMBER_DISABLE_VIRTUAL_SCROLL: "1" },
          onExit: () => {},
        }),
      );
      mounted = mountInk(element, {
        stream: { write(s: string) { raw += s; } },
        stdout: { columns, rows },
      });

      await wait(OBSERVE_MS);

      // The real memory-footprint supervisor polls every ~1s offline and fails with the SAME
      // ownership-unavailable message on every tick (no live Ember Lab pipe to identify) -- the
      // exact "known, unchanged failure class" steady state #1701 is about. Filtered by the
      // stable message PREFIX (never the full string): the suffix carries the underlying
      // connect error's own message, which is deterministic per-cause but not asserted on here.
      const ownershipEntries = getActivityFeedState().recentLines.filter(
        (line) =>
          line.source === "watchdog" &&
          line.text.startsWith("[memory-footprint] Ember Lab process identity unavailable:"),
      );

      // Pre-fix (current master): services/poll-failure-dedup.ts republishes once per elapsed
      // 15s window, so >=47s of continuous identical failure produces multiple entries here.
      // Post-fix: the class transitioned into "active" exactly once (first-seen) and never
      // again, because the message never changed and the class never recovered.
      expect(ownershipEntries.length).toBeLessThanOrEqual(1);

      // #1701 acceptance clause 2: the persistent class also renders as ONE in-place status
      // element (class, message, running count, since-timestamp) in the status/watchdog region
      // -- never only in the scrolling transcript. Loose on exact layout (column width/border
      // glyphs); strict only on the class key being visibly present on the live frame.
      const frameText = renderedLines(raw, columns, rows).join("\n");
      expect(frameText).toContain("memory-footprint:ownership");
    },
    60_000,
  );
});
