// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/llama-harness.ts -- start, probe and stop a throwaway llama-server
// for calibration / template / slot measurements.  Every server started here is
// tracked, killed by PID (never by name), and verified gone.

import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { closeSync, openSync, mkdirSync } from "node:fs";
import { createServer } from "node:net";
import { dirname } from "node:path";

export const PORT_RANGE: [number, number] = [18800, 18899];
const GiB = 1024 ** 3;
void GiB;

export async function freePort(range: [number, number] = PORT_RANGE, isFree: (p: number) => Promise<boolean> = portIsFree): Promise<number> {
  for (let p = range[0]; p <= range[1]; p++) if (await isFree(p)) return p;
  throw new Error(`no free port in ${range[0]}-${range[1]}`);
}

function portIsFree(port: number): Promise<boolean> {
  return new Promise((res) => {
    const s = createServer();
    s.once("error", () => res(false));
    s.listen(port, "127.0.0.1", () => s.close(() => res(true)));
  });
}

/** GPU memory in use, whole device, bytes.  Per-process figures are "[N/A]" under WDDM,
 * so the whole-device number sampled during a run (minus the baseline taken before
 * the server started) is the peak that is measurable. */
export function gpuMemoryUsedBytes(): number | null {
  const r = spawnSync("nvidia-smi", ["--query-gpu=memory.used", "--format=csv,noheader,nounits"], { encoding: "utf-8" });
  if (r.status !== 0) return null;
  const n = Number((r.stdout ?? "").trim().split(/\r?\n/)[0]);
  return Number.isFinite(n) ? n * 1024 * 1024 : null;
}

export interface Running {
  child: ChildProcess;
  pid: number;
  port: number;
  url: string;
  exited: () => boolean;
  stop: (why?: string) => Promise<void>;
}

const live = new Set<ChildProcess>();

/** Append a kill receipt (python JSON serializer) before a kill, when
 * EMBER_KILL_RECEIPT_FILE names a receipts file (the operator's PID-cohort
 * kill discipline).  No-op otherwise. */
export function writeKillReceipt(pid: number, matchRule: string): void {
  const file = process.env["EMBER_KILL_RECEIPT_FILE"];
  if (!file) return;
  const py = "import json,sys,datetime;" +
    "r={'ts':datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),'script':'ember-cli/model-calibrate','pids':[int(sys.argv[2])],'match_rule':sys.argv[3],'survivors_expected':'none'};" +
    "f=open(sys.argv[1],'ab');f.write((json.dumps(r)+chr(10)).encode('utf-8'));f.close()";
  spawnSync(process.platform === "win32" ? "python" : "python3", ["-I", "-c", py, file, String(pid), matchRule], { encoding: "utf-8" });
}

function pidAlive(pid: number): boolean {
  try { process.kill(pid, 0); return true; } catch { return false; }
}

export async function startServer(binary: string, args: string[], logPath: string, env: Record<string, string> = {}, range?: [number, number]): Promise<Running> {
  const port = await freePort(range);
  mkdirSync(dirname(logPath), { recursive: true });
  const fd = openSync(logPath, "a");
  const child = spawn(binary, [...args, "--host", "127.0.0.1", "--port", String(port)], {
    stdio: ["ignore", "ignore", fd], detached: false, windowsHide: true, env: { ...process.env, ...env },
  });
  live.add(child);
  let gone = false;
  child.on("exit", () => { gone = true; live.delete(child); try { closeSync(fd); } catch { /* ignore */ } });
  const pid = child.pid!;
  return {
    child, pid, port, url: `http://127.0.0.1:${port}`, exited: () => gone,
    stop: async (why = "calibration server started by this process (child handle)") => {
      if (gone) return;
      writeKillReceipt(pid, why);
      try { child.kill(); } catch { /* already gone */ }
      const deadline = Date.now() + 15_000;
      while (!gone && pidAlive(pid) && Date.now() < deadline) await Bun.sleep(100);
    },
  };
}

/** Stop every server this process still holds (error paths). */
export async function stopAllLive(): Promise<void> {
  for (const c of [...live]) {
    if (c.exitCode !== null || c.killed) continue;
    if (c.pid) writeKillReceipt(c.pid, "leftover calibration server (child handle), cleanup path");
    try { c.kill(); } catch { /* ignore */ }
  }
}

export async function waitHealthy(r: Running, timeoutMs = 600_000): Promise<{ ok: true; seconds: number } | { ok: false; error: string }> {
  const t0 = Date.now();
  for (;;) {
    if (r.exited()) return { ok: false, error: "llama-server exited during load" };
    if (Date.now() - t0 > timeoutMs) return { ok: false, error: `llama-server not healthy within ${Math.round(timeoutMs / 1000)} s` };
    try {
      const h = await fetch(`${r.url}/health`);
      if (h.ok) return { ok: true, seconds: (Date.now() - t0) / 1000 };
    } catch { /* not up yet */ }
    await Bun.sleep(500);
  }
}

export interface Timings { prompt_n?: number; prompt_ms?: number; prompt_per_second?: number; predicted_n?: number; predicted_per_second?: number; draft_n?: number; draft_n_accepted?: number }

export interface ChatResult {
  ok: boolean; status: number; text: string; reasoning: string; toolCalls: Array<{ name: string; arguments: string }>;
  finishReason: string | null; timings: Timings; wallMs: number; raw?: unknown;
}

export async function chat(url: string, body: Record<string, unknown>, timeoutMs = 600_000): Promise<ChatResult> {
  const t0 = Date.now();
  const res = await fetch(`${url}/v1/chat/completions`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body), signal: AbortSignal.timeout(timeoutMs),
  }).catch((e: Error) => e);
  if (res instanceof Error) return { ok: false, status: 0, text: String(res.message), reasoning: "", toolCalls: [], finishReason: null, timings: {}, wallMs: Date.now() - t0 };
  const raw = (await res.json().catch(() => null)) as Record<string, any> | null;
  const msg = raw?.["choices"]?.[0]?.message ?? {};
  return {
    ok: res.ok, status: res.status, text: typeof msg.content === "string" ? msg.content : "",
    reasoning: typeof msg.reasoning_content === "string" ? msg.reasoning_content : "",
    toolCalls: Array.isArray(msg.tool_calls) ? msg.tool_calls.map((t: any) => ({ name: String(t?.function?.name ?? ""), arguments: String(t?.function?.arguments ?? "") })) : [],
    finishReason: raw?.["choices"]?.[0]?.finish_reason ?? null,
    timings: (raw?.["timings"] ?? {}) as Timings, wallMs: Date.now() - t0, raw: res.ok ? undefined : raw,
  };
}

/** Deterministic filler prose of roughly `tokens` tokens.  `salt` changes the
 * text so llama-server's prompt cache cannot serve it from a previous request. */
export function filler(tokens: number, salt: string): string {
  const words = ["amber", "beacon", "cipher", "delta", "ember", "falcon", "garnet", "harbor", "ivory", "jasper", "kernel", "lantern", "meadow", "nectar", "orchid", "prism"];
  const out: string[] = [`[${salt}]`];
  // ~1.3 tokens per short word on a BPE tokenizer
  const n = Math.ceil(tokens / 1.3);
  for (let i = 0; i < n; i++) out.push(words[(i * 7 + salt.length + (i >> 3)) % words.length]!);
  return out.join(" ");
}
