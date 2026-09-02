// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { expect, test } from "bun:test";
import { join } from "node:path";

test("open deadline rejects silent and late transports in fresh isolated clients", async () => {
  for (const testCase of ["silent", "late"]) {
    const child = Bun.spawn(
      [process.execPath, "test", join(import.meta.dir, "ember-lab-rpc-open-timeout-child.test.ts")],
      { stdout: "pipe", stderr: "pipe", env: { ...process.env, EMBER_LAB_OPEN_TIMEOUT_CASE: testCase } },
    );
    const [stdout, stderr, exitCode] = await Promise.all([
      new Response(child.stdout).text(), new Response(child.stderr).text(), child.exited,
    ]);
    expect(exitCode).toBe(0);
    expect(stdout + stderr).toContain("1 pass");
  }
}, 25_000);
