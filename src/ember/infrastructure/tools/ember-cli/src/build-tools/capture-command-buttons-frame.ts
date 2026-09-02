// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// build-tools/capture-command-buttons-frame.ts — visual proof for #1399: what the operator
// actually sees after the command buttons moved into the live-run pane.
//
// This mounts the REAL ReplScreen against the REAL command registry and reconstructs the frame
// through the product's own rendering pipeline, the same way screens/width-sweep-probe.test.ts
// does. It is deliberately NOT the pty harnesses (build-tools/drive-train-frame.ts,
// palette-frame-capture.ts): those drive the compiled binary, which is the right instrument for
// proving the BINARY paints, and the wrong one for a layout change that needs to be re-captured
// at half a dozen widths on every edit. Nothing here types, clicks, or writes outside `outDir`.
//
//   bun run ./build-tools/capture-command-buttons-frame.ts <outDir> [cols x rows ...]
//
// Point `outDir` OUTSIDE the repository. The frames are PR evidence, not repository receipts:
// everything under `receipts/` must carry an authority binding the guard can verify (a plain
// .txt frame fails it), and `state/` is ignored. The reusable artifact is this harness; the
// frames it emits belong in the pull request that cites them.
//
// Default sizes are the cockpit sizes the width sweep already treats as supported.

import { mkdirSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../ink/rendering-pipeline.ts";
import { TerminalSizeContext } from "../ink/components.ts";
import { ReplScreen } from "../screens/repl.ts";
import { startTelemetryWatch } from "../services/telemetry-watch.ts";
import { headlessCaptureEnv } from "../services/headless-capture.ts";

// Belt and braces: writers that read the ambient process env rather than the screen's `env` prop
// must see the instrument flag too, and this process IS the harness rather than a child of it.
Object.assign(process.env, headlessCaptureEnv());

const DEFAULT_SIZES: Array<[number, number]> = [[80, 24], [100, 30], [140, 40]];

function parseSizes(args: string[]): Array<[number, number]> {
  const parsed = args
    .map((arg) => arg.split("x").map((part) => Number.parseInt(part, 10)))
    .filter((pair): pair is [number, number] =>
      pair.length === 2 && pair.every((value) => Number.isFinite(value) && value > 0));
  return parsed.length > 0 ? parsed : DEFAULT_SIZES;
}

async function settle(): Promise<void> {
  for (let flush = 0; flush < 8; flush++) {
    await new Promise<void>((done) => setTimeout(done, 40));
    await new Promise<void>((done) => setImmediate(done));
  }
}

async function captureOne(columns: number, rows: number): Promise<string> {
  let raw = "";
  const element = React.createElement(
    TerminalSizeContext.Provider,
    { value: { columns, rows } },
    React.createElement(ReplScreen, {
      config: { model: "ember", permissionMode: "bypass" as const, baseSystemPrompt: "" },
      cwd: process.cwd(),
      // This process is an INSTRUMENT, not the operator's cockpit: without this it publishes a
      // liveness heartbeat the watchdog reads as a live cockpit, and an activity-feed watermark —
      // both of which resolve to the MAIN repo root by design, so running from a worktree does
      // not contain either. See services/headless-capture.ts.
      env: { ...headlessCaptureEnv(), EMBER_DISABLE_TERMINAL_TITLE: "1", EMBER_DISABLE_VIRTUAL_SCROLL: "1" },
      onExit: () => {},
    }),
  );
  const handle = mountInk(element, {
    stream: { write(chunk: string) { raw += chunk; } },
    stdout: { columns, rows },
  });
  try {
    await settle();
    // Parse BEFORE unmount: unmount emits a screen-clearing pass that blanks every cell.
    const frame = buildFrame(columns, rows);
    parseRenderedIntoFrame(raw, frame, new StylePool());
    return frame.cells.map((line) => line.map((cell) => cell?.char ?? " ").join("").replace(/\s+$/, "")).join("\n");
  } finally {
    handle.unmount();
  }
}

async function main(): Promise<void> {
  const outDir = resolve(process.argv[2] ?? "");
  if (!process.argv[2]) throw new Error("usage: capture-command-buttons-frame.ts <outDir> [80x24 ...]");
  mkdirSync(outDir, { recursive: true });
  const sizes = parseSizes(process.argv.slice(3));
  startTelemetryWatch().stop();
  for (const [columns, rows] of sizes) {
    const frame = await captureOne(columns, rows);
    const path = join(outDir, `cockpit-${columns}x${rows}.frame.txt`);
    writeFileSync(path, `${frame}\n`, "utf8");
    console.log(`wrote ${path}`);
  }
  startTelemetryWatch().stop();
}

await main();
process.exit(0);
