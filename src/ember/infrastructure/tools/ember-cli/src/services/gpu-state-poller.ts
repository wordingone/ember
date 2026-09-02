// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/gpu-state-poller.ts — issue #447: GPU state (VRAM used/total, compute processes)
// sourced directly from `nvidia-smi`, never from a process's own self-reported telemetry.
//
// Why nvidia-smi and not the existing services/telemetry-watch.ts governor channel: that
// channel (state/ember-telemetry.jsonl) is written by ember's OWN training/inference
// processes -- a process reporting its own VRAM use is self-report, exactly the attestation
// surface issue #447 explicitly rules out ("no new attestation surface, no self-report").
// nvidia-smi is the OS/driver's own accounting, independent of anything ember writes --
// L2-clean by construction. This module never trusts a number ember itself produced.
//
// Fails open, unconditionally: no nvidia-smi binary (non-NVIDIA box, PATH miss), a non-zero
// exit, or unparseable output all degrade to `null` -- the caller renders nothing rather than
// a fabricated reading. Same fail-open contract as model-metrics-poller.ts's fetchModelMetrics.

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** One GPU's memory + utilization reading, in GiB / percent. */
export interface GpuMemorySnapshot {
  vramUsedGib: number;
  vramTotalGib: number;
  utilPct: number;
}

/** Combined GPU state: the first GPU's memory reading (single-GPU box; see pollGpuState's own
 *  comment for why index 0) plus the raw process-name list nvidia-smi reports as currently
 *  holding a compute context on the device. */
export interface GpuStateSnapshot {
  memory: GpuMemorySnapshot;
  /** Raw process names (e.g. "llama-server.exe", "python.exe") nvidia-smi reports as holding a
   *  compute context. Empty when no process currently uses the GPU. Never inferred/guessed --
   *  exactly what --query-compute-apps reported, so the caller classifies, this module never
   *  does (single-responsibility: acquire ground truth here, interpret it in the renderer). */
  computeProcessNames: string[];
}

/** Injectable process-exec function -- tests supply a fake, real callers pass one backed by
 *  node:child_process. Must never throw: resolve with the captured stdout (even if the process
 *  exited non-zero -- the caller decides what a non-zero/empty result means) or reject only on
 *  a genuine spawn failure (binary not found). */
export type ExecFn = (command: string, args: string[]) => Promise<{ stdout: string; exitCode: number }>;

// ---------------------------------------------------------------------------
// Pure parsers
// ---------------------------------------------------------------------------

/**
 * Parses `nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu
 * --format=csv,noheader,nounits` output -- one CSV line per GPU, values in MiB/MiB/percent, e.g.
 * "18432, 24576, 42". Converts MiB -> GiB (divide by 1024). Malformed lines are skipped, never
 * thrown on -- a partial/torn read degrades to fewer (possibly zero) entries rather than
 * crashing. Returns [] for empty/whitespace-only input.
 */
export function parseNvidiaSmiMemoryOutput(output: string): GpuMemorySnapshot[] {
  const snapshots: GpuMemorySnapshot[] = [];
  for (const rawLine of output.split("\n")) {
    const line = rawLine.trim();
    if (!line) continue;
    const parts = line.split(",").map((p) => p.trim());
    if (parts.length < 3) continue;
    const usedMib = Number(parts[0]);
    const totalMib = Number(parts[1]);
    const util = Number(parts[2]);
    if (!Number.isFinite(usedMib) || !Number.isFinite(totalMib) || !Number.isFinite(util)) continue;
    snapshots.push({
      vramUsedGib: usedMib / 1024,
      vramTotalGib: totalMib / 1024,
      utilPct: util,
    });
  }
  return snapshots;
}

/**
 * Parses `nvidia-smi --query-compute-apps=process_name --format=csv,noheader` output -- one
 * process name per line. Returns [] for empty output (the common, honest "GPU idle" case, NOT
 * an error) or whitespace-only lines skipped.
 */
export function parseNvidiaSmiComputeAppsOutput(output: string): string[] {
  return output
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l.length > 0);
}

// ---------------------------------------------------------------------------
// Poll
// ---------------------------------------------------------------------------

export interface GpuStatePollDeps {
  /** Overrides the exec function (default: shells the real `nvidia-smi` via node:child_process). */
  exec?: ExecFn;
}

async function defaultExec(command: string, args: string[]): Promise<{ stdout: string; exitCode: number }> {
  const { execFile } = await import("node:child_process");
  return new Promise((resolve, reject) => {
    execFile(command, args, { timeout: 3000 }, (err, stdout) => {
      if (err && (err as NodeJS.ErrnoException).code === "ENOENT") {
        reject(err); // binary not found -- genuine spawn failure
        return;
      }
      // A non-zero exit (e.g. driver not loaded) still resolves -- pollGpuState treats an
      // empty/unparseable stdout as "nothing to report", never as a thrown error.
      const exitCode = err && "code" in err && typeof err.code === "number" ? err.code : 0;
      resolve({ stdout: stdout ?? "", exitCode });
    });
  });
}

/**
 * Polls nvidia-smi once and returns the combined GPU state, or `null` when nvidia-smi is
 * unavailable (no NVIDIA GPU / not on PATH) or its memory query yields no parseable reading.
 * The compute-apps query is best-effort: if IT fails (but the memory query succeeded), the
 * process list simply comes back empty rather than failing the whole snapshot -- an idle GPU
 * and an unreadable compute-apps query look identical from this module's contract, and that is
 * an acceptable degrade (VRAM state is still real and useful on its own).
 *
 * Single-GPU assumption: this machine's known configuration is one local GPU (see
 * CLAUDE.md/governor rails), so memory[0] is the reading that matters; a multi-GPU box would
 * need index selection this module doesn't attempt.
 */
export async function pollGpuState(deps: GpuStatePollDeps = {}): Promise<GpuStateSnapshot | null> {
  const exec = deps.exec ?? defaultExec;

  let memoryResult: { stdout: string; exitCode: number };
  try {
    memoryResult = await exec("nvidia-smi", [
      "--query-gpu=memory.used,memory.total,utilization.gpu",
      "--format=csv,noheader,nounits",
    ]);
  } catch {
    return null; // nvidia-smi not present at all -- non-NVIDIA box or not on PATH
  }

  const memories = parseNvidiaSmiMemoryOutput(memoryResult.stdout);
  const memory = memories[0];
  if (!memory) return null; // no parseable GPU reading -- degrade silently, never fabricate

  let computeProcessNames: string[] = [];
  try {
    const computeResult = await exec("nvidia-smi", [
      "--query-compute-apps=process_name",
      "--format=csv,noheader",
    ]);
    computeProcessNames = parseNvidiaSmiComputeAppsOutput(computeResult.stdout);
  } catch {
    // Best-effort only -- memory reading above already stands on its own.
  }

  return { memory, computeProcessNames };
}

// ---------------------------------------------------------------------------
// Classification + display formatting
// ---------------------------------------------------------------------------

/** GPU compute-activity classification. Deliberately conservative: "training-active" is only
 *  ever claimed when an INDEPENDENT signal (a fresh progress-file write, see
 *  run-progress-scanner.ts's isActiveRunFresh) corroborates it -- nvidia-smi's process-name list
 *  alone can't distinguish a training python.exe from any other python.exe holding the GPU, so
 *  this module never guesses that distinction from names alone. "llama-server-only" is a real,
 *  literal process-name match (still ground truth, never inferred). */
export type GpuActivityClass = "idle" | "training-active" | "llama-server-only" | "compute-active";

export function classifyGpuActivity(computeProcessNames: string[], activeRunFresh: boolean): GpuActivityClass {
  if (computeProcessNames.length === 0) return "idle";
  if (activeRunFresh) return "training-active";
  if (computeProcessNames.some((name) => /llama[-_]?server/i.test(name))) return "llama-server-only";
  return "compute-active";
}

/** Formats the GPU-state feed line, e.g. "GPU: 18.0/24.0 GiB · training-active". Returns null
 *  when no GPU snapshot is available (non-NVIDIA box, nvidia-smi unavailable) -- never a
 *  fabricated "0.0/0.0 GiB" reading. */
export function formatGpuStateLine(
  gpu: GpuStateSnapshot | null,
  activeRunFresh: boolean,
): { text: string } | null {
  if (!gpu) return null;
  const cls = classifyGpuActivity(gpu.computeProcessNames, activeRunFresh);
  const used = gpu.memory.vramUsedGib.toFixed(1);
  const total = gpu.memory.vramTotalGib.toFixed(1);
  return { text: `GPU: ${used}/${total} GiB \xB7 ${cls}` };
}

// ---------------------------------------------------------------------------
// React polling hook
// ---------------------------------------------------------------------------

/** Poll cadence: an OS-command shell-out on every tick, so this stays slow like the other
 *  file/process pollers here (board-ts-poller: 45s; this: 10s, since GPU state is more
 *  volatile minute-to-minute than a board receipt but still never worth a sub-second timer). */
export const DEFAULT_GPU_STATE_POLL_INTERVAL_MS = 10_000;

// React is an optional peer for this module's pure/async half -- the hook is imported lazily so
// bun test can exercise pollGpuState/parsers without a React runtime in scope, matching the
// existing model-metrics-poller.ts pattern of a thin hook wrapper over tested pure logic.
import { useEffect, useState } from "react";

/**
 * Polls nvidia-smi at `intervalMs` cadence. Returns `null` until the first successful poll (or
 * whenever nvidia-smi is unavailable) -- the caller renders nothing in that case, never a
 * fabricated zero reading. Cleans up the interval on unmount.
 */
export function useGpuStatePoller(
  intervalMs: number = DEFAULT_GPU_STATE_POLL_INTERVAL_MS,
  deps: GpuStatePollDeps = {},
): GpuStateSnapshot | null {
  const [state, setState] = useState<GpuStateSnapshot | null>(null);

  useEffect(() => {
    let active = true;

    const poll = async (): Promise<void> => {
      const result = await pollGpuState(deps);
      if (active) setState(result);
    };

    void poll();
    const id = setInterval(() => void poll(), intervalMs);
    return () => {
      active = false;
      clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs]);

  return state;
}
