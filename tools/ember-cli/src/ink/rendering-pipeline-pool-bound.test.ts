// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// rendering-pipeline-pool-bound.test.ts — issue #1455 (cockpit leaked to 64.5 GiB of commit
// while idle, 2026-08-05 02:01:10 local, PID 48660, Resource-Exhaustion-Detector event 2004).
//
// StylePool and HyperlinkPool are constructed exactly ONCE per createRenderer() call
// (ink/reconciler.ts's mountInk mounts exactly one renderer for the cockpit's entire process
// lifetime) and BOTH `.intern()` methods are pure appenders: a style/hyperlink identity not
// already present is pushed onto an array that nothing ever shrinks. Under a bounded terminal
// palette (a handful of named colors) this array stabilizes at a tiny size and the defect is
// invisible. It stops being invisible the moment ANY code path paints a style whose identity is
// not stable across renders -- e.g. a numeric-driven gradient, a per-tick computed true-color
// value, or syntax-highlighted tool output with enough distinct token colors over a long enough
// session. Nothing bounds that growth before this fix; the renderer keeps the object alive for
// as long as the cockpit stays up, which an idle cockpit with a redrawing spinner/clock does for
// hours.
//
// This file proves two things with the REAL render path (mountInk, not a reimplementation):
// 1. StylePool.intern()/HyperlinkPool.intern() are still unbounded appenders in isolation --
//    that primitive behavior is intentional (mid-frame eviction would invalidate refs the
//    CURRENT frame is still building) and is exactly what createRenderer's cap now bounds from
//    the outside.
// 2. createRenderer's cap check actually fires on the real mountInk path, resets both pools, and
//    the renderer keeps producing byte-correct output afterward -- the fix does not trade a slow
//    leak for a visible corruption bug.
import { describe, test, expect } from "bun:test";
import React from "react";
import { Box, Text } from "./components.ts";
import { mountInk } from "./reconciler.ts";
import {
  StylePool,
  HyperlinkPool,
  STYLE_POOL_CAP,
  HYPERLINK_POOL_CAP,
} from "./rendering-pipeline.ts";

describe("StylePool / HyperlinkPool primitives (issue #1455)", () => {
  test("StylePool.intern never evicts on its own -- N distinct styles produce N+1 live slots", () => {
    const pool = new StylePool();
    const n = 500;
    for (let i = 0; i < n; i++) {
      // Splits i across the three 8-bit channels so every i in range produces a genuinely
      // distinct (r,g,b) triple -- i < 2^24, well within range for n=500.
      pool.intern({ fg: { type: "rgb", r: i & 0xff, g: (i >> 8) & 0xff, b: (i >> 16) & 0xff } });
    }
    // +1 for the permanent default style at handle 0. This is the exact shape of the defect:
    // nothing in StylePool itself ever shrinks this number.
    expect(pool.size()).toBe(n + 1);
  });

  test("StylePool.reset() drops every interned style except the permanent default", () => {
    const pool = new StylePool();
    for (let i = 0; i < 200; i++) pool.intern({ fg: { type: "rgb", r: i, g: 0, b: 0 } });
    expect(pool.size()).toBe(201);
    pool.reset();
    expect(pool.size()).toBe(1);
    // The default handle is still valid and still resolves to the empty style.
    expect(pool.lookup(0)).toEqual({});
  });

  test("HyperlinkPool.intern never evicts on its own; reset() drops every entry", () => {
    const pool = new HyperlinkPool();
    for (let i = 0; i < 300; i++) pool.intern(null, `https://example.invalid/${i}`);
    expect(pool.size()).toBe(300);
    pool.reset();
    expect(pool.size()).toBe(0);
  });

  test("re-interning a style seen before the reset gets a handle that may collide with a stale one -- callers MUST treat a reset as a full-repaint boundary, never a mid-diff swap", () => {
    const pool = new StylePool();
    const preResetRef = pool.intern({ bold: true });
    pool.reset();
    const postResetRef = pool.intern({ bold: true });
    // Both are legitimately handle 1 (first non-default slot) -- the SAME numeric ref now means a
    // DIFFERENT thing than it did before the reset. This is exactly why createRenderer's cap
    // check forces geometryChanged=true (bypass the diff entirely) instead of trusting the old
    // prevFrame's styleRef values across a reset.
    expect(postResetRef).toBe(preResetRef);
  });
});

describe("createRenderer cap: real mountInk path resets pools and keeps rendering correctly (issue #1455)", () => {
  function mountWithInjectedPools(cols = 20, rows = 4) {
    let buf = "";
    const stream = { write(s: string) { buf += s; } };
    const stylePool = new StylePool();
    const hyperlinkPool = new HyperlinkPool();
    const handle = mountInk(
      React.createElement(Box, null, React.createElement(Text, { color: "#000000" }, "seed")),
      { stream, stdout: { columns: cols, rows }, stylePool, hyperlinkPool },
    );
    return { handle, stylePool, hyperlinkPool, getBuf: () => buf };
  }

  function distinctColorUpdate(i: number): React.ReactElement {
    const hex = `#${(i % 0xffffff).toString(16).padStart(6, "0")}`;
    return React.createElement(Box, null, React.createElement(Text, { color: hex }, `v${i}`));
  }

  test("driving far more distinct colors than STYLE_POOL_CAP never lets the pool grow past a small bounded slack", () => {
    const { handle, stylePool } = mountWithInjectedPools();
    const updates = STYLE_POOL_CAP + 500;
    let maxObservedSize = 0;
    for (let i = 0; i < updates; i++) {
      handle.update(distinctColorUpdate(i));
      maxObservedSize = Math.max(maxObservedSize, stylePool.size());
    }
    handle.unmount();

    // Pre-fix (StylePool.intern with no external cap), this loop would have driven pool.size()
    // to `updates + 1` (~4597) and kept growing forever on a longer-lived process -- proven by
    // the unbounded-appender unit test above. Post-fix, size() must never be observed climbing
    // past the cap plus the handful of new styles a single in-flight frame can add before the
    // NEXT render's cap check catches it.
    const singleFrameSlack = 8;
    expect(maxObservedSize).toBeLessThanOrEqual(STYLE_POOL_CAP + singleFrameSlack);
  });

  test("after the cap resets the pool mid-session, the renderer still renders the CURRENT frame's content correctly (no corruption from the forced full repaint)", () => {
    const { handle, stylePool, getBuf } = mountWithInjectedPools();
    for (let i = 0; i < STYLE_POOL_CAP + 50; i++) handle.update(distinctColorUpdate(i));

    // Confirm the cap actually fired at least once during that run (this test is meaningless if
    // it didn't -- it would just be re-testing "rendering works", not "the reset path is safe").
    expect(stylePool.size()).toBeLessThan(STYLE_POOL_CAP + 50);

    const finalIndex = STYLE_POOL_CAP + 49;
    handle.update(distinctColorUpdate(finalIndex));
    handle.unmount();

    const buf = getBuf();
    expect(buf).toContain(`v${finalIndex}`);
    const expectedHex = `#${(finalIndex % 0xffffff).toString(16).padStart(6, "0")}`;
    const r = parseInt(expectedHex.slice(1, 3), 16);
    const g = parseInt(expectedHex.slice(3, 5), 16);
    const b = parseInt(expectedHex.slice(5, 7), 16);
    expect(buf).toContain(`${r};${g};${b}`);
  });

  test("HyperlinkPool.reset() is reachable through the same cap path and never corrupts a subsequent render (defensive bound -- HyperlinkPool.intern() has no production caller today, but the pool must not silently grow unbounded the day one is wired)", () => {
    const stream = { write(_s: string) {} };
    const hyperlinkPool = new HyperlinkPool();
    for (let i = 0; i < HYPERLINK_POOL_CAP + 10; i++) {
      hyperlinkPool.intern(null, `https://example.invalid/${i}`);
    }
    expect(hyperlinkPool.size()).toBe(HYPERLINK_POOL_CAP + 10);

    const stylePool = new StylePool();
    const handle = mountInk(
      React.createElement(Text, null, "hyperlink-cap-probe"),
      { stream, stdout: { columns: 40, rows: 3 }, stylePool, hyperlinkPool },
    );
    // mountInk's own initial synchronous render already observes the pre-seeded breach and
    // resets before this test drives anything further -- nothing here calls
    // hyperlinkPool.intern() (no production node type does yet), so the pool stays at exactly 0
    // once reset rather than climbing back toward the cap.
    handle.update(React.createElement(Text, null, "hyperlink-cap-probe-2"));
    handle.unmount();
    expect(hyperlinkPool.size()).toBe(0);
  });
});
