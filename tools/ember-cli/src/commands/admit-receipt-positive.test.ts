// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "bun:test";
import { ADMISSION_CONSUMER_COMMANDS, createAdmitCommand } from "./admit.ts";
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const object = value as Record<string, unknown>;
    return `{${Object.keys(object).sort().map(
      (key) => `${JSON.stringify(key)}:${canonical(object[key])}`,
    ).join(",")}}`;
  }
  const encoded = JSON.stringify(value);
  if (encoded === undefined) throw new TypeError("non-JSON test value");
  return encoded;
}



describe("/admit on-disk receipt verification", () => {
  it("rehashes the exact receipt and candidate digest before success", async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "ember-admit-receipt-"));
    const outputRoot = path.join(root, "candidates");
    const identities = { checkpoint: "c".repeat(64) };
    const digestJoin = createHash("sha256").update(
      `${canonical({ role_sha256: identities })}\n`,
    ).digest("hex");
    const receipt = {
      candidate_id: "candidate-one",
      benchmark_claim: false,
      capability_claim: false,
      claim_boundary: ["candidate_produced", "identity_consumer_accepted", "restart_consumer_accepted"],
      consumers: {
        identity: {
          accepted: true,
          command: ADMISSION_CONSUMER_COMMANDS.identity,
          returncode: 0,
          stdout_sha256: "3".repeat(64),
          validator_sha256: "1".repeat(64),
        },
        restart: {
          accepted: true,
          command: ADMISSION_CONSUMER_COMMANDS.restart,
          returncode: 0,
          stdout_sha256: "4".repeat(64),
          validator_sha256: "2".repeat(64),
        },
      },
      loaded: false,
      cross_consumer_digest_join_sha256: digestJoin,
      output_identities: identities,
      schema_version: "ember-owned-admission-producer-receipt-v1",
      selected: false,
      source_identities: identities,
      training_claim: false,
      training_started: false,
    };
    const receiptBytes = Buffer.from(`${canonical(receipt)}\n`);
    const receiptSha256 = createHash("sha256").update(receiptBytes).digest("hex");
    const receiptRoot = path.join(
      outputRoot,
      "candidate-one",
      "producer-receipts",
    );
    fs.mkdirSync(receiptRoot, { recursive: true });
    fs.writeFileSync(path.join(receiptRoot, `${receiptSha256}.json`), receiptBytes);
    const candidateSha256 = createHash("sha256").update(
      canonical({
        producer_receipt_sha256: receiptSha256,
        role_sha256: identities,
      }),
    ).digest("hex");
    const command = createAdmitCommand({
      producerPath: path.join(root, "produce_candidate.py"),
      runProducer() {
        return {
          status: 0,
          stdout: JSON.stringify({
            candidate_id: "candidate-one",
            candidate_sha256: candidateSha256,
            producer_receipt_sha256: receiptSha256,
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
        `--output-root ${outputRoot}`,
      { sessionId: "s", mode: "local", cwd: root },
    );

    expect(result?.exitCode).toBeUndefined();
    expect(result?.message).toContain(candidateSha256);
  });
});
