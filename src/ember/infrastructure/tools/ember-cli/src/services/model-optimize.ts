// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/model-optimize.ts -- orchestrates `ember pull --calibrate`:
//   1. detect what the llama-server binary supports (turbo KV types, flash-attn dialect, draft-mtp)
//   2. search server configurations by measurement (model-calibrate.ts), from the model's native
//      context down; q4_0/q8_0 KV; `--spec-type draft-mtp` when the GGUF has an MTP head and the
//      backend lists it; the winner must recall a needle from a ~90% context prompt
//   3. decide by probe whether an avir fixed chat template is needed (chat-template-decision.ts)
//   4. measure system-prompt KV slot reuse (kv-slot.ts)
//   5. write the winner + a `calibration` receipt into models.json (previous file backed up)
// Nothing is written to models.json unless step 2 found a configuration that
// loaded, answered coherently and left the VRAM headroom.

import { copyFileSync, existsSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { calibrationKvChoices, probeBackend, STOCK_KV_CHOICE, type BackendCaps } from "./llama-backend.ts";
import { kvBytesPerTokenFromMeta, readGgufMeta, type GgufMeta } from "./gguf-meta.ts";
import { gpuMemoryUsedBytes, startServer, stopAllLive, waitHealthy } from "./llama-harness.ts";
import {
  HEADROOM_BYTES, applyCalibration, buildReceipt, calibrationPath, ctxLadderFor, measureCandidate, mtpAvailable, searchConfigs, serverArgsFor, writeJsonAtomic,
  type Candidate, type CalibrationOutcome,
} from "./model-calibrate.ts";
import { decideTemplate, templateFor, templatePath, toolCallProbe, type FixedTemplate, type TemplateDecision, type ToolProbeResult } from "./chat-template-decision.ts";
import { measureSlotReuse, modelIdentity } from "./kv-slot.ts";

const GiB = 1024 ** 3;
/** Refuse to calibrate while something else already holds this much VRAM: the
 * calibration would OOM against it (or, worse, OOM the other tenant). */
export const MAX_FOREIGN_VRAM_BYTES = 4 * GiB;

export interface OptimizeOptions {
  home: string;
  cfgPath: string;
  cfg: Record<string, unknown>;
  binary: string;
  modelPath: string;
  mmprojPath?: string;
  modelName: string;
  totalVramBytes: number;
  /** Context to start from when the GGUF declares no native context; otherwise calibration starts at
   * the native maximum (native, 196608, 131072, then ctxLadder) and steps down. */
  startCtx: number;
  ctxLadder: number[];
  /** Catalog-known fp16 KV bytes per token (preferred over GGUF geometry: hybrid models). */
  kvBytesPerToken?: number;
  /** Probe this avir template even if the GGUF architecture does not select it (never adopted). */
  probeTemplate?: FixedTemplate;
  skipSlot?: boolean;
  /** Do not run the long-context needle check (it prefills ~90% of the context: ~12 min at 262144). */
  skipRecall?: boolean;
  /** VRAM (bytes) every candidate must leave free; default 1 GiB (`ember pull --calibrate --headroom-mib N`). */
  headroomBytes?: number;
  tryFlashOff?: boolean;
  log: (s: string) => void;
}

export interface TemplateRecord {
  architecture: string | null;
  embeddedTemplatePresent: boolean;
  decision: TemplateDecision;
}

async function withServer<T>(binary: string, args: string[], logPath: string, fn: (url: string) => Promise<T>): Promise<T | { startError: string }> {
  const s = await startServer(binary, args, logPath);
  try {
    const h = await waitHealthy(s);
    if (!h.ok) return { startError: h.error };
    return await fn(s.url);
  } finally { await s.stop(); }
}

export async function runTemplateDecision(o: {
  binary: string; modelPath: string; mmprojPath?: string; caps: BackendCaps | null; best: Candidate; meta: GgufMeta; modelName: string;
  probeTemplate?: FixedTemplate; logPath: string; log: (s: string) => void;
}): Promise<TemplateRecord> {
  const matched = templateFor(o.meta.architecture, `${o.modelName} ${o.meta.name ?? ""}`);
  const template = matched ?? o.probeTemplate ?? null;
  const forced = !matched && !!o.probeTemplate;
  const rec = (decision: TemplateDecision): TemplateRecord => ({ architecture: o.meta.architecture, embeddedTemplatePresent: o.meta.hasChatTemplate, decision });
  if (!template) return rec(decideTemplate({ template: null, arch: o.meta.architecture }));

  const argsFor = (tpl?: FixedTemplate) => ["--model", o.modelPath, "--ctx-size", String(o.best.ctx), "--jinja",
    ...(o.mmprojPath ? ["--mmproj", o.mmprojPath] : []), ...serverArgsFor(o.best, o.caps, tpl ? { chatTemplateFile: templatePath(tpl) } : {})];
  const probeWith = async (tpl?: FixedTemplate): Promise<ToolProbeResult> => {
    o.log(`template probe: ${tpl ? "avir " + tpl : "embedded"} ...`);
    const r = await withServer(o.binary, argsFor(tpl), o.logPath, (url) => toolCallProbe(url));
    if ("startError" in r) return { ok: false, stage: "render", detail: `server failed to start with this template: ${r.startError}` };
    o.log(`template probe: ${tpl ? "avir " + tpl : "embedded"} -> ${r.ok ? "PASS" : "FAIL " + r.stage} (${r.detail})`);
    return r;
  };

  const embeddedProbe = await probeWith();
  // The fixed template is probed when the embedded one failed to render, or when forced (for the record).
  const fixedProbe = (!embeddedProbe.ok && embeddedProbe.stage === "render") || forced ? await probeWith(template) : undefined;
  let d = decideTemplate({ template, arch: o.meta.architecture, embeddedProbe, ...(fixedProbe ? { fixedProbe } : {}), forced });
  if (forced && d.use) d = { ...d, use: false, reason: `forced probe on architecture ${o.meta.architecture}: ${d.reason}; not adopted (architecture not matched)` };
  return rec(d);
}

export async function optimizeModel(o: OptimizeOptions): Promise<number> {
  const log = o.log;
  if (o.totalVramBytes <= 0) { log("no NVIDIA GPU: calibration skipped"); return 0; }
  const baseline = gpuMemoryUsedBytes();
  if (baseline !== null && baseline > MAX_FOREIGN_VRAM_BYTES) {
    log(`calibration refused: ${(baseline / GiB).toFixed(1)} GiB of VRAM already in use by other processes (limit ${MAX_FOREIGN_VRAM_BYTES / GiB} GiB); free the GPU and rerun \`ember pull --calibrate\``);
    return 4;
  }
  const caps = probeBackend(o.binary);
  log(`backend: ${caps.version ?? "unknown version"}; KV types: ${caps.kvTypes.join(",") || "(none parsed)"}; ` +
    (caps.turboTypes.length ? `TurboQuant available (${caps.turboTypes.join(",")})` : "stock llama.cpp (no turbo types): q8_0 is the quantised-KV fallback"));

  const meta = readGgufMeta(o.modelPath);
  const kvBytes = o.kvBytesPerToken ?? kvBytesPerTokenFromMeta(meta) ?? 48 * 8 * 128 * 2 * 2;
  const weights = statSync(o.modelPath).size;
  const extra = o.mmprojPath && existsSync(o.mmprojPath) ? statSync(o.mmprojPath).size : 0;
  const kvChoices = caps.kvTypes.length ? calibrationKvChoices(caps, { includeF16: true }) : [STOCK_KV_CHOICE];
  const ctxLadder = ctxLadderFor(meta.contextLength, o.ctxLadder);
  const startCtx = meta.contextLength ? ctxLadder[0]! : o.startCtx;
  const mtp = mtpAvailable(meta, caps);
  log(`context: native ${meta.contextLength ?? "unknown"}, starting at ${startCtx}; ` +
    (mtp ? "MTP head present and backend lists draft-mtp: --spec-type draft-mtp will be tried"
      : `speculative decoding off (MTP head ${meta.nextnPredictLayers ? "present" : "absent"}, backend draft-mtp ${caps.draftMtp ? "listed" : "not listed"})`) +
    `; needle recall ${o.skipRecall ? "SKIPPED" : "required"}`);
  const logPath = join(o.home, "calibration", "calibration-server.log");
  const total = o.totalVramBytes;
  const startedAt = new Date().toISOString();

  let outcome: CalibrationOutcome;
  try {
    outcome = await searchConfigs({
      caps, kvChoices, weightsBytes: weights, extraBytes: extra, kvBytesPerToken: kvBytes, startCtx, ctxLadder,
      totalVramBytes: total, log, tryFlashOff: o.tryFlashOff ?? true, mtp, verifyRecall: !o.skipRecall, ...(o.headroomBytes !== undefined ? { headroomBytes: o.headroomBytes } : {}),
      run: (c, opts) => measureCandidate({ binary: o.binary, modelPath: o.modelPath, ...(o.mmprojPath ? { mmprojPath: o.mmprojPath } : {}), caps, totalVramBytes: total, logPath, log }, c, opts),
    });
  } finally { await stopAllLive(); }

  const resultsFile = calibrationPath(o.home, o.modelName);
  writeJsonAtomic(resultsFile, {
    schema: "ember-calibration/1", model: o.modelName, modelPath: o.modelPath, startedAt, finishedAt: new Date().toISOString(),
    backend: caps, gguf: { architecture: meta.architecture, name: meta.name, blockCount: meta.blockCount, headCountKv: meta.headCountKv, contextLength: meta.contextLength, nextnPredictLayers: meta.nextnPredictLayers },
    kvBytesPerTokenFp16: kvBytes, totalVramBytes: total, baselineVramBytes: baseline, rule: outcome.rule,
    selected: outcome.selected?.candidate.id ?? null, candidates: outcome.results,
  });
  log(`candidate results: ${resultsFile}`);
  const receipt = buildReceipt(outcome, caps, total, resultsFile);
  if (!receipt || !outcome.selected) { log(`calibration found no configuration that loads, answers coherently${o.skipRecall ? "" : ", recalls the needle"} and leaves ${Math.round((o.headroomBytes ?? HEADROOM_BYTES) / 1024 ** 2)} MiB free; models.json unchanged`); return 3; }
  const best = outcome.selected.candidate;
  log(`selected ${best.id}: pp ${receipt.ppTokensPerSecond.toFixed(0)} tok/s, tg ${receipt.tgTokensPerSecond.toFixed(1)} tok/s, ` +
    `peak ${((receipt.peakVramBytes ?? 0) / GiB).toFixed(1)} GiB, headroom ${((receipt.headroomBytes ?? 0) / GiB).toFixed(1)} GiB, ` +
    `context ${best.ctx}, ${receipt.specType ?? "no speculation"}${receipt.draftAcceptance === null ? "" : ` (draft acceptance ${(receipt.draftAcceptance * 100).toFixed(0)}%)`}, recall ${receipt.recall.status}`);

  let tplRec: TemplateRecord;
  try {
    tplRec = await runTemplateDecision({ binary: o.binary, modelPath: o.modelPath, ...(o.mmprojPath ? { mmprojPath: o.mmprojPath } : {}), caps, best, meta,
      modelName: o.modelName, ...(o.probeTemplate ? { probeTemplate: o.probeTemplate } : {}), logPath, log });
  } finally { await stopAllLive(); }
  log(`chat template: ${tplRec.decision.use ? "avir " + tplRec.decision.template : "embedded"} -- ${tplRec.decision.reason}`);
  const chatTemplateFile = tplRec.decision.use && tplRec.decision.template ? templatePath(tplRec.decision.template) : undefined;

  let slot: unknown = { skipped: true };
  if (!o.skipSlot && caps.slotSavePath) {
    try {
      const id = modelIdentity(o.modelPath);
      slot = await measureSlotReuse({
        binary: o.binary, slotDir: join(o.home, "slots"), ctx: best.ctx, logPath, log,
        serverArgs: ["--model", o.modelPath, "--ctx-size", String(best.ctx), "--jinja", ...(o.mmprojPath ? ["--mmproj", o.mmprojPath] : []), ...serverArgsFor(best, caps, chatTemplateFile ? { chatTemplateFile } : {})],
        keyParts: { modelPath: o.modelPath, modelSize: id.size, modelMtimeMs: id.mtimeMs, backendVersion: caps.version, kvK: best.kvK, kvV: best.kvV, ctx: best.ctx, templateId: chatTemplateFile ? tplRec.decision.template : null },
      });
      const s = slot as { coldTtftMs: number; restoredTtftMs: number; restoreEffective: boolean; coldPromptN: number | null; restoredPromptN: number | null };
      log(`kv slot reuse: TTFT ${s.coldTtftMs} ms cold -> ${s.restoredTtftMs} ms restored (prompt_n ${s.coldPromptN} -> ${s.restoredPromptN}); effective=${s.restoreEffective}`);
    } catch (e) {
      slot = { error: (e as Error).message };
      log(`kv slot measurement failed: ${(e as Error).message}`);
    } finally { await stopAllLive(); }
  }

  receipt.chatTemplate = tplRec;
  receipt.slotReuse = slot;
  // Re-read: another process may have edited models.json during a long calibration.
  const current: Record<string, unknown> = existsSync(o.cfgPath) ? JSON.parse(readFileSync(o.cfgPath, "utf-8")) : o.cfg;
  if (existsSync(o.cfgPath)) {
    const backup = o.cfgPath + ".bak-" + new Date().toISOString().replace(/[:.]/g, "-");
    copyFileSync(o.cfgPath, backup);
    log(`previous models.json backed up to ${backup}`);
  }
  writeJsonAtomic(o.cfgPath, applyCalibration(current, receipt, caps, chatTemplateFile));
  // Keep the results file's view of the final decision next to the candidates.
  writeJsonAtomic(resultsFile, { ...(JSON.parse(readFileSync(resultsFile, "utf-8")) as object), receipt });
  log(`models.json updated with calibrated serverArgs and calibration receipt (${o.cfgPath})`);
  return 0;
}
