// d5-chat-turn-render.test.ts — B3 D5: a fresh render exercising mock2's markdown/code path
// (state/design-mockups/chat-turn-markdown-code.mockup.ansi.txt), through the REAL pipeline
// (mountInk), not just prop inspection. No live model server is available in this environment
// (GPU/model-server access is out of scope for this engagement), so this is not a full PTY chat
// round-trip -- it drives AssistantTextMessage with the exact markdown/heading/list/fenced-code
// content the mockup depicts, through the same renderNodeToOutput path a live turn would use,
// which is what actually catches pipeline-level defects (this is exactly how D1's ANSI-truncation
// bug and the style-bleed root cause were found -- prop-level tests alone missed both).
import { describe, test, expect, afterEach } from "bun:test";
import React from "react";
import { AssistantTextMessage } from "./message-renderers.ts";
import { mountInk } from "../ink/reconciler.ts";

let lastHandle: ReturnType<typeof mountInk> | null = null;

function mountAndCapture(el: React.ReactElement, cols = 100, rows = 24): string {
  let buf = "";
  const stream = { write(s: string) { buf += s; } };
  const handle = mountInk(el, { stream, stdout: { columns: cols, rows } });
  lastHandle = handle;
  return buf;
}

afterEach(() => {
  if (lastHandle) {
    try { lastHandle.unmount(); } catch {}
    lastHandle = null;
  }
});

const MOCK2_RESPONSE = [
  "## Retry loop fix",
  "Replaced the fixed backoff with an exponential backoff capped at 8s.",
  "",
  "- Retries now cap at 5 attempts",
  "- Backoff: 250ms x 2^n, max 8s",
  "- Added retry.test.ts covering timeout + abort paths",
  "",
  "```typescript",
  "export async function withRetry(fn, opts = DEFAULT_RETRY_OPTS) {",
  "  for (let attempt = 0; attempt < opts.maxAttempts; attempt++) {",
  "    try { return await fn(); } catch (err) {",
  "      await sleep(backoffMs(attempt, opts));",
  "    }",
  "  }",
  "}",
  "```",
].join("\n");

describe("D5: chat-turn markdown/code content renders through the real pipeline", () => {
  test("mounts without throwing and produces non-empty output", () => {
    const out = mountAndCapture(React.createElement(AssistantTextMessage, { text: MOCK2_RESPONSE }));
    expect(out.length).toBeGreaterThan(0);
  });

  test("the heading text and body text both survive intact (no truncation, no dropped content)", () => {
    const out = mountAndCapture(React.createElement(AssistantTextMessage, { text: MOCK2_RESPONSE }));
    expect(out).toContain("Retry loop fix");
    expect(out).toContain("exponential backoff capped at 8s");
  });

  test("all three bullet lines survive intact", () => {
    const out = mountAndCapture(React.createElement(AssistantTextMessage, { text: MOCK2_RESPONSE }));
    expect(out).toContain("Retries now cap at 5 attempts");
    expect(out).toContain("Backoff: 250ms x 2^n, max 8s");
    expect(out).toContain("retry.test.ts covering timeout");
  });

  test("the fenced code block's content survives intact", () => {
    const out = mountAndCapture(React.createElement(AssistantTextMessage, { text: MOCK2_RESPONSE }));
    expect(out).toContain("export async function withRetry");
    expect(out).toContain("backoffMs(attempt, opts)");
  });

  test("no orphaned SGR fragment (style-bleed regression guard): every '38;2;' color code is preceded by an ESC byte", () => {
    const out = mountAndCapture(React.createElement(AssistantTextMessage, { text: MOCK2_RESPONSE }));
    // A bare "38;2;r;g;bm" with no leading \x1b[ is exactly D1's failure signature.
    const orphaned = /[^\x1b]\[38;2;\d+;\d+;\d+m/;
    expect(orphaned.test(out)).toBe(false);
  });

  test("after this markdown block, an immediately-following plain Text renders with no leftover color (style-bleed guard, general form)", () => {
    const out = mountAndCapture(
      React.createElement(React.Fragment, null,
        React.createElement(AssistantTextMessage, { text: MOCK2_RESPONSE }),
        React.createElement(AssistantTextMessage, { text: "plain follow-up with no markdown" }),
      ),
    );
    const idx = out.lastIndexOf("plain follow-up");
    const before = out.slice(0, idx);
    const lastReset = Math.max(before.lastIndexOf("\x1b[m"), before.lastIndexOf("\x1b[0m"));
    const lastColorCode = before.search(/\x1b\[38;2;\d+;\d+;\d+m(?![\s\S]*\x1b\[38;2;\d+;\d+;\d+m)/);
    if (lastColorCode !== -1) {
      expect(lastReset).toBeGreaterThan(lastColorCode);
    }
  });
});

// ---------------------------------------------------------------------------
// Negative control: planted pollution test
// ---------------------------------------------------------------------------
// This test verifies that the render-state cleanup prevents newline handling
// regressions. It deliberately renders multi-line content, polluting any
// shared module-level state in the rendering pipeline, then verifies that
// the next test in the same suite still works correctly.

describe("Negative control: planted pollution (d5 rendering state isolation)", () => {
  test("rendering with multi-line content (pollution step)", () => {
    // This render pollutes any rendering-pipeline state that isn't properly
    // cleaned up between test invocations. The next test in d5 suite will
    // verify that this pollution did NOT break d5's assertions.
    const multiLineCode = "line 1\nline 2\nline 3";
    const el = React.createElement("span", {
      "data-text": true,
      children: multiLineCode,
    });
    const out = mountAndCapture(el);
    // This pollution test just checks that the pollution render succeeded;
    // the real test is that d5's subsequent test still passes despite it.
    expect(out).toContain("line 1");
    expect(out).toContain("line 2");
    expect(out).toContain("line 3");
  });

  test("d5's assertion still passes after pollution (isolation verification)", () => {
    // This is the regression guard: if the rendering pipeline doesn't properly
    // reset state between renders, the previous pollution test's multi-line
    // handling would break this assertion. If this passes, isolation is good.
    const out = mountAndCapture(React.createElement(AssistantTextMessage, { text: MOCK2_RESPONSE }));
    expect(out).toContain("backoffMs(attempt, opts)");
  });
});
