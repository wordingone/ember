// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// emberd-rpc-post-connect-error.test.ts — fresh-process regression for a connected transport reset.

import { expect, test } from "bun:test";
import { join } from "node:path";

test("callEmberd rejects a post-connect transport reset without an unhandled child error or response deadline", async () => {
  const child = Bun.spawn(
    [process.execPath, "test", join(import.meta.dir, "emberd-rpc-post-connect-error-child.test.ts")],
    { stdout: "pipe", stderr: "pipe", env: { ...process.env, EMBERD_POST_CONNECT_ERROR_CHILD: "1" } },
  );
  const [stdout, stderr, exitCode] = await Promise.all([
    new Response(child.stdout).text(),
    new Response(child.stderr).text(),
    child.exited,
  ]);
  expect(exitCode).toBe(0);
  expect(stdout + stderr).toContain("connected reset rejects promptly");
});
