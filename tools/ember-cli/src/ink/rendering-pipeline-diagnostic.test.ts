// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// issue #898: discriminate elapsed-time, renderer-work, and stdout-byte growth.
import { afterEach, describe, expect, spyOn, test } from "bun:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";
import React from "react";
import { Text } from "./components.ts";
import { mountInk } from "./reconciler.ts";
import {
  createRendererDiagnostic,
  RENDER_DIAGNOSTIC_ENV,
  RENDER_DIAGNOSTIC_SOURCE_ENV,
  runtimeOriginToken,
  type RendererDiagnosticRow,
} from "./renderer-diagnostic.ts";

const roots: string[] = [];

function scratch(): string {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "issue898-render-diag-"));
  roots.push(root);
  return root;
}

afterEach(() => {
  for (const root of roots.splice(0)) fs.rmSync(root, { recursive: true, force: true });
});

function readRows(filePath: string): RendererDiagnosticRow[] {
  return fs.readFileSync(filePath, "utf8").trim().split("\n").filter(Boolean).map((line) => JSON.parse(line));
}

describe("renderer byte diagnostic (issue #898)", () => {
  test("binds runtime origin to a narrow band after the Windows kernel process start", () => {
    if (process.platform !== "win32") return;
    const observed = execFileSync(
      "powershell.exe",
      [
        "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
        `(Get-Process -Id ${process.pid}).StartTime.ToUniversalTime().Ticks`,
      ],
      { encoding: "utf8", windowsHide: true },
    ).trim();
    const hostStartTicks = BigInt(observed);
    const runtimeOriginTicks = BigInt(runtimeOriginToken());
    expect(runtimeOriginTicks).toBeGreaterThanOrEqual(hostStartTicks);
    expect(runtimeOriginTicks - hostStartTicks).toBeLessThanOrEqual(50_000_000n); // 5 seconds
  });

  test("is absent by default and cannot change stdout bytes", () => {
    const render = (diagnostic?: ReturnType<typeof createRendererDiagnostic>): { raw: string; exists: boolean } => {
      let raw = "";
      const handle = mountInk(React.createElement(Text, null, "same"), {
        stream: { write(chunk: string) { raw += chunk; return true; } },
        stdout: { columns: 20, rows: 2 },
        diagnostic,
      });
      handle.update(React.createElement(Text, null, "changed"));
      handle.unmount();
      return { raw, exists: diagnostic ? fs.existsSync(diagnostic.filePath) : false };
    };

    const without = render();
    expect(without.exists).toBe(false);

    const filePath = path.join(scratch(), "renderer.jsonl");
    let now = 0;
    const withDiagnostic = render(createRendererDiagnostic({
      filePath,
      sourceCommit: "d76e9bfd285f30536ef6922ea03c6b89c82ae47a",
      now: () => now,
      emitEveryMs: 30_000,
    }));
    now += 30_000;
    expect(withDiagnostic.raw).toBe(without.raw);
  });

  test("the installed mount path activates from the exact environment pair", () => {
    const filePath = path.join(scratch(), "renderer.jsonl");
    const previousPath = process.env[RENDER_DIAGNOSTIC_ENV];
    const previousSource = process.env[RENDER_DIAGNOSTIC_SOURCE_ENV];
    let handle: ReturnType<typeof mountInk> | undefined;
    try {
      process.env[RENDER_DIAGNOSTIC_ENV] = filePath;
      process.env[RENDER_DIAGNOSTIC_SOURCE_ENV] = "d76e9bfd285f30536ef6922ea03c6b89c82ae47a";
      handle = mountInk(React.createElement(Text, null, "env-wired"), {
        stream: { write() { return true; } },
        stdout: { columns: 20, rows: 2 },
      });
      expect(fs.existsSync(filePath)).toBe(true);
    } finally {
      handle?.unmount();
      if (previousPath === undefined) delete process.env[RENDER_DIAGNOSTIC_ENV];
      else process.env[RENDER_DIAGNOSTIC_ENV] = previousPath;
      if (previousSource === undefined) delete process.env[RENDER_DIAGNOSTIC_SOURCE_ENV];
      else process.env[RENDER_DIAGNOSTIC_SOURCE_ENV] = previousSource;
    }
  });

  test("reports one named sink write failure without stopping renderer output", () => {
    const filePath = path.join(scratch(), "renderer.jsonl");
    const previousPath = process.env[RENDER_DIAGNOSTIC_ENV];
    const previousSource = process.env[RENDER_DIAGNOSTIC_SOURCE_ENV];
    let now = 1_000;
    const nowSpy = spyOn(Date, "now").mockImplementation(() => now);
    const writeSpy = spyOn(fs, "writeSync").mockImplementation(() => {
      throw new Error("RENDER_DIAGNOSTIC_WRITE_TEST_FAILURE");
    });
    const errors: string[] = [];
    let raw = "";
    let handle: ReturnType<typeof mountInk> | undefined;
    try {
      process.env[RENDER_DIAGNOSTIC_ENV] = filePath;
      process.env[RENDER_DIAGNOSTIC_SOURCE_ENV] = "d76e9bfd285f30536ef6922ea03c6b89c82ae47a";
      handle = mountInk(React.createElement(Text, null, "frame-0"), {
        stream: { write(chunk: string) { raw += chunk; return true; } },
        stdout: { columns: 20, rows: 2 },
        onDiagnosticError(error) { errors.push(error.message); },
      });

      now += 30_000;
      handle.update(React.createElement(Text, null, "frame-1"));
      const bytesAfterFailure = Buffer.byteLength(raw);
      now += 30_000;
      handle.update(React.createElement(Text, null, "frame-2"));

      expect(errors).toEqual(["RENDER_DIAGNOSTIC_WRITE_TEST_FAILURE"]);
      expect(Buffer.byteLength(raw)).toBeGreaterThan(bytesAfterFailure);
    } finally {
      handle?.unmount();
      writeSpy.mockRestore();
      nowSpy.mockRestore();
      if (previousPath === undefined) delete process.env[RENDER_DIAGNOSTIC_ENV];
      else process.env[RENDER_DIAGNOSTIC_ENV] = previousPath;
      if (previousSource === undefined) delete process.env[RENDER_DIAGNOSTIC_SOURCE_ENV];
      else process.env[RENDER_DIAGNOSTIC_SOURCE_ENV] = previousSource;
    }
  });

  test("exclusive-creates its path and refuses overwrite", () => {
    const filePath = path.join(scratch(), "renderer.jsonl");
    fs.writeFileSync(filePath, "custody\n", "utf8");
    expect(() => createRendererDiagnostic({
      filePath,
      sourceCommit: "d76e9bfd285f30536ef6922ea03c6b89c82ae47a",
    })).toThrow("RENDER_DIAGNOSTIC_PATH_EXISTS");
    expect(fs.readFileSync(filePath, "utf8")).toBe("custody\n");
  });

  test("emits cumulative render, diff, stdout, and backpressure counters without a timer", () => {
    const filePath = path.join(scratch(), "renderer.jsonl");
    let now = 1_000;
    const diagnostic = createRendererDiagnostic({
      filePath,
      sourceCommit: "d76e9bfd285f30536ef6922ea03c6b89c82ae47a",
      now: () => now,
      emitEveryMs: 30_000,
    });
    const writes: string[] = [];
    let drain: (() => void) | undefined;
    let reject = false;
    const handle = mountInk(React.createElement(Text, null, "frame-0"), {
      stream: {
        write(chunk: string): boolean { writes.push(chunk); return !reject; },
        once(_event: "drain", listener: () => void): void { drain = listener; },
      },
      stdout: { columns: 24, rows: 3 },
      diagnostic,
    });

    handle.update(React.createElement(Text, null, "frame-1"));
    expect(readRows(filePath)).toHaveLength(0);

    now += 30_000;
    reject = true;
    handle.update(React.createElement(Text, null, "frame-2"));
    handle.update(React.createElement(Text, null, "frame-3"));
    expect(drain).toBeDefined();
    reject = false;
    drain!();

    // The first 30s row was emitted by the rejected pass before the subsequent
    // coalesced call and drain repaint existed. Cross one more boundary so the
    // cumulative row under assertion includes the complete episode.
    now += 30_000;
    handle.update(React.createElement(Text, null, "frame-4"));

    const rows = readRows(filePath);
    expect(rows).toHaveLength(2);
    const row = rows[1]!;
    expect(row.schema_version).toBe("ember-renderer-diagnostic-v1");
    expect(row.sequence).toBe(1);
    expect(row.source_commit).toBe("d76e9bfd285f30536ef6922ea03c6b89c82ae47a");
    expect(row.pid).toBe(process.pid);
    expect(row.runtime_origin_token).toMatch(/^\d+$/);
    expect(row.render_calls).toBeGreaterThanOrEqual(5);
    expect(row.render_passes).toBeGreaterThanOrEqual(4);
    expect(row.backpressured_coalesces).toBe(1);
    expect(row.write_false_events).toBe(1);
    expect(row.drain_repaints).toBe(1);
    expect(row.rendered_frame_utf8_bytes).toBeGreaterThan(0);
    expect(row.diff_cells).toBeGreaterThan(0);
    expect(row.optimized_runs).toBeGreaterThan(0);
    expect(row.stream_write_calls).toBe(writes.length);
    expect(row.submitted_utf8_bytes).toBe(writes.reduce((sum, chunk) => sum + Buffer.byteLength(chunk), 0));
    handle.unmount();
  });

  test("counts static-frame commits without inventing submitted stdout bytes", () => {
    const filePath = path.join(scratch(), "renderer.jsonl");
    let now = 1_000;
    const diagnostic = createRendererDiagnostic({
      filePath,
      sourceCommit: "d76e9bfd285f30536ef6922ea03c6b89c82ae47a",
      now: () => now,
      emitEveryMs: 30_000,
    });
    const handle = mountInk(React.createElement(Text, { key: "initial" }, "static"), {
      stream: { write() { return true; } },
      stdout: { columns: 20, rows: 2 },
      diagnostic,
    });

    now += 30_000;
    handle.update(React.createElement(Text, { key: "static-1" }, "static"));
    now += 30_000;
    handle.update(React.createElement(Text, { key: "static-2" }, "static"));

    const rows = readRows(filePath);
    expect(rows).toHaveLength(2);
    expect(rows[1]!.render_calls - rows[0]!.render_calls).toBe(1);
    expect(rows[1]!.render_passes - rows[0]!.render_passes).toBe(1);
    expect(rows[1]!.rendered_frame_utf8_bytes).toBeGreaterThan(rows[0]!.rendered_frame_utf8_bytes);
    expect(rows[1]!.diff_cells).toBe(rows[0]!.diff_cells);
    expect(rows[1]!.optimized_runs).toBe(rows[0]!.optimized_runs);
    expect(rows[1]!.submitted_utf8_bytes).toBe(rows[0]!.submitted_utf8_bytes);
    handle.unmount();
  });

  test("separates changing truecolor frames from static frames at equal commit counts", () => {
    const runArm = (colors: string[]): RendererDiagnosticRow => {
      const filePath = path.join(scratch(), "renderer.jsonl");
      let now = 1_000;
      const diagnostic = createRendererDiagnostic({
        filePath,
        sourceCommit: "d76e9bfd285f30536ef6922ea03c6b89c82ae47a",
        now: () => now,
        emitEveryMs: 30_000,
      });
      const handle = mountInk(React.createElement(Text, { color: colors[0], key: "frame-0" }, "color"), {
        stream: { write() { return true; } },
        stdout: { columns: 20, rows: 2 },
        diagnostic,
      });
      for (let index = 1; index < colors.length; index += 1) {
        now += 30_000;
        handle.update(React.createElement(Text, { color: colors[index], key: `frame-${index}` }, "color"));
      }
      const row = readRows(filePath).at(-1)!;
      handle.unmount();
      return row;
    };

    const staticRow = runArm(["#010101", "#010101", "#010101"]);
    const changingRow = runArm(["#010101", "#fefefe", "#020202"]);
    expect(changingRow.render_calls).toBe(staticRow.render_calls);
    expect(changingRow.render_passes).toBe(staticRow.render_passes);
    expect(changingRow.rendered_frame_utf8_bytes).toBeGreaterThan(staticRow.rendered_frame_utf8_bytes);
    expect(changingRow.diff_cells).toBeGreaterThan(staticRow.diff_cells);
    expect(changingRow.optimized_runs).toBeGreaterThan(staticRow.optimized_runs);
    expect(changingRow.submitted_utf8_bytes).toBeGreaterThan(staticRow.submitted_utf8_bytes);
  });
});
