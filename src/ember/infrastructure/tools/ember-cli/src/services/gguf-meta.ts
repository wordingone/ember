// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/gguf-meta.ts -- minimal GGUF header reader.  Reads only the
// metadata key/value section (never tensor data) to learn the architecture and
// KV geometry of a model file, so `ember pull --calibrate` can work on any
// GGUF the operator already has.

import { openSync, readSync, closeSync, fstatSync } from "node:fs";

export interface GgufMeta {
  version: number;
  /** general.architecture, e.g. "qwen3", "qwen35", "gemma4" */
  architecture: string | null;
  name: string | null;
  /** Whether the file embeds a tokenizer.chat_template. */
  hasChatTemplate: boolean;
  blockCount: number | null;
  headCountKv: number | null;
  keyLength: number | null;
  valueLength: number | null;
  embeddingLength: number | null;
  headCount: number | null;
  contextLength: number | null;
  /** `<arch>.nextn_predict_layers`: layers of multi-token-prediction (MTP) head the file carries; null when absent. */
  nextnPredictLayers: number | null;
}

const WANTED_PREFIX = ["general.architecture", "general.name", "tokenizer.chat_template"];

class Cursor {
  constructor(public buf: Buffer, public pos = 0) {}
  need(n: number): void { if (this.pos + n > this.buf.length) throw new RangeError("gguf: header truncated"); }
  u8() { this.need(1); return this.buf[this.pos++]!; }
  u16() { this.need(2); const v = this.buf.readUInt16LE(this.pos); this.pos += 2; return v; }
  u32() { this.need(4); const v = this.buf.readUInt32LE(this.pos); this.pos += 4; return v; }
  u64() { this.need(8); const v = Number(this.buf.readBigUInt64LE(this.pos)); this.pos += 8; return v; }
  str(): string { const n = this.u64(); this.need(n); const s = this.buf.toString("utf-8", this.pos, this.pos + n); this.pos += n; return s; }
  skipStr(): void { const n = this.u64(); this.need(n); this.pos += n; }
}

const FIXED_SIZE: Record<number, number> = { 0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8 };

function readScalar(c: Cursor, t: number): number | string | boolean | null {
  switch (t) {
    case 0: return c.u8();
    case 1: { c.need(1); const v = c.buf.readInt8(c.pos); c.pos += 1; return v; }
    case 2: return c.u16();
    case 3: { c.need(2); const v = c.buf.readInt16LE(c.pos); c.pos += 2; return v; }
    case 4: return c.u32();
    case 5: { c.need(4); const v = c.buf.readInt32LE(c.pos); c.pos += 4; return v; }
    case 6: { c.need(4); const v = c.buf.readFloatLE(c.pos); c.pos += 4; return v; }
    case 7: return c.u8() !== 0;
    case 8: return c.str();
    case 10: return c.u64();
    case 11: { c.need(8); const v = Number(c.buf.readBigInt64LE(c.pos)); c.pos += 8; return v; }
    case 12: { c.need(8); const v = c.buf.readDoubleLE(c.pos); c.pos += 8; return v; }
    default: throw new Error(`gguf: unsupported value type ${t}`);
  }
}

function skipValue(c: Cursor, t: number): void {
  if (t === 8) { c.skipStr(); return; }
  if (t === 9) {
    const et = c.u32(); const n = c.u64();
    if (et === 8) { for (let i = 0; i < n; i++) c.skipStr(); return; }
    const sz = FIXED_SIZE[et];
    if (sz === undefined) throw new Error(`gguf: unsupported array element type ${et}`);
    c.need(sz * n); c.pos += sz * n; return;
  }
  const sz = FIXED_SIZE[t];
  if (sz === undefined) throw new Error(`gguf: unsupported value type ${t}`);
  c.need(sz); c.pos += sz;
}

/** Parse GGUF metadata from the bytes of the file's head.  Tolerates a
 * truncated buffer: whatever keys were fully read before the cut are returned. */
export function parseGgufMeta(buf: Buffer): GgufMeta {
  const meta: GgufMeta = { version: 0, architecture: null, name: null, hasChatTemplate: false, blockCount: null, headCountKv: null,
    keyLength: null, valueLength: null, embeddingLength: null, headCount: null, contextLength: null, nextnPredictLayers: null };
  if (buf.length < 24 || buf.toString("ascii", 0, 4) !== "GGUF") throw new Error("not a GGUF file");
  const c = new Cursor(buf, 4);
  meta.version = c.u32();
  c.u64(); // tensor count
  const kvCount = c.u64();
  const vals: Record<string, number | string | boolean | null> = {};
  try {
    for (let i = 0; i < kvCount; i++) {
      const key = c.str();
      const t = c.u32();
      const arch = (vals["general.architecture"] as string | undefined) ?? "";
      const wanted = WANTED_PREFIX.includes(key) || (arch !== "" && key.startsWith(arch + "."));
      if (wanted && t !== 9) vals[key] = readScalar(c, t);
      else skipValue(c, t);
    }
  } catch (e) {
    if (!(e instanceof RangeError)) throw e;
  }
  const arch = (vals["general.architecture"] as string | undefined) ?? null;
  const num = (suffix: string): number | null => {
    const v = arch ? vals[`${arch}.${suffix}`] : undefined;
    return typeof v === "number" ? v : null;
  };
  meta.architecture = arch;
  meta.name = typeof vals["general.name"] === "string" ? (vals["general.name"] as string) : null;
  meta.hasChatTemplate = typeof vals["tokenizer.chat_template"] === "string";
  meta.blockCount = num("block_count");
  meta.headCountKv = num("attention.head_count_kv");
  meta.keyLength = num("attention.key_length");
  meta.valueLength = num("attention.value_length");
  meta.embeddingLength = num("embedding_length");
  meta.headCount = num("attention.head_count");
  meta.contextLength = num("context_length");
  meta.nextnPredictLayers = num("nextn_predict_layers");
  return meta;
}

/** True when the GGUF carries a multi-token-prediction head (`nextn_predict_layers` > 0),
 * i.e. `--spec-type draft-mtp` has something to draft with. */
export function hasMtpHead(m: Pick<GgufMeta, "nextnPredictLayers">): boolean {
  return m.nextnPredictLayers !== null && m.nextnPredictLayers > 0;
}

export function readGgufMeta(path: string, maxBytes = 64 * 1024 * 1024): GgufMeta {
  const fd = openSync(path, "r");
  try {
    const size = Math.min(fstatSync(fd).size, maxBytes);
    const buf = Buffer.alloc(size);
    let off = 0;
    while (off < size) { const n = readSync(fd, buf, off, size - off, off); if (n <= 0) break; off += n; }
    return parseGgufMeta(buf.subarray(0, off));
  } finally { closeSync(fd); }
}

/** fp16 KV bytes per token from GGUF geometry: layers * kv_heads * (K+V head dims) * 2 bytes.
 * An over-estimate for hybrid models where only some layers keep a KV cache (safe direction).
 * Returns null when the geometry is not a plain number set. */
export function kvBytesPerTokenFromMeta(m: GgufMeta): number | null {
  if (m.blockCount === null || m.headCountKv === null) return null;
  const headDim = m.keyLength ?? (m.embeddingLength !== null && m.headCount ? m.embeddingLength / m.headCount : null);
  if (headDim === null) return null;
  return m.blockCount * m.headCountKv * (headDim + (m.valueLength ?? headDim)) * 2;
}
