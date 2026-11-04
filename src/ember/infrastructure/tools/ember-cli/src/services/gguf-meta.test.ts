// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, it } from "bun:test";

import { hasMtpHead, kvBytesPerTokenFromMeta, parseGgufMeta } from "./gguf-meta.ts";

function str(s: string): Buffer { const b = Buffer.from(s, "utf-8"); const l = Buffer.alloc(8); l.writeBigUInt64LE(BigInt(b.length)); return Buffer.concat([l, b]); }
function u32(n: number): Buffer { const b = Buffer.alloc(4); b.writeUInt32LE(n); return b; }
function kv(key: string, type: number, value: Buffer): Buffer { return Buffer.concat([str(key), u32(type), value]); }
function gguf(entries: Buffer[]): Buffer {
  const head = Buffer.alloc(24); head.write("GGUF", 0, "ascii"); head.writeUInt32LE(3, 4); head.writeBigUInt64LE(0n, 8); head.writeBigUInt64LE(BigInt(entries.length), 16);
  return Buffer.concat([head, ...entries]);
}
function strArray(items: string[]): Buffer { const n = Buffer.alloc(8); n.writeBigUInt64LE(BigInt(items.length)); return Buffer.concat([u32(8), n, ...items.map(str)]); }

describe("gguf metadata reader", () => {
  const buf = gguf([
    kv("general.architecture", 8, str("qwen35")),
    kv("general.name", 8, str("Qwen3.8 27B")),
    kv("qwen35.block_count", 4, u32(64)),
    kv("qwen35.attention.head_count_kv", 4, u32(4)),
    kv("qwen35.attention.key_length", 4, u32(256)),
    kv("qwen35.context_length", 4, u32(262144)),
    kv("tokenizer.ggml.tokens", 9, strArray(["a", "bb", "ccc"])),
    kv("tokenizer.chat_template", 8, str("{{ x }}")),
  ]);

  it("reads architecture and geometry, skipping big arrays", () => {
    const m = parseGgufMeta(buf);
    expect(m).toMatchObject({ architecture: "qwen35", name: "Qwen3.8 27B", blockCount: 64, headCountKv: 4, keyLength: 256, contextLength: 262144, hasChatTemplate: true });
  });

  it("derives fp16 KV bytes per token from geometry (K and V, 2 bytes each)", () => {
    expect(kvBytesPerTokenFromMeta(parseGgufMeta(buf))).toBe(64 * 4 * (256 + 256) * 2);
  });

  it("returns what was read from a truncated header instead of throwing", () => {
    const m = parseGgufMeta(buf.subarray(0, buf.length - 20));
    expect(m.architecture).toBe("qwen35");
    expect(m.hasChatTemplate).toBe(false);
  });

  it("rejects non-GGUF bytes", () => {
    expect(() => parseGgufMeta(Buffer.from("not a gguf file at all, definitely not"))).toThrow("not a GGUF");
  });
});

describe("MTP head detection", () => {
  const withHead = gguf([
    kv("general.architecture", 8, str("qwen35")),
    kv("qwen35.context_length", 4, u32(262144)),
    kv("qwen35.nextn_predict_layers", 4, u32(1)),
  ]);
  const noHead = gguf([kv("general.architecture", 8, str("qwen3")), kv("qwen3.context_length", 4, u32(40960))]);
  const zeroHead = gguf([kv("general.architecture", 8, str("qwen35")), kv("qwen35.nextn_predict_layers", 4, u32(0))]);

  it("reads nextn_predict_layers and the native context", () => {
    const m = parseGgufMeta(withHead);
    expect(m.nextnPredictLayers).toBe(1);
    expect(m.contextLength).toBe(262144);
    expect(hasMtpHead(m)).toBe(true);
  });

  it("a file without the key, or with zero layers, has no MTP head", () => {
    expect(parseGgufMeta(noHead).nextnPredictLayers).toBeNull();
    expect(hasMtpHead(parseGgufMeta(noHead))).toBe(false);
    expect(hasMtpHead(parseGgufMeta(zeroHead))).toBe(false);
  });
});
