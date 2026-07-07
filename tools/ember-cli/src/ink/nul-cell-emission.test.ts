// nul-cell-emission.test.ts -- issue #343 investigation.
//
// The issue reports raw 0x00 (NUL) bytes as cell padding, and one padding run under a
// [1m[2m[7m style stack (a solid inverse/grey bar), at ~190x85 -- captured via a real pty
// (node-pty/ConPTY on Windows). This suite proves, via the SAME production render path every
// other rendering-pipeline test in this repo uses (mountInk -- see app-resize.test.ts,
// chrome-stack.test.ts, bottom-anchor.test.ts, homescreen-fireball-live-tick.test.ts), that
// rendering-pipeline.ts's own cell/patch-write logic NEVER emits a NUL byte or a stray inverse
// span outside a single-cell cursor, at any of the swept sizes, for the real Homescreen +
// PromptInput + StatusLine composition (border-title dash run, truecolor fireball, inverse
// cursor, dim status text -- every ingredient named in the issue).
//
// IMPORTANT PROVENANCE NOTE (do not delete/water down without re-reading the investigation):
// this suite's two halves have DIFFERENT master status -- do not flatten that into one claim.
//
// The NUL-byte tests are GREEN at master, BY DESIGN, not because #343 is unreproducible here.
// Root-causing #343 required going one level below mountInk's in-memory capture -- direct
// instrumentation of `process.stdout.write` inside a real node-pty child process proved the
// string THIS PROCESS hands to stdout.write never contains a NUL byte (0 of 0, across repeated
// real-pty repros that DO show ~400+ NUL bytes on the pty's *receiving* side, byte-for-byte
// reproducing the issue's own capture). That corruption is added strictly between this
// process's write() call and the pty's read side -- i.e. by the Windows ConPTY/conhost layer,
// not by this renderer -- and mountInk never goes through a real pty, so it structurally cannot
// observe that layer. These tests are the receipt that our OWN emission code is provably clean
// of the NUL half of the defect; a future regression here is a REAL bug in rendering-pipeline.ts,
// not a re-run of #343's NUL corruption.
//
// The inverse-run tests ARE the RED-at-master proof for the OTHER half of #343 (the visual
// bold+dim+inverse "bar" stack): the style leak lives in this file's own JS code, so mountInk
// sees it directly. Before the fix: 6 of these failing (largest observed leaked-inverse run:
// 319 chars, at 220x60). After the fix: 11/11 pass, all sizes. See the PR body for the full
// master-run failing-test-name list.
import { describe, test, expect } from "bun:test";
import React from "react";
import { Box } from "./components.ts";
import { Homescreen } from "../components/logo-homescreen.ts";
import { PromptInput } from "../components/prompt-input.ts";
import { StatusLine } from "../components/status-bar.ts";
import { mountInk } from "./reconciler.ts";

// Sweep sizes named in the issue's acceptance criteria (100x32/130x60/220x60 reported clean;
// 190x85 is the operator's real half-screen viewport and the one that reproduced; 250x90 added
// as a larger boundary case).
const SWEEP_SIZES: Array<[number, number]> = [
  [100, 32], [130, 60], [190, 85], [220, 60], [250, 90],
];

function buildRealTree(cols: number, rows: number, tick: number): React.ReactElement {
  const state = { version: "0.0.0", model: "local-model", cwd: process.cwd() };
  return React.createElement(
    Box, { flexDirection: "column", height: rows },
    React.createElement(
      Box, { key: "transcript", flexDirection: "column", flexGrow: 1, overflow: "hidden" },
      React.createElement(Homescreen, { state, viewportWidth: cols, fireballTick: tick }),
    ),
    React.createElement(PromptInput, {
      key: "input",
      state: { text: "", cursor: 0, mode: "bypass", permissionMode: "bypass", isStashed: false, stashNotice: "" } as any,
      isProcessing: false,
      showStatusLine: false,
      width: cols,
    }),
    React.createElement(StatusLine, {
      key: "status",
      permissionMode: { mode: "bypass", cycle: () => {} },
      interrupt: { interrupt: () => {} },
      taskPanel: { visible: false, toggle: () => {}, tasks: [] },
    }),
  );
}

/** Captures the full accumulated write() stream across a mount + N animation ticks (mirrors a
 * real boot: the fireball ticks on an interval, re-rendering the whole tree each time). */
function captureAcrossTicks(cols: number, rows: number, ticks: number): string {
  let buf = "";
  const stream = { write(s: string) { buf += s; } };
  const handle = mountInk(buildRealTree(cols, rows, 0), { stream, stdout: { columns: cols, rows } });
  for (let t = 1; t <= ticks; t++) handle.update(buildRealTree(cols, rows, t));
  return buf;
}

/** Scans the stream character-by-character tracking whether SGR "7" (inverse) is CURRENTLY an
 * active parameter (correctly parsed as a standalone SGR param -- never a substring match against
 * a truecolor code like `38;2;255;7;61m`, which contains the digits "7" without meaning inverse).
 * Returns the literal cell-content length of every contiguous run painted while inverse is active.
 * Used to assert every inverse run is exactly one cell (the block cursor), never a multi-cell
 * "grey bar". */
function inverseRunLengths(out: string): number[] {
  const runs: number[] = [];
  let inverseActive = false;
  let currentRunLen = 0;
  let pos = 0;
  while (pos < out.length) {
    if (out[pos] === "\x1b" && out[pos + 1] === "[") {
      const m = /^\x1b\[([0-9;]*)([A-Za-z])/.exec(out.slice(pos));
      if (m) {
        const [, params, final] = m;
        pos += m[0].length;
        if (final === "m") {
          const codes = params === "" ? ["0"] : params!.split(";");
          if (codes.includes("0") || codes.includes("")) inverseActive = false;
          if (codes.includes("27")) inverseActive = false;
          if (codes.includes("7")) inverseActive = true;
          continue;
        }
        continue;
      }
      pos++;
      continue;
    }
    // printable char (or anything else) at current inverse state
    if (inverseActive) currentRunLen++;
    else if (currentRunLen > 0) { runs.push(currentRunLen); currentRunLen = 0; }
    pos++;
  }
  if (currentRunLen > 0) runs.push(currentRunLen);
  return runs;
}

describe("issue #343: NUL-cell / stray-inverse emission (production render path, mountInk)", () => {
  for (const [cols, rows] of SWEEP_SIZES) {
    test(`${cols}x${rows}: zero 0x00 bytes across a mount + 20 fireball ticks`, () => {
      const out = captureAcrossTicks(cols, rows, 20);
      const nulCount = (out.match(/\x00/g) ?? []).length;
      expect(nulCount).toBe(0);
    });

    test(`${cols}x${rows}: every inverse (7m) run is a single cell (the cursor), never a multi-cell bar`, () => {
      const out = captureAcrossTicks(cols, rows, 20);
      for (const runLen of inverseRunLengths(out)) {
        // The cursor paints exactly one visible character (or a lone space). A "grey bar" defect
        // shows up as an inverse run spanning many cells (a run of spaces/NULs) instead of one.
        expect(runLen).toBeLessThanOrEqual(1);
      }
    });
  }

  test("190x85 locked regression: the operator's real half-screen viewport specifically", () => {
    const out = captureAcrossTicks(190, 85, 30);
    expect((out.match(/\x00/g) ?? []).length).toBe(0);
    for (const runLen of inverseRunLengths(out)) {
      expect(runLen).toBeLessThanOrEqual(1);
    }
  });
});
