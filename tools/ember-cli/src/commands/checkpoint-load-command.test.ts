// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { afterEach, describe, expect, it } from "bun:test";
import { createHash } from "crypto";
import { mkdtempSync, rmSync, writeFileSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";
import { createModelCommand } from "./model.ts";
import type { OwnedModelIdentity } from "../entrypoints/model-seat.ts";
import type { CommandContext } from "../types/command-types.ts";

const roots: string[] = [];

function sha256(bytes: Uint8Array): string {
  return createHash("sha256").update(bytes).digest("hex");
}

function writeTamperedV5Bundle(): {
  root: string;
  manifestSha256: string;
} {
  const root = mkdtempSync(join(tmpdir(), "ember-command-checkpoint-load-"));
  roots.push(root);
  const payloads = new Map<string, Buffer>([
    ["shared-model.pt", Buffer.from("shared-model")],
    ["optimizer-state.pt", Buffer.from("optimizer-state")],
    ["replay-state.pt", Buffer.from("replay-state")],
    ["expert-vision.pt", Buffer.from("expert-vision")],
    ["expert-audio.pt", Buffer.from("expert-audio")],
    ["expert-reasoning.pt", Buffer.from("expert-reasoning")],
    ["expert-tool.pt", Buffer.from("expert-tool")],
  ]);
  const manifestBytes = Buffer.from(
    JSON.stringify({
      schema_version: "ember-sparse-checkpoint-v5",
      shards: [...payloads].map(([path, bytes]) => ({
        path,
        bytes: bytes.length,
        sha256: sha256(bytes),
      })),
    }) + "\n",
    "utf8",
  );
  for (const [path, bytes] of payloads) {
    writeFileSync(join(root, path), bytes);
  }
  writeFileSync(join(root, "checkpoint-manifest.json"), manifestBytes);

  // The manifest stays byte-identical while one named shard is substituted.
  writeFileSync(join(root, "expert-audio.pt"), Buffer.from("tampered-audio"));
  return { root, manifestSha256: sha256(manifestBytes) };
}

afterEach(() => {
  for (const root of roots.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
});

const context: CommandContext = {
  sessionId: "checkpoint-load-test",
  mode: "test",
  cwd: "C:\\ember",
};

const ownedIdentity = {
  checkpointSha256: "b".repeat(64),
  endpointUrl: "http://127.0.0.1:29777/",
  launch: {
    mode: "INTERACTIVE",
    authorityKind: "ADMISSION",
    checkpointDir: "C:\\old-checkpoint",
    tokenizerPath: "C:\\ember\\tokenizer\\tokenizer.json",
  },
} as unknown as OwnedModelIdentity;

describe("/model checkpoint load", () => {
  it("refuses a real named-shard substitution before lifecycle authority", async () => {
    const bundle = writeTamperedV5Bundle();
    let ensureCalls = 0;
    let lifecycleCalls = 0;
    let registerCalls = 0;
    const command = createModelCommand({
      loadOwnedIdentity: () =>
        ({
          ...ownedIdentity,
          checkpointSha256: bundle.manifestSha256,
        }) as OwnedModelIdentity,
      ensureOwnedServer: async () => {
        ensureCalls += 1;
        throw new Error("must not start");
      },
      loadModel: async () => {
        lifecycleCalls += 1;
        return "must not load";
      },
      registerManagedModel: () => {
        registerCalls += 1;
      },
    });

    const result = await command.execute(
      `checkpoint load ${bundle.root}`,
      context,
    );

    expect(result?.exitCode).toBe(1);
    expect(result?.message).toMatch(
      /corrupt, incomplete, or tampered.*expert-audio\.pt/i,
    );
    expect(ensureCalls).toBe(0);
    expect(lifecycleCalls).toBe(0);
    expect(registerCalls).toBe(0);
  });

  it("refuses an intact but unauthorized checkpoint before any model process starts", async () => {
    let ensureCalls = 0;
    let lifecycleCalls = 0;
    const command = createModelCommand({
      verifyCheckpointBundle: async () => ({
        checkpointDir: "C:\\candidate-checkpoint",
        manifestPath: "C:\\candidate-checkpoint\\checkpoint-manifest.json",
        manifestSha256: "a".repeat(64),
        schemaVersion: "ember-sparse-checkpoint-v5",
        artifacts: [],
      }),
      loadOwnedIdentity: () => ownedIdentity,
      ensureOwnedServer: async () => {
        ensureCalls += 1;
        throw new Error("must not start");
      },
      loadModel: async () => {
        lifecycleCalls += 1;
        return "must not load";
      },
    });

    const result = await command.execute(
      "checkpoint load C:\\candidate-checkpoint",
      context,
    );

    expect(result?.exitCode).toBe(1);
    expect(result?.message).toContain(
      "not the currently authorized owned checkpoint",
    );
    expect(result?.message).toContain(
      "governed owned-model identity/admission workflow",
    );
    expect(ensureCalls).toBe(0);
    expect(lifecycleCalls).toBe(0);
  });

  it("selects an authorized byte-valid checkpoint through the owned supervisor", async () => {
    let receivedIdentity: OwnedModelIdentity | null = null;
    const authorizedIdentity = {
      ...ownedIdentity,
      checkpointSha256: "a".repeat(64),
    } as OwnedModelIdentity;
    const command = createModelCommand({
      verifyCheckpointBundle: async () => ({
        checkpointDir: "C:\\candidate-checkpoint",
        manifestPath: "C:\\candidate-checkpoint\\checkpoint-manifest.json",
        manifestSha256: "a".repeat(64),
        schemaVersion: "ember-sparse-checkpoint-v5",
        artifacts: [],
      }),
      loadOwnedIdentity: () => authorizedIdentity,
      ensureOwnedServer: async (identity) => {
        receivedIdentity = identity;
        return {
          outcome: "spawned",
          port: 29777,
          handle: {
            process: { pid: 4242 },
            port: 29777,
            kill: () => {},
          } as never,
        };
      },
      loadModel: async () => "model loaded (pid 4242)",
      registerManagedModel: () => {},
    });

    const result = await command.execute(
      "checkpoint load C:\\candidate-checkpoint",
      context,
    );

    expect(result?.exitCode).toBeUndefined();
    expect(result?.message).toContain("model loaded");
    expect(result?.message).toContain("a".repeat(64));
    expect(receivedIdentity).not.toBeNull();
    expect(receivedIdentity!.launch?.checkpointDir).toBe(
      "C:\\candidate-checkpoint",
    );
    expect(authorizedIdentity.launch?.checkpointDir).toBe("C:\\old-checkpoint");
  });
});

describe("/model discoverability", () => {
  it("keeps every dispatched command family visible in the description", async () => {
    const command = createModelCommand();
    const source = await Bun.file(new URL("./model.ts", import.meta.url)).text();
    const topLevel = [
      ...new Set(
        [...source.matchAll(/(?<!_)subcommand === "([^"]+)"/g)].map(
          (match) => match[1],
        ),
      ),
    ].sort();
    const manifestActions = [
      ...source.matchAll(/manifest_subcommand === "([^"]+)"/g),
    ].map((match) => match[1]).sort();
    const checkpointActions = [
      ...source.matchAll(/action === "([^"]+)"/g),
    ].map((match) => match[1]).sort();

    expect(topLevel).toEqual([
      "checkpoint",
      "load",
      "manifest",
      "status",
      "unload",
    ]);
    expect(manifestActions).toEqual(["inspect"]);
    expect(checkpointActions).toEqual(["load", "save"]);
    for (const visible of [
      "status",
      "load",
      "unload",
      "manifest inspect",
      "checkpoint load",
      "checkpoint save",
      "data/tokenizer lineage",
    ]) {
      expect(String(command.description)).toContain(visible);
    }
  });
});
