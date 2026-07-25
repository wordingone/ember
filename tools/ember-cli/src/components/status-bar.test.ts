// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// components/status-bar.test.ts — mode indicator + model metrics tests (AC4-AC6)
// Spec: specs/surface6-fireball-observatory.md; m10-battery-harness.md (A2/A7)

import { describe, it, expect } from "bun:test";
import {
  renderModeIndicator,
  formatTokenCount,
  formatGb,
  formatModelMetrics,
  formatDegradedBannerText,
  DegradedBanner,
  formatOutageBannerText,
  OutageBanner,
  formatRoundtripAgeDuration,
  formatRoundtripAgeText,
  RoundtripAgeIndicator,
  statusBarText,
  BYPASS_STATUS_TEXT,
  type ModelMetrics,
  type DegradedBannerState,
  type OutageBannerState,
  type RoundtripAgeState,
} from "./status-bar.ts";
import type { CognitiveMode } from "../cognitive-mode.ts";

const ALL_MODES: CognitiveMode[] = [
  "observe", "orient", "act", "verify",
  "consolidate", "ask", "report", "rollback",
];

// ---------------------------------------------------------------------------
// AC4: renderModeIndicator returns "<glyph> <label>" (no codepoint > 0x7f in ascii mode)
// ---------------------------------------------------------------------------

describe("AC4: renderModeIndicator — '<glyph> <label>' format", () => {
  it("observe mode returns '○ observe' when ascii=false", () => {
    expect(renderModeIndicator("observe", false)).toBe("○ observe");
  });

  it("act mode returns '🔥 act' when ascii=false", () => {
    expect(renderModeIndicator("act", false)).toBe("🔥 act");
  });

  it("report mode returns '✓ report' when ascii=false", () => {
    expect(renderModeIndicator("report", false)).toBe("✓ report");
  });

  it("ask mode returns '? ask' when ascii=false", () => {
    expect(renderModeIndicator("ask", false)).toBe("? ask");
  });

  it("rollback mode returns '⚠ rollback' when ascii=false", () => {
    expect(renderModeIndicator("rollback", false)).toBe("⚠ rollback");
  });

  it("orient mode with ascii=true contains only ASCII chars (≤ 0x7f)", () => {
    const result = renderModeIndicator("orient", true);
    for (const ch of [...result]) {
      expect(ch.codePointAt(0)!).toBeLessThanOrEqual(0x7f);
    }
  });

  it("all modes with ascii=true contain only ASCII chars", () => {
    for (const mode of ALL_MODES) {
      const result = renderModeIndicator(mode, true);
      for (const ch of [...result]) {
        expect(ch.codePointAt(0)!).toBeLessThanOrEqual(0x7f);
      }
    }
  });

  it("result has a space separating glyph and label", () => {
    const result = renderModeIndicator("ask", false);
    expect(result).toContain(" ");
    const spaceIdx = result.indexOf(" ");
    expect(result.slice(spaceIdx + 1)).toBe("ask");
  });

  it("result is non-empty for every mode", () => {
    for (const mode of ALL_MODES) {
      expect(renderModeIndicator(mode, false).length).toBeGreaterThan(0);
    }
  });
});

// ---------------------------------------------------------------------------
// AC5: absent cognitiveMode prop → defaults to "observe"; never blank, never crash
// ---------------------------------------------------------------------------

describe("AC5: default mode is 'observe' — never blank, never crash", () => {
  it("renderModeIndicator('observe', false) is non-empty (the default mode path)", () => {
    const result = renderModeIndicator("observe", false);
    expect(result.length).toBeGreaterThan(0);
  });

  it("renderModeIndicator does not throw for any valid mode", () => {
    for (const mode of ALL_MODES) {
      expect(() => renderModeIndicator(mode, false)).not.toThrow();
    }
  });

  it("default 'observe' indicator is '○ observe'", () => {
    // This is what StatusLine renders when no cognitiveMode prop is provided.
    expect(renderModeIndicator("observe", false)).toBe("○ observe");
  });
});

// ---------------------------------------------------------------------------
// AC6: ModelMetrics formatting — live inference meter unique to ember
// M10 A2 unique capability: neither competitor shows local VRAM/throughput.
// ---------------------------------------------------------------------------

describe("AC6: formatTokenCount", () => {
  it("1000 → '1k'", () => expect(formatTokenCount(1000)).toBe("1k"));
  it("120000 → '120k'", () => expect(formatTokenCount(120000)).toBe("120k"));
  it("2048 → '2k'", () => expect(formatTokenCount(2048)).toBe("2k"));
  it("999 → '999' (no k suffix below 1000)", () => expect(formatTokenCount(999)).toBe("999"));
  it("0 → '0'", () => expect(formatTokenCount(0)).toBe("0"));
});

describe("AC6: formatGb", () => {
  it("12.4 → '12.4'", () => expect(formatGb(12.4)).toBe("12.4"));
  it("0.0 → '0.0'", () => expect(formatGb(0)).toBe("0.0"));
  it("24 → '24.0'", () => expect(formatGb(24)).toBe("24.0"));
  it("rounds to 1 decimal: 12.46 → '12.5'", () => expect(formatGb(12.46)).toBe("12.5"));
});

describe("AC6: formatModelMetrics", () => {
  const sample: ModelMetrics = {
    contextTokens:    12000,
    maxContextTokens: 120000,
    vramUsedGb:       12.4,
    vramTotalGb:      24.0,
    tokensPerSec:     28.3,
  };

  it("contains context token ratio", () => {
    expect(formatModelMetrics(sample)).toContain("12k/120k");
  });

  it("contains throughput (rounded t/s)", () => {
    expect(formatModelMetrics(sample)).toContain("28t/s");
  });

  it("contains VRAM ratio", () => {
    expect(formatModelMetrics(sample)).toContain("12.4/24.0GB");
  });

  it("segments are separated by SEGMENT_SEPARATOR", () => {
    const text = formatModelMetrics(sample);
    // Must contain at least two separators between the three segments
    const count = (text.match(/·/g) ?? []).length;
    expect(count).toBeGreaterThanOrEqual(2);
  });

  it("0 t/s renders as '0t/s' (not NaN)", () => {
    const zero = { ...sample, tokensPerSec: 0 };
    expect(formatModelMetrics(zero)).toContain("0t/s");
  });
});

// ---------------------------------------------------------------------------
// issue #239 mission 2: DegradedBanner — the persistent degraded-state
// surface shown once the model-client circuit breaker opens. "broken must
// LOOK broken" (the operator's law from the dispatch spec): a silent wedge
// with no visible signal is the defect this exists to close.
// ---------------------------------------------------------------------------

describe("formatDegradedBannerText — issue #239 degraded banner content", () => {
  const inactive: DegradedBannerState = { active: false };

  it("inactive banner formats to an empty string", () => {
    expect(formatDegradedBannerText(inactive, 0)).toBe("");
  });

  const active: DegradedBannerState = {
    active: true,
    endpoint: "http://localhost:8081",
    lastStatus: 400,
    lastReason: "HTTP 400",
    attemptCount: 1,
    nextProbeAt: 60_000,
    probing: false,
  };

  it("includes the endpoint URL", () => {
    expect(formatDegradedBannerText(active, 0)).toContain("http://localhost:8081");
  });

  it("includes the last HTTP status", () => {
    expect(formatDegradedBannerText(active, 0)).toContain("400");
  });

  it("includes the attempt count", () => {
    expect(formatDegradedBannerText(active, 0)).toContain("attempts 1");
  });

  it("includes a next-probe countdown derived from nextProbeAt - now", () => {
    const text = formatDegradedBannerText(active, 45_000); // 15s remaining
    expect(text).toContain("15s");
  });

  it("shows 'probing' instead of a countdown while a half-open probe is in flight", () => {
    const probing: DegradedBannerState = { ...active, probing: true };
    const text = formatDegradedBannerText(probing, 60_000);
    expect(text.toLowerCase()).toContain("probing");
  });

  it("falls back to lastReason (connection error) when there is no HTTP status", () => {
    const networkFailure: DegradedBannerState = {
      active: true,
      endpoint: "http://localhost:8081",
      lastStatus: null,
      lastReason: "connection error",
      attemptCount: 6,
      nextProbeAt: 60_000,
      probing: false,
    };
    expect(formatDegradedBannerText(networkFailure, 0)).toContain("connection error");
  });
});

describe("DegradedBanner component — hook-free, follows EffortCallout conventions", () => {
  it("renders null when inactive", () => {
    expect(DegradedBanner({ degraded: { active: false }, now: 0 })).toBeNull();
  });

  it("renders a red Text element with the formatted banner text when active", () => {
    const degraded: DegradedBannerState = {
      active: true,
      endpoint: "http://localhost:8081",
      lastStatus: 400,
      lastReason: "HTTP 400",
      attemptCount: 1,
      nextProbeAt: 1000,
      probing: false,
    };
    const el = DegradedBanner({ degraded, now: 0 });
    expect(el).not.toBeNull();
    expect((el as { props: { color: string } }).props.color).toBe("red");
    const text = (el as { props: { children: string } }).props.children;
    expect(text).toContain("http://localhost:8081");
  });
});

// ---------------------------------------------------------------------------
// issue #475: OutageBanner — cockpit status banner for the frozen
// planned-outage.json marker contract (#464). "model offline should say WHY"
// -- a planned maintenance window must be visually distinguishable from an
// actual crash, which today look identical from the operator's chair.
// ---------------------------------------------------------------------------

describe("formatOutageBannerText — issue #475 banner content", () => {
  const inactive: OutageBannerState = { active: false };

  it("inactive banner formats to an empty string", () => {
    expect(formatOutageBannerText(inactive)).toBe("");
  });

  const active: OutageBannerState = {
    active: true,
    owner: "jun",
    reason: "grow-event window",
    expires: "2026-07-09T05:00:00Z",
  };

  it("matches the spec's exact shape: PLANNED OUTAGE (<owner>): <reason> — until <expires>", () => {
    expect(formatOutageBannerText(active)).toBe(
      "PLANNED OUTAGE (jun): grow-event window — until 2026-07-09T05:00:00Z",
    );
  });

  it("includes the owner", () => {
    expect(formatOutageBannerText(active)).toContain("jun");
  });

  it("includes the reason", () => {
    expect(formatOutageBannerText(active)).toContain("grow-event window");
  });

  it("includes the expiry", () => {
    expect(formatOutageBannerText(active)).toContain("2026-07-09T05:00:00Z");
  });

  it("falls back to placeholders when fields are missing but active is true", () => {
    const sparse: OutageBannerState = { active: true };
    const text = formatOutageBannerText(sparse);
    expect(text).toContain("unknown");
    expect(text).toContain("no reason given");
  });
});

describe("OutageBanner component — hook-free, follows DegradedBanner conventions", () => {
  it("renders null when inactive", () => {
    expect(OutageBanner({ outage: { active: false } })).toBeNull();
  });

  it("renders a yellow Text element with the formatted banner text when active", () => {
    const outage: OutageBannerState = {
      active: true,
      owner: "jun",
      reason: "grow-event window",
      expires: "2026-07-09T05:00:00Z",
    };
    const el = OutageBanner({ outage });
    expect(el).not.toBeNull();
    expect((el as { props: { color: string } }).props.color).toBe("yellow");
    const text = (el as { props: { children: string } }).props.children;
    expect(text).toContain("PLANNED OUTAGE (jun)");
  });
});

// ---------------------------------------------------------------------------
// issue #239 final acceptance clause: RoundtripAgeIndicator — the
// always-visible "last-successful-model-roundtrip age" status-line segment.
// ---------------------------------------------------------------------------

describe("formatRoundtripAgeDuration — compact duration formatting", () => {
  it("sub-second durations render as ms", () => {
    expect(formatRoundtripAgeDuration(0)).toBe("0ms");
    expect(formatRoundtripAgeDuration(900)).toBe("900ms");
  });

  it("sub-minute durations render as whole seconds", () => {
    expect(formatRoundtripAgeDuration(1000)).toBe("1s");
    expect(formatRoundtripAgeDuration(45_000)).toBe("45s");
    expect(formatRoundtripAgeDuration(59_999)).toBe("59s");
  });

  it("minute-scale durations render as MmSs", () => {
    expect(formatRoundtripAgeDuration(60_000)).toBe("1m0s");
    expect(formatRoundtripAgeDuration(125_000)).toBe("2m5s");
  });

  it("clamps a negative duration to 0ms", () => {
    expect(formatRoundtripAgeDuration(-500)).toBe("0ms");
  });
});

describe("formatRoundtripAgeText — pure formatter, #239 acceptance text", () => {
  it("reports 'no roundtrip yet' before any success", () => {
    const s: RoundtripAgeState = { lastSuccessAt: null };
    expect(formatRoundtripAgeText(s, 10_000)).toBe("no roundtrip yet");
  });

  it("reports the age since the last successful roundtrip", () => {
    const s: RoundtripAgeState = { lastSuccessAt: 1000 };
    expect(formatRoundtripAgeText(s, 6500)).toBe("last roundtrip 5s ago");
  });

  it("never negative even if now < lastSuccessAt", () => {
    const s: RoundtripAgeState = { lastSuccessAt: 5000 };
    expect(formatRoundtripAgeText(s, 1000)).toBe("last roundtrip 0ms ago");
  });
});

describe("RoundtripAgeIndicator component — always renders, never hidden like DegradedBanner", () => {
  it("renders a dim Text element even with no roundtrip yet (never returns null)", () => {
    const el = RoundtripAgeIndicator({ roundtripAge: { lastSuccessAt: null }, now: 0 });
    expect(el).not.toBeNull();
    expect((el as { props: { dimColor: boolean } }).props.dimColor).toBe(true);
    const text = (el as { props: { children: string } }).props.children;
    expect(text).toBe("no roundtrip yet");
  });

  it("renders the formatted age text once a roundtrip has succeeded", () => {
    const el = RoundtripAgeIndicator({ roundtripAge: { lastSuccessAt: 1000 }, now: 3000 });
    const text = (el as { props: { children: string } }).props.children;
    expect(text).toBe("last roundtrip 2s ago");
  });
});

// ---------------------------------------------------------------------------
// issue #1044: keybinding-hint chrome removed from the status bar text.
// Keybindings themselves (shift+tab, esc, ctrl+t) stay live via StatusLine's own
// useInput -- only the always-on textual advertisement goes. RED-first: these
// assertions fail on pre-#1044 master (the old strings were always present).
// ---------------------------------------------------------------------------
describe("issue #1044: statusBarText carries no keybinding-hint chrome", () => {
  it("bypass mode: no hint substrings, mode indicator survives", () => {
    const text = statusBarText("bypass", true);
    expect(text).not.toContain("shift+tab");
    expect(text).not.toContain("esc to interrupt");
    expect(text).not.toContain("ctrl+t");
    expect(text).toContain("bypass permissions on");
  });

  it("regular mode: no hint substrings, mode indicator survives", () => {
    const text = statusBarText("regular", false);
    expect(text).not.toContain("shift+tab");
    expect(text).not.toContain("esc to interrupt");
    expect(text).not.toContain("ctrl+t");
    expect(text).toContain("regular mode");
  });

  it("tasksVisible no longer changes the rendered text (dead param, kept for call-site compat)", () => {
    expect(statusBarText("bypass", true)).toBe(statusBarText("bypass", false));
    expect(statusBarText("regular", true)).toBe(statusBarText("regular", false));
  });

  it("BYPASS_STATUS_TEXT matches statusBarText('bypass', ...) exactly and carries no hint chrome", () => {
    expect(BYPASS_STATUS_TEXT).toBe(statusBarText("bypass", true));
    expect(BYPASS_STATUS_TEXT).not.toContain("shift+tab");
    expect(BYPASS_STATUS_TEXT).not.toContain("esc to interrupt");
    expect(BYPASS_STATUS_TEXT).not.toContain("ctrl+t");
  });
});
