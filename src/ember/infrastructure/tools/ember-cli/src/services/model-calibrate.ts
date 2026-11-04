// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/model-calibrate.ts -- `ember pull --calibrate`: measure a small set
// of llama-server configurations on THIS machine with THIS model, and pick the
// fastest one that still leaves 1 GiB of VRAM free.
//
// What is ported from avir-cli scripts/calibrate-model.ts: the measurement
// discipline -- a per-run salt in the prompt so the prefix cache cannot serve it,
// `cache_prompt: false`, a discarded warm-up, speeds read from the server's own
// counters.  What is NOT ported: avir's R^2 / piecewise latency fit over KV
// depth (that calibrates a perf model for a test registry); here the output is
// a server configuration, so the unit of measurement is a restartable config,
// not a point on a latency curve.
//
// Search (coordinate descent; the context steps down from the model's native
// maximum -- native, 196608, 131072, then the smaller ladder -- and the first
// context with a verified winner is the answer):
//   stage 1  KV type (q4_0 first, then the quality-floor list from llama-backend), with
//            `--spec-type draft-mtp` when the GGUF has an MTP head AND the backend lists it
//            (a candidate that will not load or answer with MTP is retried without it)
//   stage 2  -ub/-b batch sizes for the winning KV pair
//   stage 3  flash attention off, only where it is legal (unquantised f16 KV)
//   verify   the best candidate is re-launched and a needle is recalled from a prompt of
//            ~90% of its context (RECALL_FRACTION); a candidate that fails recall is dropped
//            and the next best is verified.  Skippable (verifyRecall: false / --skip-recall).
//   headroom if nothing leaves the headroom (or passes recall) at this context, step down
// Selection rule (pure, unit-tested): among candidates that load, answer
// coherently, did not fail recall and leave >= 1 GiB free, take the lowest modelled
// turn time (8000 prompt tokens / pp tok/s + 500 generated tokens / tg tok/s);
// candidates within 3% of the best prefer the higher-quality KV type.

import { mkdirSync, writeFileSync, renameSync } from "node:fs";
import { createHash } from "node:crypto";
import { dirname, join } from "node:path";
import { hasMtpHead, type GgufMeta } from "./gguf-meta.ts";
import { QUALITY_FLOOR_ORDER, flashAttnArgs, type BackendCaps, type KvChoice } from "./llama-backend.ts";
import { chat, filler, gpuMemoryUsedBytes, startServer, waitHealthy } from "./llama-harness.ts";

const GiB = 1024 ** 3;
export const HEADROOM_BYTES = 1 * GiB;
/** A representative agent turn: large prompt, short answer. */
export const TURN_PROMPT_TOKENS = 8000;
export const TURN_GEN_TOKENS = 500;
export const TIE_TOLERANCE = 0.03;
const PP_PROBE_TOKENS = 3000;
const TG_PROBE_TOKENS = 128;

export interface Candidate {
  id: string;
  kvK: string;
  kvV: string;
  ctx: number;
  ubatch: number;
  batch: number;
  flashAttn: boolean;
  /** `--spec-type draft-mtp` (only ever set when the GGUF has an MTP head and the backend lists draft-mtp). */
  mtp?: boolean;
}

/** Outcome of the long-context needle check run against a live candidate server. */
export interface RecallResult {
  status: "passed" | "failed";
  ctx: number;
  /** Tokens the server counted in the prompt (null when it could not say). */
  promptTokens: number | null;
  /** promptTokens / ctx. */
  fractionOfCtx: number | null;
  needle: string;
  /** First characters of what the model answered. */
  answer: string;
  seconds: number;
  error?: string;
}

export interface CandidateResult {
  candidate: Candidate;
  ok: boolean;
  /** Why it did not run or failed. */
  error?: string;
  coherent?: boolean;
  ppTps?: number;
  tgTps?: number;
  loadSeconds?: number;
  baselineVramBytes?: number | null;
  peakVramBytes?: number | null;
  /** totalVram - peak. */
  headroomBytes?: number | null;
  /** Modelled seconds for one TURN_PROMPT_TOKENS-in / TURN_GEN_TOKENS-out turn. */
  turnSeconds?: number;
  /** Draft tokens accepted / drafted, when the server reported speculation counters. */
  draftAcceptance?: number | null;
  /** Present only on a run that executed the recall check. */
  recall?: RecallResult;
  at: string;
}

export function candidateId(c: Omit<Candidate, "id">): string {
  return `${c.kvK}-${c.kvV}_ctx${c.ctx}_ub${c.ubatch}_b${c.batch}_fa${c.flashAttn ? "on" : "off"}${c.mtp ? "_mtp" : ""}`;
}

export function makeCandidate(p: Omit<Candidate, "id">): Candidate {
  return { ...p, id: candidateId(p) };
}

/** The models.json `serverArgs` for a candidate (context travels separately as nCtx). */
export function serverArgsFor(c: Candidate, caps: Pick<BackendCaps, "flashAttn"> | null, extra: { chatTemplateFile?: string } = {}): string[] {
  return [
    "-ngl", "999", ...flashAttnArgs(caps, c.flashAttn),
    "-ctk", c.kvK, "-ctv", c.kvV,
    "-ub", String(c.ubatch), "-b", String(c.batch),
    // One slot: the whole context belongs to one conversation, and KV slot save/restore addresses slot 0.
    // (avir registry turboquant_optimizations.parallel: 1)
    "--parallel", "1",
    ...(c.mtp ? ["--spec-type", "draft-mtp"] : []),
    ...(extra.chatTemplateFile ? ["--chat-template-file", extra.chatTemplateFile] : []),
  ];
}

/** MTP is used only when BOTH the GGUF carries an MTP head and the backend's help lists
 * draft-mtp.  A model without the head never gets --spec-type. */
export function mtpAvailable(meta: Pick<GgufMeta, "nextnPredictLayers">, caps: Pick<BackendCaps, "draftMtp"> | null): boolean {
  return hasMtpHead(meta) && caps?.draftMtp === true;
}

/** Native maximum first, then the long-context steps, then the ordinary ladder; nothing
 * above the model's native window.  With no native figure the ordinary ladder is used as is. */
export const LONG_CTX_STEPS = [196608, 131072];
export function ctxLadderFor(native: number | null, base: number[]): number[] {
  if (!native || native <= 0) return [...base];
  const all = [native, ...LONG_CTX_STEPS, ...base].filter((x) => x > 0 && x <= native);
  return [...new Set(all)].sort((a, b) => b - a);
}

export function modelledTurnSeconds(ppTps: number, tgTps: number): number {
  return TURN_PROMPT_TOKENS / ppTps + TURN_GEN_TOKENS / tgTps;
}

export function estimateVramBytes(weightsBytes: number, extraBytes: number, kvBytesPerToken: number, scale: number, ctx: number): number {
  return weightsBytes + extraBytes + kvBytesPerToken * scale * ctx + 0.75 * GiB;
}

function kvRank(c: Candidate): number {
  if (c.kvK === "f16") return -1;
  const i = (QUALITY_FLOOR_ORDER as readonly string[]).indexOf(c.kvK);
  return i < 0 ? 99 : i;
}

export function isFeasible(r: CandidateResult, totalVramBytes: number, headroomBytes = HEADROOM_BYTES): boolean {
  if (!r.ok || r.coherent !== true || !(r.ppTps! > 0) || !(r.tgTps! > 0)) return false;
  if (r.recall?.status === "failed") return false;
  const peak = r.peakVramBytes;
  if (peak === null || peak === undefined) return false; // unmeasured memory cannot prove headroom
  return totalVramBytes - peak >= headroomBytes;
}

/** Pure selection rule.  Returns null when nothing is feasible. */
export function selectBest(results: CandidateResult[], totalVramBytes: number, headroomBytes = HEADROOM_BYTES, tolerance = TIE_TOLERANCE): CandidateResult | null {
  const ok = results.filter((r) => isFeasible(r, totalVramBytes, headroomBytes));
  if (ok.length === 0) return null;
  const t = (r: CandidateResult) => modelledTurnSeconds(r.ppTps!, r.tgTps!);
  const best = Math.min(...ok.map(t));
  const pool = ok.filter((r) => t(r) <= best * (1 + tolerance));
  pool.sort((a, b) => kvRank(a.candidate) - kvRank(b.candidate) || t(a) - t(b) || b.candidate.ctx - a.candidate.ctx);
  return pool[0]!;
}

// ---------------------------------------------------------------------------
// Live measurement of one candidate
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Long-context recall check
// ---------------------------------------------------------------------------

/** The needle sits in a prompt of about this fraction of the candidate's context. */
export const RECALL_FRACTION = 0.9;
/** Prefill of ~240k tokens at ~330 tok/s takes about twelve minutes; leave generous room. */
export const RECALL_TIMEOUT_MS = 60 * 60 * 1000;
const RECALL_SIZING_ROUNDS = 3;

export interface RecallDeps {
  /** Token count of `text` as the candidate server tokenizes it; null when it cannot say. */
  tokenize: (text: string) => Promise<number | null>;
  ask: (prompt: string, maxTokens: number) => Promise<{ ok: boolean; status: number; text: string; reasoning: string; promptTokens: number | null }>;
}

export function needleFor(salt: string): string {
  return "NX-" + createHash("sha256").update(salt).digest("hex").slice(0, 8).toUpperCase();
}

/** Filler prose with the needle sentence in the middle and the question last. */
export function buildNeedlePrompt(tokens: number, salt: string, needle: string): string {
  const half = Math.max(1, Math.floor(tokens / 2));
  return `${filler(half, `${salt}-a`)}\n\nThe secret passphrase for this session is ${needle}. Remember it.\n\n${filler(Math.max(1, tokens - half), `${salt}-b`)}` +
    `\n\nQuestion: what is the secret passphrase for this session? Reply with only the passphrase.`;
}

export async function runRecallCheck(deps: RecallDeps, ctx: number, salt = `recall-${Date.now()}`): Promise<RecallResult> {
  const t0 = Date.now();
  const needle = needleFor(salt);
  const target = Math.floor(ctx * RECALL_FRACTION);
  const maxTokens = Math.max(64, Math.min(1024, ctx - target - 16));
  const fail = (error: string, promptTokens: number | null, answer = ""): RecallResult => ({
    status: "failed", ctx, promptTokens, fractionOfCtx: promptTokens === null ? null : promptTokens / ctx, needle, answer, seconds: (Date.now() - t0) / 1000, error });
  // The filler's tokens-per-word figure is a guess; ask the server's own tokenizer and rescale so the
  // prompt really lands near RECALL_FRACTION of the context.
  let tokens = target;
  let prompt = buildNeedlePrompt(tokens, salt, needle);
  let counted: number | null = null;
  for (let round = 0; round < RECALL_SIZING_ROUNDS; round++) {
    counted = await deps.tokenize(prompt).catch(() => null);
    if (counted === null || counted <= 0) break;
    if (counted >= target * 0.97 && counted <= target * 1.03) break;
    tokens = Math.max(16, Math.round(tokens * (target / counted)));
    prompt = buildNeedlePrompt(tokens, salt, needle);
    counted = null;
  }
  const a = await deps.ask(prompt, maxTokens);
  const promptTokens = a.promptTokens ?? counted;
  if (!a.ok) return fail(`recall request failed: HTTP ${a.status} ${a.text.slice(0, 160)}`, promptTokens);
  const answer = (a.text || a.reasoning).trim();
  const found = (a.text + " " + a.reasoning).includes(needle);
  return {
    status: found ? "passed" : "failed", ctx, promptTokens, fractionOfCtx: promptTokens === null ? null : promptTokens / ctx,
    needle, answer: answer.slice(0, 120), seconds: (Date.now() - t0) / 1000,
    ...(found ? {} : { error: `needle ${needle} not recalled` }),
  };
}

async function liveTokenize(url: string, text: string): Promise<number | null> {
  const res = await fetch(`${url}/tokenize`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ content: text }), signal: AbortSignal.timeout(300_000) }).catch(() => null);
  if (!res || !res.ok) return null;
  const j = (await res.json().catch(() => null)) as { tokens?: unknown[] } | null;
  return Array.isArray(j?.tokens) ? j!.tokens!.length : null;
}

/** The recall check against a running llama-server. */
export function liveRecallCheck(url: string, ctx: number): Promise<RecallResult> {
  return runRecallCheck({
    tokenize: (text) => liveTokenize(url, text),
    ask: async (prompt, maxTokens) => {
      const r = await chat(url, { messages: [{ role: "user", content: prompt }], max_tokens: maxTokens, temperature: 0, cache_prompt: false }, RECALL_TIMEOUT_MS);
      return { ok: r.ok, status: r.status, text: r.text, reasoning: r.reasoning, promptTokens: r.timings.prompt_n ?? null };
    },
  }, ctx);
}

export interface MeasureInput {
  binary: string;
  modelPath: string;
  mmprojPath?: string;
  caps: BackendCaps | null;
  totalVramBytes: number;
  logPath: string;
  chatTemplateFile?: string;
  /** Overrides the live needle check (tests). */
  recallCheck?: (url: string, ctx: number) => Promise<RecallResult>;
  log: (s: string) => void;
}

function median(xs: number[]): number {
  const s = [...xs].sort((a, b) => a - b);
  return s.length % 2 ? s[(s.length - 1) / 2]! : (s[s.length / 2 - 1]! + s[s.length / 2]!) / 2;
}

export async function measureCandidate(inp: MeasureInput, c: Candidate, opts: { recall?: boolean } = {}): Promise<CandidateResult> {
  const at = new Date().toISOString();
  const baseline = gpuMemoryUsedBytes();
  const args = ["--model", inp.modelPath, "--ctx-size", String(c.ctx), "--jinja",
    ...(inp.mmprojPath ? ["--mmproj", inp.mmprojPath] : []), ...serverArgsFor(c, inp.caps, { chatTemplateFile: inp.chatTemplateFile })];
  const srv = await startServer(inp.binary, args, inp.logPath);
  let peak = baseline ?? 0;
  const sample = () => { const u = gpuMemoryUsedBytes(); if (u !== null && u > peak) peak = u; };
  const timer = setInterval(sample, 700);
  const peakOut = () => (baseline === null ? null : peak);
  try {
    const h = await waitHealthy(srv);
    sample();
    if (!h.ok) return { candidate: c, ok: false, error: h.error + ` (see ${inp.logPath})`, baselineVramBytes: baseline, peakVramBytes: peakOut(), at };
    // Warm-up (discarded): first request pays kernel compilation / lazy allocation.
    await chat(srv.url, { messages: [{ role: "user", content: "Say hi." }], max_tokens: 8, temperature: 0, cache_prompt: false });
    sample();
    const coh = await chat(srv.url, { messages: [{ role: "user", content: "What is 17 + 25? Reply with only the number." }], max_tokens: 1024, temperature: 0, cache_prompt: false });
    const coherent = coh.ok && /\b42\b/.test(coh.text + " " + coh.reasoning);
    sample();
    const ppN = Math.min(PP_PROBE_TOKENS, Math.floor(c.ctx / 2));
    const pp: number[] = []; const tg: number[] = []; const drafted: number[] = []; const accepted: number[] = [];
    for (let run = 0; run < 2; run++) {
      const r = await chat(srv.url, {
        messages: [{ role: "user", content: `${filler(ppN, `cal-${c.id}-${run}-${Date.now()}`)}\n\nWrite one sentence about the words above.` }],
        max_tokens: TG_PROBE_TOKENS, temperature: 0, cache_prompt: false, ignore_eos: true,
      });
      sample();
      if (!r.ok) return { candidate: c, ok: false, error: `measurement request failed: HTTP ${r.status} ${r.text.slice(0, 120)}`, baselineVramBytes: baseline, peakVramBytes: peakOut(), at };
      // A rate read from a handful of tokens is noise (a rejected turbo3 run once reported 500,056 tok/s).
      if ((r.timings.predicted_n ?? 0) < 0.9 * TG_PROBE_TOKENS) {
        return { candidate: c, ok: false, error: `generation too short to time: ${r.timings.predicted_n ?? 0} of ${TG_PROBE_TOKENS} tokens`, baselineVramBytes: baseline, peakVramBytes: peakOut(), at };
      }
      if ((r.timings.prompt_per_second ?? 0) > 0) pp.push(r.timings.prompt_per_second!);
      if ((r.timings.predicted_per_second ?? 0) > 0) tg.push(r.timings.predicted_per_second!);
      if ((r.timings.draft_n ?? 0) > 0) { drafted.push(r.timings.draft_n!); accepted.push(r.timings.draft_n_accepted ?? 0); }
    }
    sample();
    if (pp.length === 0 || tg.length === 0) return { candidate: c, ok: false, error: "server returned no timings", baselineVramBytes: baseline, peakVramBytes: peakOut(), at };
    const ppTps = median(pp); const tgTps = median(tg);
    const draftN = drafted.reduce((a, b) => a + b, 0);
    const draftAcceptance = draftN > 0 ? accepted.reduce((a, b) => a + b, 0) / draftN : null;
    let recall: RecallResult | undefined;
    if (opts.recall && coherent) {
      inp.log(`calibrate: ${c.id} recall check (needle in a ~${Math.round(RECALL_FRACTION * 100)}% context prompt) ...`);
      recall = await (inp.recallCheck ?? liveRecallCheck)(srv.url, c.ctx).catch((e: Error): RecallResult => ({
        status: "failed", ctx: c.ctx, promptTokens: null, fractionOfCtx: null, needle: "", answer: "", seconds: 0, error: `recall check threw: ${e.message}` }));
      sample();
    }
    const peakB = peakOut();
    return { candidate: c, ok: true, draftAcceptance, ...(recall ? { recall } : {}), coherent, ppTps, tgTps, loadSeconds: h.seconds, baselineVramBytes: baseline, peakVramBytes: peakB,
      headroomBytes: peakB === null ? null : inp.totalVramBytes - peakB, turnSeconds: modelledTurnSeconds(ppTps, tgTps), at,
      ...(coherent ? {} : { error: `incoherent answer to 17+25: ${JSON.stringify((coh.text || coh.reasoning).slice(0, 80))}` }) };
  } finally {
    clearInterval(timer);
    await srv.stop();
  }
}

// ---------------------------------------------------------------------------
// The search
// ---------------------------------------------------------------------------

export interface CalibrateInput {
  caps: BackendCaps | null;
  kvChoices: KvChoice[];
  weightsBytes: number;
  extraBytes: number;
  kvBytesPerToken: number;
  startCtx: number;
  ctxLadder: number[];
  totalVramBytes: number;
  /** Measures one candidate (`recall: true` also runs the needle check); the live implementation is measureCandidate. */
  run: (c: Candidate, opts?: { recall?: boolean }) => Promise<CandidateResult>;
  log: (s: string) => void;
  /** Also try flash attention off (legal only with unquantised f16 KV). */
  tryFlashOff?: boolean;
  /** Launch candidates with `--spec-type draft-mtp`: set only when mtpAvailable(meta, caps). */
  mtp?: boolean;
  /** Gate the winner of each context on the long-context recall check (default off here; optimizeModel turns it on). */
  verifyRecall?: boolean;
  /** VRAM that must stay free (default HEADROOM_BYTES = 1 GiB). */
  headroomBytes?: number;
  /** How many contexts to actually launch servers at, largest first (default 6).  A context whose every
   * candidate is skipped by the VRAM estimate costs no launch and does not count, so a small card walks
   * past the contexts it cannot hold. */
  maxCtxSteps?: number;
}

export interface CalibrationOutcome {
  selected: CandidateResult | null;
  results: CandidateResult[];
  rule: string;
  /** The VRAM headroom the search required (default HEADROOM_BYTES). */
  headroomRequiredBytes?: number;
}

export function selectionRule(headroomBytes = HEADROOM_BYTES): string {
  const h = headroomBytes >= GiB ? `${headroomBytes / GiB} GiB` : `${Math.round(headroomBytes / 1024 ** 2)} MiB`;
  return `largest context that has a winner (native maximum first); fastest modelled turn (${TURN_PROMPT_TOKENS} prompt tokens / pp + ${TURN_GEN_TOKENS} generated tokens / tg) among candidates that load, ` +
    `answer coherently, recall a needle from a ~${RECALL_FRACTION * 100}% context prompt (unless skipped) and leave >= ${h} VRAM free; within ${TIE_TOLERANCE * 100}% prefer higher-quality KV type. ` +
    `A candidate that fails only on headroom is retried with smaller -ub (${HEADROOM_UBATCH_FALLBACKS.join(", ")}) before the context steps down.`;
}

/** Smaller physical batch sizes tried for a candidate whose only defect is headroom: -ub sizes the compute buffer. */
export const HEADROOM_UBATCH_FALLBACKS = [512, 256];

export const SELECTION_RULE = selectionRule();

/** Loaded, coherent, timed -- and rejected for nothing but VRAM headroom. */
export function failsOnlyOnHeadroom(r: CandidateResult, totalVramBytes: number, headroomBytes: number): boolean {
  if (!r.ok || r.coherent !== true || !(r.ppTps! > 0) || !(r.tgTps! > 0) || r.recall?.status === "failed") return false;
  const peak = r.peakVramBytes;
  return peak !== null && peak !== undefined && totalVramBytes - peak < headroomBytes;
}

/** Recall verifications spent on one context before stepping down. */
const MAX_RECALL_VERIFICATIONS = 3;

/** Later results for the same candidate id supersede earlier ones (a recall re-run replaces its first measurement). */
function latestById(rs: CandidateResult[]): CandidateResult[] {
  const m = new Map<string, CandidateResult>();
  for (const r of rs) m.set(r.candidate.id, r);
  return [...m.values()];
}

export async function searchConfigs(inp: CalibrateInput): Promise<CalibrationOutcome> {
  const results: CandidateResult[] = [];
  const total = inp.totalVramBytes;
  const H = inp.headroomBytes ?? HEADROOM_BYTES;
  const pick = (rs: CandidateResult[]) => selectBest(rs, total, H);
  const exec = async (c: Candidate, o: { recall?: boolean } = {}): Promise<CandidateResult> => {
    inp.log(`calibrate: ${c.id}${o.recall ? " (with recall check)" : ""} ...`);
    const r = await inp.run(c, o).catch((e: Error): CandidateResult => ({ candidate: c, ok: false, error: `measurement threw: ${e.message}`, at: new Date().toISOString() }));
    results.push(r);
    launches++;
    const rejected = !isFeasible(r, total, H)
      ? " (REJECTED: " + (r.recall?.status === "failed" ? "recall" : r.coherent ? "headroom" : "incoherent") + ")" : "";
    inp.log(r.ok
      ? `calibrate: ${c.id} -> pp ${r.ppTps!.toFixed(0)} tok/s, tg ${r.tgTps!.toFixed(1)} tok/s, peak ${((r.peakVramBytes ?? 0) / GiB).toFixed(1)} GiB, ` +
        `coherent ${r.coherent}${r.recall ? `, recall ${r.recall.status}` : ""}${rejected}`
      : `calibrate: ${c.id} -> FAILED: ${r.error}`);
    return r;
  };
  const skip = (c: Candidate, error: string) => results.push({ candidate: c, ok: false, error, at: new Date().toISOString() });
  const mtpOn = inp.mtp === true;
  const withMtp = (on: boolean): { mtp?: boolean } => (on ? { mtp: true } : {});

  const ctxSteps = [inp.startCtx, ...inp.ctxLadder.filter((x) => x < inp.startCtx)];
  let selected: CandidateResult | null = null;
  let launches = 0, launchesAtLastStep = 0, launchedSteps = 0;
  for (const ctx of ctxSteps) {
    if (launches > launchesAtLastStep) { launchedSteps++; launchesAtLastStep = launches; }
    if (launchedSteps >= (inp.maxCtxSteps ?? 6)) break;
    const before = results.length;
    const step = () => latestById(results.slice(before));
    // stage 1: KV types
    for (const kv of inp.kvChoices) {
      const c = makeCandidate({ kvK: kv.k, kvV: kv.v, ctx, ubatch: 512, batch: 2048, flashAttn: true, ...withMtp(mtpOn) });
      const need = estimateVramBytes(inp.weightsBytes, inp.extraBytes, inp.kvBytesPerToken, kv.scale, ctx);
      if (need > total - H) { skip(c, `estimated ${(need / GiB).toFixed(1)} GiB exceeds budget (${((total - H) / GiB).toFixed(1)} GiB)`); continue; }
      const r = await exec(c);
      if (mtpOn && (!r.ok || r.coherent !== true)) {
        inp.log(`calibrate: ${c.id} did not load or answer coherently with draft-mtp; trying the same KV without it`);
        await exec(makeCandidate({ ...c, mtp: undefined }));
      }
    }
    // A candidate whose only defect is headroom may fit with a smaller compute buffer (-ub): retry it
    // before giving the context up.  Siblings of the same KV pair share the verdict, so one retry chain each.
    for (const hr of step().filter((r) => failsOnlyOnHeadroom(r, total, H))) {
      for (const ub of HEADROOM_UBATCH_FALLBACKS) {
        if (ub >= hr.candidate.ubatch) continue;
        const retry = await exec(makeCandidate({ ...hr.candidate, ubatch: ub, batch: Math.max(2048, ub) }));
        if (isFeasible(retry, total, H)) break;
        if (!failsOnlyOnHeadroom(retry, total, H)) break;
      }
    }
    const stage1 = pick(step());
    if (!stage1) { inp.log(`calibrate: nothing feasible at context ${ctx}; stepping down`); continue; }
    // stage 2: batch sizes for the winning KV pair
    const w = stage1.candidate;
    // (larger batches are not tried for a winner that only fit with a reduced -ub: they would take the headroom back)
    if (w.ubatch >= 512) {
      for (const ub of [1024, 2048]) {
        await exec(makeCandidate({ ...w, ubatch: ub, batch: Math.max(2048, ub) }));
      }
    }
    const stage2 = pick(step())!;
    // stage 3: flash attention off, legal only for unquantised KV
    const fa = stage2.candidate;
    if (inp.tryFlashOff && fa.kvK === "f16" && inp.caps?.flashAttn !== "none") {
      await exec(makeCandidate({ ...fa, flashAttn: false }));
    } else {
      skip(makeCandidate({ ...fa, flashAttn: false }),
        fa.kvK === "f16" ? "flash attention off not requested" : "flash attention off is only valid for unquantised f16 KV (quantised V cache requires it)");
    }
    // verify: the best candidate must recall a needle from a ~90% context prompt; one that fails is dropped
    // and the next best is verified, a bounded number of times, before the context is given up.
    let winner: CandidateResult | null = null;
    if (!inp.verifyRecall) {
      winner = pick(step());
    } else {
      // Recall is a property of the KV type, context and speculation mode, not of the batch sizes: a
      // verification covers every sibling of the same config, pass or fail, so siblings cost nothing.
      const failedConfigs = new Set<string>();
      const passedConfigs = new Map<string, RecallResult>();
      const configOf = (c: Candidate) => `${c.kvK}/${c.kvV}/${c.mtp ? "mtp" : "plain"}`;
      const live = () => step().filter((r) => !failedConfigs.has(configOf(r.candidate)));
      for (let verified = 0; ;) {
        const best = pick(live());
        if (!best) break;
        const passed = passedConfigs.get(configOf(best.candidate));
        if (passed) { winner = { ...best, recall: best.recall ?? passed }; break; }
        if (verified >= MAX_RECALL_VERIFICATIONS) break;
        verified++;
        const v = await exec(best.candidate, { recall: true });
        if (v.recall?.status === "passed") passedConfigs.set(configOf(v.candidate), v.recall);
        else if (v.recall?.status === "failed") failedConfigs.add(configOf(v.candidate));
        // a re-run that no longer loads or answers is infeasible and drops out of live() on its own
      }
      if (!winner) inp.log(`calibrate: no candidate at context ${ctx} passed the recall check; stepping down`);
    }
    if (winner) { selected = winner; break; }
  }
  return { selected, results, rule: selectionRule(H), headroomRequiredBytes: H };
}

// ---------------------------------------------------------------------------
// Persistence
// ---------------------------------------------------------------------------

export function calibrationPath(home: string, modelName: string): string {
  return join(home, "calibration", modelName.replace(/[^A-Za-z0-9._-]+/g, "_") + ".json");
}

export function writeJsonAtomic(path: string, value: unknown): void {
  mkdirSync(dirname(path), { recursive: true });
  const tmp = path + ".tmp";
  writeFileSync(tmp, JSON.stringify(value, null, 2) + "\n");
  renameSync(tmp, path);
}

export interface CalibrationReceipt {
  at: string;
  backendVersion: string | null;
  turboAvailable: boolean;
  rule: string;
  selected: { id: string; kvK: string; kvV: string; ctx: number; ubatch: number; batch: number; flashAttn: boolean; mtp: boolean };
  /** `--spec-type` recorded for the managed spawn: "draft-mtp" or null (never set for a model without an MTP head). */
  specType: "draft-mtp" | null;
  /** Draft tokens accepted / drafted during the speed probe; null when not reported. */
  draftAcceptance: number | null;
  /** The long-context needle check on the selected candidate; "skipped" when it was not run. */
  recall: RecallResult | { status: "skipped" };
  ppTokensPerSecond: number;
  tgTokensPerSecond: number;
  peakVramBytes: number | null;
  baselineVramBytes: number | null;
  totalVramBytes: number;
  headroomBytes: number | null;
  /** The headroom the search required of every candidate. */
  headroomRequiredBytes: number;
  candidatesTried: number;
  candidatesFeasible: number;
  resultsFile: string;
  chatTemplate?: unknown;
  slotReuse?: unknown;
}

export function buildReceipt(outcome: CalibrationOutcome, caps: BackendCaps | null, totalVramBytes: number, resultsFile: string, at = new Date().toISOString()): CalibrationReceipt | null {
  const s = outcome.selected;
  if (!s) return null;
  const c = s.candidate;
  return {
    at, backendVersion: caps?.version ?? null, turboAvailable: (caps?.turboTypes.length ?? 0) > 0, rule: outcome.rule,
    selected: { id: c.id, kvK: c.kvK, kvV: c.kvV, ctx: c.ctx, ubatch: c.ubatch, batch: c.batch, flashAttn: c.flashAttn, mtp: c.mtp === true },
    specType: c.mtp ? "draft-mtp" : null, draftAcceptance: s.draftAcceptance ?? null, recall: s.recall ?? { status: "skipped" },
    ppTokensPerSecond: s.ppTps!, tgTokensPerSecond: s.tgTps!, peakVramBytes: s.peakVramBytes ?? null, baselineVramBytes: s.baselineVramBytes ?? null,
    totalVramBytes, headroomBytes: s.headroomBytes ?? null, headroomRequiredBytes: outcome.headroomRequiredBytes ?? HEADROOM_BYTES,
    candidatesTried: outcome.results.filter((r) => r.ok).length,
    candidatesFeasible: outcome.results.filter((r) => isFeasible(r, totalVramBytes, outcome.headroomRequiredBytes ?? HEADROOM_BYTES)).length,
    resultsFile,
  };
}

/** Next models.json after calibration: serverArgs + nCtx from the winner, receipt attached. */
export function applyCalibration(cfg: Record<string, unknown>, receipt: CalibrationReceipt, caps: BackendCaps | null, chatTemplateFile?: string): Record<string, unknown> {
  const s = receipt.selected;
  const c: Candidate = { id: s.id, kvK: s.kvK, kvV: s.kvV, ctx: s.ctx, ubatch: s.ubatch, batch: s.batch, flashAttn: s.flashAttn, ...(s.mtp ? { mtp: true } : {}) };
  return {
    ...cfg,
    nCtx: s.ctx,
    maxOutputTokens: Math.min(8192, Math.floor(s.ctx / 4)),
    serverArgs: serverArgsFor(c, caps, { chatTemplateFile }),
    calibration: receipt,
  };
}
