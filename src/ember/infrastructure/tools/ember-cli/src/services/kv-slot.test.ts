// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, it } from "bun:test";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { restoreIfPresent, slotFileName, slotKey, type SlotKeyParts } from "./kv-slot.ts";

const base: SlotKeyParts = {
  modelPath: "/m/a.gguf", modelSize: 100, modelMtimeMs: 5, backendVersion: "version: 8786", kvK: "turbo3", kvV: "turbo3", ctx: 65536, templateId: null, systemPrompt: "sys",
};

describe("slot key", () => {
  it("is stable for identical inputs", () => {
    expect(slotKey(base)).toBe(slotKey({ ...base }));
    expect(slotFileName(slotKey(base))).toMatch(/^sysprompt-[0-9a-f]{24}\.bin$/);
  });

  it("changes with every part of the KV domain (a stale slot under another build or KV type is silently wrong)", () => {
    const k = slotKey(base);
    for (const change of [
      { backendVersion: "version: 8787" }, { kvK: "q8_0" }, { kvV: "q8_0" }, { ctx: 32768 }, { modelSize: 101 },
      { modelMtimeMs: 6 }, { templateId: "qwen36" }, { systemPrompt: "sys2" }, { modelPath: "/m/b.gguf" },
    ] as Array<Partial<SlotKeyParts>>) expect(slotKey({ ...base, ...change })).not.toBe(k);
  });
});

describe("restoreIfPresent", () => {
  it("does nothing, without calling the server, when no slot file exists for the key", async () => {
    const dir = mkdtempSync(join(tmpdir(), "slots-"));
    const r = await restoreIfPresent("http://127.0.0.1:9", dir, "abc");
    expect(r).toMatchObject({ restored: false, reason: "no slot file for this key" });
  });

  it("reports a failed restore (server unreachable) as not restored, never throws", async () => {
    const dir = mkdtempSync(join(tmpdir(), "slots-"));
    writeFileSync(join(dir, slotFileName("abc")), "x");
    const r = await restoreIfPresent("http://127.0.0.1:9", dir, "abc");
    expect(r.restored).toBe(false);
  });
});
