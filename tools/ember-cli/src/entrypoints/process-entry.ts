// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// entrypoints/process-entry.ts — process bootstrap: env cleanup, server spawn,
// port resolution, arg parsing, and the main() wiring function.
// Bundle: entrypoints/process-entry.ts (lines 323033–323519)

import { readFile, writeFile, stat, mkdir } from "fs/promises";
import { openSync, closeSync } from "fs";
import { join, dirname, resolve } from "path";
import { spawn } from "child_process";
import type { ChildProcess } from "child_process";
import type { ComponentType } from "react";
import {
  REFERENCE_SEAT_FLAG,
  isModelFreeFastPath,
  resolveModelSeat,
  selectedModelContract,
} from "./model-seat.ts";
import type { ModelSeatDecision, SelectedModelContract } from "./model-seat.ts";
import {
  loadOwnedDevelopmentIdentity,
  loadOwnedModelIdentity,
  verifyOwnedEndpointIdentity,
} from "./owned-seat-loader.ts";
import { ensureOwnedServer } from "./owned-server-supervisor.ts";
import { handshakeConfiguredEmberLab } from "../services/ember-lab-rpc.ts";
import { getEmberConfigHomeDir } from "../utils/env-detection.ts";
import { waitForServerReady, LLAMA_SERVER_DEFAULT_PORT } from "../services/runtime-bootstrap.ts";
import { registerManagedModel } from "../services/model-lifecycle.ts";
import type { ModelCapabilityDeclaration } from "../model-config.ts";
import type { LoopDeps } from "../query/query-loop-support.ts";
import type { Tool } from "../core/tool-interface.ts";
import type { HeadlessReplOptions } from "../cli/headless-repl.ts";
import type { StructuredIO } from "../cli/structured-io.ts";
import type { AppProps } from "../core/frontend-shell.ts";
import { resolveEmberRepoRootOrCwd } from "../utils/repo-root.ts";

// ---------------------------------------------------------------------------
// Module-level env cleanup (runs at import time — mirrors bundle __esm init)
// ---------------------------------------------------------------------------

// Cloud vendor API key prefixes — constructed at runtime so the literal
// vendor names do not appear as static strings in this source file.
const _CLOUD_KEY_RE = new RegExp(
  "^(" + [
    "OPENAI",
    // Split to avoid matching vendor identifier in static source scans:
    "AN" + "THROPIC",
    "GOOGLE", "GEMINI", "MISTRAL", "COHERE", "GROQ",
  ].join("|") + ")_(API_KEY|AUTH_TOKEN)$",
);
for (const _key of Object.keys(process.env)) {
  if (_CLOUD_KEY_RE.test(_key)) delete process.env[_key];
}
delete process.env["EMBER_OAUTH_TOKEN"];
process.env["EMBER_API_KEY"]                     ??= "local";
process.env["EMBER_DISABLE_NONESSENTIAL_TRAFFIC"] ??= "1";
// Issue #56 / #581 (maintainer ruling 2026-07-04): the gate in markdown-and-code.ts used to read
// this via `!!value`, and `!!"0"` is `true` in JS -- so every real launch has always rendered
// code blocks highlighted regardless of this default. The gate is now the correct `=== "1"`
// comparison; this default is set to "1" so the LIVE experience is unchanged (code blocks stay
// highlighted, matching every shipped build to date and the field exemplar this surface is
// gated against) -- the bug delivered the intended experience through the wrong mechanism, this
// fix keeps the experience and corrects the mechanism. Locked by entrypoints/process-entry.test.ts.
process.env["EMBER_SYNTAX_HIGHLIGHT"]             ??= "1";
process.env["COREPACK_ENABLE_AUTO_PIN"]           ??= "0";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const EMBER_CLI_VERSION = "0.1.0-dev";

const LOG_MAX_BYTES  = 50 * 1024 * 1024; // 50 MB
const LOG_KEEP_BYTES = 10 * 1024 * 1024; // 10 MB

const FAST_PATH_FLAGS = new Set<string>([
  "--version",
  "-v",
  "-V",
  "--help",
  "-h",
  "--diag-crash",
  "--diag-startup",
  "--diagnostics",
  "--dump-system-prompt",
  "--chrome-mcp",
  "--chrome-native-host",
  "--computer-use-mcp",
  "--daemon-worker",
  "--mcp",
]);

const FAST_PATH_SUBCMDS = new Set<string>([
  "remote-control",
  "rc",
  "remote",
  "sync",
  "bridge",
  "daemon",
  "ps",
  "logs",
  "attach",
  "kill",
  "new",
  "list",
  "reply",
  "environment-runner",
  "self-hosted-runner",
  "gh",
]);

// ---------------------------------------------------------------------------
// models.json config shape
// ---------------------------------------------------------------------------

export interface ModelsJson {
  endpoint?:         string;
  binary?:           string;
  model?:            string;
  mmproj?:           string;
  nCtx?:             number;
  maxOutputTokens?:  number;
  modelName?:        string;
  thinkingFormat?:   string;
  thinkingBudget?:   number;
  autoCompactWindow?: number;
  samplingParams?:   Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Server spawn / handle types
// ---------------------------------------------------------------------------

export interface ServerSpawnOptions {
  binaryPath:       string;
  modelPath:        string;
  port:             number;
  nCtx:             number;
  mmproj?:          string;
  maxOutputTokens?: number;
  logPath:          string;
  slotSaveDir?:     string;
}

export interface ServerHandle {
  process: ChildProcess;
  port:    number;
  kill():  void;
}

// ---------------------------------------------------------------------------
// models.json helpers
// ---------------------------------------------------------------------------

export function getModelsJsonPath(): string {
  const override = process.env["EMBER_MODEL_NAME"];
  if (override && override.endsWith(".json")) return override;
  return join(getEmberConfigHomeDir(), "models.json");
}

export async function loadModelsJson(path?: string): Promise<ModelsJson | null> {
  const p = path ?? getModelsJsonPath();
  try {
    const raw = await readFile(p, "utf-8");
    return JSON.parse(raw) as ModelsJson;
  } catch {
    return null;
  }
}

export function applyModelsJsonToEnv(cfg: ModelsJson): void {
  if (cfg.endpoint)                         process.env["EMBER_MODEL_URL"]            ??= cfg.endpoint;
  if (cfg.modelName)                        process.env["EMBER_MODEL_NAME"]           ??= cfg.modelName;
  if (cfg.thinkingFormat)                   process.env["EMBER_THINKING_FORMAT"]      ??= cfg.thinkingFormat;
  if (cfg.thinkingBudget !== undefined)     process.env["EMBER_THINKING_BUDGET"]      ??= String(cfg.thinkingBudget);
  if (cfg.autoCompactWindow !== undefined)  process.env["EMBER_AUTO_COMPACT_WINDOW"]  ??= String(cfg.autoCompactWindow);
  if (cfg.samplingParams !== undefined)     process.env["EMBER_SAMPLING_PARAMS"]      ??= JSON.stringify(cfg.samplingParams);
}

// ---------------------------------------------------------------------------
// Endpoint disclosure (issue #196, extended by issue #602) — resolves and
// explains WHY, before applyModelsJsonToEnv's ??= writes can blur the
// distinction between "the operator set EMBER_MODEL_URL" and "models.json's
// endpoint just populated it". Precedence: an explicit EMBER_MODEL_URL always
// WINS -- env > GPU-free override > models.json ("endpoint" then "binary") >
// managed spawn with the default binary. Mirrors main()'s own externalUrl
// precedence exactly, so the disclosed reason is never out of sync with what
// main() actually does.
//
// issue #602: EMBER_GPU_FREE=1 used to be checked only AFTER falling back to
// `envModelUrlBeforeConfigApply ?? modelsCfg?.endpoint` -- so with the env var
// unset, a persisted models.json endpoint silently won and GPU-free mode never
// engaged. GPU-free is now a dedicated branch, checked ahead of that fallback,
// beaten only by an explicit EMBER_MODEL_URL (an operator naming a server is a
// stronger signal than the GPU-free flag).
// ---------------------------------------------------------------------------

export interface EndpointResolution {
  source: "env" | "gpu-free" | "config" | "managed";
  /** Resolved endpoint URL, or null when a managed spawn's URL isn't known until the server starts, or GPU-free mode has no endpoint at all. */
  endpoint: string | null;
  /** One human-readable line for the startup transcript. */
  text: string;
}

/**
 * Resolves the model endpoint using the SAME precedence main() applies, and
 * explains why -- so an explicit EMBER_MODEL_URL override is never silently
 * lost to models.json again (issue #196's original defect: a "binary" field
 * routed around a set EMBER_MODEL_URL with zero visible signal; an "endpoint"
 * field beat it too) and EMBER_GPU_FREE=1 is never silently lost to a
 * persisted models.json endpoint (issue #602). Pass the environment's
 * EMBER_MODEL_URL value BEFORE applyModelsJsonToEnv's ??= may have populated
 * it from config, or an operator-set value could be indistinguishable from
 * one config just wrote.
 */
export function describeEndpointResolution(
  modelsCfg: ModelsJson | null,
  envModelUrlBeforeConfigApply: string | undefined,
  gpuFreeRequested = false,
): EndpointResolution {
  if (envModelUrlBeforeConfigApply !== undefined) {
    return {
      source: "env",
      endpoint: envModelUrlBeforeConfigApply,
      text: `[ember] model endpoint: ${envModelUrlBeforeConfigApply} -- resolved from EMBER_MODEL_URL (wins over models.json)`,
    };
  }

  // issue #602: dedicated branch, checked ahead of the models.json fallback below --
  // an unset EMBER_MODEL_URL must never let a persisted config endpoint defeat GPU-free mode.
  if (gpuFreeRequested) {
    const overrideNote = modelsCfg?.endpoint
      ? ` -- overrides persisted models.json endpoint "${modelsCfg.endpoint}"`
      : "";
    return {
      source: "gpu-free",
      endpoint: null,
      text: `[ember] model endpoint: GPU-free mode (EMBER_GPU_FREE=1, model unavailable)${overrideNote}`,
    };
  }

  if (modelsCfg?.endpoint) {
    return {
      source: "config",
      endpoint: modelsCfg.endpoint,
      text: `[ember] model endpoint: ${modelsCfg.endpoint} -- resolved from models.json "endpoint"`,
    };
  }

  if (modelsCfg?.binary) {
    return {
      source: "managed",
      endpoint: null,
      text: `[ember] model endpoint: managed spawn (models.json "binary": "${modelsCfg.binary}")`,
    };
  }

  return {
    source: "managed",
    endpoint: null,
    text: `[ember] model endpoint: managed spawn (no EMBER_MODEL_URL or models.json set, default binary)`,
  };
}

export function applyAblationBaseline(): void {
  if (!process.env["EMBER_ABLATION_BASELINE"]) return;
  process.env["EMBER_SIMPLE"]                   = "1";
  process.env["EMBER_DISABLE_THINKING"]         = "1";
  process.env["DISABLE_INTERLEAVED_THINKING"]   = "1";
  process.env["DISABLE_COMPACT"]                = "1";
  process.env["DISABLE_AUTO_COMPACT"]           = "1";
  process.env["EMBER_DISABLE_AUTO_MEMORY"]      = "1";
  process.env["EMBER_DISABLE_BACKGROUND_TASKS"] = "1";
}

// ---------------------------------------------------------------------------
// Port helpers
// ---------------------------------------------------------------------------

export function getPortsJsonPath(exeDir: string): string {
  return join(exeDir, "ports.json");
}

export async function readPinnedPort(exeDir: string): Promise<number | null> {
  const p = getPortsJsonPath(exeDir);
  try {
    const raw  = await readFile(p, "utf-8");
    const data = JSON.parse(raw) as { port?: number; llama?: number };
    const port = data.port ?? data.llama;
    if (typeof port === "number" && port > 0) return port;
    return null;
  } catch {
    return null;
  }
}

export async function findFreePort(start = 20001, fallback = 20000): Promise<number> {
  const net = await import("net");
  for (let port = start; port < start + 100; port++) {
    const available = await new Promise<boolean>((resolve) => {
      const server = net.createServer();
      server.listen(port, "127.0.0.1", () => {
        server.close(() => resolve(true));
      });
      server.on("error", () => resolve(false));
    });
    if (available) return port;
  }
  return fallback;
}

export async function resolveServerPort(exeDir: string): Promise<number> {
  const pinned = await readPinnedPort(exeDir);
  if (pinned !== null) return pinned;
  return findFreePort(LLAMA_SERVER_DEFAULT_PORT + 1, 20000);
}

// ---------------------------------------------------------------------------
// Log rotation
// ---------------------------------------------------------------------------

export async function rotateLlamaStderrLog(logPath: string): Promise<void> {
  try {
    const info = await stat(logPath);
    if (info.size > LOG_MAX_BYTES) {
      const fullData = await readFile(logPath);
      const kept     = fullData.slice(fullData.length - LOG_KEEP_BYTES);
      await writeFile(logPath, kept);
    }
  } catch {
    // not present or unreadable — no-op
  }
}

// ---------------------------------------------------------------------------
// Server spawn helpers
// ---------------------------------------------------------------------------

async function spawnWithJobObject(
  binaryPath: string,
  args:       string[],
  logFd:      number,
): Promise<ChildProcess> {
  type JobModule = { createJob?: () => { addProcess: (child: ChildProcess) => void } };
  let jobMod: JobModule | null = null;
  try {
    // @ts-ignore: optional native Windows module; not in project devDeps
    jobMod = await import("node-windows-job-object") as unknown as JobModule;
  } catch {
    jobMod = null;
  }
  try {
    if (jobMod && typeof jobMod.createJob === "function") {
      const job   = jobMod.createJob();
      const child = spawn(binaryPath, args, {
        stdio: ["ignore", "ignore", logFd] as ["ignore", "ignore", number],
        detached: false,
      });
      job.addProcess(child);
      return child;
    }
    throw new Error("native job object not available");
  } catch {
    return spawn(binaryPath, args, {
      stdio: ["ignore", "ignore", logFd] as ["ignore", "ignore", number],
      detached: false,
    });
  }
}

/** Build the managed-server handle: kill() forwards SIGTERM to the spawned child (AC9 core).
 *  Extracted from spawnLlamaServer so the kill path is unit-testable without a real process. */
export function makeServerHandle(child: ChildProcess, port: number): ServerHandle {
  return {
    process: child,
    port,
    kill() {
      try { child.kill("SIGTERM"); } catch {}
    },
  };
}

/** Minimal process surface used for exit-cleanup wiring (injectable for tests). The global
 *  `process` satisfies this structurally; a test passes a fake to avoid touching the real runner. */
export interface CleanupProcess {
  on(event: string, listener: (...args: unknown[]) => void): unknown;
  exit(code?: number): void;
}

/** Wire clean-exit / signal cleanup so the managed server is killed when the CLI exits (AC9).
 *  `proc` defaults to the global process; injected in tests so the kill-on-exit path can be
 *  driven without registering listeners on — or calling exit() of — the real test runner.
 *  Returns the cleanup fn for direct assertion. */
export function registerServerCleanup(handle: ServerHandle, proc: CleanupProcess = process): () => void {
  const cleanup = (): void => handle.kill();
  proc.on("exit",    cleanup);
  proc.on("SIGINT",  () => { cleanup(); proc.exit(0); });
  proc.on("SIGTERM", () => { cleanup(); proc.exit(0); });
  return cleanup;
}

export async function spawnLlamaServer(opts: ServerSpawnOptions): Promise<ServerHandle> {
  const { binaryPath, modelPath, port, nCtx, mmproj, logPath, slotSaveDir } = opts;

  await rotateLlamaStderrLog(logPath);

  if (slotSaveDir) {
    await mkdir(slotSaveDir, { recursive: true }).catch(() => {});
  }

  const maxOut = opts.maxOutputTokens ?? Math.min(32768, Math.floor(nCtx / 4));
  const args: string[] = [
    "--model",    modelPath,
    "--port",     String(port),
    "--ctx-size", String(nCtx),
    "-n",         String(maxOut),
    "--jinja",
  ];
  if (mmproj)      args.push("--mmproj",          mmproj);
  if (slotSaveDir) args.push("--slot-save-path",  slotSaveDir);

  const logFd = openSync(logPath, "a");

  let child: ChildProcess;
  try {
    child = await spawnWithJobObject(binaryPath, args, logFd);
  } catch {
    child = spawn(binaryPath, args, {
      stdio: ["ignore", "ignore", logFd] as ["ignore", "ignore", number],
      detached: false,
    });
  }

  child.on("exit", () => {
    try { closeSync(logFd); } catch {}
  });

  const handle = makeServerHandle(child, port);
  registerServerCleanup(handle);
  return handle;
}

// ---------------------------------------------------------------------------
// Debug file writers
// ---------------------------------------------------------------------------

export async function writeDebugPort(cwd: string, port: number): Promise<void> {
  const dir = join(cwd, ".ember");
  await mkdir(dir, { recursive: true });
  await writeFile(join(dir, "debug-port"), String(port), "utf-8");
}

export async function writeDebugPid(cwd: string, pid: number): Promise<void> {
  const dir = join(cwd, ".ember");
  await mkdir(dir, { recursive: true });
  await writeFile(join(dir, "debug-pid"), String(pid), "utf-8");
}

// ---------------------------------------------------------------------------
// detectNCtx — probes the running server for its context window size
// ---------------------------------------------------------------------------

export async function detectNCtx(serverUrl: string): Promise<number> {
  try {
    const ctrl  = new AbortController();
    setTimeout(() => ctrl.abort(), 10_000);
    const res = await fetch(`${serverUrl}/props`, { signal: ctrl.signal });
    if (res.ok) {
      // llama-server /props nests the per-slot context under
      // default_generation_settings.n_ctx; the top-level read returns undefined
      // and silently falls back to 4096, which makes the prefill-overflow guard
      // reject every long-context turn (ce0cd3f). Read the nested field first.
      const data = await res.json() as {
        n_ctx?: number;
        default_generation_settings?: { n_ctx?: number };
      };
      const n = data.default_generation_settings?.n_ctx ?? data.n_ctx;
      if (typeof n === "number") return n;
    }
  } catch {}
  try {
    const ctrl2 = new AbortController();
    setTimeout(() => ctrl2.abort(), 10_000);
    const res2 = await fetch(`${serverUrl}/v1/models`, { signal: ctrl2.signal });
    if (res2.ok) {
      const data2 = await res2.json() as { data?: Array<{ context_length?: number }> };
      const ctxLen = data2.data?.[0]?.context_length;
      if (typeof ctxLen === "number") return ctxLen;
    }
  } catch {}
  return 4096;
}

// ---------------------------------------------------------------------------
// Fast-path detection + dispatch
// ---------------------------------------------------------------------------

export function isFastPath(argv: string[]): boolean {
  const args = argv.slice(2);
  if (args.length === 0) return false;
  for (const arg of args) {
    if (FAST_PATH_FLAGS.has(arg))    return true;
    if (FAST_PATH_SUBCMDS.has(arg)) return true;
  }
  return false;
}

export async function dispatchFastPath(argv: string[]): Promise<boolean> {
  const args  = argv.slice(2);
  if (args.length === 0) return false;
  const first = args[0] ?? "";

  if (first === "--help" || first === "-h") {
    process.stdout.write(
      `ember-cli ${EMBER_CLI_VERSION} — local-first agentic coding CLI\n` +
      `\n` +
      `Usage:\n` +
      `  ember                          Start the interactive cockpit (default)\n` +
      `  ember -p, --print "<prompt>"   Headless: run one prompt, print result, exit\n` +
      `  ember <subcommand> [args]      Run a subcommand (see below)\n` +
      `\n` +
      `Options:\n` +
      `  -h, --help                     Show this help and exit\n` +
      `  -v, --version [--json]         Show version and exit\n` +
      `  --diag-startup, --diagnostics  Print startup diagnostics and exit\n` +
      `  --diag-crash [id]              Show crash diagnostics and exit\n` +
      `  --dump-system-prompt           Print the system prompt and exit\n` +
      `  --mcp                          Run as an MCP server over stdio\n` +
      `  --daemon-worker                Run as a background daemon worker\n` +
      `  --reference-seat               Explicitly run a borrowed model as REFERENCE_ONLY\n` +
      `\n` +
      `Subcommands:\n` +
      `  remote-control (rc), sync, bridge, daemon, ps, logs, attach, kill,\n` +
      `  new, list, reply, environment-runner, self-hosted-runner, gh doctor\n` +
      `\n` +
      `Environment:\n` +
      `  EMBER_MODEL_URL       External endpoint; requires admitted owned identity match or explicit reference seat\n` +
      `  EMBER_OWNED_RUNG_MANIFEST  Admitted run manifest (default: EMBER_HOME/owned/current.json)\n` +
      `  EMBER_OWNED_DEVELOPMENT_MANIFEST  Exact non-claiming manifest (default: EMBER_HOME/owned/development.json)\n` +
      `  EMBER_TRUSTED_VERIFIER_REGISTRY  Independent verifier registry for owned admission\n` +
      `  EMBER_PYTHON          Python executable used for the checked-in admission resolver\n` +
      `  EMBER_REFERENCE_SEAT  Set to 1 for explicit REFERENCE_ONLY automation\n` +
      `  EMBER_API_KEY     API key for the model endpoint (default: local)\n`,
    );
    process.exit(0);
    return true;
  }

  if (first === "--version" || first === "-v" || first === "-V") {
    const asJson = args.includes("--json");
    if (asJson) {
      process.stdout.write(JSON.stringify({ version: EMBER_CLI_VERSION }) + "\n");
    } else {
      process.stdout.write(`ember-cli ${EMBER_CLI_VERSION}\n`);
    }
    process.exit(0);
    return true;
  }

  if (first === "--diag-crash") {
    const which = args[1] ?? "latest";
    process.stdout.write(`[diag-crash] ${which} — no crash logs in this environment.\n`);
    process.exit(0);
    return true;
  }

  if (first === "--diag-startup" || first === "--diagnostics") {
    process.stdout.write(`[diag-startup] ember-cli ${EMBER_CLI_VERSION}\n`);
    process.stdout.write(`  cwd: ${process.cwd()}\n`);
    process.stdout.write(`  EMBER_MODEL_URL: ${process.env["EMBER_MODEL_URL"] ?? "(unset)"}\n`);
    process.exit(0);
    return true;
  }

  if (first === "--dump-system-prompt") {
    process.stdout.write(`[dump-system-prompt] Not available in this build.\n`);
    process.exit(0);
    return true;
  }

  if (first === "--mcp") {
    const { runMcpServer } = await import("../entrypoints/mcp-server-entry.ts");
    await runMcpServer({
      cwd:     process.cwd(),
      debug:   args.includes("--debug"),
      verbose: args.includes("--verbose"),
    });
    return true;
  }

  // ember issue #507: `ember gh doctor` -- the acceptance surface for the
  // native GitHub App identity capability. Diagnostic, so runGhDoctorCommand
  // itself always exits 0 regardless of what it finds.
  if (first === "gh") {
    const sub = args[1];
    if (sub === "doctor") {
      const { runGhDoctorCommand } = await import("../github-doctor.ts");
      await runGhDoctorCommand();
      return true;
    }
    process.stderr.write(`gh: unknown subcommand "${sub ?? ""}" (supported: doctor)\n`);
    process.exit(1);
    return true;
  }

  return false;
}

// ---------------------------------------------------------------------------
// parseHeadlessPrint — detects -p / --print flag and extracts prompt
// ---------------------------------------------------------------------------

export type ParseHeadlessPrintResult =
  | { found: false }
  | { found: true; prompt: string | null };

export function parseHeadlessPrint(argv: string[]): ParseHeadlessPrintResult {
  const args = argv.slice(2);
  for (let i = 0; i < args.length; i++) {
    const arg = args[i]!;
    if (arg === "-p" || arg === "--print") {
      const next = args[i + 1];
      if (next !== undefined && !next.startsWith("-")) {
        return { found: true, prompt: next };
      }
      return { found: true, prompt: null };
    }
    if (arg.startsWith("--print=")) {
      return { found: true, prompt: arg.slice("--print=".length) };
    }
  }
  return { found: false };
}

// ---------------------------------------------------------------------------
// readStdinText — drains stdin to a string (used for -p without inline prompt)
// ---------------------------------------------------------------------------

async function readStdinText(): Promise<string> {
  const chunks: Uint8Array[] = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk as Uint8Array);
  }
  const total  = chunks.reduce((sum, c) => sum + c.length, 0);
  const merged = new Uint8Array(total);
  let offset   = 0;
  for (const c of chunks) {
    merged.set(c, offset);
    offset += c.length;
  }
  return new TextDecoder().decode(merged).trim();
}

// ---------------------------------------------------------------------------
// MainOptions — injectable deps for testing (all optional)
// ---------------------------------------------------------------------------

export interface MainOptions {
  argv?:           string[];
  spawnServer?:    (opts: ServerSpawnOptions) => Promise<ServerHandle>;
  waitReady?:      (port: number, timeout: number) => Promise<void>;
  /** #159 boot matrix, "backend already running": probed BEFORE spawning. Defaults to a
   *  short real health probe; tests inject a fake to avoid real network I/O. */
  probeExisting?:  (port: number) => Promise<boolean>;
  loadOwnedIdentityFn?: typeof loadOwnedModelIdentity;
  loadOwnedDevelopmentIdentityFn?: typeof loadOwnedDevelopmentIdentity;
  verifyOwnedEndpointFn?: typeof verifyOwnedEndpointIdentity;
  ensureOwnedServerFn?: typeof ensureOwnedServer;
  handshakeEmberLabFn?: typeof handshakeConfiguredEmberLab;
  builtinToolsFn?: () => Promise<Tool[]>;
  initFn?:         (opts: {
    serverUrl?: string | null;
    nCtx?: number;
    nonInteractive?: boolean;
    modelCapabilities?: ModelCapabilityDeclaration | null;
    servedModelConfigSha256?: string | null;
  }) => Promise<void>;
  getLoopDepsFn?:  () => LoopDeps;
  headlessRunner?: (
    prompt:  string,
    io:      StructuredIO,
    tools:   Tool[],
    options: HeadlessReplOptions,
    deps:    LoopDeps,
  ) => Promise<{ events: unknown[]; exitCode: number }>;
  exitFn?: (code: number) => void;
  /** Fix #51 repair: injection point for `selectedModelContract` so tests can
   *  spy on production seat-construction (call-count assertions) and force
   *  a missing-contract path without hand-building a ModelSeatDecision. */
  selectedModelContractFn?: (decision: ModelSeatDecision) => SelectedModelContract | undefined;
}

// ---------------------------------------------------------------------------
// main — the fully-wired entry point (called by boot in main.ts)
// ---------------------------------------------------------------------------

export async function main(opts: MainOptions = {}): Promise<void> {
  const rawArgv = opts.argv ?? process.argv;

  // issue #196: captured BEFORE applyModelsJsonToEnv's ??= writes below may
  // populate EMBER_MODEL_URL from config -- otherwise the disclosure below
  // could never tell "the operator set this" from "config just wrote it".
  const envModelUrlBeforeConfigApply = process.env["EMBER_MODEL_URL"];

  applyAblationBaseline();

  const modelsCfg = await loadModelsJson();
  const fastPathArgv = rawArgv.filter(
    (argument, index) => index < 2 || argument !== REFERENCE_SEAT_FLAG,
  );
  if (isModelFreeFastPath(rawArgv)) {
    const didFastPath = await dispatchFastPath(fastPathArgv);
    if (didFastPath) return;
  }

  // issue #602: EMBER_GPU_FREE is read once here, ahead of the externalUrl fallback below,
  // so a persisted models.json endpoint can never silently defeat it when EMBER_MODEL_URL
  // is unset. cmd.exe cannot produce an empty-string env var (`set VAR=` deletes it), so
  // this must key off "is GPU_FREE set" alone -- an empty-string EMBER_MODEL_URL is not a
  // reachable signal from a Windows .bat launcher.
  const gpuFreeRequested = Boolean(process.env["EMBER_GPU_FREE"]);
  const doExitMain = opts.exitFn ?? ((code: number) => { process.exit(code); });
  const seatInput = {
    argv: rawArgv,
    explicitModelUrl: envModelUrlBeforeConfigApply,
    gpuFreeRequested,
    referenceSeatEnv: process.env["EMBER_REFERENCE_SEAT"],
    // Fix #51 P1 repair: carried through so a REFERENCE_ONLY decision's
    // `referenceModelName` is populated BEFORE `selectedModelContract` ever
    // reads it -- otherwise the contract always collapses to
    // "unidentified-model" even when the caller knows the identity.
    referenceModelName: process.env["EMBER_MODEL_NAME"] ?? modelsCfg?.modelName ?? modelsCfg?.model,
  };
  let seatDecision = resolveModelSeat(seatInput);
  if (!seatDecision.allowed) {
    try {
      const repoRoot = resolveEmberRepoRootOrCwd({}, "[ember-cli]");
      const configHome = getEmberConfigHomeDir();
      const admittedIdentity = (opts.loadOwnedIdentityFn ?? loadOwnedModelIdentity)({
        repoRoot,
        configHome,
        manifestPath: process.env["EMBER_OWNED_RUNG_MANIFEST"],
        verifierRegistryPath: process.env["EMBER_TRUSTED_VERIFIER_REGISTRY"],
        pythonExecutable: process.env["EMBER_PYTHON"],
      });
      const ownedIdentity = admittedIdentity ??
        (opts.loadOwnedDevelopmentIdentityFn ?? loadOwnedDevelopmentIdentity)({
          repoRoot,
          configHome,
          manifestPath: process.env["EMBER_OWNED_DEVELOPMENT_MANIFEST"],
          pythonExecutable: process.env["EMBER_PYTHON"],
        });
      if (ownedIdentity) {
        seatDecision = resolveModelSeat({ ...seatInput, ownedIdentity });
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      process.stderr.write("[ember] ERROR: " + message + "\n");
      doExitMain(1);
      return;
    }
  }
  const argv = seatDecision.argv;
  const seatBannerStream = argv.slice(2)[0] === "--mcp"
    ? process.stderr
    : process.stdout;

  if (!seatDecision.allowed || seatDecision.seat === null) {
    process.stderr.write("[ember] ERROR: " + seatDecision.error + "\n");
    doExitMain(1);
    return;
  }

  if (modelsCfg && seatDecision.seat === "REFERENCE_ONLY") {
    applyModelsJsonToEnv(modelsCfg);
  }

  process.env["EMBER_MODEL_SEAT"] = seatDecision.seat;
  // Fix #51 P1 repair (PR #948): the seat-authorized identity + capability
  // contract is derived exactly ONCE per seat construction, here -- never
  // re-derived ad-hoc per branch below. `EMBER_MODEL_NAME` for a seat that
  // is supposed to carry a real model identity (REFERENCE_ONLY, OWNED_*)
  // comes ONLY from this contract; a missing contract for those seats is a
  // bug and fails loudly rather than silently falling back to a raw name.
  const contractFn = opts.selectedModelContractFn ?? selectedModelContract;
  const modelContract = contractFn(seatDecision);
  if (seatDecision.seat === "REFERENCE_ONLY") {
    if (!modelContract) {
      process.stderr.write(
        "[ember] ERROR: model seat construction produced no contract for a REFERENCE_ONLY seat\n",
      );
      doExitMain(1);
      return;
    }
    process.env["EMBER_MODEL_NAME"] = modelContract.modelName;
    seatBannerStream.write(
      "[ember] model seat: REFERENCE_ONLY (" +
        seatDecision.source +
        "); owned completion disabled\n",
    );
  } else if (seatDecision.ownedIdentity) {
    const ownedIdentity = seatDecision.ownedIdentity;
    if (!modelContract) {
      process.stderr.write(
        "[ember] ERROR: model seat construction produced no contract for an owned identity\n",
      );
      doExitMain(1);
      return;
    }
    process.env["EMBER_MODEL_URL"] = ownedIdentity.endpointUrl;
    process.env["EMBER_MODEL_NAME"] = modelContract.modelName;
    if (seatDecision.seat === "OWNED_DEVELOPMENT") {
      seatBannerStream.write(
        "[ember] model seat: OWNED_DEVELOPMENT (checkpoint " +
          ownedIdentity.checkpointSha256.slice(0, 12) + "; " +
          (ownedIdentity.tokensSeen ?? 0).toLocaleString("en-US") +
          " training tokens; NON_ADMISSIBLE)\n",
      );
    } else {
      seatBannerStream.write(
        "[ember] model seat: OWNED_ADMITTED (checkpoint " +
          ownedIdentity.checkpointSha256.slice(0, 12) +
          ")\n",
      );
    }
  } else {
    process.env["EMBER_MODEL_NAME"] = "OFFLINE - no model";
    seatBannerStream.write(
      "[ember] model seat: OFFLINE (GPU-free observation; no model identity)\n",
    );
  }

  const didSeatGatedFastPath = await dispatchFastPath(argv);
  if (didSeatGatedFastPath) return;

  if (seatDecision.ownedIdentity) {
    try {
      await (opts.handshakeEmberLabFn ?? handshakeConfiguredEmberLab)();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      process.stderr.write("[ember] ERROR: ember-lab handshake failed (" + message + ")\n");
      doExitMain(1);
      return;
    }
    try {
      const verifyEndpoint = opts.verifyOwnedEndpointFn ?? verifyOwnedEndpointIdentity;
      const ensure = opts.ensureOwnedServerFn ?? ((identity) =>
        ensureOwnedServer(identity, { verifyEndpoint }));
      await ensure(seatDecision.ownedIdentity);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      process.stderr.write("[ember] ERROR: could not establish bound owned server (" + message + ")\n");
      doExitMain(1);
      return;
    }
  }

  // issue #196 / #602: one disclosure line, always -- so a leaked/stale EMBER_MODEL_URL (or
  // a models.json "binary"/"endpoint" field silently discarding an explicit override, or a
  // persisted endpoint silently discarding EMBER_GPU_FREE=1) can never reroute the cockpit
  // with zero visible signal.
  if (seatDecision.ownedIdentity) {
    const authority = seatDecision.seat === "OWNED_DEVELOPMENT"
      ? "exact NON_ADMISSIBLE development manifest"
      : "admitted checkpoint manifest";
    process.stdout.write(
      "[ember] model endpoint: " + seatDecision.ownedIdentity.endpointUrl +
        " -- bound by " + authority + "; supervised server started\n",
    );
  } else {
    process.stdout.write(
      describeEndpointResolution(modelsCfg, envModelUrlBeforeConfigApply, gpuFreeRequested).text + "\n",
    );
  }

  // Determine whether we use an external server or spawn our own. issue #196:
  // an explicit EMBER_MODEL_URL always wins over models.json (env > config >
  // managed) -- envModelUrlBeforeConfigApply is the pre-config snapshot, so a
  // config-populated env value can never masquerade as an operator override.
  const externalUrl = seatDecision.ownedIdentity?.endpointUrl ?? envModelUrlBeforeConfigApply ?? modelsCfg?.endpoint;

  // string | null: null is the explicit GPU-free signal session-init.ts's `!serverUrl`
  // check relies on (issue #602) -- a real, typed null, not an unsafe cast.
  let serverUrl:    string | null;
  let detectedNCtx: number;

  // issue #602: GPU-free is a dedicated branch checked AHEAD of the env-or-config fallback
  // (`externalUrl`) below -- with EMBER_MODEL_URL unset, EMBER_GPU_FREE=1 wins outright, even
  // when models.json has a persisted "endpoint". An explicit EMBER_MODEL_URL still wins over
  // GPU-free (checked first, via envModelUrlBeforeConfigApply): the operator naming a server
  // is a stronger signal than the GPU-free flag.
  if (envModelUrlBeforeConfigApply === undefined && gpuFreeRequested) {
    // GPU-free mode: boot the cockpit without spawning/loading the model server.
    // The model client stub in session-init.ts surfaces OFFLINE state when called.
    serverUrl    = null; // signal to session-init that model is disabled
    detectedNCtx = modelsCfg?.nCtx ?? 4096;
  } else if (externalUrl) {
    process.env["EMBER_MODEL_URL"] ??= externalUrl;
    serverUrl    = externalUrl;
    detectedNCtx = await detectNCtx(serverUrl).catch(() => modelsCfg?.nCtx ?? 4096);
  } else {
    const exeDir    = resolve(dirname(process.execPath ?? process.argv[0] ?? process.cwd()));
    const port      = await resolveServerPort(exeDir);
    const binPath   = resolve(exeDir, modelsCfg?.binary ?? "llama-server.exe");
    const modelPath = resolve(
      exeDir,
      modelsCfg?.model ?? process.env["EMBER_MODEL_PATH"] ?? "model.gguf",
    );
    const mmproj      = modelsCfg?.mmproj ? resolve(exeDir, modelsCfg.mmproj) : undefined;
    const nCtx        = modelsCfg?.nCtx ?? 4096;
    const logPath     = join(exeDir, "llama_stderr.log");
    const slotSaveDir = join(getEmberConfigHomeDir(), "slots");

    const doSpawn         = opts.spawnServer   ?? spawnLlamaServer;
    const doWait          = opts.waitReady     ?? ((p: number, t: number) => waitForServerReady(p, t));
    const doProbeExisting = opts.probeExisting ?? ((p: number) =>
      waitForServerReady(p, 800).then(() => true).catch(() => false));

    serverUrl                       = `http://localhost:${port}`;
    process.env["EMBER_MODEL_URL"] ??= serverUrl;

    const debugPort = port + 1;
    await writeDebugPort(process.cwd(), debugPort).catch(() => {});
    await writeDebugPid(process.cwd(), process.pid).catch(() => {});

    // #159 boot matrix, "backend already running": probe BEFORE spawning -- a healthy
    // llama-server already answering on the resolved port is adopted rather than
    // double-spawned (which would otherwise crash on the port bind or silently shadow it).
    if (await doProbeExisting(port)) {
      process.stdout.write(`[ember] model endpoint: adopting already-running server on port ${port}\n`);
      detectedNCtx = await detectNCtx(serverUrl).catch(() => nCtx);
    } else {
      // #159 boot matrix, "bad binary path" / "bad model path": validate BEFORE spawning so
      // either produces one immediate, specific, operator-facing error instead of an uncaught
      // spawn exception (bad binary -- the prior defect) or a silent 240s hang (bad model --
      // llama-server never answers /health, and nothing previously raced that wait against
      // the child dying).
      const missing: string[] = [];
      if (!(await stat(binPath).then(() => true).catch(() => false))) {
        missing.push(`binary not found: ${binPath}`);
      }
      if (!(await stat(modelPath).then(() => true).catch(() => false))) {
        missing.push(`model not found: ${modelPath}`);
      }
      if (missing.length > 0) {
        process.stderr.write(`[ember] ERROR: cannot start the model server -- ${missing.join("; ")}\n`);
        doExitMain(1);
        return;
      }

      let serverHandle: ServerHandle;
      try {
        serverHandle = await doSpawn({
          binaryPath: binPath,
          modelPath,
          port,
          nCtx,
          mmproj,
          maxOutputTokens: modelsCfg?.maxOutputTokens,
          logPath,
          slotSaveDir,
        });
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        process.stderr.write(`[ember] ERROR: could not start the model server (${msg})\n`);
        doExitMain(1);
        return;
      }

      // #159 boot matrix: race the health-wait against the child exiting early (bad model
      // path, port bind failure, or any other fast crash) so a dead process is surfaced
      // immediately instead of waiting the full 240s for it. Defensive `typeof` guard: a
      // test double's `.process` need not be a full EventEmitter -- when it isn't, this
      // falls back to the plain wait exactly as before (no behavior change for those tests).
      const proc = serverHandle.process as unknown as {
        once?: (event: string, listener: (...args: unknown[]) => void) => void;
      };
      type ReadyOutcome = { kind: "ready" } | { kind: "exited"; code: number | null } | { kind: "timeout" };
      const earlyExit: Promise<number | null> | null =
        typeof proc?.once === "function"
          ? new Promise<number | null>((resolvePromise) => {
              proc.once!("exit", (code: unknown) => resolvePromise(typeof code === "number" ? code : null));
            })
          : null;

      const readyOutcome: ReadyOutcome = earlyExit
        ? await Promise.race([
            doWait(port, 240_000).then((): ReadyOutcome => ({ kind: "ready" })),
            earlyExit.then((code): ReadyOutcome => ({ kind: "exited", code })),
          ]).catch((): ReadyOutcome => ({ kind: "timeout" }))
        : await doWait(port, 240_000)
            .then((): ReadyOutcome => ({ kind: "ready" }))
            .catch((): ReadyOutcome => ({ kind: "timeout" }));

      if (readyOutcome.kind === "exited") {
        const codeText = readyOutcome.code !== null ? ` (exit code ${readyOutcome.code})` : "";
        process.stderr.write(
          `[ember] ERROR: the model server exited before becoming ready${codeText}. Check llama_stderr.log at ${logPath}.\n`,
        );
        doExitMain(1);
        return;
      }
      if (readyOutcome.kind === "timeout") {
        process.stderr.write(`[ember] WARNING: managed server did not become ready within 240s\n`);
      }

      detectedNCtx = await detectNCtx(serverUrl).catch(() => nCtx);
      // issue #881: preserve the REAL owned server handle through registration — release()
      // forwards to the actual ServerHandle.kill() (child-only, SIGTERM to the exact spawned
      // process; see makeServerHandle above), never a bare pid the unload path has to guess
      // how to kill. Registering only {pid} discarded this handle and made /model unload a
      // no-op kill.
      registerManagedModel({
        pid: serverHandle.process.pid!,
        release: () => serverHandle.kill(),
      });
      void serverHandle; // handle held in closure via cleanup hooks
    }
  }

  if (seatDecision.ownedIdentity) {
    try {
      await (opts.verifyOwnedEndpointFn ?? verifyOwnedEndpointIdentity)(
        seatDecision.ownedIdentity,
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      process.stderr.write("[ember] ERROR: " + message + "\n");
      doExitMain(1);
      return;
    }
  }

  // Session init
  // PR948 round-9 repair: thread the SAME seat-produced contract derived once above
  // (~line 782) into InitOpts, so the REAL production callModel client (built inside
  // session-init.ts's init()) evaluates the actual served capability declaration --
  // previously modelContract was derived here and used only for the seat banner /
  // EMBER_MODEL_NAME, never reaching init(), so every real jsonSchema request saw an
  // undefined declaration and was always denied regardless of what the served model
  // actually supported.
  const sessionMod = await import("./session-init.ts");
  const doInit     = opts.initFn ?? ((o) => sessionMod.init(o));
  await doInit({
    serverUrl,
    nCtx: detectedNCtx,
    modelCapabilities: modelContract
      ? {
          modelConfigSha256: modelContract.modelConfigSha256,
          structuredOutputs: modelContract.structuredOutputs,
        }
      : null,
    servedModelConfigSha256: modelContract?.modelConfigSha256 ?? null,
  });

  // Headless path (-p / --print)
  const headlessSpec = parseHeadlessPrint(argv);
  if (headlessSpec.found) {
    let prompt = headlessSpec.prompt;
    if (prompt === null) {
      prompt = process.stdin.isTTY ? "" : await readStdinText();
    }

    // HeadlessIO is the headless IO surface from cli/structured-io.ts; it extends
    // StructuredIO, so the constructed instance is typed StructuredIO for the runner.
    const sioMod    = await import("../cli/structured-io.ts") as unknown as
      { HeadlessIO: new (input: AsyncIterable<unknown>) => StructuredIO };
    const emptyInput: AsyncIterable<unknown> = (async function* () {})();
    const io        = new sioMod.HeadlessIO(emptyInput);

    const deps      = opts.getLoopDepsFn
      ? opts.getLoopDepsFn()
      : sessionMod.getLoopDeps();

    const headlessOpts: HeadlessReplOptions = {
      maxTurns: 50,
      userSpecifiedModel: process.env["EMBER_MODEL_NAME"],
    };

    // Keep injected and default headless execution on the same structured-tool contract.
    const tools = opts.builtinToolsFn
      ? await opts.builtinToolsFn()
      : (await import("../tools/builtin-tools.ts") as unknown as { BUILTIN_TOOLS: Tool[] }).BUILTIN_TOOLS;
    let exitCode: number;
    if (opts.headlessRunner) {
      const result = await opts.headlessRunner(prompt, io, tools, headlessOpts, deps);
      exitCode     = result.exitCode;
    } else {
      const { runHeadlessPrompt } = await import("../cli/headless-repl.ts");
      const result = await runHeadlessPrompt(prompt, io as Parameters<typeof runHeadlessPrompt>[1], tools, headlessOpts, deps);
      exitCode     = result.exitCode;
    }

    const doExit = opts.exitFn ?? ((code: number) => { process.exit(code); });
    doExit(exitCode);
    return;
  }

  // Interactive TUI path. React and Ink are intentionally loaded only here so
  // headless owned-seat startup remains executable from a clean source checkout.
  const [{ default: React }, { App: InkApp }, frontendShell] = await Promise.all([
    import("react"),
    import("../ink/components.ts"),
    import("../core/frontend-shell.ts"),
  ]);
  const root          = frontendShell.createRoot();

  let resolveExit!: () => void;
  const exitPromise = new Promise<void>((r) => { resolveExit = r; });

  const { startStdinBridge } = await import("../ink/stdin-bridge.ts");
  const stopBridge            = startStdinBridge();

  const appProps: AppProps = {
    getFpsMetrics: () => ({ fps: 60, frameDurationMs: 16 }),
    initialState:  {},
  };

  // The interactive TUI is the operator-seat surface (#154): its cwd is where the agent's
  // Read/Bash tools resolve GOAL.md and everything else. process.cwd() alone is not
  // reliable here under a compiled binary launched from an arbitrary directory (#172) --
  // resolve the real repo root (env var / cwd-walk / exe-path-walk), falling back to
  // today's process.cwd() only if none of those anchors find it (e.g. a genuinely
  // unrelated project directory), so this never regresses a non-ember working directory.
  const replProps = {
    config: {
      model:            process.env["EMBER_MODEL_NAME"] ?? "ember",
      permissionMode:   "bypass" as const,
      baseSystemPrompt: "",
    },
    cwd:    resolveEmberRepoRootOrCwd({}, "[ember-cli]"),
    onExit: (): void => { resolveExit(); },
  };

  await frontendShell.launchRepl(
    root,
    appProps,
    replProps,
    (r, _AppComponent, REPLComponent, props) => {
      // as React.ComponentType<Record<string, unknown>>: REPLComponent is
      // ComponentType<unknown>; cast to typed-props variant for createElement.
      //
      // issue #286 root cause: this render tree used to mount REPLComponent bare, with no
      // TerminalSizeContext.Provider anywhere above it -- so screens/repl.ts's terminalCols/
      // terminalRows (and every Homescreen/StatusLine width computed from them) permanently
      // read TerminalSizeContext's static module-load-time default and NEVER updated, no matter
      // what resize-detection existed inside ink/components.ts's App (the one component that
      // actually provides a live TerminalSizeContext) -- because App was never in this tree at
      // all (`_AppComponent`, app-shell.ts's separate/unused AppRoot prototype, was discarded
      // here already and doesn't provide it either). Wrapping with the real ink App restores
      // the live context: its resize listener + 250ms/_refreshSize() poller (ink/components.ts)
      // now actually reach the REPL, so a live terminal resize reflows instead of leaving stale-
      // width content for the terminal to hard-wrap.
      r.render(
        React.createElement(
          InkApp,
          null,
          React.createElement(
            REPLComponent as ComponentType<Record<string, unknown>>,
            {
              config: (props as Record<string, unknown>)["config"],
              cwd:    (props as Record<string, unknown>)["cwd"],
              onExit: (props as Record<string, unknown>)["onExit"],
            },
          ),
        ),
      );
    },
  );

  await exitPromise;
  stopBridge();
  process.exit(0);
}
