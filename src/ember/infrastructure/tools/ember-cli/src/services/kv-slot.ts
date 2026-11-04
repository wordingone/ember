// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/kv-slot.ts -- persisted system-prompt KV slots.  A new session
// normally re-prefills the harness system prompt (tens of thousands of tokens
// for an agent with tool schemas).  llama-server can save slot 0's KV state to
// `--slot-save-path` and restore it after a restart, so a fresh session skips
// that prefill.
//
// Provenance: avir-cli reserves kv-slots/ directories and passes
// `--slot-save-path` (registry slot_save_path), but all three of its kv-slots/
// directories are EMPTY in the tree and no avir code calls the save/restore
// endpoints -- the persistence was wired as a flag, never exercised.  This module
// implements and MEASURES it.
//
// Safety: the vendor doc (TURBOQUANT_CUDA_IMPLEMENTATION.md, "Cache compatibility
// note (G5.5)") warns that slot files written under a different KV domain or
// build load without error and give silently wrong output.  The slot file name is
// therefore a hash of everything that defines that domain: model file identity,
// backend version, KV types, context size, chat template, and the prompt itself.
// Proof that a restore took effect is `timings.prompt_n` on the next request
// (tokens actually prefilled), not the 200 from the restore call.

import { createHash } from "node:crypto";
import { existsSync, mkdirSync, statSync, unlinkSync } from "node:fs";
import { join } from "node:path";
import { chat, filler, startServer, waitHealthy } from "./llama-harness.ts";

export interface SlotKeyParts {
  modelPath: string;
  modelSize: number;
  modelMtimeMs: number;
  backendVersion: string | null;
  kvK: string;
  kvV: string;
  ctx: number;
  templateId: string | null;
  systemPrompt: string;
}

export function slotKey(p: SlotKeyParts): string {
  const h = createHash("sha256");
  h.update(JSON.stringify([p.modelPath, p.modelSize, Math.floor(p.modelMtimeMs), p.backendVersion, p.kvK, p.kvV, p.ctx, p.templateId]));
  h.update("\0");
  h.update(p.systemPrompt);
  return h.digest("hex").slice(0, 24);
}

export function slotFileName(key: string): string {
  return `sysprompt-${key}.bin`;
}

export function modelIdentity(modelPath: string): { size: number; mtimeMs: number } {
  const s = statSync(modelPath);
  return { size: s.size, mtimeMs: s.mtimeMs };
}

export interface SlotOpResult { ok: boolean; ms: number; tokens?: number; error?: string }

async function slotOp(url: string, slot: number, action: "save" | "restore" | "erase", filename?: string): Promise<SlotOpResult> {
  const t0 = Date.now();
  const res = await fetch(`${url}/slots/${slot}?action=${action}`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(filename ? { filename } : {}),
  }).catch((e: Error) => e);
  if (res instanceof Error) return { ok: false, ms: Date.now() - t0, error: res.message };
  const j = (await res.json().catch(() => ({}))) as { n_saved?: number; n_restored?: number; error?: { message?: string } };
  if (!res.ok) return { ok: false, ms: Date.now() - t0, error: `HTTP ${res.status} ${j.error?.message ?? ""}`.trim() };
  return { ok: true, ms: Date.now() - t0, tokens: j.n_saved ?? j.n_restored };
}

export const saveSlot = (url: string, filename: string, slot = 0) => slotOp(url, slot, "save", filename);
export const restoreSlot = (url: string, filename: string, slot = 0) => slotOp(url, slot, "restore", filename);
export const eraseSlot = (url: string, slot = 0) => slotOp(url, slot, "erase");

/** Runtime hook: restore the slot for this exact (model, backend, KV, ctx, template, prompt)
 * if a file for it exists in the slot directory.  Returns what happened; never throws. */
export async function restoreIfPresent(url: string, slotDir: string, key: string): Promise<{ restored: boolean; ms: number; tokens?: number; reason?: string }> {
  const file = slotFileName(key);
  if (!existsSync(join(slotDir, file))) return { restored: false, ms: 0, reason: "no slot file for this key" };
  const r = await restoreSlot(url, file);
  return r.ok ? { restored: true, ms: r.ms, ...(r.tokens !== undefined ? { tokens: r.tokens } : {}) } : { restored: false, ms: r.ms, reason: r.error ?? "restore failed" };
}

export interface SlotMeasurement {
  at: string;
  promptTokensRequested: number;
  slotFile: string;
  slotFileBytes: number | null;
  savedTokens: number | null;
  restoreMs: number;
  coldTtftMs: number;
  restoredTtftMs: number;
  coldPromptN: number | null;
  restoredPromptN: number | null;
  speedup: number;
  /** True when the restored run prefilled < 20% of the tokens the cold run did. */
  restoreEffective: boolean;
  note: string;
}

export interface SlotMeasureInput {
  binary: string;
  /** Full launch args EXCEPT --host/--port and --slot-save-path (added here). */
  serverArgs: string[];
  slotDir: string;
  ctx: number;
  keyParts: Omit<SlotKeyParts, "systemPrompt">;
  logPath: string;
  log: (s: string) => void;
}

/** TTFT with and without slot restore, ACROSS a server restart (so the in-process
 * prompt cache cannot explain the difference):
 *   server A: cold prefill of system+user1 -> TTFT_cold; save slot; stop.
 *   server B: restore slot; system+user2 -> TTFT_restored.
 * TTFT is the wall time of a max_tokens=1 completion (prefill plus one decode step). */
export async function measureSlotReuse(inp: SlotMeasureInput): Promise<SlotMeasurement> {
  const promptTokens = Math.max(512, Math.min(6000, Math.floor(inp.ctx / 2) - 512));
  const system = `You are an agent harness. Standing instructions follow.\n${filler(promptTokens, "slot-system-prompt")}`;
  const key = slotKey({ ...inp.keyParts, systemPrompt: system });
  const file = slotFileName(key);
  mkdirSync(inp.slotDir, { recursive: true }); // llama-server refuses a --slot-save-path that does not exist
  const args = [...inp.serverArgs, "--slot-save-path", inp.slotDir];
  const ask = (url: string, user: string) => chat(url, { messages: [{ role: "system", content: system }, { role: "user", content: user }], max_tokens: 1, temperature: 0 });
  const warm = (url: string, salt: string) => chat(url, { messages: [{ role: "user", content: `${filler(64, salt)} say hi` }], max_tokens: 4, temperature: 0, cache_prompt: false });

  inp.log("kv-slot: server A (cold prefill, then save) ...");
  const a = await startServer(inp.binary, args, inp.logPath);
  let cold, saved: SlotOpResult;
  try {
    const h = await waitHealthy(a);
    if (!h.ok) throw new Error(h.error);
    await warm(a.url, "warmA");
    cold = await ask(a.url, "Question one: what is the capital of France?");
    if (!cold.ok) throw new Error(`cold request failed: HTTP ${cold.status}`);
    saved = await saveSlot(a.url, file);
    if (!saved.ok) throw new Error(`slot save failed: ${saved.error}`);
  } finally { await a.stop(); }

  inp.log("kv-slot: server B (restart, restore, same system prompt) ...");
  const b = await startServer(inp.binary, args, inp.logPath);
  let restore: SlotOpResult, hot;
  try {
    const h = await waitHealthy(b);
    if (!h.ok) throw new Error(h.error);
    await warm(b.url, "warmB");
    restore = await restoreSlot(b.url, file);
    if (!restore.ok) throw new Error(`slot restore failed: ${restore.error}`);
    hot = await ask(b.url, "Question two: what is the capital of Italy?");
    if (!hot.ok) throw new Error(`restored request failed: HTTP ${hot.status}`);
  } finally { await b.stop(); }

  const coldN = cold.timings.prompt_n ?? null;
  const hotN = hot.timings.prompt_n ?? null;
  const effective = coldN !== null && hotN !== null && hotN < coldN * 0.2;
  const bytes = existsSync(join(inp.slotDir, file)) ? statSync(join(inp.slotDir, file)).size : null;
  // The measurement slot holds a synthetic prompt no real session will ever match; do not leave
  // a multi-hundred-MB file behind per calibration run.
  try { unlinkSync(join(inp.slotDir, file)); } catch { /* already gone */ }
  return {
    at: new Date().toISOString(), promptTokensRequested: promptTokens, slotFile: file, slotFileBytes: bytes, savedTokens: saved.tokens ?? null,
    restoreMs: restore.ms, coldTtftMs: cold.wallMs, restoredTtftMs: hot.wallMs + restore.ms, coldPromptN: coldN, restoredPromptN: hotN,
    speedup: cold.wallMs / (hot.wallMs + restore.ms), restoreEffective: effective,
    note: effective ? "restored run prefilled only the new user turn" : "restore did not reduce prefill (prompt_n not < 20% of cold); do not enable",
  };
}
