// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, it } from "bun:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createAdmitCommand } from "./admit.ts";


describe("/admit receipt authority", () => {
  it("rejects success stdout when no exact producer receipt exists on disk", async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "ember-admit-authority-"));
    const command = createAdmitCommand({
      producerPath: path.join(root, "produce_candidate.py"),
      runProducer() {
        return {
          status: 0,
          stdout: JSON.stringify({
            candidate_id: "candidate-one",
            candidate_sha256: "a".repeat(64),
            producer_receipt_sha256: "b".repeat(64),
            ok: true,
            selected: false,
            loaded: false,
            training_started: false,
          }),
        };
      },
    });

    const result = await command.execute(
      `--workspace ${root} --descriptor ${path.join(root, "admission.json")} ` +
        `--output-root ${path.join(root, "candidates")}`,
      { sessionId: "s", mode: "local", cwd: root },
    );

    expect(result?.exitCode).toBe(2);
    expect(result?.message).toContain("authority evidence");
  });
});
