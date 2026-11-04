// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/llama-backend.ts -- what the llama-server binary on this machine can
// do, learned from the binary itself (`--help`), plus the KV-cache type table
// the fit rule uses.  Nothing here is assumed from a version string: a stock
// llama.cpp build and the avir TurboQuant fork are told apart by the KV types
// their own `--cache-type-k` help line lists.

import { spawnSync } from "node:child_process";

export interface BackendCaps {
  /** First line of `--version` ("version: 8786 (32ec212a5)"), or null if unreadable. */
  version: string | null;
  /** Values the binary's --cache-type-k accepts. */
  kvTypes: string[];
  /** The subset of kvTypes that are turbo* (TurboQuant fork). */
  turboTypes: string[];
  /** "value" when `-fa on|off|auto` is taken, "flag" when bare `-fa`/`--flash-attn`, "none" when absent. */
  flashAttn: "value" | "flag" | "none";
  slotSavePath: boolean;
  chatTemplateFile: boolean;
  ubatch: boolean;
  parallel: boolean;
  /** `--spec-type` lists `draft-mtp` (multi-token-prediction speculative decoding). */
  draftMtp: boolean;
}

/** Parse the text of `llama-server --help`.  Pure; exit status and stderr noise
 * (CUDA init lines) are irrelevant, only stdout text is read. */
export function parseHelp(help: string, version: string | null = null): BackendCaps {
  const kvTypes = parseKvTypes(help);
  const faLine = help.split(/\r?\n/).find((l) => /(^|\s)-fa,\s|--flash-attn/.test(l)) ?? "";
  const flashAttn: BackendCaps["flashAttn"] = !faLine ? "none" : /\[on\|off\|auto\]/.test(faLine) ? "value" : "flag";
  return {
    version,
    kvTypes,
    turboTypes: kvTypes.filter((t) => /^turbo\d$/.test(t)),
    flashAttn,
    slotSavePath: /--slot-save-path/.test(help),
    chatTemplateFile: /--chat-template-file/.test(help),
    ubatch: /--ubatch-size/.test(help),
    parallel: /--parallel/.test(help),
    draftMtp: parseDraftMtp(help),
  };
}

/** Values of the `-ctk/--cache-type-k` option: the token list after
 * "allowed values:" up to the "(default" line (it wraps across lines). */
export function parseKvTypes(help: string): string[] {
  const lines = help.split(/\r?\n/);
  const start = lines.findIndex((l) => /--cache-type-k\b/.test(l));
  if (start < 0) return [];
  const out: string[] = [];
  let inList = false;
  for (let i = start + 1; i < Math.min(lines.length, start + 8); i++) {
    const l = lines[i]!;
    if (/^\s*-/.test(l)) break; // next option
    const m = l.match(/allowed values:\s*(.*)$/);
    if (m) { inList = true; out.push(...splitTypes(m[1]!)); continue; }
    if (inList) {
      if (/\(default|\(env/.test(l)) break;
      out.push(...splitTypes(l));
    }
  }
  return out;
}

/** Whether the `--spec-type` option's own help block names `draft-mtp`.  Read from the
 * binary's help the same way the turbo KV types are: a build that predates MTP
 * simply does not list it.  The block runs from the option line to the next option. */
export function parseDraftMtp(help: string): boolean {
  const lines = help.split(/\r?\n/);
  const start = lines.findIndex((l) => /--spec-type\b/.test(l));
  if (start < 0) return false;
  let block = lines[start]!;
  for (let i = start + 1; i < Math.min(lines.length, start + 12); i++) {
    if (/^\s*-/.test(lines[i]!)) break; // next option
    block += "\n" + lines[i]!;
  }
  return /\bdraft-mtp\b/.test(block);
}

function splitTypes(s: string): string[] {
  return s.split(/[,\s]+/).map((x) => x.trim()).filter((x) => /^[a-z0-9_]+$/.test(x));
}

export function probeBackend(binary: string): BackendCaps {
  const help = spawnSync(binary, ["--help"], { encoding: "utf-8", maxBuffer: 16 * 1024 * 1024 });
  const ver = spawnSync(binary, ["--version"], { encoding: "utf-8" });
  const verLine = `${ver.stdout ?? ""}\n${ver.stderr ?? ""}`.split(/\r?\n/).find((l) => /^version:/i.test(l.trim()))?.trim() ?? null;
  // Parse stdout whatever the exit status: a busy GPU can make --help exit
  // nonzero after it has already printed everything.
  return parseHelp(help.stdout ?? "", verLine);
}

// ---------------------------------------------------------------------------
// KV cache types: size and quality
// ---------------------------------------------------------------------------

export interface KvFormat {
  /** Storage cost in bits per element, from the block struct sizes. */
  bitsPerElement: number;
  /** Where the number comes from. */
  source: string;
}

/** Bits per element come from the block structs in the compiled header
 * (avir-cli vendor/llama-turboquant/ggml/src/ggml-common.h), not from the
 * prose docs, which disagree with each other (README / TURBOQUANT_CUDA_IMPLEMENTATION.md
 * say "turbo3 3.25-bit" and "turbo4 4.25-bit, 68-byte block with rnorm"; the header
 * says 14 B / 32 = 3.5 and 66 B / 128 = 4.125).  Using the header's numbers
 * keeps the estimate tied to the binary that actually runs. */
export const KV_FORMATS: Record<string, KvFormat> = {
  f16:    { bitsPerElement: 16,    source: "ggml f16" },
  q4_0:   { bitsPerElement: 4.5,   source: "ggml block_q4_0: 18 bytes / 32 elements" },
  q8_0:   { bitsPerElement: 8.5,   source: "ggml block_q8_0: 34 bytes / 32 elements" },
  turbo4: { bitsPerElement: 4.125, source: "ggml-common.h block_turbo4_0: 66 bytes / 128 elements = 4.125 bits/value" },
  turbo3: { bitsPerElement: 3.5,   source: "ggml-common.h block_turbo3_0: 14 bytes / 32 elements = 3.5 bits/value" },
  turbo2: { bitsPerElement: 2.5,   source: "ggml-common.h block_turbo2_0: 10 bytes / 32 elements = 2.5 bits/value" },
};

export interface KvChoice {
  k: string;
  v: string;
  /** Multiplier on the fp16 KV size the catalog stores: (bitsK + bitsV) / 32. */
  scale: number;
  /** Why this pair clears the quality floor. */
  evidence: string;
}

export function kvScale(k: string, v: string): number {
  const bk = KV_FORMATS[k]?.bitsPerElement;
  const bv = KV_FORMATS[v]?.bitsPerElement;
  if (bk === undefined || bv === undefined) throw new Error(`unknown KV cache type ${k}/${v}`);
  return (bk + bv) / 32;
}

/** The quality floor.  Only uniform K=V pairs that avir's docs carry perplexity
 * evidence for are allowed, best-first:
 *   q8_0   -- the reference every turbo number is measured against (README table "q8_0 baseline 5.8375").
 *   turbo4 -- README "turbo4 uniform 5.8186, -0.32% vs q8_0, 3.8x".
 *   turbo3 -- README "turbo3 uniform 5.8323, -0.09% vs q8_0, 4.9x"; also what avir ships for
 *             qwen3.6-27b (tests/gpu/registry/qwen3.6-27b.yml cache_type_k/v: turbo3).
 * Excluded on purpose:
 *   turbo2 (any side) -- experiments.md #28: "turbo2 K+V: PPL 6.78 (+8.0% vs f16) -- too much degradation".
 *   mixed turbo pairs -- TURBOQUANT_CUDA_IMPLEMENTATION.md: "Mixed K/V types: implemented but not yet tested".
 * Those PPL figures are for Qwen3.5-27B Q6_K on an RTX 3090; for other models they are
 * the best evidence available, and calibration additionally rejects a pair whose
 * output fails a coherence check on the real model. */
export const QUALITY_FLOOR_ORDER = ["q8_0", "turbo4", "turbo3"] as const;

export function allowedKvChoices(caps: Pick<BackendCaps, "kvTypes">, opts: { includeF16?: boolean } = {}): KvChoice[] {
  const evidence: Record<string, string> = {
    f16: "lossless reference",
    q8_0: "reference baseline (README PPL 5.8375)",
    turbo4: "README: turbo4 uniform PPL 5.8186, -0.32% vs q8_0",
    turbo3: "README: turbo3 uniform PPL 5.8323, -0.09% vs q8_0; avir ships turbo3/turbo3 for qwen3.6-27b",
  };
  const order = [...(opts.includeF16 ? ["f16"] : []), ...QUALITY_FLOOR_ORDER];
  return order
    .filter((t) => caps.kvTypes.includes(t))
    .map((t) => ({ k: t, v: t, scale: kvScale(t, t), evidence: evidence[t]! }));
}

/** KV order for `ember pull --calibrate` (#2371): q4_0 first -- at the model's full native
 * context it is the type that fits a 24 GB card (measured, RTX 4090, llama.cpp b12032,
 * Qwen3.8-27B at 262144 / 1 slot: q8_0 filled VRAM, q4_0 + draft-mtp ran 93-97 tok/s and
 * recalled a needle at 200k tokens) -- then the usual floor list.  q4_0 sits outside
 * QUALITY_FLOOR_ORDER on purpose: it never wins a speed tie, and no candidate is accepted
 * on a quantised cache until the long-context recall check in model-calibrate.ts passes. */
export const CALIBRATION_KV_FIRST = "q4_0";

export function calibrationKvChoices(caps: Pick<BackendCaps, "kvTypes">, opts: { includeF16?: boolean } = {}): KvChoice[] {
  const rest = allowedKvChoices(caps, opts);
  if (!caps.kvTypes.includes(CALIBRATION_KV_FIRST)) return rest;
  const q4: KvChoice = { k: "q4_0", v: "q4_0", scale: kvScale("q4_0", "q4_0"), evidence: "measured on Qwen3.8-27B at 262144 context: needle recalled at 200k tokens with draft-mtp (issue #2371); gated by the live recall check" };
  return [q4, ...rest];
}

/** Stock llama.cpp fallback: q8_0/q8_0 (needs flash attention). */
export const STOCK_KV_CHOICE: KvChoice = { k: "q8_0", v: "q8_0", scale: kvScale("q8_0", "q8_0"), evidence: "stock llama.cpp default for quantized KV" };

export function kvChoicesFor(caps: BackendCaps | null): KvChoice[] {
  if (!caps || caps.kvTypes.length === 0) return [STOCK_KV_CHOICE];
  const c = allowedKvChoices(caps);
  return c.length > 0 ? c : [STOCK_KV_CHOICE];
}

/** `-fa` argument pair in the dialect the binary speaks. */
export function flashAttnArgs(caps: Pick<BackendCaps, "flashAttn"> | null, on: boolean): string[] {
  if (caps?.flashAttn === "flag") return on ? ["-fa"] : [];
  return ["-fa", on ? "on" : "off"];
}
