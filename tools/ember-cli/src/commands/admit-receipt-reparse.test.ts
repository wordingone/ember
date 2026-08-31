// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "bun:test";
import {
  ADMISSION_CONSUMER_COMMANDS,
  verifyAdmissionProducerReceipt,
} from "./admit.ts";

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

describe("/admit receipt path authority", () => {
  it("refuses a content-addressed receipt reached through a junction", () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "ember-admit-link-"));
    const target = path.join(root, "target");
    const outputRoot = path.join(root, "linked-output");
    const checkpointBytes = Buffer.from("checkpoint");
    const identities = {
      checkpoint: {
        relative_path: "checkpoint.bin",
        sha256: createHash("sha256").update(checkpointBytes).digest("hex"),
        bytes: checkpointBytes.byteLength,
      },
    };
    const descriptorIdentity = {
      relative_path: "admission.json",
      sha256: "d".repeat(64),
      bytes: 123,
    };
    const digestJoin = createHash("sha256").update(
      `${canonical({ output_identities: identities })}\n`,
    ).digest("hex");
    const receipt = {
      benchmark_claim: false,
      candidate_id: "candidate-one",
      capability_claim: false,
      claim_boundary: [
        "candidate_produced",
        "identity_consumer_accepted",
        "restart_consumer_accepted",
      ],
      consumers: {
        identity: {
          accepted: true, command: ADMISSION_CONSUMER_COMMANDS.identity,
          returncode: 0, stdout_sha256: "3".repeat(64),
          validator_sha256: "1".repeat(64),
          validator_closure: {
            "scripts/ember_01_identity/validate_identity.py": {
              relative_path: "scripts/ember_01_identity/validate_identity.py",
              sha256: "1".repeat(64), bytes: 1,
            },
          },
        },
        restart: {
          accepted: true, command: ADMISSION_CONSUMER_COMMANDS.restart,
          returncode: 0, stdout_sha256: "4".repeat(64),
          validator_sha256: "2".repeat(64),
          validator_closure: {
            "src/ember/governance/scripts/ember_restart/cli_seat.py": {
              relative_path: "src/ember/governance/scripts/ember_restart/cli_seat.py",
              sha256: "2".repeat(64), bytes: 1,
            },
          },
        },
      },
      cross_consumer_digest_join_sha256: digestJoin,
      loaded: false,
      output_identities: identities,
      schema_version: "ember-owned-admission-producer-receipt-v1",
      selected: false,
      source_identities: {
        descriptor: descriptorIdentity,
        roles: identities,
      },
      training_claim: false,
      training_started: false,
    };
    const bytes = Buffer.from(`${canonical(receipt)}\n`);
    const receiptSha256 = createHash("sha256").update(bytes).digest("hex");
    const receiptRoot = path.join(target, "candidate-one", "producer-receipts");
    fs.mkdirSync(receiptRoot, { recursive: true });
    fs.writeFileSync(path.join(target, "candidate-one", "checkpoint.bin"), checkpointBytes);
    fs.writeFileSync(path.join(receiptRoot, `${receiptSha256}.json`), bytes);
    fs.symlinkSync(target, outputRoot, "junction");
    const candidateSha256 = createHash("sha256").update(canonical({
      producer_receipt_sha256: receiptSha256,
      descriptor_identity: descriptorIdentity,
      output_identities: identities,
    })).digest("hex");

    expect(verifyAdmissionProducerReceipt(outputRoot, {
      candidate_id: "candidate-one",
      candidate_sha256: candidateSha256,
      producer_receipt_sha256: receiptSha256,
    })).toBeNull();
  });
});
