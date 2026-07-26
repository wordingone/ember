// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// components/activity-feed-pane.test.ts — issue #485 rung 1: pure formatting + render tests
// for the activity feed pane. Follows the DegradedBanner/EffortCallout convention (call the
// component function directly, inspect the returned element's props — no render harness).

import { describe, it, expect } from "bun:test";
import {
  truncateMiddle,
  truncatePathLeft,
  visibleActivityFeedLines,
  formatActivityFeedLine,
  ActivityFeedPane,
  EMPTY_STATE_TEXT,
  DEFAULT_VISIBLE_LINES,
  formatActivityBlockTimestamp,
  ACTIVITY_GLYPH,
  ACTIVITY_SOURCE_DISPLAY,
  ActivityTranscriptBlock,
  type ActivityFeedLine,
} from "./activity-feed-pane.ts";

function line(overrides: Partial<ActivityFeedLine> = {}): ActivityFeedLine {
  return {
    ts: "2026-07-08T00:00:00.000Z",
    source: "receipt",
    text: "receipt landed [acceptance] foo.json",
    ...overrides,
  };
}

describe("truncateMiddle", () => {
  it("returns the string unchanged when within the limit", () => {
    expect(truncateMiddle("short.json", 48)).toBe("short.json");
  });

  it("middle-truncates a long path with a single ellipsis", () => {
    const long = "receipts/ember-d3-native-loop/d3-broader-multifamily-loop-20260621T145316Z/result.json";
    const result = truncateMiddle(long, 40);
    expect(result.length).toBeLessThanOrEqual(40);
    expect(result).toContain("…");
    expect(result.startsWith("receipts/")).toBe(true);
    expect(result.endsWith("result.json")).toBe(true);
  });

  it("never grows the string", () => {
    const long = "a".repeat(200);
    expect(truncateMiddle(long, 50).length).toBeLessThanOrEqual(50);
  });
});

// Legibility bar (2026-07-26): "paths truncate from the left with a marker, consistently
// everywhere" -- the operator's own measured defect showed one path rendered middle-truncated
// (via truncateMiddle above) and a sibling path in the same frame hard-clipped raw with NO marker
// at all. truncatePathLeft is the one rule every path surface now routes through.
describe("truncatePathLeft", () => {
  it("returns the string unchanged when within the limit", () => {
    expect(truncatePathLeft("short.json", 48)).toBe("short.json");
  });

  it("drops the FRONT of a long path and keeps the tail, with a single leading ellipsis", () => {
    const long = "Z:\\repo\\ember\\tools\\ember-cli\\state\\process-watch.json";
    const result = truncatePathLeft(long, 20);
    expect(result.length).toBeLessThanOrEqual(20);
    expect(result.startsWith("…")).toBe(true);
    expect(long.endsWith(result.slice(1))).toBe(true);
  });

  it("never grows the string", () => {
    const long = "a".repeat(200);
    expect(truncatePathLeft(long, 50).length).toBeLessThanOrEqual(50);
  });

  it("a budget of 1 renders just the marker; a budget of 0 renders empty", () => {
    expect(truncatePathLeft("a".repeat(10), 1)).toBe("…");
    expect(truncatePathLeft("a".repeat(10), 0)).toBe("");
  });
});

describe("visibleActivityFeedLines", () => {
  it("returns everything when under the cap, oldest-first", () => {
    const lines = [line({ text: "a" }), line({ text: "b" })];
    expect(visibleActivityFeedLines(lines, 6)).toEqual(lines);
  });

  it("keeps only the last N, newest last", () => {
    const lines = [1, 2, 3, 4, 5].map((n) => line({ text: String(n) }));
    const visible = visibleActivityFeedLines(lines, 2);
    expect(visible.map((l) => l.text)).toEqual(["4", "5"]);
  });

  it("returns empty for maxVisible=0", () => {
    expect(visibleActivityFeedLines([line()], 0)).toEqual([]);
  });
});

describe("formatActivityFeedLine", () => {
  it("includes age, source tag, text, and truncated path", () => {
    const nowMs = Date.parse("2026-07-08T00:05:00.000Z");
    const result = formatActivityFeedLine(
      line({ path: "receipts/acceptance/foo.json" }),
      nowMs,
    );
    expect(result).toContain("5m ago");
    expect(result).toContain("[receipt]");
    expect(result).toContain("receipt landed [acceptance] foo.json");
    expect(result).toContain("[receipts/acceptance/foo.json]");
  });

  it("omits the path suffix when no path is present", () => {
    const result = formatActivityFeedLine(line({ path: undefined }), Date.parse(line().ts));
    expect(result).not.toContain("[receipts");
    expect(result.endsWith("]")).toBe(false);
  });

  it("truncates a long path in the rendered line", () => {
    const longPath = "receipts/" + "x".repeat(100) + "/foo.json";
    const result = formatActivityFeedLine(line({ path: longPath }), Date.parse(line().ts), 30);
    expect(result).toContain("…");
    expect(result).not.toContain(longPath);
  });

  // Legibility bar (2026-07-26): path truncation is left-truncation (drop the front, keep the
  // identifying tail) everywhere, not middle-truncation -- RED on pre-fix master, which routed
  // this through truncateMiddle (keeps BOTH head and tail).
  it("truncates the path from the LEFT (keeps the filename tail, drops the front)", () => {
    const longPath = "Z:\\repo\\ember\\tools\\ember-cli\\state\\process-watch.json";
    const result = formatActivityFeedLine(line({ path: longPath }), Date.parse(line().ts), 20);
    expect(result).toContain(truncatePathLeft(longPath, 20));
    expect(result).toContain("[…");
    expect(result).toContain("process-watch.json");
    expect(result).not.toContain("Z:\\repo\\ember");
  });
});

describe("ActivityFeedPane", () => {
  it("renders the empty-state line when there are no events yet", () => {
    const el = ActivityFeedPane({ lines: [] });
    const children = (el as { props: { children: unknown[] } }).props.children;
    expect(Array.isArray(children) ? children.length : 1).toBe(1);
    const first = Array.isArray(children) ? children[0] : children;
    expect((first as { props: { children: string } }).props.children).toBe(EMPTY_STATE_TEXT);
  });

  it("renders one Text row per visible line, bounded by maxVisible", () => {
    const lines = [1, 2, 3, 4, 5, 6, 7, 8].map((n) => line({ text: `event-${n}` }));
    const el = ActivityFeedPane({ lines, maxVisible: 3, nowMs: Date.parse(line().ts) });
    const children = (el as { props: { children: unknown[] } }).props.children as Array<{
      props: { children: string };
    }>;
    expect(children.length).toBe(3);
    expect(children[children.length - 1].props.children).toContain("event-8");
  });

  it("defaults maxVisible to DEFAULT_VISIBLE_LINES", () => {
    const lines = Array.from({ length: 20 }, (_, i) => line({ text: `e${i}` }));
    const el = ActivityFeedPane({ lines, nowMs: Date.parse(line().ts) });
    const children = (el as { props: { children: unknown[] } }).props.children as unknown[];
    expect(children.length).toBe(DEFAULT_VISIBLE_LINES);
  });
});

// ---------------------------------------------------------------------------
// #518 — transcript-block rendering (replaces the ticker as the mounted path)
// ---------------------------------------------------------------------------

describe("formatActivityBlockTimestamp", () => {
  it("renders time-only for a same-day event, no relative-age wording", () => {
    const nowMs = Date.parse("2026-07-08T21:05:00.000Z");
    const result = formatActivityBlockTimestamp("2026-07-08T20:59:00.000Z", nowMs);
    expect(result).toBe("8:59pm");
    expect(result).not.toContain("ago");
  });

  it("prefixes a numeric M/D date for an earlier-day event", () => {
    const nowMs = Date.parse("2026-07-09T02:00:00.000Z");
    const result = formatActivityBlockTimestamp("2026-07-08T20:59:00.000Z", nowMs);
    expect(result).toBe("7/8 8:59pm");
  });

  it("handles midnight (12am) and noon (12pm) correctly", () => {
    const nowMs = Date.parse("2026-07-08T12:00:00.000Z");
    expect(formatActivityBlockTimestamp("2026-07-08T00:00:00.000Z", nowMs)).toBe("12:00am");
    expect(formatActivityBlockTimestamp("2026-07-08T12:00:00.000Z", nowMs)).toBe("12:00pm");
  });

  it("falls back to the raw string for an unparsable timestamp", () => {
    expect(formatActivityBlockTimestamp("not-a-date")).toBe("not-a-date");
  });
});

describe("ACTIVITY_SOURCE_DISPLAY", () => {
  it("defines a label and color for every ActivityFeedSource", () => {
    const sources: ActivityFeedLine["source"][] = ["receipt", "outage", "watchdog", "board", "goal"];
    for (const source of sources) {
      const display = ACTIVITY_SOURCE_DISPLAY[source];
      expect(display.label.length).toBeGreaterThan(0);
      expect(display.color.length).toBeGreaterThan(0);
    }
  });

  it("gives the goal source its own color, distinct from the other four (ember #211 §7 delta 4)", () => {
    const otherColors = new Set(
      (["receipt", "outage", "watchdog", "board"] as const).map((s) => ACTIVITY_SOURCE_DISPLAY[s].color),
    );
    expect(otherColors.has(ACTIVITY_SOURCE_DISPLAY.goal.color)).toBe(false);
  });

  it("shares one glyph across every source (field-ux-map §9: no per-category emoji salad)", () => {
    expect(ACTIVITY_GLYPH.length).toBeGreaterThan(0);
    // No per-source glyph field exists on the display record -- distinguishing power comes
    // from color + label text only, never a bespoke icon per category.
    const receiptKeys = Object.keys(ACTIVITY_SOURCE_DISPLAY.receipt);
    expect(receiptKeys).not.toContain("glyph");
  });
});

describe("ActivityTranscriptBlock", () => {
  it("renders a header row, a text row, and no path row when path is absent", () => {
    const el = ActivityTranscriptBlock({
      line: line({ path: undefined }),
      nowMs: Date.parse(line().ts),
    });
    const children = (el as { props: { children: unknown[] } }).props.children;
    expect(children.length).toBe(3);
    expect(children[2]).toBeNull();
  });

  it("includes a path row when the event carries a path", () => {
    const el = ActivityTranscriptBlock({
      line: line({ path: "receipts/acceptance/foo.json" }),
      nowMs: Date.parse(line().ts),
    });
    const children = (el as { props: { children: unknown[] } }).props.children;
    expect(children[2]).not.toBeNull();
  });

  it("never emits a relative-age string anywhere in the card (the named defect)", () => {
    const el = ActivityTranscriptBlock({
      line: line({ path: "receipts/acceptance/foo.json" }),
      nowMs: Date.parse("2026-07-08T03:00:00.000Z"),
    });
    const serialized = JSON.stringify(el);
    expect(serialized).not.toContain(" ago");
  });

  it("uses the source's own label and the shared glyph in the header", () => {
    const el = ActivityTranscriptBlock({
      line: line({ source: "board", text: "totality board rendered: 3 GREEN / 1 RED" }),
      nowMs: Date.parse(line().ts),
    });
    const serialized = JSON.stringify(el);
    expect(serialized).toContain(ACTIVITY_SOURCE_DISPLAY.board.label);
    expect(serialized).toContain(ACTIVITY_GLYPH);
  });
});
