// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/model-pull.ts -- `ember pull`: fetch an open-weights GGUF model that
// fits this machine, verify it, prove it loads, and select it as the
// OPEN_WEIGHTS seat in models.json.
//
// Safety model (why "automatic" is still safe):
//   - Only GGUF files are fetched. GGUF is a tensor container with no
//     executable payload (unlike pickle checkpoints), and llama-server only
//     reads it.
//   - Only repositories whose owner is on TRUSTED_OWNERS are fetched unless
//     the operator passes --trust-repo for that exact repo.
//   - Every download is checked against the sha256 Hugging Face publishes for
//     the LFS object, before it is renamed into place.
//   - Selection is deterministic: a fixed preference list, filtered by a fit
//     rule against measured VRAM and free disk. Nothing is random.
//   - models.json is written only AFTER a live llama-server load + completion
//     succeeds with the chosen settings (acceptance of a setting is not proof
//     that it runs), and the previous models.json is backed up first.

import { classifyLoadFailure, fetchLlamaRuntime, findInstalledRuntime, RUNTIME_REPO, type LoadFailureClass } from "./runtime-fetch.ts";
import { createHash } from "node:crypto";
import { createWriteStream, existsSync, statSync, statfsSync, renameSync, readFileSync, writeFileSync, copyFileSync, mkdirSync, openSync, closeSync } from "node:fs";
import { spawn, spawnSync } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { totalmem } from "node:os";
import { getEmberConfigHomeDir } from "../utils/env-detection.ts";
import { flashAttnArgs, kvChoicesFor, probeBackend, type BackendCaps, type KvChoice } from "./llama-backend.ts";
import { optimizeModel } from "./model-optimize.ts";
import { freePort, writeKillReceipt } from "./llama-harness.ts";
import { readGgufMeta } from "./gguf-meta.ts";
import type { FixedTemplate } from "./chat-template-decision.ts";

export const TRUSTED_OWNERS = ["Qwen", "unsloth", "bartowski", "ggml-org", "lmstudio-community", "google", "mistralai"];

/** Preference order: strongest agentic/coding models first. kvBytesPerToken is
 * an fp16 KV-cache estimate (layers * kv_heads * head_dim * 2 tensors * 2 bytes);
 * the live load test, not this estimate, is the final word on fit. */
export interface CatalogEntry {
  repo: string;
  name: string;
  kvBytesPerToken: number;
  /** quant tags in preference order (best quality first) */
  quants: string[];
  note: string;
  /** Repo ships a vision projector (mmproj): screenshots/images become readable. */
  vision?: boolean;
  /** Native context window of the model; caps how far spare KV memory may stretch the context. */
  nativeCtx?: number;
}

export const CATALOG: CatalogEntry[] = [
  // Hybrid attention (qwen35 arch): only the full-attention layers (16 of 64)
  // keep a KV cache, so long contexts are cheap; KV heads 4 x head_dim 256.
  { repo: "unsloth/Qwen3.8-27B-GGUF", name: "qwen3.8-27b",
    kvBytesPerToken: 16 * 4 * 256 * 2 * 2, quants: ["UD-Q5_K_XL", "UD-Q5_K_M", "UD-Q4_K_XL", "UD-Q4_K_M", "UD-IQ4_XS", "UD-Q3_K_XL"],
    note: "dense 27B class, current Qwen generation; strong tool calling; vision via mmproj", vision: true,
    nativeCtx: 262144 /* avir-cli tests/gpu/registry/qwen3.6-27b.yml native_ctx */ },
  { repo: "unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF", name: "qwen3-coder-30b-a3b-instruct",
    kvBytesPerToken: 48 * 4 * 128 * 2 * 2, quants: ["Q5_K_M", "UD-Q4_K_XL", "Q4_K_M", "Q4_K_S", "IQ4_XS", "Q3_K_M"],
    note: "MoE, 3B active: fast on one GPU; trained for agentic coding and tool calls", nativeCtx: 262144 },
  { repo: "unsloth/Qwen3-30B-A3B-Instruct-2507-GGUF", name: "qwen3-30b-a3b-instruct-2507",
    kvBytesPerToken: 48 * 4 * 128 * 2 * 2, quants: ["Q5_K_M", "UD-Q4_K_XL", "Q4_K_M", "Q4_K_S", "IQ4_XS", "Q3_K_M"],
    note: "general MoE instruct model", nativeCtx: 262144 },
  { repo: "Qwen/Qwen3-14B-GGUF", name: "qwen3-14b",
    kvBytesPerToken: 40 * 8 * 128 * 2 * 2, quants: ["Q8_0", "Q6_K", "Q5_K_M", "Q4_K_M"],
    note: "dense 14B" },
  { repo: "Qwen/Qwen3-8B-GGUF", name: "qwen3-8b",
    kvBytesPerToken: 36 * 8 * 128 * 2 * 2, quants: ["Q8_0", "Q6_K", "Q5_K_M", "Q4_K_M"],
    note: "dense 8B" },
  { repo: "unsloth/Qwen3-4B-Instruct-2507-GGUF", name: "qwen3-4b-instruct-2507",
    kvBytesPerToken: 36 * 8 * 128 * 2 * 2, quants: ["Q8_0", "Q6_K", "Q4_K_M"],
    note: "small fallback for low-VRAM or CPU machines", nativeCtx: 262144 },
];

const GiB = 1024 ** 3;
const CTX_LADDER = [65536, 49152, 32768, 24576, 16384, 8192];
const MIN_CTX = 8192;
/** KV cache stored as q8_0 (`-ctk q8_0 -ctv q8_0`, needs flash attention) is
 * about half the fp16 size the catalog estimates. */
const KV_SCALE_Q8 = 0.53;
/** VRAM kept free for the desktop, driver and compute buffers. */
const VRAM_RESERVE_BYTES = 2.0 * GiB;
/** Disk kept free beyond the download itself. */
const DISK_RESERVE_BYTES = 10 * GiB;

export interface DeviceSpecs {
  gpuName: string | null;
  vramTotalBytes: number;
  vramFreeBytes: number;
  ramBytes: number;
}

export function detectDevice(): DeviceSpecs {
  const ramBytes = totalmem();
  const r = spawnSync("nvidia-smi", ["--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"], { encoding: "utf-8" });
  if (r.status === 0 && r.stdout.trim()) {
    const [name, total, free] = r.stdout.trim().split("\n")[0]!.split(",").map((x) => x.trim());
    return { gpuName: name ?? null, vramTotalBytes: Number(total) * 1024 ** 2, vramFreeBytes: Number(free) * 1024 ** 2, ramBytes };
  }
  return { gpuName: null, vramTotalBytes: 0, vramFreeBytes: 0, ramBytes };
}

export interface RepoFile { path: string; size: number; sha256: string | null }

export async function listRepoGguf(repo: string, fetchFn: typeof fetch = fetch): Promise<RepoFile[]> {
  const res = await fetchFn(`https://huggingface.co/api/models/${repo}/tree/main`);
  if (!res.ok) throw new Error(`Hugging Face listing for ${repo} failed: HTTP ${res.status}`);
  const rows = (await res.json()) as Array<{ path: string; size?: number; lfs?: { oid?: string; size?: number } }>;
  return rows
    .filter((r) => r.path.toLowerCase().endsWith(".gguf"))
    .map((r) => ({ path: r.path, size: r.lfs?.size ?? r.size ?? 0, sha256: r.lfs?.oid ?? null }));
}

/** The vision projector to pair with a model: F16 preferred, then BF16, then any. */
export function mmprojFile(files: RepoFile[]): RepoFile | undefined {
  const mm = files.filter((f) => /mmproj/i.test(f.path));
  return mm.find((f) => /f16/i.test(f.path) && !/bf16/i.test(f.path)) ?? mm.find((f) => /bf16/i.test(f.path)) ?? mm[0];
}

export function fileForQuant(files: RepoFile[], quant: string): RepoFile | undefined {
  const tag = quant.toLowerCase();
  files = files.filter((f) => !/mmproj/i.test(f.path));
  // Single-file quants only; split shards (-00001-of-0000N) are skipped.
  return files.find((f) => !/-\d{5}-of-\d{5}/.test(f.path) &&
    f.path.toLowerCase().replace(/\.gguf$/, "").endsWith("-" + tag));
}

export interface Plan {
  entry: CatalogEntry;
  file: RepoFile;
  nCtx: number;
  estimatedVramBytes: number;
  mmproj?: RepoFile;
  /** KV cache types the context was sized against. */
  kv: KvChoice;
}

/** Deterministic fit rule: the first catalog entry, best quant, and largest
 * context whose weights + KV + compute buffers fit in the VRAM budget. */

/** Budget = the smaller of (total - reserve) and (currently free - 0.5 GiB),
 * so a model is never sized against memory another process already holds. */
export function vramBudget(dev: DeviceSpecs): number {
  if (dev.vramTotalBytes === 0) return 6 * GiB;
  return Math.min(dev.vramTotalBytes - VRAM_RESERVE_BYTES, dev.vramFreeBytes - 0.5 * GiB);
}

/** Contexts beyond the usable ladder that spare KV memory may buy, capped by the
 * model's native window.  avir README: turbo3 holds 128K on a 24 GB card where
 * q8_0 runs out of memory above ~65K. */
export const CTX_EXTENSION = [131072, 98304];

export interface PlanOptions {
  /** Stretch the context past CTX_LADDER's top when KV memory is left over (needs entry.nativeCtx). */
  stretch?: boolean;
}

/** Fit rule over a quality-ordered list of KV cache types.  Order of preference:
 * largest context on the ladder, then best quant, then best KV type that fits --
 * so a turbo KV type is chosen only when it is what makes a context or quant fit.
 * With `stretch`, leftover memory then extends the context (never past the model's
 * native window), which is what turbo KV buys on a model that already fits at q8_0. */
export function choosePlanKv(entry: CatalogEntry, files: RepoFile[], budget: number, kvChoices: KvChoice[], opts: PlanOptions = {}): Plan | null {
  // Context outranks quant quality: an agent harness's system prompt and tool
  // schemas alone are tens of thousands of tokens, so the best quant that
  // reaches a usable context wins over a better quant at a cramped one.
  const needFor = (file: RepoFile, mm: RepoFile | undefined, kv: KvChoice, nCtx: number) =>
    file.size + (mm?.size ?? 0) + entry.kvBytesPerToken * kv.scale * nCtx + 0.75 * GiB;
  for (const nCtx of CTX_LADDER) {
    for (const quant of entry.quants) {
      const file = fileForQuant(files, quant);
      if (!file || file.size <= 0) continue;
      const mm = entry.vision ? mmprojFile(files) : undefined;
      for (const kv of kvChoices) {
        if (needFor(file, mm, kv, nCtx) > budget) continue;
        let best = nCtx;
        if (opts.stretch && entry.nativeCtx) {
          for (const ext of CTX_EXTENSION) {
            if (ext > best && ext <= entry.nativeCtx && needFor(file, mm, kv, ext) <= budget) { best = ext; break; }
          }
        }
        return { entry, file, nCtx: best, estimatedVramBytes: needFor(file, mm, kv, best), kv, ...(mm ? { mmproj: mm } : {}) };
      }
    }
  }
  return null;
}

export function choosePlan(entry: CatalogEntry, files: RepoFile[], budget: number, kvScale = KV_SCALE_Q8): Plan | null {
  return choosePlanKv(entry, files, budget, [{ k: "q8_0", v: "q8_0", scale: kvScale, evidence: "legacy single-type fit" }]);
}

/** Free bytes on the volume that holds `dir` (or would hold it): measured at the nearest existing
 * parent, so planning a download never creates the target directory. */
export function freeDiskBytes(dir: string): number {
  let probe = resolve(dir);
  while (!existsSync(probe)) {
    const up = dirname(probe);
    if (up === probe) break;
    probe = up;
  }
  const s = statfsSync(probe);
  return Number(s.bavail) * Number(s.bsize);
}

async function sha256File(path: string): Promise<string> {
  const hash = createHash("sha256");
  const file = Bun.file(path);
  const reader = file.stream().getReader();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    hash.update(value);
  }
  return hash.digest("hex");
}

export async function download(repo: string, file: RepoFile, destDir: string, log: (s: string) => void): Promise<string> {
  mkdirSync(destDir, { recursive: true });
  const finalPath = join(destDir, file.path.split("/").pop()!);
  if (existsSync(finalPath) && statSync(finalPath).size === file.size) {
    log(`already present: ${finalPath} (verifying sha256)`);
    if (file.sha256 && (await sha256File(finalPath)) !== file.sha256) throw new Error(`sha256 mismatch on existing ${finalPath}`);
    return finalPath;
  }
  const part = finalPath + ".part";
  const have = existsSync(part) ? statSync(part).size : 0;
  const url = `https://huggingface.co/${repo}/resolve/main/${encodeURI(file.path)}`;
  const res = await fetch(url, { headers: have > 0 ? { Range: `bytes=${have}-` } : {}, redirect: "follow" });
  if (!(res.ok || res.status === 206)) throw new Error(`download failed: HTTP ${res.status} for ${url}`);
  const append = have > 0 && res.status === 206;
  const out = createWriteStream(part, { flags: append ? "a" : "w" });
  let done = append ? have : 0;
  let lastPct = -1;
  const reader = res.body!.getReader();
  for (;;) {
    const { done: end, value } = await reader.read();
    if (end) break;
    if (!out.write(value)) await new Promise((r) => out.once("drain", r));
    done += value.byteLength;
    const pct = Math.floor((done / file.size) * 100);
    if (pct !== lastPct && pct % 5 === 0) { lastPct = pct; log(`downloading ${file.path}: ${pct}% (${(done / GiB).toFixed(2)} / ${(file.size / GiB).toFixed(2)} GiB)`); }
  }
  await new Promise<void>((r, j) => out.end((e?: Error | null) => (e ? j(e) : r())));
  if (statSync(part).size !== file.size) throw new Error(`size mismatch: got ${statSync(part).size}, expected ${file.size}; rerun to resume`);
  if (file.sha256) {
    log("verifying sha256 ...");
    const got = await sha256File(part);
    if (got !== file.sha256) throw new Error(`sha256 mismatch: got ${got}, expected ${file.sha256}; the partial file was kept at ${part}`);
  } else {
    log("WARNING: Hugging Face published no sha256 for this file; size check only");
  }
  renameSync(part, finalPath);
  return finalPath;
}

export function findLlamaServer(cfgBinary: string | undefined): string | null {
  const candidates = [process.env["EMBER_LLAMA_SERVER"], cfgBinary].filter((x): x is string => !!x);
  for (const c of candidates) if (existsSync(c)) return resolve(c);
  const which = spawnSync(process.platform === "win32" ? "where" : "which", ["llama-server"], { encoding: "utf-8" });
  if (which.status === 0 && which.stdout.trim()) return which.stdout.trim().split(/\r?\n/)[0]!;
  return null;
}

export interface EnsureServerOptions {
  cfgBinary: string | undefined;
  /** EMBER_HOME; a fetched runtime lives under `<home>/runtime`. */
  home: string;
  /** Planning only: nothing is downloaded, so a missing server is reported and planning goes on without one. */
  dryRun: boolean;
  noRuntimeUpdate: boolean;
  log: (s: string) => void;
  /** Test seams. */
  find?: (cfgBinary: string | undefined) => string | null;
  findInstalled?: (root: string) => string | null;
  fetchRuntime?: typeof fetchLlamaRuntime;
  platform?: NodeJS.Platform;
}

/** Resolve the llama-server to use.  Order: EMBER_LLAMA_SERVER, models.json "binary", PATH, a runtime
 * this tool fetched earlier, then (Windows, unless --no-runtime-update, never in a dry run) a fresh
 * official ggml-org/llama.cpp build.  `binary: null` with no `code` means "dry run, none yet". */
export async function ensureLlamaServer(o: EnsureServerOptions): Promise<{ binary: string | null; code?: number }> {
  const found = (o.find ?? findLlamaServer)(o.cfgBinary);
  if (found) return { binary: found };
  const runtimeRoot = join(o.home, "runtime");
  const installed = (o.findInstalled ?? findInstalledRuntime)(runtimeRoot);
  if (installed) { o.log(`using the llama.cpp runtime fetched earlier: ${installed}`); return { binary: installed }; }
  const canFetch = (o.platform ?? process.platform) === "win32" && !o.noRuntimeUpdate;
  const manual = "set EMBER_LLAMA_SERVER to a llama-server executable, put llama-server on PATH, or set \"binary\" in models.json";
  if (o.dryRun) {
    o.log(canFetch
      ? `no llama-server found yet: a real \`ember pull\` will fetch the official ${RUNTIME_REPO} build (about 0.6 GB) into ${runtimeRoot}; planning with stock llama.cpp KV types (q8_0)`
      : `no llama-server found: ${manual}; planning with stock llama.cpp KV types (q8_0)`);
    return { binary: null };
  }
  if (!canFetch) {
    o.log(`no llama-server found: ${manual}` + ((o.platform ?? process.platform) === "win32" ? " (or drop --no-runtime-update so ember can fetch the official build)" : ""));
    return { binary: null, code: 2 };
  }
  o.log(`no llama-server found: fetching the official ${RUNTIME_REPO} build into ${runtimeRoot} (about 0.6 GB, sha256-verified)`);
  try {
    return { binary: await (o.fetchRuntime ?? fetchLlamaRuntime)(runtimeRoot, o.log) };
  } catch (e) {
    o.log(`could not fetch llama.cpp: ${(e as Error).message}. Fix the cause (network, NVIDIA driver) and re-run, or ${manual}.`);
    return { binary: null, code: 2 };
  }
}

/** Live proof: start llama-server with the chosen settings, wait for /health,
 * request one completion, then stop it.  Returns null on success or the error. */
export async function smokeTest(binary: string, modelPath: string, nCtx: number, serverArgs: string[], port: number, logPath: string, log: (s: string) => void, mmprojPath?: string, opts: { requireCoherent?: boolean } = {}): Promise<string | null> {
  const fd = openSync(logPath, "a");
  const child = spawn(binary, ["--model", modelPath, "--port", String(port), "--ctx-size", String(nCtx), "--jinja", ...(mmprojPath ? ["--mmproj", mmprojPath] : []), ...serverArgs],
    { stdio: ["ignore", "ignore", fd], detached: false });
  const stop = () => {
    if (child.pid) writeKillReceipt(child.pid, "smoke-test server started by this process (child handle)");
    try { child.kill(); } catch { /* already gone */ }
  };
  let exited = false;
  child.on("exit", () => { exited = true; });
  try {
    const deadline = Date.now() + 240_000;
    for (;;) {
      if (exited) return `llama-server exited during load (see ${logPath})`;
      if (Date.now() > deadline) return "llama-server did not become healthy within 240 s";
      try {
        const h = await fetch(`http://127.0.0.1:${port}/health`);
        if (h.ok) break;
      } catch { /* not up yet */ }
      await Bun.sleep(1000);
    }
    log("model loaded; requesting one completion ...");
    const t0 = Date.now();
    const r = await fetch(`http://127.0.0.1:${port}/v1/chat/completions`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ messages: [{ role: "user", content: "Reply with the single word: ready" }], max_tokens: 16, temperature: 0 }),
    });
    if (!r.ok) return `completion failed: HTTP ${r.status}`;
    const j = (await r.json()) as { choices?: Array<{ message?: { content?: string } }>; timings?: { predicted_per_second?: number } };
    const text = j.choices?.[0]?.message?.content ?? "";
    log(`completion ok in ${Date.now() - t0} ms: ${JSON.stringify(text.slice(0, 60))}` +
      (j.timings?.predicted_per_second ? ` (${j.timings.predicted_per_second.toFixed(1)} tok/s)` : ""));
    if (opts.requireCoherent) {
      const q = await fetch(`http://127.0.0.1:${port}/v1/chat/completions`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ messages: [{ role: "user", content: "What is 17 + 25? Reply with only the number." }], max_tokens: 1024, temperature: 0 }),
      });
      const qj = (await q.json().catch(() => null)) as { choices?: Array<{ message?: { content?: string; reasoning_content?: string } }> } | null;
      const m = qj?.choices?.[0]?.message;
      const answer = `${m?.content ?? ""} ${m?.reasoning_content ?? ""}`;
      if (!q.ok || !/\b42\b/.test(answer)) return `incoherent answer to 17+25 with this KV cache type: ${JSON.stringify(answer.trim().slice(0, 60))}`;
      log("coherence check ok (17 + 25 = 42)");
    }
    return null;
  } finally {
    stop();
    try { closeSync(fd); } catch { /* ignore */ }
  }
}

export interface PullOptions {
  auto: boolean;
  /** Print PULL_USAGE and exit; nothing is planned, fetched or changed. */
  help?: boolean;
  /** "<owner>/<repo>[:<quant>]" */
  explicit?: string;
  trustRepo?: boolean;
  dryRun?: boolean;
  modelsDir?: string;
  /** Calibrate the model already in models.json (no download); with a pull, calibration is the default anyway. */
  calibrate?: boolean;
  /** Do not fetch a newer llama.cpp when the current one cannot load the model. */
  noRuntimeUpdate?: boolean;
  /** Skip the automatic calibration after a fresh pull. */
  noCalibrate?: boolean;
  /** Probe an avir fixed chat template even if the architecture does not select it (never adopted). */
  probeTemplate?: FixedTemplate;
  skipSlot?: boolean;
  /** Do not run the long-context needle check during calibration (it prefills ~90% of the context). */
  skipRecall?: boolean;
  /** MiB of VRAM every calibration candidate must leave free (default 1024). */
  headroomMib?: number;
  log?: (s: string) => void;
  /** Test seams: fixed hardware, a canned Hugging Face listing, a canned runtime fetch. */
  device?: DeviceSpecs;
  listFiles?: (repo: string) => Promise<RepoFile[]>;
  fetchRuntime?: typeof fetchLlamaRuntime;
  findServer?: (cfgBinary: string | undefined) => string | null;
}

function parseExplicit(spec: string): { repo: string; quant?: string } {
  const i = spec.lastIndexOf(":");
  return i > 0 && !spec.slice(i + 1).includes("/") ? { repo: spec.slice(0, i), quant: spec.slice(i + 1) } : { repo: spec };
}

export async function runPull(opts: PullOptions): Promise<number> {
  const log = opts.log ?? ((s: string) => process.stdout.write(`[ember pull] ${s}\n`));
  const home = getEmberConfigHomeDir();
  const cfgPath = join(home, "models.json");
  const cfg: Record<string, unknown> = existsSync(cfgPath) ? JSON.parse(readFileSync(cfgPath, "utf-8")) : {};
  const modelsDir = resolve(opts.modelsDir ?? process.env["EMBER_MODELS_DIR"] ?? (cfg["modelsDir"] as string | undefined) ?? join(home, "models"));

  const dev = opts.device ?? detectDevice();
  log(`device: ${dev.gpuName ?? "no NVIDIA GPU detected"}; VRAM ${(dev.vramTotalBytes / GiB).toFixed(1)} GiB ` +
    `(${(dev.vramFreeBytes / GiB).toFixed(1)} free); RAM ${(dev.ramBytes / GiB).toFixed(1)} GiB`);
  if (dev.vramTotalBytes === 0) log("no GPU: only the smallest catalog entry is considered (CPU inference is slow)");

  let candidates: CatalogEntry[];
  if (opts.explicit) {
    const { repo, quant } = parseExplicit(opts.explicit);
    const owner = repo.split("/")[0] ?? "";
    if (!TRUSTED_OWNERS.includes(owner) && !opts.trustRepo) {
      log(`refusing ${repo}: owner "${owner}" is not on the trusted list (${TRUSTED_OWNERS.join(", ")}); pass --trust-repo to accept this exact repo`);
      return 2;
    }
    const known = CATALOG.find((c) => c.repo === repo);
    candidates = [{
      repo, name: known?.name ?? repo.split("/")[1]!.replace(/-GGUF$/i, "").toLowerCase(),
      kvBytesPerToken: known?.kvBytesPerToken ?? 48 * 8 * 128 * 2 * 2,
      quants: quant ? [quant] : (known?.quants ?? ["Q5_K_M", "Q4_K_M", "Q4_K_S", "IQ4_XS", "Q3_K_M"]),
      note: known?.note ?? "operator-named repo (KV size estimated conservatively)",
      ...(known?.nativeCtx ? { nativeCtx: known.nativeCtx } : {}),
      ...(known?.vision ? { vision: true } : {}),
    }];
  } else {
    candidates = dev.vramTotalBytes === 0 ? CATALOG.slice(-1) : CATALOG;
  }

  // --calibrate measures a live server, so it cannot plan without one; a plain --dry-run can.
  const resolved = await ensureLlamaServer({
    cfgBinary: cfg["binary"] as string | undefined, home, log, noRuntimeUpdate: !!opts.noRuntimeUpdate,
    dryRun: !!opts.dryRun && !(opts.calibrate && !opts.explicit),
    ...(opts.fetchRuntime ? { fetchRuntime: opts.fetchRuntime } : {}),
    ...(opts.findServer ? { find: opts.findServer, findInstalled: () => null } : {}),
  });
  if (resolved.code !== undefined) return resolved.code;
  let binary = resolved.binary;
  if (binary) log(`llama-server: ${binary}`);

  // Backend capabilities decide which KV cache types the fit rule may use.
  let caps: BackendCaps | null = dev.vramTotalBytes > 0 && binary ? probeBackend(binary) : null;
  let kvChoices: KvChoice[] = dev.vramTotalBytes > 0 ? kvChoicesFor(caps) : [{ k: "f16", v: "f16", scale: 1, evidence: "no GPU" }];
  if (dev.vramTotalBytes > 0) {
    log(caps && caps.turboTypes.length > 0
      ? `TurboQuant KV available (${caps.turboTypes.join(", ")}); fit rule may use ${kvChoices.map((c) => c.k).join(" / ")} KV`
      : "stock llama.cpp (no turbo KV types): fit rule uses q8_0 KV");
  }

  if (opts.calibrate && !opts.explicit) return binary ? await calibrateExisting(opts, cfg, cfgPath, home, binary, dev, log) : 2;

  const freeDisk = freeDiskBytes(modelsDir);
  const budget = vramBudget(dev);
  log(`VRAM budget for weights + KV + buffers: ${(budget / GiB).toFixed(1)} GiB`);
  for (const entry of candidates) {
    let files: RepoFile[];
    try { files = await (opts.listFiles ?? listRepoGguf)(entry.repo); } catch (e) { log(`skip ${entry.repo}: ${(e as Error).message}`); continue; }
    let plan = choosePlanKv(entry, files, budget, kvChoices, { stretch: dev.vramTotalBytes > 0 });
    if (!plan) { log(`skip ${entry.repo}: no quant fits ${(budget / GiB).toFixed(1)} GiB at >= ${MIN_CTX} context`); continue; }
    if (plan.file.size + DISK_RESERVE_BYTES > freeDisk) {
      log(`skip ${entry.repo}: needs ${(plan.file.size / GiB).toFixed(1)} GiB + ${DISK_RESERVE_BYTES / GiB} GiB reserve; ${modelsDir} has ${(freeDisk / GiB).toFixed(1)} GiB free`);
      continue;
    }
    log(`selected ${entry.repo} / ${plan.file.path} (${(plan.file.size / GiB).toFixed(1)} GiB), context ${plan.nCtx}, ` +
      `KV ${plan.kv.k}/${plan.kv.v}, estimated VRAM ${(plan.estimatedVramBytes / GiB).toFixed(1)} GiB -- ${entry.note}` +
      (plan.mmproj ? `; vision projector ${plan.mmproj.path} (${(plan.mmproj.size / GiB).toFixed(2)} GiB)` : ""));
    if (opts.dryRun) { log("dry run: nothing downloaded or changed"); return 0; }
    if (!binary) { log("internal error: no llama-server after planning"); return 2; }

    const modelPath = await download(entry.repo, plan.file, modelsDir, log);
    const mmprojPath = plan.mmproj ? await download(entry.repo, plan.mmproj, join(modelsDir, entry.name + "-mmproj"), log) : undefined;
    const argsFor = (kv: KvChoice): string[] => (dev.vramTotalBytes > 0 ? ["-ngl", "999", ...flashAttnArgs(caps, true), "-ctk", kv.k, "-ctv", kv.v] : []);
    const logPath = join(modelsDir, "pull-smoke.log");
    // Live proof, stepping the context down if the estimate was optimistic.  A turbo KV pair must also
    // answer a trivial question correctly (the "ready" completion alone cannot tell a quantiser that
    // produces gibberish from one that works); if it does not, fall back to q8_0 for the same weights.
    let err: string | null = "not run";
    const planned: Plan = plan;
    const ladderFrom = (n: number) => [n, ...CTX_LADDER.filter((c) => c < n)];
    let serverArgs = argsFor(planned.kv);
    let runtimeClass = "other" as LoadFailureClass; // widened: loadSearch mutates it
    const loadSearch = async (startPlan: Plan, choices: KvChoice[]): Promise<void> => {
      const attempts: Array<{ kv: KvChoice; ctxs: number[] }> = [{ kv: startPlan.kv, ctxs: ladderFrom(startPlan.nCtx) }];
      if (startPlan.kv.k.startsWith("turbo")) {
        const fb = choosePlanKv(entry, files, budget, choices.filter((c) => !c.k.startsWith("turbo")));
        if (fb && fb.file.path === startPlan.file.path) attempts.push({ kv: fb.kv, ctxs: ladderFrom(fb.nCtx) });
      }
      for (const att of attempts) {
        serverArgs = argsFor(att.kv);
        for (const nCtx of att.ctxs) {
          log(`load test at context ${nCtx} (KV ${att.kv.k}/${att.kv.v}) ...`);
          const port = await freePort();
          err = await smokeTest(binary!, modelPath, nCtx, serverArgs, port, logPath, log, mmprojPath, { requireCoherent: att.kv.k.startsWith("turbo") });
          if (err === null) { plan = { ...startPlan, nCtx, kv: att.kv }; return; }
          log(`load test failed at ${nCtx}: ${err}`);
          if (err.startsWith("incoherent")) break; // a smaller context does not fix a bad quantiser
          runtimeClass = classifyLoadFailure(existsSync(logPath) ? readFileSync(logPath, "utf-8").slice(-20000) : "");
          if (runtimeClass === "runtime-too-old") return; // no context size fixes an unsupported model
        }
      }
    };
    await loadSearch(planned, kvChoices);
    if (err !== null && runtimeClass === "runtime-too-old" && !opts.noRuntimeUpdate) {
      // Self-heal: this llama.cpp build cannot load the model at all. Fetch a current
      // official build, re-probe what it supports, and try once more.
      log(`this llama-server build cannot load ${plan.file.path} (unsupported tensors/architecture); fetching a current ${RUNTIME_REPO} build`);
      try {
        binary = await fetchLlamaRuntime(join(home, "runtime"), log);
        caps = dev.vramTotalBytes > 0 ? probeBackend(binary) : null;
        kvChoices = dev.vramTotalBytes > 0 ? kvChoicesFor(caps) : kvChoices;
        const replanned = choosePlanKv(entry, files, budget, kvChoices, { stretch: dev.vramTotalBytes > 0 });
        if (replanned && replanned.file.path === planned.file.path) {
          runtimeClass = "other";
          await loadSearch(replanned, kvChoices);
        } else {
          log("the new runtime would choose different weights; run `ember pull` again to re-select");
        }
      } catch (e) {
        log(`runtime fetch failed: ${(e as Error).message}`);
      }
    }
    if (err !== null) {
      const hint = runtimeClass === "runtime-too-old"
        ? " (the llama-server build is too old for this model; install a current llama.cpp and set EMBER_LLAMA_SERVER)"
        : "";
      log(`could not run ${plan.file.path} on this machine${hint}; models.json unchanged`);
      return 3;
    }

    if (existsSync(cfgPath)) {
      const backup = cfgPath + ".bak-" + new Date().toISOString().replace(/[:.]/g, "-");
      copyFileSync(cfgPath, backup);
      log(`previous models.json backed up to ${backup}`);
    }
    const next = { ...cfg };
    delete next["endpoint"]; // a stale fixed endpoint would bypass the managed spawn
    Object.assign(next, {
      seat: "open-weights",
      binary,
      model: modelPath,
      mmproj: mmprojPath,
      nCtx: plan.nCtx,
      maxOutputTokens: Math.min(8192, Math.floor(plan.nCtx / 4)),
      modelName: `${entry.name}:${plan.file.path.replace(/\.gguf$/i, "").split("-").pop()}`,
      serverArgs,
      modelsDir,
      pulledFrom: { repo: entry.repo, file: plan.file.path, sha256: plan.file.sha256, at: new Date().toISOString() },
    });
    mkdirSync(dirname(cfgPath), { recursive: true });
    const tmp = cfgPath + ".tmp";
    writeFileSync(tmp, JSON.stringify(next, null, 2) + "\n");
    renameSync(tmp, cfgPath);
    log(`models.json updated (${cfgPath}); OPEN_WEIGHTS seat selected.`);
    if (dev.vramTotalBytes > 0 && !opts.noCalibrate) {
      log("calibrating the pulled model (skip with --no-calibrate) ...");
      const rc = await optimizeModel({
        home, cfgPath, cfg: next, binary, modelPath, ...(mmprojPath ? { mmprojPath } : {}), modelName: next["modelName"] as string,
        totalVramBytes: dev.vramTotalBytes, startCtx: plan.nCtx, ctxLadder: CTX_LADDER, kvBytesPerToken: entry.kvBytesPerToken,
        ...(opts.probeTemplate ? { probeTemplate: opts.probeTemplate } : {}), ...(opts.skipSlot ? { skipSlot: true } : {}),
        ...(opts.skipRecall ? { skipRecall: true } : {}), ...(opts.headroomMib !== undefined ? { headroomBytes: opts.headroomMib * 1024 ** 2 } : {}), log,
      });
      // The smoke-tested configuration stays in place if calibration cannot improve on it.
      if (rc !== 0) log(`calibration did not complete (code ${rc}); the smoke-tested configuration above remains in models.json`);
    }
    log("Launch ember to use it.");
    return 0;
  }
  log("no candidate fits this machine; nothing changed");
  return 3;
}

/** `ember pull --calibrate`: re-measure the model already selected in models.json. */
async function calibrateExisting(opts: PullOptions, cfg: Record<string, unknown>, cfgPath: string, home: string, binary: string, dev: DeviceSpecs, log: (s: string) => void): Promise<number> {
  const modelPath = cfg["model"] as string | undefined;
  if (!modelPath || !existsSync(modelPath)) { log(`--calibrate needs a model in models.json ("model" is ${modelPath ? "missing on disk: " + modelPath : "unset"}); run \`ember pull\` first`); return 2; }
  if (dev.vramTotalBytes === 0) { log("no NVIDIA GPU detected: nothing to calibrate"); return 0; }
  const known = CATALOG.find((c) => c.repo === (cfg["pulledFrom"] as { repo?: string } | undefined)?.repo);
  const mmproj = cfg["mmproj"] as string | undefined;
  // Calibration starts at the model's full native context (optimizeModel reads it from the GGUF again
  // and builds the native / 196608 / 131072 / ladder steps); this value is only the no-metadata fallback.
  const native = readGgufMeta(modelPath).contextLength ?? CTX_LADDER[0]!;
  return await optimizeModel({
    home, cfgPath, cfg, binary, modelPath, ...(mmproj ? { mmprojPath: mmproj } : {}),
    modelName: (cfg["modelName"] as string | undefined) ?? "model", totalVramBytes: dev.vramTotalBytes,
    startCtx: native, ctxLadder: CTX_LADDER, ...(known ? { kvBytesPerToken: known.kvBytesPerToken } : {}),
    ...(opts.probeTemplate ? { probeTemplate: opts.probeTemplate } : {}), ...(opts.skipSlot ? { skipSlot: true } : {}),
    ...(opts.skipRecall ? { skipRecall: true } : {}), ...(opts.headroomMib !== undefined ? { headroomBytes: opts.headroomMib * 1024 ** 2 } : {}), log,
  });
}

export const PULL_USAGE = [
  "ember pull: pick a model that fits this GPU, download it, prove it loads, calibrate it.",
  "",
  "Usage: Ember-Open pull [<owner>/<repo>[:<quant>]] [options]",
  "",
  "  <owner>/<repo>[:<quant>]  pull this model instead of the one ember would pick",
  "  --dry-run                 show the model, quant and context it would pick; change nothing",
  "  --models-dir <dir>        where the model files go (default: <EMBER_HOME>/models)",
  "  --calibrate               re-measure the model already selected (no download)",
  "  --no-calibrate            skip the calibration after a fresh pull",
  "  --no-runtime-update       never fetch a llama.cpp runtime",
  "  --skip-slot, --skip-recall, --headroom-mib <MiB>   calibration tuning",
  "  --trust-repo              allow a repository that is not in the built-in list",
  "  -h, --help                this text",
  "",
  "Guide: docs/ember-cli/INSTALL.md",
].join("\n");

export function parsePullArgs(args: string[]): PullOptions {
  const o: PullOptions = { auto: false };
  for (let i = 0; i < args.length; i++) {
    const a = args[i]!;
    if (a === "--help" || a === "-h") o.help = true;
    else if (a === "--auto") o.auto = true;
    else if (a === "--dry-run") o.dryRun = true;
    else if (a === "--trust-repo") o.trustRepo = true;
    else if (a === "--models-dir") o.modelsDir = args[++i];
    else if (a === "--calibrate") o.calibrate = true;
    else if (a === "--no-calibrate") o.noCalibrate = true;
    else if (a === "--no-runtime-update") o.noRuntimeUpdate = true;
    else if (a === "--skip-slot") o.skipSlot = true;
    else if (a === "--skip-recall") o.skipRecall = true;
    else if (a === "--headroom-mib") {
      const n = Number(args[++i]);
      if (!Number.isFinite(n) || n < 0 || n > 8192) throw new Error(`--headroom-mib expects a number of MiB between 0 and 8192 (got ${args[i] ?? "nothing"})`);
      o.headroomMib = n;
    }
    else if (a === "--probe-template") {
      const t = args[++i];
      if (t === "qwen35" || t === "qwen36" || t === "gemma4") o.probeTemplate = t;
      else throw new Error(`--probe-template expects qwen35, qwen36 or gemma4 (got ${t ?? "nothing"})`);
    }
    else if (!a.startsWith("-")) o.explicit = a;
    // An unknown option must never fall through to a real pull (a mistyped --dry-run would download ~16 GB).
    else throw new Error(`unknown option ${a}`);
  }
  if (!o.explicit && !o.calibrate) o.auto = true;
  return o;
}

// Exposed for the unit test only.
export const _internals = { VRAM_RESERVE_BYTES, CTX_LADDER, readFileSync };
