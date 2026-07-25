// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { afterEach, describe, expect, it } from "bun:test";
import { createHash } from "crypto";
import { mkdtempSync, rmSync, unlinkSync, writeFileSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";
import { verifyCheckpointBundle } from "./checkpoint-load.ts";

const roots: string[] = [];

function sha256(bytes: Uint8Array): string {
  return createHash("sha256").update(bytes).digest("hex");
}

const EXPERT_PATHS = [
  "expert-vision.pt",
  "expert-audio.pt",
  "expert-reasoning.pt",
  "expert-tool.pt",
] as const;

type SupportedSchema =
  | "ember-sparse-checkpoint-v3"
  | "ember-sparse-checkpoint-v4"
  | "ember-sparse-checkpoint-v5";

interface WrittenBundle {
  root: string;
  manifest: {
    schema_version: string;
    shards: Array<{
      path: string;
      bytes: number;
      sha256: string;
      publication_mode?: string;
      incremental_bytes?: number;
    }>;
  };
}

function writeBundle(schema: SupportedSchema): WrittenBundle {
  const root = mkdtempSync(join(tmpdir(), "ember-checkpoint-load-"));
  roots.push(root);

  const common = new Map<string, Buffer>(
    EXPERT_PATHS.map((path) => [path, Buffer.from(path)]),
  );
  const payloads =
    schema === "ember-sparse-checkpoint-v5"
      ? new Map<string, Buffer>([
          ["shared-model.pt", Buffer.from("shared-model")],
          ["optimizer-state.pt", Buffer.from("optimizer-state")],
          ["replay-state.pt", Buffer.from("replay-state")],
          ...common,
        ])
      : new Map<string, Buffer>([
          ["shared.pt", Buffer.from("shared")],
          ["replay-state.pt", Buffer.from("replay-state")],
          ...common,
        ]);

  const shards = [...payloads].map(([path, bytes]) => ({
    path,
    bytes: bytes.length,
    sha256: sha256(bytes),
  }));
  const manifest = { schema_version: schema, shards };

  for (const [path, bytes] of payloads) {
    writeFileSync(join(root, path), bytes);
  }
  writeFileSync(
    join(root, "checkpoint-manifest.json"),
    Buffer.from(JSON.stringify(manifest) + "\n", "utf8"),
  );
  return { root, manifest };
}

function rewriteManifest(bundle: WrittenBundle): void {
  writeFileSync(
    join(bundle.root, "checkpoint-manifest.json"),
    Buffer.from(JSON.stringify(bundle.manifest) + "\n", "utf8"),
  );
}

afterEach(() => {
  for (const root of roots.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
});

describe("verifyCheckpointBundle", () => {
  for (const schema of [
    "ember-sparse-checkpoint-v3",
    "ember-sparse-checkpoint-v4",
    "ember-sparse-checkpoint-v5",
  ] as const) {
    it(`accepts a closed, byte-valid ${schema} bundle`, async () => {
      const bundle = writeBundle(schema);
      const verified = await verifyCheckpointBundle(bundle.root);

      expect(verified.schemaVersion).toBe(schema);
      expect(verified.checkpointDir).toBe(bundle.root);
      expect(verified.artifacts.map((row) => row.path).sort()).toEqual(
        bundle.manifest.shards.map((row) => row.path).sort(),
      );
      expect(verified.manifestSha256).toBe(
        sha256(await Bun.file(join(bundle.root, "checkpoint-manifest.json")).bytes()),
      );
    });
  }

  it("refuses an altered named shard while checkpoint-manifest.json is unchanged", async () => {
    const { root } = writeBundle("ember-sparse-checkpoint-v5");
    const manifestBefore = await Bun.file(
      join(root, "checkpoint-manifest.json"),
    ).arrayBuffer();

    writeFileSync(join(root, "expert-audio.pt"), Buffer.from("tampered-audio"));

    await expect(verifyCheckpointBundle(root)).rejects.toThrow(
      /corrupt, incomplete, or tampered.*expert-audio\.pt/i,
    );

    const manifestAfter = await Bun.file(join(root, "checkpoint-manifest.json")).arrayBuffer();
    expect(Buffer.from(manifestAfter)).toEqual(Buffer.from(manifestBefore));
  });

  it("refuses a missing named shard", async () => {
    const bundle = writeBundle("ember-sparse-checkpoint-v5");
    unlinkSync(join(bundle.root, "expert-tool.pt"));

    await expect(verifyCheckpointBundle(bundle.root)).rejects.toThrow(
      /corrupt, incomplete, or tampered.*missing/i,
    );
  });

  it("refuses an unexpected sidecar in the bundle", async () => {
    const bundle = writeBundle("ember-sparse-checkpoint-v5");
    writeFileSync(join(bundle.root, "notes.json"), "{}");

    await expect(verifyCheckpointBundle(bundle.root)).rejects.toThrow(
      /unexpected checkpoint bundle entry notes\.json/i,
    );
  });

  it("refuses a manifest byte-count mismatch", async () => {
    const bundle = writeBundle("ember-sparse-checkpoint-v5");
    bundle.manifest.shards[0].bytes += 1;
    rewriteManifest(bundle);

    await expect(verifyCheckpointBundle(bundle.root)).rejects.toThrow(
      /byte size does not match/i,
    );
  });

  it("refuses a duplicate manifest shard path", async () => {
    const bundle = writeBundle("ember-sparse-checkpoint-v5");
    bundle.manifest.shards.push({ ...bundle.manifest.shards[0] });
    rewriteManifest(bundle);

    await expect(verifyCheckpointBundle(bundle.root)).rejects.toThrow(
      /duplicate shard path/i,
    );
  });

  it("refuses an escaping manifest shard path", async () => {
    const bundle = writeBundle("ember-sparse-checkpoint-v5");
    bundle.manifest.shards[0].path = "../shared-model.pt";
    rewriteManifest(bundle);

    await expect(verifyCheckpointBundle(bundle.root)).rejects.toThrow(
      /confined bundle-relative filename/i,
    );
  });

  it("refuses a checkpoint manifest that is not strict UTF-8", async () => {
    const bundle = writeBundle("ember-sparse-checkpoint-v5");
    writeFileSync(
      join(bundle.root, "checkpoint-manifest.json"),
      Buffer.from([0xff, 0xfe, 0xfd]),
    );

    await expect(verifyCheckpointBundle(bundle.root)).rejects.toThrow(
      /checkpoint-manifest\.json is not strict UTF-8/i,
    );
  });

  it("refuses malformed checkpoint manifest JSON", async () => {
    const bundle = writeBundle("ember-sparse-checkpoint-v5");
    writeFileSync(join(bundle.root, "checkpoint-manifest.json"), "{not-json");

    await expect(verifyCheckpointBundle(bundle.root)).rejects.toThrow(
      /checkpoint-manifest\.json is not valid JSON/i,
    );
  });

  it("refuses an unsupported checkpoint schema", async () => {
    const bundle = writeBundle("ember-sparse-checkpoint-v5");
    bundle.manifest.schema_version = "ember-sparse-checkpoint-v999";
    rewriteManifest(bundle);

    await expect(verifyCheckpointBundle(bundle.root)).rejects.toThrow(
      /checkpoint schema version is unsupported/i,
    );
  });

  it("refuses a backslash-bearing artifact alias", async () => {
    const bundle = writeBundle("ember-sparse-checkpoint-v5");
    bundle.manifest.shards[0].path = "nested\\shared-model.pt";
    rewriteManifest(bundle);

    await expect(verifyCheckpointBundle(bundle.root)).rejects.toThrow(
      /confined bundle-relative filename/i,
    );
  });

  it("refuses the legacy non-round-tripping manifest shape", async () => {
    const root = mkdtempSync(join(tmpdir(), "ember-checkpoint-load-"));
    roots.push(root);
    writeFileSync(join(root, "checkpoint"), "legacy");
    writeFileSync(
      join(root, "manifest.json"),
      JSON.stringify({ schema_version: "1", file: "checkpoint" }),
    );

    await expect(verifyCheckpointBundle(root)).rejects.toThrow(
      /checkpoint-manifest\.json is missing/i,
    );
  });
});
