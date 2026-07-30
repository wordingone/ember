// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { afterEach, describe, expect, test } from "bun:test";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import React from "react";
import { Text } from "./components.ts";
import { mountInk } from "./reconciler.ts";

const originalTemp = process.env["TEMP"];
const originalTmp = process.env["TMP"];
const scratchRoots: string[] = [];

afterEach(() => {
  if (originalTemp === undefined) delete process.env["TEMP"];
  else process.env["TEMP"] = originalTemp;
  if (originalTmp === undefined) delete process.env["TMP"];
  else process.env["TMP"] = originalTmp;
  for (const root of scratchRoots.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
});

describe("production rendering has no per-frame diagnostic file side effect", () => {
  test("repeated renders never append ember-m9-diag.jsonl", () => {
    const scratch = mkdtempSync(join(tmpdir(), "ember-render-no-debug-"));
    scratchRoots.push(scratch);
    process.env["TEMP"] = scratch;
    process.env["TMP"] = scratch;

    const stream = { write(_chunk: string): void {} };
    const handle = mountInk(
      React.createElement(Text, null, "frame 0"),
      { stream, stdout: { columns: 80, rows: 24 } },
    );
    for (let frame = 1; frame <= 10; frame += 1) {
      handle.update(React.createElement(Text, null, `frame ${frame}`));
    }
    handle.unmount();

    expect(existsSync(join(scratch, "ember-m9-diag.jsonl"))).toBe(false);
  });
});
