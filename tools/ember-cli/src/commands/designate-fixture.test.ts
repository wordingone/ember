// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// Production-shaped coverage for /designate: every case here drives the REAL
// command (createDesignateCommand's default deps -- the real
// verifyAdmissionProducerReceipt from admit.ts, real fs) against real files
// on disk, matching #1107's own fixture-construction convention
// (admit-receipt-schema.test.ts / admit-authority.test.ts).

import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "bun:test";
import { ADMISSION_CONSUMER_COMMANDS } from "./admit.ts";
import { createDesignateCommand } from "./designate.ts";

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

interface BuiltCandidate {
  root: string;
  outputRoot: string;
  candidateId: string;
  candidateSha256: string;
  producerReceiptSha256: string;
  manifestBytes: Buffer;
  candidateRoot: string;
}

/** Builds one real, on-disk, receipt-verifiable admitted candidate --
 * exactly the shape #1107's own producer would publish -- with two roles:
 * restart_run_manifest (the file /designate selects) and checkpoint (a
 * second role, so the "select only the right file" behavior is actually
 * exercised). Mirrors admit-receipt-schema.test.ts's construction. */
function buildCandidate(
  root: string,
  candidateId: string,
  manifestBytes: Buffer,
  extraRoles: Record<string, Buffer> = { checkpoint: Buffer.from("checkpoint-bytes") },
): BuiltCandidate {
  const outputRoot = path.join(root, "candidates");
  const candidateRoot = path.join(outputRoot, candidateId);
  const identities: Record<string, { relative_path: string; sha256: string; bytes: number }> = {
    restart_run_manifest: {
      relative_path: "run.json",
      sha256: createHash("sha256").update(manifestBytes).digest("hex"),
      bytes: manifestBytes.byteLength,
    },
  };
  for (const [role, content] of Object.entries(extraRoles)) {
    identities[role] = {
      relative_path: `${role}.bin`,
      sha256: createHash("sha256").update(content).digest("hex"),
      bytes: content.byteLength,
    };
  }
  fs.mkdirSync(candidateRoot, { recursive: true });
  fs.writeFileSync(path.join(candidateRoot, "run.json"), manifestBytes);
  for (const [role, content] of Object.entries(extraRoles)) {
    fs.writeFileSync(path.join(candidateRoot, `${role}.bin`), content);
  }

  const descriptorIdentity = {
    relative_path: "admission.json",
    sha256: "a".repeat(64),
    bytes: 42,
  };
  const digestJoin = createHash("sha256").update(
    `${canonical({ output_identities: identities })}\n`,
  ).digest("hex");
  const closureEntry = (name: "identity" | "restart", entrypoint: string) => ({
    accepted: true,
    command: ADMISSION_CONSUMER_COMMANDS[name],
    returncode: 0,
    stdout_sha256: "3".repeat(64),
    validator_sha256: "1".repeat(64),
    validator_closure: {
      [entrypoint]: { relative_path: entrypoint, sha256: "1".repeat(64), bytes: 1 },
    },
  });
  const receipt = {
    benchmark_claim: false,
    candidate_id: candidateId,
    capability_claim: false,
    claim_boundary: [
      "candidate_produced",
      "identity_consumer_accepted",
      "restart_consumer_accepted",
    ],
    consumers: {
      identity: closureEntry("identity", "src/ember/governance/scripts/ember_01_identity/validate_identity.py"),
      restart: closureEntry("restart", "src/ember/governance/scripts/ember_restart/cli_seat.py"),
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
  const receiptBytes = Buffer.from(`${canonical(receipt)}\n`);
  const producerReceiptSha256 = createHash("sha256").update(receiptBytes).digest("hex");
  const receiptRoot = path.join(candidateRoot, "producer-receipts");
  fs.mkdirSync(receiptRoot, { recursive: true });
  fs.writeFileSync(path.join(receiptRoot, `${producerReceiptSha256}.json`), receiptBytes);

  const candidateSha256 = createHash("sha256").update(
    canonical({
      producer_receipt_sha256: producerReceiptSha256,
      descriptor_identity: descriptorIdentity,
      output_identities: identities,
    }),
  ).digest("hex");

  return {
    root,
    outputRoot,
    candidateId,
    candidateSha256,
    producerReceiptSha256,
    manifestBytes,
    candidateRoot,
  };
}

function runDesignate(candidate: BuiltCandidate, configHome: string, now?: () => Date) {
  const command = createDesignateCommand({ getConfigHome: () => configHome, now });
  return command.execute(
    `--output-root ${candidate.outputRoot} --candidate-id ${candidate.candidateId} ` +
      `--candidate-sha256 ${candidate.candidateSha256} ` +
      `--producer-receipt-sha256 ${candidate.producerReceiptSha256}`,
    { sessionId: "s", mode: "local", cwd: candidate.root },
  );
}

describe("/designate selection over a real admitted candidate", () => {
  it("selects the restart_run_manifest bytes into owned/current.json and receipts the designation", async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "ember-designate-select-"));
    const configHome = fs.mkdtempSync(path.join(os.tmpdir(), "ember-designate-home-"));
    const manifestBytes = Buffer.from(JSON.stringify({ stage: "OWNED_ADMITTED", run_id: "run-one" }));
    const candidate = buildCandidate(root, "candidate-one", manifestBytes);

    const result = await runDesignate(candidate, configHome);

    expect(result?.exitCode).toBeUndefined();
    const currentPath = path.join(configHome, "owned", "current.json");
    expect(fs.existsSync(currentPath)).toBe(true);
    expect(fs.readFileSync(currentPath)).toEqual(manifestBytes);
    expect(result?.message).toContain(candidate.candidateId);
    expect(result?.message).toContain("read_back_verified=true");

    const receiptDir = path.join(configHome, "owned", "designation-receipts");
    const receiptFiles = fs.readdirSync(receiptDir);
    expect(receiptFiles).toHaveLength(1);
    const receipt = JSON.parse(fs.readFileSync(path.join(receiptDir, receiptFiles[0]!), "utf8"));
    expect(receipt).toMatchObject({
      schema_version: "ember-owned-designation-receipt-v1",
      candidate_id: "candidate-one",
      candidate_sha256: candidate.candidateSha256,
      producer_receipt_sha256: candidate.producerReceiptSha256,
      designated_manifest_sha256: createHash("sha256").update(manifestBytes).digest("hex"),
      read_back_verified: true,
    });
    expect(typeof receipt.resolved_at).toBe("string");
    expect(Number.isNaN(Date.parse(receipt.resolved_at))).toBe(false);
    expect(receiptFiles[0]).toBe(
      createHash("sha256").update(fs.readFileSync(path.join(receiptDir, receiptFiles[0]!))).digest("hex") + ".json",
    );

    // The ONLY writes under configHome are current.json and its receipt.
    const ownedEntries = fs.readdirSync(path.join(configHome, "owned")).sort();
    expect(ownedEntries).toEqual(["current.json", "designation-receipts"]);
  });

  it("does not select the wrong role's bytes when multiple roles are present", async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "ember-designate-multirole-"));
    const configHome = fs.mkdtempSync(path.join(os.tmpdir(), "ember-designate-home-"));
    const manifestBytes = Buffer.from(JSON.stringify({ stage: "OWNED_ADMITTED", run_id: "run-two" }));
    const candidate = buildCandidate(root, "candidate-two", manifestBytes, {
      checkpoint: Buffer.from("not-the-manifest"),
      restart_model_config: Buffer.from("also-not-the-manifest"),
    });

    const result = await runDesignate(candidate, configHome);

    expect(result?.exitCode).toBeUndefined();
    const currentPath = path.join(configHome, "owned", "current.json");
    expect(fs.readFileSync(currentPath)).toEqual(manifestBytes);
  });

  it("refuses a candidate whose receipt has no restart_run_manifest role, leaving no trace", async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "ember-designate-norole-"));
    const configHome = fs.mkdtempSync(path.join(os.tmpdir(), "ember-designate-home-"));
    const outputRoot = path.join(root, "candidates");
    const candidateRoot = path.join(outputRoot, "candidate-norole");
    fs.mkdirSync(candidateRoot, { recursive: true });
    const checkpointBytes = Buffer.from("checkpoint-only");
    fs.writeFileSync(path.join(candidateRoot, "checkpoint.bin"), checkpointBytes);
    const identities = {
      checkpoint: {
        relative_path: "checkpoint.bin",
        sha256: createHash("sha256").update(checkpointBytes).digest("hex"),
        bytes: checkpointBytes.byteLength,
      },
    };
    const descriptorIdentity = { relative_path: "admission.json", sha256: "a".repeat(64), bytes: 1 };
    const digestJoin = createHash("sha256").update(`${canonical({ output_identities: identities })}\n`).digest("hex");
    const closureEntry = (name: "identity" | "restart", entrypoint: string) => ({
      accepted: true,
      command: ADMISSION_CONSUMER_COMMANDS[name],
      returncode: 0,
      stdout_sha256: "3".repeat(64),
      validator_sha256: "1".repeat(64),
      validator_closure: { [entrypoint]: { relative_path: entrypoint, sha256: "1".repeat(64), bytes: 1 } },
    });
    const receipt = {
      benchmark_claim: false,
      candidate_id: "candidate-norole",
      capability_claim: false,
      claim_boundary: ["candidate_produced", "identity_consumer_accepted", "restart_consumer_accepted"],
      consumers: {
        identity: closureEntry("identity", "src/ember/governance/scripts/ember_01_identity/validate_identity.py"),
        restart: closureEntry("restart", "src/ember/governance/scripts/ember_restart/cli_seat.py"),
      },
      cross_consumer_digest_join_sha256: digestJoin,
      loaded: false,
      output_identities: identities,
      schema_version: "ember-owned-admission-producer-receipt-v1",
      selected: false,
      source_identities: { descriptor: descriptorIdentity, roles: identities },
      training_claim: false,
      training_started: false,
    };
    const receiptBytes = Buffer.from(`${canonical(receipt)}\n`);
    const producerReceiptSha256 = createHash("sha256").update(receiptBytes).digest("hex");
    const receiptRoot = path.join(candidateRoot, "producer-receipts");
    fs.mkdirSync(receiptRoot, { recursive: true });
    fs.writeFileSync(path.join(receiptRoot, `${producerReceiptSha256}.json`), receiptBytes);
    const candidateSha256 = createHash("sha256").update(
      canonical({ producer_receipt_sha256: producerReceiptSha256, descriptor_identity: descriptorIdentity, output_identities: identities }),
    ).digest("hex");

    const command = createDesignateCommand({ getConfigHome: () => configHome });
    const result = await command.execute(
      `--output-root ${outputRoot} --candidate-id candidate-norole ` +
        `--candidate-sha256 ${candidateSha256} --producer-receipt-sha256 ${producerReceiptSha256}`,
      { sessionId: "s", mode: "local", cwd: root },
    );

    expect(result?.exitCode).toBe(2);
    expect(result?.message).toContain("no restart_run_manifest role");
    expect(fs.existsSync(path.join(configHome, "owned"))).toBe(false);
  });

  it("refuses a candidate with a symlinked bundle path", async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "ember-designate-symlink-"));
    const configHome = fs.mkdtempSync(path.join(os.tmpdir(), "ember-designate-home-"));
    const manifestBytes = Buffer.from(JSON.stringify({ stage: "OWNED_ADMITTED" }));
    const candidate = buildCandidate(root, "candidate-symlink", manifestBytes);

    // Replace the published manifest file with a symlink to itself's sibling
    // content -- same bytes, but the tree walk must refuse on sight of any
    // symlink regardless of what it points at.
    const realManifestPath = path.join(candidate.candidateRoot, "run.json");
    const shadowPath = path.join(candidate.candidateRoot, "run.real.json");
    fs.renameSync(realManifestPath, shadowPath);
    try {
      fs.symlinkSync(shadowPath, realManifestPath, "file");
    } catch (error) {
      // Symlink creation requires elevated privileges on some Windows
      // configurations; skip rather than false-fail the suite when the
      // platform itself refuses the setup step.
      fs.renameSync(shadowPath, realManifestPath);
      return;
    }

    const result = await runDesignate(candidate, configHome);

    expect(result?.exitCode).toBe(2);
    expect(result?.message).toContain("failed integrity verification");
    expect(fs.existsSync(path.join(configHome, "owned"))).toBe(false);
  });

  it("leaves a pre-existing current.json untouched when the bundle fails verification", async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "ember-designate-preserve-"));
    const configHome = fs.mkdtempSync(path.join(os.tmpdir(), "ember-designate-home-"));
    const ownedDir = path.join(configHome, "owned");
    fs.mkdirSync(ownedDir, { recursive: true });
    const priorBytes = Buffer.from(JSON.stringify({ stage: "OWNED_ADMITTED", run_id: "prior" }));
    fs.writeFileSync(path.join(ownedDir, "current.json"), priorBytes);

    const manifestBytes = Buffer.from(JSON.stringify({ stage: "OWNED_ADMITTED", run_id: "tampered" }));
    const candidate = buildCandidate(root, "candidate-tamper", manifestBytes);
    // Tamper the published manifest bytes after the receipt was written, so
    // the receipt's own hash no longer matches what's on disk.
    fs.writeFileSync(path.join(candidate.candidateRoot, "run.json"), Buffer.concat([manifestBytes, Buffer.from("TAMPERED")]));

    const result = await runDesignate(candidate, configHome);

    expect(result?.exitCode).toBe(2);
    expect(fs.readFileSync(path.join(ownedDir, "current.json"))).toEqual(priorBytes);
    const leftoverTemp = fs.readdirSync(ownedDir).filter((name) => name.startsWith(".current.json."));
    expect(leftoverTemp).toEqual([]);
    expect(fs.existsSync(path.join(ownedDir, "designation-receipts"))).toBe(false);
  });

  it("replaces a pre-existing current.json on a successful designation (selection replaces prior selection)", async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "ember-designate-replace-"));
    const configHome = fs.mkdtempSync(path.join(os.tmpdir(), "ember-designate-home-"));

    const first = buildCandidate(root, "candidate-first", Buffer.from(JSON.stringify({ run_id: "first" })));
    const firstResult = await runDesignate(first, configHome);
    expect(firstResult?.exitCode).toBeUndefined();

    const second = buildCandidate(root, "candidate-second", Buffer.from(JSON.stringify({ run_id: "second" })));
    const secondResult = await runDesignate(second, configHome);
    expect(secondResult?.exitCode).toBeUndefined();

    const currentPath = path.join(configHome, "owned", "current.json");
    expect(fs.readFileSync(currentPath)).toEqual(second.manifestBytes);

    const receiptDir = path.join(configHome, "owned", "designation-receipts");
    expect(fs.readdirSync(receiptDir)).toHaveLength(2);
  });

  it("refuses an empty bundle (no candidate directory at all)", async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "ember-designate-empty-"));
    const configHome = fs.mkdtempSync(path.join(os.tmpdir(), "ember-designate-home-"));
    const outputRoot = path.join(root, "candidates");
    fs.mkdirSync(outputRoot, { recursive: true });

    const command = createDesignateCommand({ getConfigHome: () => configHome });
    const result = await command.execute(
      `--output-root ${outputRoot} --candidate-id candidate-missing ` +
        `--candidate-sha256 ${"a".repeat(64)} --producer-receipt-sha256 ${"b".repeat(64)}`,
      { sessionId: "s", mode: "local", cwd: root },
    );

    expect(result?.exitCode).toBe(2);
    expect(result?.message).toContain("failed integrity verification");
    expect(fs.existsSync(path.join(configHome, "owned"))).toBe(false);
  });

  it("refuses a partially-written bundle (receipt present, a declared role file missing)", async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "ember-designate-partial-"));
    const configHome = fs.mkdtempSync(path.join(os.tmpdir(), "ember-designate-home-"));
    const manifestBytes = Buffer.from(JSON.stringify({ run_id: "partial" }));
    const candidate = buildCandidate(root, "candidate-partial", manifestBytes);
    // Delete the second role's published file after the receipt was written
    // for it -- the bundle is now incomplete relative to its own receipt.
    fs.unlinkSync(path.join(candidate.candidateRoot, "checkpoint.bin"));

    const result = await runDesignate(candidate, configHome);

    expect(result?.exitCode).toBe(2);
    expect(result?.message).toContain("failed integrity verification");
    expect(fs.existsSync(path.join(configHome, "owned"))).toBe(false);
  });

  it("refuses a bundle whose declared relative_path escapes the candidate root", async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "ember-designate-escape-"));
    const configHome = fs.mkdtempSync(path.join(os.tmpdir(), "ember-designate-home-"));
    const outputRoot = path.join(root, "candidates");
    const candidateRoot = path.join(outputRoot, "candidate-escape");
    fs.mkdirSync(candidateRoot, { recursive: true });
    const manifestBytes = Buffer.from(JSON.stringify({ run_id: "escape" }));
    // Write the "escaping" target OUTSIDE the candidate root, matching the
    // traversal path a hostile relative_path would resolve to.
    fs.writeFileSync(path.join(outputRoot, "escaped.json"), manifestBytes);
    const identities = {
      restart_run_manifest: {
        relative_path: "../escaped.json",
        sha256: createHash("sha256").update(manifestBytes).digest("hex"),
        bytes: manifestBytes.byteLength,
      },
    };
    const descriptorIdentity = { relative_path: "admission.json", sha256: "a".repeat(64), bytes: 1 };
    const digestJoin = createHash("sha256").update(`${canonical({ output_identities: identities })}\n`).digest("hex");
    const closureEntry = (name: "identity" | "restart", entrypoint: string) => ({
      accepted: true,
      command: ADMISSION_CONSUMER_COMMANDS[name],
      returncode: 0,
      stdout_sha256: "3".repeat(64),
      validator_sha256: "1".repeat(64),
      validator_closure: { [entrypoint]: { relative_path: entrypoint, sha256: "1".repeat(64), bytes: 1 } },
    });
    const receipt = {
      benchmark_claim: false,
      candidate_id: "candidate-escape",
      capability_claim: false,
      claim_boundary: ["candidate_produced", "identity_consumer_accepted", "restart_consumer_accepted"],
      consumers: {
        identity: closureEntry("identity", "src/ember/governance/scripts/ember_01_identity/validate_identity.py"),
        restart: closureEntry("restart", "src/ember/governance/scripts/ember_restart/cli_seat.py"),
      },
      cross_consumer_digest_join_sha256: digestJoin,
      loaded: false,
      output_identities: identities,
      schema_version: "ember-owned-admission-producer-receipt-v1",
      selected: false,
      source_identities: { descriptor: descriptorIdentity, roles: identities },
      training_claim: false,
      training_started: false,
    };
    const receiptBytes = Buffer.from(`${canonical(receipt)}\n`);
    const producerReceiptSha256 = createHash("sha256").update(receiptBytes).digest("hex");
    const receiptRoot = path.join(candidateRoot, "producer-receipts");
    fs.mkdirSync(receiptRoot, { recursive: true });
    fs.writeFileSync(path.join(receiptRoot, `${producerReceiptSha256}.json`), receiptBytes);
    const candidateSha256 = createHash("sha256").update(
      canonical({ producer_receipt_sha256: producerReceiptSha256, descriptor_identity: descriptorIdentity, output_identities: identities }),
    ).digest("hex");

    const command = createDesignateCommand({ getConfigHome: () => configHome });
    const result = await command.execute(
      `--output-root ${outputRoot} --candidate-id candidate-escape ` +
        `--candidate-sha256 ${candidateSha256} --producer-receipt-sha256 ${producerReceiptSha256}`,
      { sessionId: "s", mode: "local", cwd: root },
    );

    expect(result?.exitCode).toBe(2);
    expect(result?.message).toContain("failed integrity verification");
    expect(fs.existsSync(path.join(configHome, "owned"))).toBe(false);
  });

  it("is idempotent when the same candidate is designated twice at the same resolved_at", async () => {
    // A live clock makes two calls produce two distinct (differently
    // timestamped) receipts, which is correct -- each designation IS a
    // distinct event. The idempotency guarantee this test proves is at the
    // content-addressed-write layer: if the exact same receipt payload
    // (same candidate, same resolved_at) is ever written twice, the second
    // write is a no-op success, not a collision error.
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "ember-designate-idempotent-"));
    const configHome = fs.mkdtempSync(path.join(os.tmpdir(), "ember-designate-home-"));
    const candidate = buildCandidate(root, "candidate-repeat", Buffer.from(JSON.stringify({ run_id: "repeat" })));
    const fixedNow = () => new Date("2026-08-01T12:00:00.000Z");

    const first = await runDesignate(candidate, configHome, fixedNow);
    const second = await runDesignate(candidate, configHome, fixedNow);

    expect(first?.exitCode).toBeUndefined();
    expect(second?.exitCode).toBeUndefined();
    const receiptDir = path.join(configHome, "owned", "designation-receipts");
    expect(fs.readdirSync(receiptDir)).toHaveLength(1);
  });
});
