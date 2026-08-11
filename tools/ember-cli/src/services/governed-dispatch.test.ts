// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { afterEach, describe, expect, it } from "bun:test";
import { createHash } from "node:crypto";
import { mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, win32 } from "node:path";
import {
  isStrictContainedRelative,
  parseGovernedDispatchArgs,
  runGovernedDispatch,
} from "./governed-dispatch.ts";

const SOURCE = "a".repeat(40);
const roots: string[] = [];

afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

function fixture(): {
  root: string;
  manifestPath: string;
  manifestBytes: Buffer;
  receiptPath: string;
  receiptSha256: string;
} {
  const root = mkdtempSync(join(tmpdir(), "ember-governed-dispatch-"));
  roots.push(root);
  const receiptPath = join(root, "dispatch-preflight.json");
  writeFileSync(receiptPath, "preflight-receipt\n");
  const receiptSha256 = createHash("sha256").update("preflight-receipt\n").digest("hex");
  const manifest = {
    schema_version: "ember-lab-dispatch-manifest-v3",
    job_id: "q2-actual-update",
    source_commit: SOURCE,
    not_before_ms: 1,
    expires_at_ms: 2,
    resource_lease: "gpu-q2-actual-update",
    program: { path: join(root, "python.exe"), sha256: "b".repeat(64) },
    args: [join(root, "producer.py"), "governed-vertical"],
    workload_profile: {
      profile_id: "governed_vertical",
      pinned_host_producers: [{ kind: "model_reconstruction", maximum_bytes: 1 }],
      requires_ui_responsiveness: false,
      cpu_rate_percent: 80,
    },
    env: {},
    bindings: [],
    custody_root: root,
    storage_reserves: [{ root, minimum_free_bytes: 1 }],
    minimum_free_vram_bytes: 1,
    required_available_maximum_commit_bytes: 1,
    maximum_job_memory_bytes: 1,
    simulated_peak_commit_bytes: 1,
    preflight_receipt: receiptPath,
  };
  const manifestBytes = Buffer.from(JSON.stringify(manifest) + "\n");
  const manifestPath = join(root, "dispatch-manifest.json");
  writeFileSync(manifestPath, manifestBytes);
  return { root, manifestPath, manifestBytes, receiptPath, receiptSha256 };
}

describe("governed Ember Lab dispatch", () => {
  it("refuses different Windows drive and UNC roots while accepting a same-root descendant", () => {
    expect(isStrictContainedRelative(win32.relative("C:\\custody", "C:\\custody\\receipts\\ok.json"))).toBe(true);
    expect(isStrictContainedRelative(win32.relative("C:\\custody", "D:\\foreign\\receipt.json"))).toBe(false);
    expect(isStrictContainedRelative(win32.relative("\\\\server\\custody", "\\\\other\\share\\receipt.json"))).toBe(false);
  });

  it("accepts exactly one absolute --manifest argument", () => {
    const absolute = join(tmpdir(), "dispatch.json");
    expect(parseGovernedDispatchArgs(["--manifest", absolute])).toBe(absolute);
    for (const args of [
      [], ["--manifest"], ["--manifest", "relative.json"],
      ["--manifest", absolute, "extra"], ["--other", absolute],
    ]) {
      expect(() => parseGovernedDispatchArgs(args)).toThrow("usage:");
    }
  });

  it("transports the original manifest bytes and verifies the daemon receipt in custody", async () => {
    const value = fixture();
    let request: Record<string, unknown> | undefined;
    const result = await runGovernedDispatch({
      manifestPath: value.manifestPath,
      expectedSourceCommit: SOURCE,
      pipeName: "\\\\.\\pipe\\ember-lab-q2",
      callEmberLab: async (options) => {
        request = options as unknown as Record<string, unknown>;
        return {
          pid: 4242,
          preflight_receipt_path: value.receiptPath,
          preflight_receipt_sha256: value.receiptSha256,
        };
      },
    });

    expect(request).toEqual({
      pipeName: "\\\\.\\pipe\\ember-lab-q2",
      method: "dispatch_manifest",
      params: {
        manifest_utf8: value.manifestBytes.toString("utf8"),
        manifest_sha256: createHash("sha256").update(value.manifestBytes).digest("hex"),
      },
    });
    expect(result).toEqual({
      pid: 4242,
      preflight_receipt_path: value.receiptPath,
      preflight_receipt_sha256: value.receiptSha256,
      manifest_sha256: createHash("sha256").update(value.manifestBytes).digest("hex"),
    });
  });

  it("refuses manifests outside the one governed vertical authority", async () => {
    const cases: Array<[string, (manifest: Record<string, any>) => void]> = [
      ["source commit", (manifest) => { manifest.source_commit = "b".repeat(40); }],
      ["workload profile", (manifest) => { manifest.workload_profile.profile_id = "owned_serving"; }],
      ["resource lease", (manifest) => { manifest.resource_lease = "gpu-other"; }],
      ["fields are not closed", (manifest) => { manifest.parallel_launcher = true; }],
    ];
    for (const [message, mutate] of cases) {
      const value = fixture();
      const manifest = JSON.parse(value.manifestBytes.toString("utf8"));
      mutate(manifest);
      writeFileSync(value.manifestPath, JSON.stringify(manifest));
      await expect(runGovernedDispatch({
        manifestPath: value.manifestPath,
        expectedSourceCommit: SOURCE,
        pipeName: "\\\\.\\pipe\\ember-lab-q2",
        callEmberLab: async () => { throw new Error("RPC MUST NOT RUN"); },
      })).rejects.toThrow(message);
    }
  });

  it("refuses malformed UTF-8 and malformed JSON before RPC", async () => {
    for (const bytes of [Buffer.from([0xff]), Buffer.from("{not-json")]) {
      const value = fixture();
      writeFileSync(value.manifestPath, bytes);
      await expect(runGovernedDispatch({
        manifestPath: value.manifestPath,
        expectedSourceCommit: SOURCE,
        pipeName: "\\\\.\\pipe\\ember-lab-q2",
        callEmberLab: async () => { throw new Error("RPC MUST NOT RUN"); },
      })).rejects.toThrow(/UTF-8|JSON/);
    }
  });

  it("refuses malformed daemon results", async () => {
    for (const [response, message] of [
      [{ pid: 0, preflight_receipt_path: "INSIDE", preflight_receipt_sha256: "c".repeat(64) }, /pid/],
      [{ pid: 7, preflight_receipt_path: join(tmpdir(), "foreign.json"), preflight_receipt_sha256: "c".repeat(64) }, /receipt/],
      [{ pid: 7, preflight_receipt_path: "INSIDE", preflight_receipt_sha256: "c".repeat(64) }, /receipt/],
    ]) {
      const value = fixture();
      if ((response as Record<string, unknown>).preflight_receipt_path === "INSIDE") {
        (response as Record<string, unknown>).preflight_receipt_path = value.receiptPath;
      }
      await expect(runGovernedDispatch({
        manifestPath: value.manifestPath,
        expectedSourceCommit: SOURCE,
        pipeName: "\\\\.\\pipe\\ember-lab-q2",
        callEmberLab: async () => response as Record<string, unknown>,
      })).rejects.toThrow(message as RegExp);
    }
  });

  it("refuses an in-custody junction that resolves to a foreign receipt", async () => {
    const value = fixture();
    const foreign = mkdtempSync(join(tmpdir(), "ember-governed-foreign-"));
    roots.push(foreign);
    const foreignReceipt = join(foreign, "dispatch-preflight.json");
    writeFileSync(foreignReceipt, "foreign-receipt\n");
    const foreignSha = createHash("sha256").update("foreign-receipt\n").digest("hex");
    const junction = join(value.root, "foreign-junction");
    symlinkSync(foreign, junction, "junction");

    await expect(runGovernedDispatch({
      manifestPath: value.manifestPath,
      expectedSourceCommit: SOURCE,
      pipeName: "\\\\.\\pipe\\ember-lab-q2",
      callEmberLab: async () => ({
        pid: 7,
        preflight_receipt_path: join(junction, "dispatch-preflight.json"),
        preflight_receipt_sha256: foreignSha,
      }),
    })).rejects.toThrow(/reparse|canonical|receipt/);
  });
});
