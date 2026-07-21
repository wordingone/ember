// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// components/logo-homescreen.test.ts — increment 6 step B: Observatory identity tokens applied
// to the welcome/homescreen surface (border color, wordmark color, tagline, ember-native hint).
// Spec: state/field-ux-map.md §8b/§9; step-A mockups (state/design-mockups/welcome-homescreen...).

import { describe, it, expect } from "bun:test";
import { WelcomeV2, LogoV2, Homescreen, IDENTITY_TAGLINE, FeedComponent, rightColWidth, clipToWidth, formatWallClock, shortenDataRootForDisplay } from "./logo-homescreen.ts";
import { color } from "./design-system.ts";

// React.createElement returns a plain {type, props} tree -- inspectable without a renderer.
function children(el: any): any[] {
  const c = el.props.children;
  return Array.isArray(c) ? c : [c];
}

/** Homescreen now wraps [leftCol, rightCol, ChannelsNotice] in an outer titled panel (D4) --
 * this unwraps that one extra level so leftCol/rightCol lookups stay stable regardless of exactly
 * how many wrapper Boxes surround the panel. */
function findPanel(el: any): any {
  if (el?.props?.borderTitle === "ember") return el;
  const kids = children(el);
  for (const c of kids) {
    if (c && typeof c === "object") {
      const found = findPanel(c);
      if (found) return found;
    }
  }
  return null;
}

/** Recursively finds the first descendant whose own `children` prop is exactly `target`
 * (a plain string leaf), anywhere under `el`. */
function findTextChild(el: any, target: string): boolean {
  if (!el || typeof el !== "object") return false;
  const c = el.props?.children;
  if (c === target) return true;
  if (Array.isArray(c)) return c.some((k: any) => findTextChild(k, target));
  if (c && typeof c === "object") return findTextChild(c, target);
  return false;
}

/** Recursively finds the first descendant whose `children` string satisfies `pred`. */
function findTextWhere(el: any, pred: (s: string) => boolean): boolean {
  if (!el || typeof el !== "object") return false;
  const c = el.props?.children;
  if (typeof c === "string" && pred(c)) return true;
  if (Array.isArray(c)) return c.some((k: any) => findTextWhere(k, pred));
  if (c && typeof c === "object") return findTextWhere(c, pred);
  return false;
}

/** Finds the `color` prop on the descendant Text element whose children exactly equal `target`. */
function colorForText(el: any, target: string): string | undefined {
  if (!el || typeof el !== "object") return undefined;
  const c = el.props?.children;
  if (c === target) return el.props?.color;
  if (Array.isArray(c)) {
    for (const k of c) {
      const found = colorForText(k, target);
      if (found !== undefined) return found;
    }
    return undefined;
  }
  if (c && typeof c === "object") return colorForText(c, target);
  return undefined;
}

/** Extracts rightCol's SECOND FeedComponent element (the "recent activity" feed) and actually
 * CALLS it to get its rendered Text tree -- Homescreen only creates a <FeedComponent feed=.../>
 * element (props carry the feed data), it never invokes FeedComponent itself, so entry text is
 * not reachable by walking Homescreen's own return value alone (same technique as the B5 W6
 * rightColWidth test above). */
function renderedRecentFeed(el: any): any {
  const panel = findPanel(el);
  const rightCol = children(panel)[1];
  const recentFeedEl = children(rightCol)[1];
  return FeedComponent(recentFeedEl.props);
}

describe("Homescreen — recent-activity feed carries real board substance (B7 item 2: kill the void)", () => {
  it("falls back to 'No recent activity' when no board summary has been fetched yet (never fabricates)", () => {
    const rendered = renderedRecentFeed(Homescreen({ state: {} }));
    expect(findTextChild(rendered, "No recent activity")).toBe(true);
  });

  it("shows a real board summary line when a boardSummary is supplied", () => {
    const rendered = renderedRecentFeed(Homescreen({
      state: {},
      boardSummary: { green: 23, total: 30, pctComplete: 76.7, topAttention: [] },
    }));
    expect(findTextWhere(rendered, (s) => s.includes("23/30 GREEN"))).toBe(true);
    expect(findTextWhere(rendered, (s) => s.includes("76.7"))).toBe(true);
    expect(findTextChild(rendered, "No recent activity")).toBe(false);
  });

  it("includes top-attention lines from the board summary when present", () => {
    const rendered = renderedRecentFeed(Homescreen({
      state: {},
      boardSummary: {
        green: 23, total: 30, pctComplete: 76.7,
        topAttention: ["C-TALLY: RED — invalid-token pct<100", "C0: AUDIT-INCIDENT — needs disposition"],
      },
    }));
    expect(findTextWhere(rendered, (s) => s.includes("C-TALLY"))).toBe(true);
    expect(findTextWhere(rendered, (s) => s.includes("C0"))).toBe(true);
  });

  it("still carries the /resume footer regardless of boardSummary presence", () => {
    const rendered = renderedRecentFeed(Homescreen({
      state: {},
      boardSummary: { green: 30, total: 30, pctComplete: 100, topAttention: [] },
    }));
    expect(findTextChild(rendered, "/resume for more")).toBe(true);
  });
});

describe("Homescreen — recent-activity feed carries the receipt-age badge (#404/#405: boot surface parity with /cockpit)", () => {
  it("shows 'board: <age>' (no color) when the board receipt is fresh", () => {
    const boardTs = new Date(Date.now() - 5 * 60 * 1000).toISOString(); // 5 minutes ago
    const rendered = renderedRecentFeed(Homescreen({
      state: {},
      boardSummary: { green: 23, total: 30, pctComplete: 76.7, topAttention: [], boardTs },
    }));
    expect(findTextWhere(rendered, (s) => /^board: \d+m ago$/.test(s))).toBe(true);
    expect(findTextWhere(rendered, (s) => s.includes("STALE"))).toBe(false);
  });

  it("shows red 'STALE: <age>' when the board receipt is older than the staleness threshold (2h)", () => {
    const boardTs = new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString(); // 3 hours ago -- safely past the 2h threshold
    const rendered = renderedRecentFeed(Homescreen({
      state: {},
      boardSummary: { green: 23, total: 30, pctComplete: 76.7, topAttention: [], boardTs },
    }));
    expect(findTextWhere(rendered, (s) => /^STALE: \d+h ago$/.test(s))).toBe(true);
    expect(colorForText(rendered, "STALE: 3h ago")).toBe("red");
  });

  it("shows plain 'board: <age>' (not stale) at 1h old -- inside the 2h cadence window, no wolf-cry", () => {
    const boardTs = new Date(Date.now() - 60 * 60 * 1000).toISOString(); // 1 hour ago
    const rendered = renderedRecentFeed(Homescreen({
      state: {},
      boardSummary: { green: 23, total: 30, pctComplete: 76.7, topAttention: [], boardTs },
    }));
    expect(findTextWhere(rendered, (s) => /^board: 1h ago$/.test(s))).toBe(true);
    expect(findTextWhere(rendered, (s) => s.includes("STALE"))).toBe(false);
  });

  it("carries no badge line when boardSummary has no boardTs (older callers / partial data, never fabricates)", () => {
    const rendered = renderedRecentFeed(Homescreen({
      state: {},
      boardSummary: { green: 23, total: 30, pctComplete: 76.7, topAttention: [] },
    }));
    expect(findTextWhere(rendered, (s) => s.startsWith("board:") || s.startsWith("STALE:"))).toBe(false);
  });
});

describe("Homescreen — recent-activity feed carries board condition-transition events (issue #433)", () => {
  it("renders a recentTransitions entry above the topAttention lines, with its color", () => {
    const rendered = renderedRecentFeed(Homescreen({
      state: {},
      boardSummary: {
        green: 23, total: 30, pctComplete: 76.7,
        topAttention: ["C-TALLY: RED — invalid-token pct<100"],
        recentTransitions: [{ text: "board: C(-1) GREEN->RED (27 red / 8 green)", color: "red" }],
      },
    }));
    expect(findTextChild(rendered, "board: C(-1) GREEN->RED (27 red / 8 green)")).toBe(true);
    expect(colorForText(rendered, "board: C(-1) GREEN->RED (27 red / 8 green)")).toBe("red");
    // Still carries the pre-existing static attention line too -- transitions are additive.
    expect(findTextWhere(rendered, (s) => s.includes("C-TALLY"))).toBe(true);
  });

  it("renders a plain (no color) transition entry when the formatter carried none", () => {
    const rendered = renderedRecentFeed(Homescreen({
      state: {},
      boardSummary: {
        green: 23, total: 30, pctComplete: 76.7, topAttention: [],
        recentTransitions: [{ text: "board: C0 RED->AUDIT-INCIDENT (10 red / 20 green)" }],
      },
    }));
    expect(findTextChild(rendered, "board: C0 RED->AUDIT-INCIDENT (10 red / 20 green)")).toBe(true);
    expect(colorForText(rendered, "board: C0 RED->AUDIT-INCIDENT (10 red / 20 green)")).toBeUndefined();
  });

  it("carries no transition lines when recentTransitions is absent (never fabricates)", () => {
    const rendered = renderedRecentFeed(Homescreen({
      state: {},
      boardSummary: { green: 23, total: 30, pctComplete: 76.7, topAttention: [] },
    }));
    expect(findTextWhere(rendered, (s) => s.startsWith("board: C"))).toBe(false);
  });
});

describe("Homescreen — recent-activity feed carries live telemetry + cockpit-restart events (issue #447)", () => {
  it("renders the cockpit-restart event even when boardSummary itself carries no other data", () => {
    const rendered = renderedRecentFeed(Homescreen({
      state: {},
      boardSummary: {
        green: 0, total: 0, pctComplete: 0, topAttention: [],
        cockpitRestartEvent: { text: "cockpit: relaunched after 26m gap (pid 1234 -> 5678)" },
      },
    }));
    expect(findTextChild(rendered, "cockpit: relaunched after 26m gap (pid 1234 -> 5678)")).toBe(true);
  });

  it("carries no restart event when boardSummary itself is absent (mount-time race, never fabricated)", () => {
    const rendered = renderedRecentFeed(Homescreen({ state: {} }));
    expect(findTextWhere(rendered, (s) => s.startsWith("cockpit: relaunched"))).toBe(false);
  });

  it("renders GPU/active-run/last-receipt lines from liveTelemetry, each independently optional", () => {
    const rendered = renderedRecentFeed(Homescreen({
      state: {},
      boardSummary: {
        green: 23, total: 30, pctComplete: 76.7, topAttention: [],
        liveTelemetry: {
          gpu: { text: "GPU: 18.0/24.0 GiB \xB7 training-active" },
          activeRun: { text: "run: ember-c-scale/w1-live-progress step 1800, eval_loss 4.9375 \xB7 12s ago" },
          lastReceipt: { text: "receipts: STALE 3h ago", color: "red" },
        },
      },
    }));
    expect(findTextChild(rendered, "GPU: 18.0/24.0 GiB \xB7 training-active")).toBe(true);
    expect(findTextChild(rendered, "run: ember-c-scale/w1-live-progress step 1800, eval_loss 4.9375 \xB7 12s ago")).toBe(true);
    expect(findTextChild(rendered, "receipts: STALE 3h ago")).toBe(true);
    expect(colorForText(rendered, "receipts: STALE 3h ago")).toBe("red");
  });

  it("renders only the fields present in liveTelemetry, never fabricating the absent ones", () => {
    const rendered = renderedRecentFeed(Homescreen({
      state: {},
      boardSummary: {
        green: 23, total: 30, pctComplete: 76.7, topAttention: [],
        liveTelemetry: { gpu: { text: "GPU: 1.0/8.0 GiB \xB7 idle" } },
      },
    }));
    expect(findTextChild(rendered, "GPU: 1.0/8.0 GiB \xB7 idle")).toBe(true);
    expect(findTextWhere(rendered, (s) => s.startsWith("run:"))).toBe(false);
    expect(findTextWhere(rendered, (s) => s.startsWith("receipts:"))).toBe(false);
  });

  it("carries no live-telemetry lines when the field is absent entirely (never fabricates)", () => {
    const rendered = renderedRecentFeed(Homescreen({
      state: {},
      boardSummary: { green: 23, total: 30, pctComplete: 76.7, topAttention: [] },
    }));
    expect(findTextWhere(rendered, (s) => s.startsWith("GPU:") || s.startsWith("run:") || s.startsWith("receipts:"))).toBe(false);
  });
});

describe("formatWallClock — HH:MM:SS local (issue #413: cockpit liveness clock)", () => {
  it("zero-pads hours, minutes, and seconds", () => {
    const nowMs = new Date(2026, 6, 7, 9, 5, 3).getTime(); // local 09:05:03
    expect(formatWallClock(nowMs)).toBe("09:05:03");
  });

  it("renders a full 24h hour without leading-zero truncation", () => {
    const nowMs = new Date(2026, 6, 7, 23, 59, 9).getTime(); // local 23:59:09
    expect(formatWallClock(nowMs)).toBe("23:59:09");
  });

  it("defaults to the real current time when nowMs is omitted", () => {
    const before = Date.now();
    const clock = formatWallClock();
    const after = Date.now();
    expect(clock).toMatch(/^\d{2}:\d{2}:\d{2}$/);
    // The formatted string must be consistent with SOME instant between before/after.
    expect(clock).toBe(formatWallClock(before));
    void after;
  });
});

describe("Homescreen — liveness clock in the recent-activity feed (issue #413)", () => {
  it("shows 'clock: HH:MM:SS' even when no boardSummary has loaded yet (liveness is never gated on board data)", () => {
    const nowMs = new Date(2026, 6, 7, 14, 30, 45).getTime();
    const rendered = renderedRecentFeed(Homescreen({ state: {}, nowMs }));
    expect(findTextChild(rendered, "clock: 14:30:45")).toBe(true);
    expect(findTextChild(rendered, "No recent activity")).toBe(true);
  });

  it("shows the clock line alongside a real board summary, without disturbing the existing badge", () => {
    const nowMs = new Date(2026, 6, 7, 8, 1, 2).getTime();
    const rendered = renderedRecentFeed(Homescreen({
      state: {},
      nowMs,
      boardSummary: { green: 23, total: 30, pctComplete: 76.7, topAttention: [] },
    }));
    expect(findTextChild(rendered, "clock: 08:01:02")).toBe(true);
    expect(findTextWhere(rendered, (s) => s.includes("23/30 GREEN"))).toBe(true);
  });

  it("two renders one second apart produce different clock text (a live re-render actually ticks)", () => {
    const t0 = new Date(2026, 6, 7, 10, 0, 0).getTime();
    const t1 = t0 + 1000;
    const renderedAt0 = renderedRecentFeed(Homescreen({ state: {}, nowMs: t0 }));
    const renderedAt1 = renderedRecentFeed(Homescreen({ state: {}, nowMs: t1 }));
    expect(findTextChild(renderedAt0, "clock: 10:00:00")).toBe(true);
    expect(findTextChild(renderedAt1, "clock: 10:00:01")).toBe(true);
  });

  it("defaults nowMs to the real current time when the caller passes none (matches every other call site's Date.now() default)", () => {
    const rendered = renderedRecentFeed(Homescreen({ state: {} }));
    expect(findTextWhere(rendered, (s) => /^clock: \d{2}:\d{2}:\d{2}$/.test(s))).toBe(true);
  });
});

describe("WelcomeV2 — identity-colored border (not the unstyled default)", () => {
  it("dark theme: border color is the identity token, not left unset", () => {
    const el: any = WelcomeV2({ theme: "dark" });
    expect(el.props.borderColor).toBe(color("identity", "fg", "dark"));
  });

  it("light theme: border color resolves to the light-theme identity token", () => {
    const el: any = WelcomeV2({ theme: "light" });
    expect(el.props.borderColor).toBe(color("identity", "fg", "light"));
  });
});

describe("LogoV2 — wordmark uses the identity token, not a hardcoded color literal", () => {
  it("condensed logo text color equals the identity fg token (dark)", () => {
    const el = LogoV2({ viewportWidth: 80, state: {} });
    const textEl = children(el)[0];
    expect(textEl.props.color).toBe(color("identity", "fg", "dark"));
  });
});

describe("Homescreen — identity tagline (team-lead: 'perfect -- keep it verbatim')", () => {
  it("exports the exact tagline string", () => {
    expect(IDENTITY_TAGLINE).toBe("inference + training, on this machine");
  });

  it("renders the tagline somewhere in the left column (D4: now nested inside the fireball-interleaved identity block, not a flat child)", () => {
    const el = Homescreen({ state: {} });
    const panel = findPanel(el);
    const leftCol = children(panel)[0];
    expect(findTextChild(leftCol, IDENTITY_TAGLINE)).toBe(true);
  });
});

describe("Homescreen — ember-native onboarding hint (not generic-agent phrasing)", () => {
  it("onboarding feed includes an ember-native conversational hint", () => {
    const el = Homescreen({ state: {} });
    const panel = findPanel(el);
    const rightCol = children(panel)[1];
    const onboardingFeedEl = children(rightCol)[0]; // a <FeedComponent feed=...> descriptor
    const rendered = FeedComponent(onboardingFeedEl.props); // actually render it
    const entryTexts = children(rendered)
      .slice(2) // index 0 = title, index 1 = title-underline rule; entries start at 2
      .map((e: any) => e?.props?.children)
      .filter((t: any) => typeof t === "string");
    expect(entryTexts).toContain(`Try "what changed on the board today?"`);
    // never the generic phrasing team-lead flagged
    expect(entryTexts.some((t: string) => t.includes("explain this repo"))).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// #51 regression guard: the identity block renders whatever manifest-derived
// string it is handed, verbatim, for an OWNED artifact -- and never substitutes
// a hardcoded third-party model name. `state.model` for an owned seat is
// produced by entrypoints/model-seat.ts::selectedModelContract() from the
// served manifest's own `modelName` (see entrypoints/owned-seat-loader.ts,
// which validates it against "ember-owned:"/"ember-owned-development:" +
// the checkpoint hash) -- this surface must never diverge from that value by
// falling back to a literal like "qwen"/"deepseek"/"llama".
// ---------------------------------------------------------------------------

describe("Homescreen — owned-seat identity render is truthful (#51)", () => {
  it("renders the manifest-derived owned identity string verbatim in the left column", () => {
    const ownedModelName = "ember-owned:abc123def456";
    const el = Homescreen({ state: { model: ownedModelName } });
    const panel = findPanel(el);
    const leftCol = children(panel)[0];
    expect(findTextChild(leftCol, ownedModelName)).toBe(true);
  });

  it("never substitutes a hardcoded third-party model name for the owned identity", () => {
    const ownedModelName = "ember-owned-development:0011223344ff";
    const el = Homescreen({ state: { model: ownedModelName } });
    const panel = findPanel(el);
    const leftCol = children(panel)[0];
    const HARDCODED_THIRD_PARTY_NAMES = ["qwen", "deepseek", "llama"];
    for (const literal of HARDCODED_THIRD_PARTY_NAMES) {
      expect(findTextWhere(leftCol, (s) => s.toLowerCase().includes(literal))).toBe(false);
    }
  });

  it("omits the identity line entirely when no model is selected (never fabricates a placeholder identity)", () => {
    const el = Homescreen({ state: {} });
    const panel = findPanel(el);
    const leftCol = children(panel)[0];
    expect(findTextWhere(leftCol, (s) => s.includes("\xB7 Local"))).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Polish wince-list (operator regrade 2026-07-03, mock1 flaws):
//  - "Tips" underline overran its own text width (28 dashes under a 25-char title)
//  - no version+update-hint line (a version-and-optional-update-nudge row, standard across CLI tools)
// ---------------------------------------------------------------------------

describe("FeedComponent — section-title underline (polish: exact width, never overrun)", () => {
  it("underline rule is exactly the visible width of the title, never longer or shorter", () => {
    const feed = { title: "Tips for getting started", entries: [{ text: "x" }] };
    const rendered = FeedComponent({ feed });
    const underline = children(rendered)[1];
    expect(underline.props.children).toBe("─".repeat([...feed.title].length));
    expect(underline.props.dimColor).toBe(true);
  });

  it("tracks a different title's width exactly (not a fixed constant)", () => {
    const feed = { title: "Recent activity", entries: [{ text: "x" }] };
    const rendered = FeedComponent({ feed });
    const underline = children(rendered)[1];
    expect(underline.props.children).toBe("─".repeat("Recent activity".length));
  });
});

// ---------------------------------------------------------------------------
// B5 W6 (team-lead, 2026-07-03 pixel pass on welcome-b8-100col): the Tips right-column lines
// overrun the viewport edge at 100 cols -- "Run /init to create an EMBER.md file with" cuts dead
// at column 100, no ellipsis, mid-sentence. Same class as D3/W3: free-length text with no clip
// model. FeedComponent must clip its entries/footer to its own available width, exactly like
// clipToWidth already does for the left column's cwd/model/tagline lines.
// ---------------------------------------------------------------------------

describe("rightColWidth (B5 W6)", () => {
  it("stacked layout (viewportWidth below the row-vs-column threshold): full panel content width", () => {
    // Homescreen stacks column-wise when viewportWidth < LEFT_PANEL_MAX_WIDTH*2 (100) --
    // rightCol isn't sharing a row with leftCol, so it gets the panel's full content width
    // (viewportWidth minus the outer panel's own 2-cell border reservation).
    expect(rightColWidth(80)).toBe(78);
  });

  it("row layout (viewportWidth at/above the threshold): remaining width after leftCol", () => {
    // At 100 cols: panel content = 100-2=98; leftCol claims 58 (Math.max(LEFT_PANEL_MAX_WIDTH,
    // WELCOME_THRESHOLD) = Math.max(50,58)); rightCol gets the rest = 40.
    expect(rightColWidth(100)).toBe(40);
  });

  it("never returns less than 1, even at a pathologically narrow viewport", () => {
    expect(rightColWidth(1)).toBeGreaterThanOrEqual(1);
  });
});

describe("FeedComponent — clips entries/footer to the panel's actual available width (B5 W6)", () => {
  it("at a width narrower than the entry text, the entry is clipped with an ellipsis, never cut with no indicator", () => {
    const feed = { title: "Tips", entries: [{ text: "Run /init to create an EMBER.md file with instructions for Ember" }] };
    const rendered = FeedComponent({ feed, width: 40 });
    const entry = children(rendered)[2]; // 0=title, 1=underline, 2=first entry
    // issue #44 / §8g item 1: clipToWidth is now word-boundary-aware, so the clipped result is
    // whatever length lands on the last whole word within budget -- <= width, not always == width
    // (the prior exact-40 assertion locked in the mid-word-severing bug: "...file wi…").
    expect(entry.props.children.length).toBeLessThanOrEqual(40);
    expect(entry.props.children).toBe("Run /init to create an EMBER.md file…");
    expect(entry.props.children.endsWith("…")).toBe(true);
  });

  it("at a width wide enough to hold the text, nothing is clipped (regression guard)", () => {
    const feed = { title: "Tips", entries: [{ text: "short line" }] };
    const rendered = FeedComponent({ feed, width: 78 });
    const entry = children(rendered)[2];
    expect(entry.props.children).toBe("short line");
  });

  it("with no width prop at all (existing call sites), entries are never clipped -- backward compatible", () => {
    const longText = "Run /init to create an EMBER.md file with instructions for Ember";
    const feed = { title: "Tips", entries: [{ text: longText }] };
    const rendered = FeedComponent({ feed });
    const entry = children(rendered)[2];
    expect(entry.props.children).toBe(longText);
  });

  it("the footer line is clipped the same way as entries", () => {
    const feed = { title: "Recent activity", entries: [{ text: "x" }], footer: "/resume for more -- a much longer footer line than the panel can actually hold at this width" };
    const rendered = FeedComponent({ feed, width: 20 });
    const footer = children(rendered).at(-1);
    // issue #44 / §8g item 1: word-boundary-aware clip -- see note above.
    expect(footer.props.children.length).toBeLessThanOrEqual(20);
    expect(footer.props.children).toBe("/resume for more…");
    expect(footer.props.children.endsWith("…")).toBe(true);
  });
});

// issue #44 / field-ux-map §8g item 1: the right column clipped mid-word ("...for Em",
// "...20260702T174352Z: 1" dangling) because clipToWidth was a raw codepoint-count clip with no
// word-boundary awareness. Fixed to cut at the last whitespace boundary within budget, falling
// back to the raw clip only when a single word alone exceeds the whole width.
describe("clipToWidth — word-boundary-aware truncation (issue #44 / §8g item 1)", () => {
  it("never severs mid-word: cuts back to the last whitespace boundary before the width budget", () => {
    // Exact string + width from the pre-existing FeedComponent clip test -- the raw clip used to
    // produce "...file wi…" (severing "with" mid-word); word-aware must stop at "file" instead.
    const text = "Run /init to create an EMBER.md file with instructions for Ember";
    const clipped = clipToWidth(text, 40);
    expect(clipped).toBe("Run /init to create an EMBER.md file…");
    expect([...clipped].length).toBeLessThanOrEqual(40);
    // The character immediately before the ellipsis must not be adjacent to a word that continues
    // past the cut -- i.e. the source text at the cut point is a real space, not mid-token.
    const cutText = clipped.slice(0, -1); // drop the ellipsis
    expect(text.startsWith(cutText)).toBe(true);
    expect(text[cutText.length]).toBe(" ");
  });

  it("a single word wider than the whole budget falls back to the raw codepoint clip (no infinite regress, never empty)", () => {
    const text = "supercalifragilisticexpialidocious-and-then-some-more-unbroken-text";
    const clipped = clipToWidth(text, 20);
    expect(clipped.endsWith("…")).toBe(true);
    expect([...clipped].length).toBe(20);
    expect(clipped).not.toBe("…"); // must not degrade to nothing-but-ellipsis when real content fits
  });

  it("text that already fits is returned unchanged (regression guard, pre-existing behavior)", () => {
    expect(clipToWidth("short line", 78)).toBe("short line");
  });
});

// #303: the `Data: <path>` line collapsed to a bare "Data:…" at LEFT_TEXT_WIDTH (40) -- a real
// worktree capture showed this exact defect. clipToWidth's word-boundary clip found the ONE space
// in "Data: " itself (a filesystem path has none) and cut everything after it, same failure class
// as the #447 `run:` line's narrow-viewport collapse. shortenDataRootForDisplay shortens the PATH
// (last two segments, leading ellipsis) before clipToWidth ever sees it -- never lossy when the
// full path already fits.
describe("shortenDataRootForDisplay — #303 narrow-viewport collapse fix", () => {
  it("returns a short path unchanged when the full 'Data: <path>' label already fits the budget", () => {
    expect(shortenDataRootForDisplay("Z:\\M\\ember", 40)).toBe("Z:\\M\\ember");
  });

  it("shortens a long worktree path to its last two segments with a leading ellipsis", () => {
    const long = "Z:\\M\\ember\\.claude\\worktrees\\cockpit-telemetry-447";
    expect(shortenDataRootForDisplay(long, 40)).toBe("…\\worktrees\\cockpit-telemetry-447");
  });

  it("uses forward-slash separators for a forward-slash path (never mixes separators)", () => {
    const long = "/home/user/repos/ember/.claude/worktrees/cockpit-telemetry-447";
    expect(shortenDataRootForDisplay(long, 40)).toBe(".../worktrees/cockpit-telemetry-447".replace("...", "…"));
  });

  it("a path with two or fewer segments is returned unchanged even if it doesn't fit (nothing meaningful to trim)", () => {
    // Pathological: a single very long segment. Falls through to clipToWidth's own safety net at
    // the call site, not this function's job to fix.
    const oneLongSegment = "Z:\\" + "x".repeat(60);
    expect(shortenDataRootForDisplay(oneLongSegment, 40)).toBe(oneLongSegment);
  });

  it("never produces the bare-label collapse: the shortened form always carries real path content", () => {
    const long = "Z:\\M\\ember\\.claude\\worktrees\\cockpit-telemetry-447";
    const result = shortenDataRootForDisplay(long, 40);
    expect(result.length).toBeGreaterThan(1);
    expect(clipToWidth(`Data: ${result}`, 40)).not.toBe("Data:…");
  });
});

describe("Homescreen renders the Data: line without collapsing on a long worktree path (#303)", () => {
  it("shows the shortened path, not a bare 'Data:…', for a real long worktree cwd", () => {
    const state = { dataRoot: "Z:\\M\\ember\\.claude\\worktrees\\cockpit-telemetry-447" };
    const rendered = Homescreen({ state, viewportWidth: 190 });
    expect(findTextChild(rendered, "Data: …\\worktrees\\cockpit-telemetry-447")).toBe(true);
    expect(findTextChild(rendered, "Data:…")).toBe(false);
  });

  it("shows the full path untouched for a short dataRoot (no information lost when there's room)", () => {
    const state = { dataRoot: "Z:\\M\\ember" };
    const rendered = Homescreen({ state, viewportWidth: 190 });
    expect(findTextChild(rendered, "Data: Z:\\M\\ember")).toBe(true);
  });
});

describe("Homescreen wires the computed rightColWidth into rightCol's FeedComponents (B5 W6)", () => {
  it("at 100 cols, the onboarding feed's rendered /init line is clipped with an ellipsis, not cut dead", () => {
    const el = Homescreen({ state: {}, viewportWidth: 100 });
    const panel = findPanel(el);
    const rightCol = children(panel)[1];
    const onboardingFeedEl = children(rightCol)[0];
    expect(onboardingFeedEl.props.width).toBe(rightColWidth(100));
    const rendered = FeedComponent(onboardingFeedEl.props);
    const entry = children(rendered)[2];
    expect(entry.props.children.endsWith("…")).toBe(true);
    expect([...entry.props.children].length).toBeLessThanOrEqual(rightColWidth(100));
  });
});

describe("Homescreen — version line + optional update hint (standard CLI version-nudge row)", () => {
  // D4/mock1: the version now renders folded into the wordmark row ("ember" bold + "  vX" dim,
  // two sibling Text nodes -- mock1's own row 2 composition), not a standalone "Ember CLI vX"
  // line. The old exact-string form predates the approved mock1 wordmark row; this still enforces
  // the same intent (a version is always visible, never absent).
  it("always renders a version line (never absent)", () => {
    const el = Homescreen({ state: { version: "0.4.2" } });
    const panel = findPanel(el);
    const leftCol = children(panel)[0];
    expect(findTextChild(leftCol, "ember")).toBe(true);
    expect(findTextWhere(leftCol, (s) => s.includes("0.4.2"))).toBe(true);
  });

  it("no update-hint line when no update is known (model-honest -- never fabricate one)", () => {
    const el = Homescreen({ state: {} });
    const panel = findPanel(el);
    const leftCol = children(panel)[0];
    expect(findTextWhere(leftCol, (s) => s.includes("Update available"))).toBe(false);
  });

  it("renders the update hint only when state.updateAvailable is set", () => {
    const el = Homescreen({ state: { updateAvailable: "0.5.0" } });
    const panel = findPanel(el);
    const leftCol = children(panel)[0];
    expect(findTextChild(leftCol, "Update available: v0.5.0 (run /update)")).toBe(true);
  });
});
