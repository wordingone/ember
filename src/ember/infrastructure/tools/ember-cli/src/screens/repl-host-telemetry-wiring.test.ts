// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// R1e (state/operator-pass-2026-07-26.md, "W3 diagnosed" -- corrected root cause, see the
// delivery report): the operator-pass description of this defect as "nothing in the production
// path calls pushGpuSample(), so vram/gpu series have ZERO entries" is WRONG as of this branch's
// base -- commit 9f998b4 already wires `useGpuStatePoller()` -> `useHostTelemetryPoller(gpuState)`
// -> `host: hostTelemetry` into OperatorSurfacePane inside screens/repl.ts (verified via git blame
// before this commit). host-telemetry-poller.test.ts already covers `createHostTelemetryPoller`
// and `pushGpuSample` in isolation, but never through the REAL React hook chain at its production
// entry point (mounting ReplScreen) -- "production entry is a chain, not a point"
// (state/failure-classes/production-entry-is-a-chain-not-a-point-2026-07-25.md): the isolated
// tests verify the mechanism works when called directly, not that repl.ts's composition actually
// calls it. This file closes that gap.
//
// The REAL residual defect this commit fixes (operator-surface-pane.ts's hostMetricLines): the
// pane's total line budget (prefix.length + plotColumns, this component's own innerWidth) had zero
// slack for the trailing `[reason]` bracket a null-with-reason sample appends, so the outer
// boundedSurfaceLine pass silently truncated it off -- an all-null series with a real
// unavailableReason then rendered IDENTICAL to a genuinely-never-polled empty series (both just a
// gap-glyph axis, no visible text), which is exactly the "distinguish empty from all-null"
// requirement failing silently. Verified below at the pane's real production width.
import { afterEach, describe, expect, test } from "bun:test";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../../../../../../../tools/ember-cli/src/ink/rendering-pipeline.ts";
import { TerminalSizeContext } from "../ink/components.ts";
import { resetCommandRegistryForTests } from "../../../../../../../tools/ember-cli/src/command-registry.ts";
import { ReplScreen } from "../../../../../../../tools/ember-cli/src/screens/repl.ts";

async function flushRepl(): Promise<void> {
  for (let index = 0; index < 5; index++) {
    await new Promise<void>((resolve) => setImmediate(resolve));
  }
}

function renderedLines(raw: string, columns: number, rows: number): string[] {
  const frame = buildFrame(columns, rows);
  parseRenderedIntoFrame(raw, frame, new StylePool());
  return frame.cells.map((line) => line.map((cell) => cell?.char ?? " ").join(""));
}

describe("host telemetry wiring at the real production entry point (ReplScreen)", () => {
  let mounted: ReturnType<typeof mountInk> | null = null;

  afterEach(() => {
    mounted?.unmount();
    mounted = null;
  });

  test("pushGpuSample fires through the real hook chain: vram/gpu carry a real sample, not a zero-entry series", async () => {
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
    mounted = mountInk(element, { stream: { write(s: string) { raw += s; } }, stdout: { columns, rows } });
    await flushRepl();
    const lines = renderedLines(raw, columns, rows);

    // Before the mount effect flushes, gpuState starts null (useGpuStatePoller's own initial
    // state) -- useHostTelemetryPoller's `useEffect(() => pushGpuSample(gpuState), [gpuState])`
    // still fires with that initial null on mount, without waiting for a real nvidia-smi poll to
    // land. So vram/gpu are NOT the zero-entry "SOURCE UNBOUND" the operator-pass described --
    // they are bound, null-with-reason ("nvidia-smi unavailable" in this sandboxed test env,
    // where nvidia-smi is genuinely absent) -- a real sample arrived through the real chain.
    const vramLine = lines.find((l) => l.includes("host VRAM"));
    const gpuLine  = lines.find((l) => l.includes("host GPU"));
    expect(vramLine).toBeDefined();
    expect(gpuLine).toBeDefined();
    expect(vramLine!).not.toContain("SOURCE UNBOUND");
    expect(gpuLine!).not.toContain("SOURCE UNBOUND");

    // The R1e fix under test: the reason bracket must SURVIVE the pane's own width bounding, not
    // get silently clipped (the defect this commit actually fixes).
    expect(vramLine!).toContain("[");
    expect(vramLine!).toContain("]");
    expect(gpuLine!).toContain("[");
    expect(gpuLine!).toContain("]");
  });
});
