// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// ember-lab-rpc-access.test.ts — child-isolated client failure boundary for same-user pipe enforcement.

import { expect, test } from "bun:test";
import { join } from "node:path";

test("callEmberLab fails closed on same-user named-pipe access denial without retry", async () => {
  const child = Bun.spawn(
    [process.execPath, "test", join(import.meta.dir, "ember-lab-rpc-access-child.test.ts")],
    { stdout: "pipe", stderr: "pipe", env: { ...process.env, EMBER_LAB_ACCESS_CHILD: "1" } },
  );
  const [stdout, stderr, exitCode] = await Promise.all([
    new Response(child.stdout).text(),
    new Response(child.stderr).text(),
    child.exited,
  ]);
  expect(exitCode).toBe(0);
  expect(stdout + stderr).toContain("one denied connection");
});