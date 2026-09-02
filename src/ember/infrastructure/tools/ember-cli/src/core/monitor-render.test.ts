// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// core/monitor-render.test.ts — unit coverage for the `monitor` cockpit surface's pure
// rendering helpers (issue: monitor verb was an unusable per-row verdict dump + a pct_complete
// field-read bug reading zero). Covers: truncation rules, color on/off fallback, not-green-first
// ordering with evidence-index consistency, and the full renderMonitor() composition.

import { describe, it, expect } from "bun:test";
import type { Claim, EmberWorldState } from "./ember-world-state.ts";
import {
  ANSI,
  colorEnabledFor,
  splitStatusAndReason,
  isGreenStatus,
  statusGlyph,
  truncateReason,
  sortMonitorConditions,
  conditionName,
  buildTopAttentionLines,
  formatBoardTransitionEvent,
  formatCockpitRestartEvent,
  COCKPIT_RESTART_GAP_THRESHOLD_MS,
  renderMonitor,
  renderMonitorPanel,
  visiblePanelWidth,
  truncateAnsiLineToWidth,
} from "./monitor-render.ts";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function claim(condition: string, status: string, reason: string): Claim {
  return {
    id: `board.${condition}`,
    label: `[?] ${condition}`,
    detail: `${status}: ${reason}`,
    evidence: { path: "scripts/ember_totality/receipts-totality/fixture.json", sha256: "deadbeef" },
  };
}

function stateWith(conditions: Claim[], overrides: Partial<EmberWorldState["monitor"]> = {}): EmberWorldState {
  const green = conditions.filter((c) => splitStatusAndReason(c.detail).status === "GREEN").length;
  const red = conditions.filter((c) => splitStatusAndReason(c.detail).status === "RED").length;
  return {
    ts: "2026-07-03T00:00:00.000Z",
    monitor: {
      boardTs: "20260703T120000Z",
      total: conditions.length,
      green,
      red,
      pctComplete: 76.7,
      conditions,
      ...overrides,
    },
    understand: { goalTitle: "fixture", topology: [] },
    interact: { ledgerRows: [] },
    sources: {
      goal: { path: "docs/domains/governance/authority/GOAL.md", sha256: "x" },
      ledger: { path: "docs/domains/governance/ledgers/ember-debt-ledger.md", sha256: "x" },
      board: { path: "scripts/ember_totality/receipts-totality/fixture.json", sha256: "x" },
    },
  };
}

// ---------------------------------------------------------------------------
// splitStatusAndReason / isGreenStatus
// ---------------------------------------------------------------------------

describe("splitStatusAndReason", () => {
  it("splits on the first ': '", () => {
    expect(splitStatusAndReason("GREEN: all good")).toEqual({ status: "GREEN", reason: "all good" });
  });

  it("does not split on later colons inside the reason", () => {
    const r = splitStatusAndReason("RED: verdict=FAIL: retry needed");
    expect(r.status).toBe("RED");
    expect(r.reason).toBe("verdict=FAIL: retry needed");
  });

  it("falls back to status='' when there is no ': ' at all", () => {
    expect(splitStatusAndReason("no colon here")).toEqual({ status: "", reason: "no colon here" });
  });
});

describe("isGreenStatus", () => {
  it("is true only for the literal string GREEN", () => {
    expect(isGreenStatus("GREEN")).toBe(true);
    expect(isGreenStatus("RED")).toBe(false);
    expect(isGreenStatus("AUDIT-OK")).toBe(false);
    expect(isGreenStatus("AUDIT-INCIDENT")).toBe(false);
    expect(isGreenStatus("")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// statusGlyph
// ---------------------------------------------------------------------------

describe("statusGlyph", () => {
  it("GREEN -> green glyph", () => {
    expect(statusGlyph("GREEN")).toEqual({ glyph: "[G]", color: ANSI.green });
  });
  it("RED -> red glyph", () => {
    expect(statusGlyph("RED")).toEqual({ glyph: "[R]", color: ANSI.red });
  });
  it("any AUDIT-* variant -> yellow glyph", () => {
    expect(statusGlyph("AUDIT-OK")).toEqual({ glyph: "[A]", color: ANSI.yellow });
    expect(statusGlyph("AUDIT-INCIDENT")).toEqual({ glyph: "[A]", color: ANSI.yellow });
    expect(statusGlyph("AUDIT-PENDING-EPOCH")).toEqual({ glyph: "[A]", color: ANSI.yellow });
  });
  it("unknown status -> plain glyph, no color", () => {
    expect(statusGlyph("WHATEVER")).toEqual({ glyph: "[?]", color: "" });
  });
});

// ---------------------------------------------------------------------------
// truncateReason
// ---------------------------------------------------------------------------

describe("truncateReason", () => {
  it("leaves short reasons untouched", () => {
    expect(truncateReason("short reason")).toBe("short reason");
  });

  it("leaves a reason exactly at the hard limit untouched", () => {
    const exact = "a".repeat(110);
    expect(truncateReason(exact)).toBe(exact);
  });

  it("cuts at the first '. ' past 40 chars when one exists within the hard limit", () => {
    // Sentence break at index 50 (well past 40), well inside 110 -- should cut there, no ellipsis.
    const reason = `${"x".repeat(48)}. this trailing clause should be dropped because it runs on for a while past the cut point`;
    const result = truncateReason(reason);
    expect(result.endsWith(".")).toBe(true);
    expect(result).not.toContain("…");
    expect(result.length).toBeLessThan(reason.length);
    expect(result).toBe(reason.slice(0, 49)); // up to and including the period
  });

  it("ignores a sentence break before the 40-char floor", () => {
    // Period at index 5 is before SENTENCE_MIN(40) -- must not cut there; falls through to the
    // 110-char hard cut since no other '. ' exists past 40.
    const reason = `short. ${"y".repeat(200)}`;
    const result = truncateReason(reason);
    expect(result).not.toBe("short.");
    expect(result.endsWith("…")).toBe(true);
    expect(result.length).toBe(111); // 110 chars + ellipsis char
  });

  it("hard-cuts at 110 with an ellipsis when no usable sentence break exists", () => {
    const reason = "z".repeat(300); // no '. ' anywhere
    const result = truncateReason(reason);
    expect(result).toBe(`${"z".repeat(110)}…`);
  });

  it("hard-cuts when the only sentence break lands past the hard limit", () => {
    // '. ' exists, but only after char 110 -- must NOT use it; falls back to hard cut.
    const reason = `${"a".repeat(150)}. trailing`;
    const result = truncateReason(reason);
    expect(result.endsWith("…")).toBe(true);
    expect(result.length).toBe(111);
  });

  it("never mid-ANSI-code: truncation happens on raw text, so a caller-applied color wrapper is always intact", () => {
    const reason = "z".repeat(300);
    const truncated = truncateReason(reason);
    const wrapped = `${ANSI.dim}${truncated}${ANSI.reset}`;
    // The full reset code must survive untouched at the end -- truncation never touched it because
    // it's applied by the caller AFTER truncateReason returns.
    expect(wrapped.endsWith(ANSI.reset)).toBe(true);
    expect(wrapped.startsWith(ANSI.dim)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// sortMonitorConditions — not-GREEN first, stable within each group
// ---------------------------------------------------------------------------

describe("sortMonitorConditions", () => {
  const conditions = [
    claim("C-EFF", "GREEN", "fine"),
    claim("C0", "AUDIT-INCIDENT", "needs attention"),
    claim("C10", "RED", "broken"),
    claim("C-BASE", "GREEN", "fine too"),
    claim("C9", "AUDIT-OK", "audit passed"),
    claim("C14", "RED", "also broken"),
  ];

  it("puts every not-GREEN row before every GREEN row", () => {
    const sorted = sortMonitorConditions(conditions);
    const statuses = sorted.map((c) => splitStatusAndReason(c.detail).status);
    const firstGreen = statuses.indexOf("GREEN");
    // everything before firstGreen must be non-GREEN
    expect(statuses.slice(0, firstGreen).every((s) => s !== "GREEN")).toBe(true);
    // everything from firstGreen onward must be GREEN
    expect(statuses.slice(firstGreen).every((s) => s === "GREEN")).toBe(true);
  });

  it("preserves original relative order within the not-GREEN group", () => {
    const sorted = sortMonitorConditions(conditions);
    const notGreenNames = sorted
      .filter((c) => splitStatusAndReason(c.detail).status !== "GREEN")
      .map(conditionName);
    // Original order of not-GREEN entries was: C0, C10, C9, C14
    expect(notGreenNames).toEqual(["C0", "C10", "C9", "C14"]);
  });

  it("preserves original relative order within the GREEN group", () => {
    const sorted = sortMonitorConditions(conditions);
    const greenNames = sorted
      .filter((c) => splitStatusAndReason(c.detail).status === "GREEN")
      .map(conditionName);
    expect(greenNames).toEqual(["C-EFF", "C-BASE"]);
  });

  it("does not mutate the input array", () => {
    const before = conditions.map(conditionName);
    sortMonitorConditions(conditions);
    expect(conditions.map(conditionName)).toEqual(before);
  });

  it("evidence-index consistency: the sorted array's [n] is the row an evidence/act lookup by n must return", () => {
    const sorted = sortMonitorConditions(conditions);
    // Simulates resolveClaim(state, "monitor", "0") in the REPL: index 0 into the SAME sorted
    // array the renderer used must be the first not-GREEN row shown, not the original array's [0].
    expect(conditionName(sorted[0]!)).toBe("C0");
    expect(conditionName(conditions[0]!)).toBe("C-EFF"); // original order unaffected
  });
});

// ---------------------------------------------------------------------------
// colorEnabledFor
// ---------------------------------------------------------------------------

describe("colorEnabledFor", () => {
  it("true when TTY and NO_COLOR unset", () => {
    expect(colorEnabledFor(true, {})).toBe(true);
  });
  it("false when not a TTY, regardless of NO_COLOR", () => {
    expect(colorEnabledFor(false, {})).toBe(false);
    expect(colorEnabledFor(undefined, {})).toBe(false);
  });
  it("false when NO_COLOR is set, even on a TTY", () => {
    expect(colorEnabledFor(true, { NO_COLOR: "1" })).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// renderMonitor — full composition
// ---------------------------------------------------------------------------

describe("buildTopAttentionLines (B7 item 2: welcome-screen ambient board snapshot)", () => {
  const conditions = [
    claim("C-EFF", "GREEN", "closure receipt present, gate-9 stamped"),
    claim("C0", "AUDIT-INCIDENT", "unresolved post-epoch incident pending review, needs a disposition table before it can close"),
    claim("C10", "RED", "broken"),
    claim("C-BASE", "GREEN", "fine too"),
    claim("C14", "RED", "also broken"),
  ];

  it("returns only not-GREEN conditions, not-green-first order, capped at `max`", () => {
    const lines = buildTopAttentionLines(conditions, 2);
    expect(lines.length).toBe(2);
    expect(lines[0]).toContain("C0");
    expect(lines[1]).toContain("C10");
    expect(lines.some((l) => l.includes("C-EFF") || l.includes("C-BASE"))).toBe(false);
  });

  it("each line includes the condition name and its status", () => {
    const lines = buildTopAttentionLines(conditions, 1);
    expect(lines[0]).toContain("C0");
    expect(lines[0]).toContain("AUDIT-INCIDENT");
  });

  it("truncates a long reason rather than overflowing the line", () => {
    const lines = buildTopAttentionLines(conditions, 1);
    // truncateReason's HARD_LIMIT applies -- the reason for C0 is long, must not appear verbatim.
    expect(lines[0]!.length).toBeLessThan(120);
  });

  it("returns an empty array when every condition is GREEN (never fabricates attention)", () => {
    const allGreen = [claim("C-EFF", "GREEN", "fine"), claim("C-BASE", "GREEN", "fine too")];
    expect(buildTopAttentionLines(allGreen, 3)).toEqual([]);
  });

  it("returns an empty array for an empty conditions list", () => {
    expect(buildTopAttentionLines([], 3)).toEqual([]);
  });

  // B7 gate ask (operator regrade 2026-07-03): rendered verbatim as
  // "C0: AUDIT-INCIDENT — AUDIT-INCIDENT C0: 4 Ember loop receipt(s) cited in window >…" --
  // the reason string ITSELF begins with "<STATUS> <ID>: " (the same label the formatter already
  // prepends), so it appeared twice.
  it("strips a redundant leading '<STATUS> <ID>: ' from the reason before joining", () => {
    const dupe = [claim("C0", "AUDIT-INCIDENT", "AUDIT-INCIDENT C0: 4 Ember loop receipt(s) cited in window")];
    const lines = buildTopAttentionLines(dupe, 1);
    expect(lines[0]).toBe("C0: AUDIT-INCIDENT — 4 Ember loop receipt(s) cited in window");
    expect(lines[0]).not.toContain("AUDIT-INCIDENT C0:");
  });

  it("leaves a reason alone when it does NOT carry the redundant status/id prefix", () => {
    const clean = [claim("C0", "AUDIT-INCIDENT", "4 Ember loop receipt(s) cited in window")];
    const lines = buildTopAttentionLines(clean, 1);
    expect(lines[0]).toBe("C0: AUDIT-INCIDENT — 4 Ember loop receipt(s) cited in window");
  });

  // B7 gate ask: the C0 line truncated into "window >…" -- the cut landed mid-way into a raw
  // shell/path fragment. Two-part cure: (a) drop everything from the first raw-internals marker
  // before truncating, (b) truncate at the last WORD boundary that fits, never mid-token.
  it("drops raw shell/path internals (' >&...') before truncating, showing only the human clause", () => {
    const raw = [claim("C0", "AUDIT-INCIDENT", "4 Ember loop receipt(s) cited in window >&Z:\\M\\ember\\tools\\ember-cli\\scratchpad\\somefile.log for review")];
    const lines = buildTopAttentionLines(raw, 1);
    expect(lines[0]).toBe("C0: AUDIT-INCIDENT — 4 Ember loop receipt(s) cited in window");
    expect(lines[0]).not.toContain(">&");
    expect(lines[0]).not.toContain("Z:\\");
  });

  it("drops raw internals introduced by an arrow ('-> Z:\\...') before truncating", () => {
    const raw = [claim("C0", "AUDIT-INCIDENT", "board write failed -> Z:\\M\\ember\\tools\\ember-cli\\scratchpad\\out.json permission denied")];
    const lines = buildTopAttentionLines(raw, 1);
    expect(lines[0]).toBe("C0: AUDIT-INCIDENT — board write failed");
    expect(lines[0]).not.toContain("Z:\\");
  });

  it("truncates a long clean reason at the last WORD boundary, never mid-token", () => {
    // Deliberately chosen so a naive 60-char slice lands mid-word: char 60 is inside "additional"
    // (slice(0,60) ends in "...requires addit"). A correct word-safe cut must land at the space
    // after "requires" (index 54) instead.
    const reason = "unresolved post-epoch incident pending review requires additional disposition documentation before closure eligibility";
    const long = [claim("C0", "AUDIT-INCIDENT", reason)];
    const lines = buildTopAttentionLines(long, 1);
    const line = lines[0]!;
    expect(line.endsWith("…")).toBe(true);
    // The character immediately before the ellipsis must be a real word boundary: strip the
    // ellipsis and confirm the remainder does NOT end mid-word (i.e. it matches a prefix of the
    // original reason that ends exactly at a space in the source).
    const beforeEllipsis = line.slice(line.indexOf("— ") + 2, -1).trimEnd();
    expect(reason.startsWith(beforeEllipsis)).toBe(true);
    const nextChar = reason[beforeEllipsis.length];
    expect(nextChar === " " || nextChar === undefined).toBe(true);
  });
});

describe("formatBoardTransitionEvent (issue #433: board condition transitions as activity events)", () => {
  it("matches the issue's literal example format for a GREEN->RED transition, colored red", () => {
    const entry = formatBoardTransitionEvent(
      { condition: "C(-1)", from: "GREEN", to: "RED" },
      { red: 27, green: 8 },
    );
    expect(entry).toEqual({ text: "board: C(-1) GREEN->RED (27 red / 8 green)", color: "red" });
  });

  it("colors a RED->GREEN transition green", () => {
    const entry = formatBoardTransitionEvent(
      { condition: "C-GROW", from: "RED", to: "GREEN" },
      { red: 5, green: 30 },
    );
    expect(entry).toEqual({ text: "board: C-GROW RED->GREEN (5 red / 30 green)", color: "green" });
  });

  it("carries no color for a transition into a non-GREEN/RED status (e.g. an AUDIT-* variant)", () => {
    const entry = formatBoardTransitionEvent(
      { condition: "C0", from: "RED", to: "AUDIT-INCIDENT" },
      { red: 10, green: 20 },
    );
    expect(entry).toEqual({ text: "board: C0 RED->AUDIT-INCIDENT (10 red / 20 green)" });
    expect(entry.color).toBeUndefined();
  });
});

describe("formatCockpitRestartEvent (issue #447: cockpit self-restart as an activity event)", () => {
  it("formats a genuine restart with a minute-scale gap", () => {
    const previous = { previousTs: "2026-07-07T12:00:00.000Z", previousPid: 1234 };
    const nowMs = Date.parse("2026-07-07T12:26:00.000Z"); // 26 minutes later
    const entry = formatCockpitRestartEvent(previous, 5678, nowMs);
    expect(entry).toEqual({ text: "cockpit: relaunched after 26m gap (pid 1234 -> 5678)" });
  });

  it("formats a multi-hour gap", () => {
    const previous = { previousTs: "2026-07-07T00:00:00.000Z", previousPid: 111 };
    const nowMs = Date.parse("2026-07-07T03:15:00.000Z");
    const entry = formatCockpitRestartEvent(previous, 222, nowMs);
    expect(entry).toEqual({ text: "cockpit: relaunched after 3h15m gap (pid 111 -> 222)" });
  });

  it("returns null on first-ever boot (no prior heartbeat -- boot-suppression, same discipline as diffBoardConditions)", () => {
    expect(formatCockpitRestartEvent(null, 5678, Date.now())).toBeNull();
  });

  it("returns null when the previous pid equals the current pid (not actually a restart)", () => {
    const previous = { previousTs: "2026-07-07T12:00:00.000Z", previousPid: 1234 };
    const nowMs = Date.parse("2026-07-07T12:26:00.000Z");
    expect(formatCockpitRestartEvent(previous, 1234, nowMs)).toBeNull();
  });

  it("returns null when the gap is unparseable", () => {
    const previous = { previousTs: "not-a-date", previousPid: 1234 };
    expect(formatCockpitRestartEvent(previous, 5678, Date.now())).toBeNull();
  });

  it("returns null when the gap is below the reportable threshold (normal process handoff, not a reportable event)", () => {
    const previous = { previousTs: "2026-07-07T12:00:00.000Z", previousPid: 1234 };
    const nowMs = Date.parse("2026-07-07T12:00:00.000Z") + (COCKPIT_RESTART_GAP_THRESHOLD_MS - 1);
    expect(formatCockpitRestartEvent(previous, 5678, nowMs)).toBeNull();
  });

  it("reports right at the threshold boundary", () => {
    const previous = { previousTs: "2026-07-07T12:00:00.000Z", previousPid: 1234 };
    const nowMs = Date.parse("2026-07-07T12:00:00.000Z") + COCKPIT_RESTART_GAP_THRESHOLD_MS;
    const entry = formatCockpitRestartEvent(previous, 5678, nowMs);
    expect(entry).not.toBeNull();
  });

  it("carries no color (plain event, matching the issue's own framing -- a fact, not a warning)", () => {
    const previous = { previousTs: "2026-07-07T12:00:00.000Z", previousPid: 1234 };
    const nowMs = Date.parse("2026-07-07T12:26:00.000Z");
    const entry = formatCockpitRestartEvent(previous, 5678, nowMs);
    expect(entry?.color).toBeUndefined();
  });
});

describe("renderMonitor", () => {
  const conditions = [
    claim("C-EFF", "GREEN", "closure receipt present, gate-9 stamped"),
    claim("C0", "AUDIT-INCIDENT", "unresolved post-epoch incident pending review"),
    claim("C10", "RED", "regression detected in owned-core gate run"),
    claim("C-BASE", "GREEN", "import-edition seed receipt landed"),
    claim("C9", "AUDIT-OK", "cadence audit passed clean"),
  ];
  const state = stateWith(conditions, { pctComplete: 76.7 });

  it("header line 1 carries board ts and GREEN fraction + pct from monitor.pctComplete (the fixed field)", () => {
    const lines = renderMonitor(state, { colorEnabled: false });
    expect(lines[0]).toContain("20260703T120000Z");
    expect(lines[0]).toContain("2/3 GREEN"); // green=2, red=1 -> denominator 3
    expect(lines[0]).toContain("76.7%");
  });

  it("header line 2 carries an audit-incident count and a not-green count", () => {
    const lines = renderMonitor(state, { colorEnabled: false });
    expect(lines[1]).toContain("1 audit incident");
    // not-green = literal status !== "GREEN": C0 (AUDIT-INCIDENT), C10 (RED), C9 (AUDIT-OK) = 3 of 5.
    expect(lines[1]).toContain("3 of 5 rows");
  });

  it("renders not-GREEN rows before GREEN rows, one line per condition, prefixed with [idx]", () => {
    const lines = renderMonitor(state, { colorEnabled: false });
    const rowLines = lines.slice(2, 2 + conditions.length);
    expect(rowLines[0]).toMatch(/^\[0\] \[A\] C0\s/);
    expect(rowLines[1]).toMatch(/^\[1\] \[R\] C10\s/);
    expect(rowLines[2]).toMatch(/^\[2\] \[A\] C9\s/);
    expect(rowLines[3]).toMatch(/^\[3\] \[G\] C-EFF\s/);
    expect(rowLines[4]).toMatch(/^\[4\] \[G\] C-BASE\s/);
  });

  it("pads the CONDITION column to the widest condition name", () => {
    const lines = renderMonitor(state, { colorEnabled: false });
    const rowLines = lines.slice(2, 2 + conditions.length);
    // "C-EFF" and "C-BASE" are the widest (6 chars); shorter names like "C0"/"C10"/"C9" must be
    // padded to that width before the reason text starts.
    for (const l of rowLines) {
      const afterGlyph = l.replace(/^\[\d+\] \[[GRA?]\] /, "");
      expect(afterGlyph.slice(0, 6)).toHaveLength(6);
    }
  });

  it("ends with a footer pointing at evidence monitor <n>", () => {
    const lines = renderMonitor(state, { colorEnabled: false });
    expect(lines[lines.length - 1]).toContain("evidence monitor <n>");
  });

  it("emits no ANSI escape codes when colorEnabled is false", () => {
    const lines = renderMonitor(state, { colorEnabled: false });
    expect(lines.join("\n")).not.toContain("\x1b[");
  });

  it("emits ANSI escape codes (glyph color + dim reason + dim footer) when colorEnabled is true", () => {
    const lines = renderMonitor(state, { colorEnabled: true });
    const joined = lines.join("\n");
    expect(joined).toContain(ANSI.yellow); // AUDIT-* row
    expect(joined).toContain(ANSI.red); // RED row
    expect(joined).toContain(ANSI.green); // GREEN row
    expect(joined).toContain(ANSI.dim); // reason text + footer
    expect(joined).toContain(ANSI.reset);
  });

  it("truncates a long reason within the rendered row", () => {
    const longReason = "z".repeat(300);
    const longState = stateWith([claim("C-LONG", "RED", longReason)]);
    const lines = renderMonitor(longState, { colorEnabled: false });
    const row = lines[2]!;
    expect(row).toContain("…");
    expect(row.length).toBeLessThan(longReason.length);
  });
});

// ---------------------------------------------------------------------------
// renderMonitorPanel — increment 6 step B: bordered-panel wrapper around
// renderMonitor()'s existing (unchanged, still-tested) lines. Additive only --
// applies the Step-A mockup3 visual container (round border, identity color)
// without altering renderConditionLine's tested per-row format.
// ---------------------------------------------------------------------------

describe("renderMonitorPanel", () => {
  const conditions = [
    claim("C-EFF", "GREEN", "closure receipt present, gate-9 stamped"),
    claim("C0", "AUDIT-INCIDENT", "unresolved post-epoch incident pending review"),
  ];
  const state = stateWith(conditions, { pctComplete: 50 });
  const WIDE = 90; // comfortable margin over the longest real row in this fixture

  it("wraps renderMonitor's exact lines with a top and bottom border of the given width", () => {
    const inner = renderMonitor(state, { colorEnabled: false });
    const panel = renderMonitorPanel(state, { colorEnabled: false, width: WIDE });
    expect(panel[0]).toMatch(/^╭─/);
    expect(panel[panel.length - 1]).toMatch(/^╰─/);
    // every inner line appears, unmodified, between the borders
    for (const line of inner) {
      expect(panel.some((l) => l.includes(line))).toBe(true);
    }
  });

  it("every bordered line (excluding the plain top/bottom rule) is exactly `width` visible cells, at a width wide enough to hold every row", () => {
    const panel = renderMonitorPanel(state, { colorEnabled: false, width: WIDE });
    for (const line of panel.slice(1, -1)) {
      expect(visiblePanelWidth(line)).toBe(WIDE);
    }
  });

  it("colorEnabled: true colors the border with ANSI (not a bare box-drawing literal)", () => {
    const panel = renderMonitorPanel(state, { colorEnabled: true, width: WIDE });
    expect(panel[0]).toContain("\x1b[");
    expect(panel[0]).toContain(ANSI.reset);
  });

  it("colorEnabled: false emits no ANSI escape codes anywhere in the panel", () => {
    const panel = renderMonitorPanel(state, { colorEnabled: false, width: WIDE });
    expect(panel.join("\n")).not.toContain("\x1b[");
  });

  it("B4 W3: ellipsis-truncates an overlong content line to fit width, rather than leaving it wider than the panel", () => {
    // Reverses the prior "never truncate, let it overflow" design: an overlong row left wider
    // than the panel just gets clipped raggedly mid-word by whatever renders outside the panel
    // (the terminal viewport) -- worse than a clean, ANSI-safe ellipsis truncation. Every row must
    // now fit exactly within `width` visible cells, at any width including a pathologically small
    // one.
    const panel = renderMonitorPanel(state, { colorEnabled: false, width: 20 });
    for (const line of panel.slice(1, -1)) {
      expect(visiblePanelWidth(line)).toBe(20);
    }
  });

  it("B4 W3: truncated rows end in an ellipsis, not a mid-word cut", () => {
    const panel = renderMonitorPanel(state, { colorEnabled: false, width: 20 });
    const inner = renderMonitor(state, { colorEnabled: false });
    for (let i = 0; i < inner.length; i++) {
      if (visiblePanelWidth(inner[i]!) > 20 - 4) {
        // this row needed truncation -- its panel counterpart must carry the ellipsis marker
        expect(panel[i + 1]).toContain("…");
      }
    }
  });

  it("at a width wide enough to hold every row (WIDE), nothing is truncated (regression guard)", () => {
    const panel = renderMonitorPanel(state, { colorEnabled: false, width: WIDE });
    expect(panel.join("\n")).not.toContain("…");
  });
});

describe("truncateAnsiLineToWidth", () => {
  it("returns the line unchanged when it already fits", () => {
    expect(truncateAnsiLineToWidth("short line", 40)).toBe("short line");
  });

  it("truncates a plain (uncolored) line to exactly maxWidth visible cells, ending in an ellipsis", () => {
    const long = "x".repeat(50);
    const result = truncateAnsiLineToWidth(long, 20);
    expect(visiblePanelWidth(result)).toBe(20);
    expect(result.endsWith("…")).toBe(true);
  });

  it("never cuts an ANSI escape sequence in half", () => {
    const colored = `${ANSI.red}${"x".repeat(50)}${ANSI.reset}`;
    const result = truncateAnsiLineToWidth(colored, 20);
    // every escape sequence present must be complete (start with ESC[, end with m)
    const escapes = result.match(/\x1b\[[0-9;]*/g) ?? [];
    for (const esc of escapes) {
      expect(result.includes(esc + "m") || esc.endsWith("m")).toBe(true);
    }
    expect(visiblePanelWidth(result)).toBeLessThanOrEqual(20);
  });

  it("emits a trailing reset when truncating mid-color-span, so color never bleeds into what follows", () => {
    const colored = `${ANSI.red}${"x".repeat(50)}`; // deliberately no reset in the source
    const result = truncateAnsiLineToWidth(colored, 20);
    expect(result.endsWith(ANSI.reset)).toBe(true);
  });

  it("width 0 or negative returns empty string, never throws", () => {
    expect(truncateAnsiLineToWidth("anything", 0)).toBe("");
    expect(truncateAnsiLineToWidth("anything", -5)).toBe("");
  });

  it("width 1 returns just the ellipsis", () => {
    expect(truncateAnsiLineToWidth("anything", 1)).toBe("…");
  });
});
