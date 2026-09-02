// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// #924: repl.ts wired EMBER_PUBLIC_SOURCE_COMMIT/EMBER_CLI_BINARY_SHA256
// straight to the operator surface pane with no producer ever setting
// sourceBindingVerified, so the pane always fell back to
// "SOURCE UNVERIFIED/UNBOUND" -- even when the claimed values were
// bit-for-bit correct. This end-to-end render proves the wired-in
// verifySourceBinding() producer (screens/repl.ts) renders the bound source
// line once the claimed commit and binary hash independently match the real
// git HEAD and the real running binary, and stays fail-closed the moment the
// claimed commit goes stale.
//
// A single ReplScreen mount is reused across both env variants (via
// handle.update) rather than two independent mountInk() calls -- this repo's
// Bun test runner (bun 1.3.12, Windows) panics with an internal assertion
// failure when a test FILE performs more than one independent mountInk() of
// ReplScreen, even across separate `test()` blocks with proper unmount
// (reproduced and isolated as part of #924's build; every other repl
// mountInk-based test file in this directory follows the same one-mount-
// per-file convention).
import { describe, expect, test } from "bun:test";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import React from "react";
import { mountInk } from "../ink/reconciler.ts";
import { buildFrame, parseRenderedIntoFrame, StylePool } from "../../../../../../../tools/ember-cli/src/ink/rendering-pipeline.ts";
import { TerminalSizeContext } from "../ink/components.ts";
import { ReplScreen } from "../../../../../../../tools/ember-cli/src/screens/repl.ts";

describe("repl operator surface source binding", () => {
  test("binds the source line to real evidence and fails closed on a stale claim", () => {
    const cwd = process.cwd();
    const realCommit = execFileSync("git", ["rev-parse", "HEAD"], { cwd, encoding: "utf8" }).trim();
    const realBinaryHash = createHash("sha256").update(fs.readFileSync(process.execPath)).digest("hex");
    const config = { model: "ember", permissionMode: "bypass" as const, baseSystemPrompt: "" };

    const verifiedElement = React.createElement(
      TerminalSizeContext.Provider,
      { value: { columns: 120, rows: 24 } },
      React.createElement(ReplScreen, {
        config,
        cwd,
        env: {
          EMBER_DISABLE_TERMINAL_TITLE: "1",
          EMBER_DISABLE_VIRTUAL_SCROLL: "1",
          EMBER_PUBLIC_SOURCE_COMMIT:   realCommit,
          EMBER_CLI_BINARY_SHA256:      realBinaryHash,
        },
        onExit: () => {},
      }),
    );
    let raw = "";
    const handle = mountInk(verifiedElement, { stream: { write(s: string) { raw += s; } }, stdout: { columns: 120, rows: 24 } });
    let frame = buildFrame(120, 24);
    parseRenderedIntoFrame(raw, frame, new StylePool());
    let lines = frame.cells.map((line) => line.map((cell) => cell?.char ?? " ").join(""));
    expect(lines.some((line) => line.includes("SOURCE UNVERIFIED/UNBOUND"))).toBe(false);
    expect(lines.some((line) => /source [0-9a-f]{12}… binary [0-9a-f]{12}…/i.test(line))).toBe(true);

    const staleElement = React.createElement(
      TerminalSizeContext.Provider,
      { value: { columns: 120, rows: 24 } },
      React.createElement(ReplScreen, {
        config,
        cwd,
        env: {
          EMBER_DISABLE_TERMINAL_TITLE: "1",
          EMBER_DISABLE_VIRTUAL_SCROLL: "1",
          EMBER_PUBLIC_SOURCE_COMMIT:   "0".repeat(40),
          EMBER_CLI_BINARY_SHA256:      realBinaryHash,
        },
        onExit: () => {},
      }),
    );
    raw = "";
    handle.update(staleElement);
    frame = buildFrame(120, 24);
    parseRenderedIntoFrame(raw, frame, new StylePool());
    lines = frame.cells.map((line) => line.map((cell) => cell?.char ?? " ").join(""));
    expect(lines.some((line) => line.includes("SOURCE UNVERIFIED/UNBOUND"))).toBe(true);

    handle.unmount();
  });
});
