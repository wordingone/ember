// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/runtime-fetch.ts -- self-heal for "the model is newer than llama.cpp".
//
// A new model family (observed: Qwen3.8 GGUFs with an MTP layer) can be published
// before the local llama-server build knows how to load it. The load log then says
// "missing tensor ..." or "unknown model architecture" at EVERY context size, so
// stepping the context down (the OOM heal) is pointless. This module recognises
// that failure class and fetches an official ggml-org/llama.cpp Windows release
// matched to the installed NVIDIA driver, sha256-verified against the digest the
// GitHub release API publishes. Only that one repository is ever used.

import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { createReadStream, createWriteStream, existsSync, mkdirSync, readdirSync, renameSync, rmSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { Readable, Transform } from "node:stream";
import { pipeline } from "node:stream/promises";

export const RUNTIME_REPO = "ggml-org/llama.cpp";
/** A release must be this old before it is fetched (soak time for a bad build to be pulled). */
export const RUNTIME_MIN_AGE_HOURS = 24;

export type LoadFailureClass = "runtime-too-old" | "out-of-memory" | "other";

/** Classify a llama-server load failure from its log text. */
export function classifyLoadFailure(logText: string): LoadFailureClass {
  if (/missing tensor|unknown model architecture|unknown architecture|wrong number of tensors|unsupported model|key not found in model/i.test(logText)) {
    return "runtime-too-old";
  }
  if (/out of memory|cudaMalloc failed|failed to allocate|CUDA error: out of memory|unable to allocate/i.test(logText)) {
    return "out-of-memory";
  }
  return "other";
}

/** CUDA runtime major supported by the installed driver, from nvidia-smi's header. */
export function driverCudaMajor(): number | null {
  const r = spawnSync("nvidia-smi", [], { encoding: "utf-8" });
  if (r.status !== 0) return null;
  return parseCudaMajor(r.stdout);
}

/** Header formats seen: "CUDA Version: 12.4" and (driver 600+) "CUDA UMD Version: 13.3".
 * Falls back to the driver version: R580+ drivers run CUDA 13 builds, R525+ CUDA 12. */
export function parseCudaMajor(nvidiaSmiOut: string): number | null {
  const m = /CUDA(?: UMD)? Version:\s*(\d+)\.(\d+)/.exec(nvidiaSmiOut);
  if (m) return Number(m[1]);
  const d = /(?:NVIDIA-SMI|Driver Version:|KMD Version:)\s*(\d+)\.\d+/.exec(nvidiaSmiOut);
  if (!d) return null;
  const drv = Number(d[1]);
  return drv >= 580 ? 13 : drv >= 525 ? 12 : null;
}

export interface ReleaseAsset { name: string; browser_download_url: string; size: number; digest?: string | null }
export interface Release { tag_name: string; published_at: string; draft?: boolean; prerelease?: boolean; assets: ReleaseAsset[] }

/** Pick the newest release at least `minAgeHours` old with a Windows CUDA build this
 * driver can run, plus its cudart bundle. */
export function chooseRuntimeAssets(
  releases: Release[],
  cudaMajor: number,
  now: number,
  minAgeHours = RUNTIME_MIN_AGE_HOURS,
): { release: Release; llama: ReleaseAsset; cudart: ReleaseAsset | undefined } | null {
  const sorted = [...releases]
    // ggml-org publishes every numbered build (bNNNN) flagged as a prerelease; those are
    // the normal release channel. Other prereleases and drafts are skipped.
    .filter((r) => !r.draft && (!r.prerelease || /^b\d+$/.test(r.tag_name)))
    .sort((a, b) => Date.parse(b.published_at) - Date.parse(a.published_at));
  for (const rel of sorted) {
    if (now - Date.parse(rel.published_at) < minAgeHours * 3_600_000) continue;
    const cudaBuilds = rel.assets
      .map((a) => ({ a, m: /^llama-.*-bin-win-cuda-(\d+)\.(\d+)-x64\.zip$/.exec(a.name) }))
      .filter((x): x is { a: ReleaseAsset; m: RegExpExecArray } => x.m !== null && Number(x.m[1]) <= cudaMajor)
      .sort((x, y) => Number(y.m[1]) - Number(x.m[1]) || Number(y.m[2]) - Number(x.m[2]));
    const pick = cudaBuilds[0];
    if (!pick) continue;
    const ver = `${pick.m[1]}.${pick.m[2]}`;
    const cudart = rel.assets.find((a) => a.name === `cudart-llama-bin-win-cuda-${ver}-x64.zip`);
    return { release: rel, llama: pick.a, cudart };
  }
  return null;
}

async function sha256Of(path: string): Promise<string> {
  const h = createHash("sha256");
  await pipeline(createReadStream(path), h);
  return h.digest("hex");
}

async function fetchAsset(asset: ReleaseAsset, dir: string, log: (s: string) => void): Promise<string> {
  const dest = join(dir, asset.name);
  const expected = asset.digest?.startsWith("sha256:") ? asset.digest.slice(7).toLowerCase() : null;
  if (!expected) throw new Error(`release asset ${asset.name} publishes no sha256 digest; refusing to run it unverified`);
  if (existsSync(dest) && statSync(dest).size === asset.size && (await sha256Of(dest)) === expected) return dest;
  log(`downloading ${asset.name} (${(asset.size / 1024 ** 2).toFixed(0)} MiB) from ${RUNTIME_REPO} ...`);
  const res = await fetch(asset.browser_download_url);
  if (!res.ok || !res.body) throw new Error(`download of ${asset.name} failed: HTTP ${res.status}`);
  const part = dest + ".part";
  let got = 0;
  let nextPct = 10;
  const progress = new Transform({
    transform(chunk: Buffer, _enc, cb) {
      got += chunk.length;
      const pct = asset.size > 0 ? Math.floor((got / asset.size) * 100) : 0;
      if (pct >= nextPct) { log(`  ${asset.name}: ${pct}%`); nextPct = pct - (pct % 10) + 10; }
      cb(null, chunk);
    },
  });
  await pipeline(Readable.fromWeb(res.body as never), progress, createWriteStream(part));
  const digest = await sha256Of(part);
  if (digest !== expected) { rmSync(part, { force: true }); throw new Error(`sha256 mismatch for ${asset.name}`); }
  renameSync(part, dest);
  return dest;
}

function extractZip(zip: string, dir: string): void {
  // Windows 10+ ships bsdtar, which reads zip archives. Name it by full path: a Git
  // or MSYS GNU tar earlier on PATH reads "B:\..." as a remote host and fails.
  const sysTar = join(process.env["SystemRoot"] ?? "C:/Windows", "System32", "tar.exe");
  const r = existsSync(sysTar) ? spawnSync(sysTar, ["-xf", zip, "-C", dir], { encoding: "utf-8" }) : null;
  if (r && r.status === 0) return;
  const ps = spawnSync("powershell.exe", [
    "-NoProfile", "-NonInteractive", "-Command",
    `Expand-Archive -LiteralPath '${zip.replace(/'/g, "''")}' -DestinationPath '${dir.replace(/'/g, "''")}' -Force`,
  ], { encoding: "utf-8" });
  if (ps.status !== 0) throw new Error(`could not extract ${zip}: ${r?.stderr || ""} ${ps.stderr || ps.stdout}`.trim());
}

function findServerExe(dir: string): string | null {
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    const p = join(dir, e.name);
    if (e.isFile() && e.name.toLowerCase() === "llama-server.exe") return p;
    if (e.isDirectory()) { const f = findServerExe(p); if (f) return f; }
  }
  return null;
}

/** Written last, after every archive of a release is extracted: a directory without it is an
 * interrupted fetch (llama-server.exe present, CUDA DLLs missing) and is never reused as-is. */
export const RUNTIME_COMPLETE_MARKER = ".ember-runtime-complete";

/** The newest complete llama-server.exe already fetched under `root` (one directory per release
 * tag), or null. Lets a re-run reuse the runtime without any network call. */
export function findInstalledRuntime(root: string): string | null {
  if (!existsSync(root)) return null;
  const dirs = readdirSync(root, { withFileTypes: true })
    .filter((e) => e.isDirectory() && existsSync(join(root, e.name, RUNTIME_COMPLETE_MARKER)))
    .map((e) => ({ dir: join(root, e.name), mtime: statSync(join(root, e.name)).mtimeMs }))
    .sort((a, b) => b.mtime - a.mtime);
  for (const d of dirs) {
    const exe = findServerExe(d.dir);
    if (exe) return exe;
  }
  return null;
}

export const RELEASE_PAGE_SIZE = 100;
const RELEASE_MAX_PAGES = 3;

/** The newest releases, paged until one old enough with a usable Windows CUDA build is in hand.
 * ggml-org publishes a numbered build every 30-60 minutes, so the 15 newest releases (the page size
 * this once used) can all be younger than the 24-hour soak and nothing would ever be selected. */
export async function listRuntimeReleases(
  cudaMajor: number,
  now: number,
  fetchFn: typeof fetch = fetch,
): Promise<Release[]> {
  const all: Release[] = [];
  for (let page = 1; page <= RELEASE_MAX_PAGES; page++) {
    const res = await fetchFn(`https://api.github.com/repos/${RUNTIME_REPO}/releases?per_page=${RELEASE_PAGE_SIZE}&page=${page}`, { headers: { accept: "application/vnd.github+json" } });
    if (!res.ok) throw new Error(`GitHub release listing failed: HTTP ${res.status}${res.status === 403 ? " (rate limited: unauthenticated API calls are limited to 60 per hour; wait and re-run)" : ""}`);
    const rows = (await res.json()) as Release[];
    all.push(...rows);
    if (chooseRuntimeAssets(all, cudaMajor, now) || rows.length < RELEASE_PAGE_SIZE) break;
  }
  return all;
}

/** Fetch (or reuse) an official llama.cpp runtime under `root`; returns llama-server.exe. */
export async function fetchLlamaRuntime(
  root: string,
  log: (s: string) => void,
  deps: { fetchReleases?: () => Promise<Release[]>; cudaMajor?: number | null; now?: number; fetchFn?: typeof fetch } = {},
): Promise<string> {
  if (process.platform !== "win32") throw new Error("automatic runtime fetch is implemented for Windows only; install a current llama.cpp and set EMBER_LLAMA_SERVER");
  const cuda = deps.cudaMajor !== undefined ? deps.cudaMajor : driverCudaMajor();
  if (cuda === null) throw new Error("no NVIDIA driver found (nvidia-smi); cannot choose a CUDA build");
  const now = deps.now ?? Date.now();
  const releases = deps.fetchReleases ? await deps.fetchReleases() : await listRuntimeReleases(cuda, now, deps.fetchFn);
  const pick = chooseRuntimeAssets(releases, cuda, now);
  if (!pick) throw new Error(`no ${RUNTIME_REPO} release with a Windows CUDA <= ${cuda} build found`);
  const dir = join(root, pick.release.tag_name);
  const existing = existsSync(join(dir, RUNTIME_COMPLETE_MARKER)) ? findServerExe(dir) : null;
  if (existing) { log(`using llama.cpp ${pick.release.tag_name} already in ${dir}`); return existing; }
  mkdirSync(dir, { recursive: true });
  const dl = join(dir, "download");
  mkdirSync(dl, { recursive: true });
  for (const a of [pick.llama, pick.cudart]) {
    if (!a) continue;
    const zip = await fetchAsset(a, dl, log);
    extractZip(zip, dir);
  }
  const exe = findServerExe(dir);
  if (!exe) throw new Error(`llama-server.exe not found after extracting ${pick.llama.name}`);
  writeFileSync(join(dir, RUNTIME_COMPLETE_MARKER), `${pick.release.tag_name}
`);
  log(`installed llama.cpp ${pick.release.tag_name} (${pick.llama.name}) at ${exe}`);
  return exe;
}
