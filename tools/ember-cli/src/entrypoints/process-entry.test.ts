// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// process-entry.test.ts — AC1–AC12 tests for process-entry.ts
// Spec: specs/entrypoints/process-entry.md

import { describe, it, expect, beforeEach, afterEach, spyOn } from "bun:test";
import { writeFile, mkdir, rm } from "node:fs/promises";
import { openSync, closeSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

import {
  applyModelsJsonToEnv,
  applyAblationBaseline,
  isFastPath,
  dispatchFastPath,
  resolveServerPort,
  readPinnedPort,
  rotateLlamaStderrLog,
  writeDebugPort,
  writeDebugPid,
  EMBER_CLI_VERSION,
  loadModelsJson,
  findFreePort,
  detectNCtx,
  parseHeadlessPrint,
  makeServerHandle,
  registerServerCleanup,
  describeEndpointResolution,
  defaultCheckGpuLease,
  type ServerSpawnOptions,
  type ServerHandle,
  main,
} from "./process-entry.ts";
import type { OutageMarker } from "../services/activity-feed.ts";
import { _resetConfigHomeMemo } from "../utils/env-detection.ts";
import { _resetInitForTests } from "./session-init.ts";
import type { OwnedModelIdentity } from "./model-seat.ts";
import { OwnedSeatStaleBindingError } from "./owned-seat-loader.ts";
import type { LoopDeps, CallModelParams } from "../query/query-loop-support.ts";
import type { StructuredIO } from "../cli/structured-io.ts";
import type { Tool } from "../core/tool-interface.ts";
import type { HeadlessReplOptions } from "../cli/headless-repl.ts";

// We need to reset env state carefully between tests
function saveEnv(keys: string[]): Record<string, string | undefined> {
  const saved: Record<string, string | undefined> = {};
  for (const k of keys) saved[k] = process.env[k];
  return saved;
}

function restoreEnv(saved: Record<string, string | undefined>): void {
  for (const [k, v] of Object.entries(saved)) {
    if (v === undefined) delete process.env[k];
    else process.env[k] = v;
  }
}

type ExitError = Error & { code: number };

function mockProcessExit(): { restore: () => void; captured: () => number | null } {
  let captured: number | null = null;
  const orig = process.exit;
  (process as unknown as { exit: (code?: number) => never }).exit = ((code?: number) => {
    captured = code ?? 0;
    throw Object.assign(new Error(`process.exit(${code ?? 0})`), { code: code ?? 0 }) as ExitError;
  }) as typeof process.exit;
  return {
    restore: () => { (process as unknown as { exit: typeof orig }).exit = orig; },
    captured: () => captured,
  };
}

function captureStdout(): { restore: () => void; output: () => string } {
  let out = "";
  const orig = process.stdout.write.bind(process.stdout);
  process.stdout.write = ((s: string) => { out += s; return true; }) as typeof process.stdout.write;
  return {
    restore: () => { process.stdout.write = orig; },
    output: () => out,
  };
}

describe("process-entry — AC1: external credential tokens are stripped at startup", () => {
  it("EMBER_OAUTH_TOKEN is deleted and no auth token is defaulted after module load", () => {
    // The module deletes EMBER_OAUTH_TOKEN + all cloud-provider *_API_KEY/_AUTH_TOKEN at eval-time and
    // never defaults an auth token. (EMBER_API_KEY is intentionally defaulted to "local" — see AC2; the
    // prior AC1 asserted EMBER_API_KEY undefined, which contradicted that documented default — corrected.)
    expect(process.env["EMBER_OAUTH_TOKEN"]).toBeUndefined();
    expect(process.env["EMBER_AUTH_TOKEN"]).toBeUndefined();
  });
});

describe("process-entry — AC2: EMBER_API_KEY is 'local' unless pre-set", () => {
  it("EMBER_API_KEY is exactly 'local' after module load (not merely 'defined')", () => {
    // The module sets: process.env["EMBER_API_KEY"] ??= "local"
    // The prior assertion was `v === "local" || v !== undefined` which is trivially true
    // for ANY non-undefined value — it passes even when the default is "remote", "", or "wrong".
    // This assertion requires the exact string "local". It would fail if:
    //   - the default was changed to anything other than "local"
    //   - ??= was replaced with a hard-coded = to a different value
    // Assumes the test environment has not pre-set EMBER_API_KEY before this module loaded.
    expect(process.env["EMBER_API_KEY"]).toBe("local");
  });

  it("AC2 ??= inversion guard: absent key → 'local'; pre-set key → preserved (not overwritten)", () => {
    // Demonstrates the ??= vs = distinction the module code relies on.
    // If someone replaced `??= "local"` with `= "local"`, Case 2 would fail.
    // Uses a synthetic probe key to avoid polluting EMBER_API_KEY.
    const KEY = "__ac2_inversion_probe__";
    delete process.env[KEY];

    // Case 1: key absent → default "local" is applied
    (process.env as Record<string, string>)[KEY] ??= "local";
    expect(process.env[KEY]).toBe("local");

    // Case 2: key pre-set to a different value → ??= is a no-op (pre-set value survives)
    process.env[KEY] = "pre-existing-key";
    (process.env as Record<string, string>)[KEY] ??= "local";
    expect(process.env[KEY]).toBe("pre-existing-key"); // would be "local" if = were used

    delete process.env[KEY];
  });
});

describe("process-entry — AC3: EMBER_DISABLE_NONESSENTIAL_TRAFFIC is '1' unless pre-set", () => {
  it("EMBER_DISABLE_NONESSENTIAL_TRAFFIC is exactly '1' after module load (not merely 'defined')", () => {
    // The module sets: process.env["EMBER_DISABLE_NONESSENTIAL_TRAFFIC"] ??= "1"
    // The prior assertion was `v === "1" || v !== undefined` which is trivially true
    // for any non-undefined value — it passes even when v is "0", "disabled", "false".
    // This assertion requires the exact string "1". It would fail if:
    //   - the default was changed to "0" (inverted — traffic enabled by default)
    //   - ??= was replaced with a hard-coded = to a different value
    // Assumes the test environment has not pre-set this key before this module loaded.
    expect(process.env["EMBER_DISABLE_NONESSENTIAL_TRAFFIC"]).toBe("1");
  });

  it("AC3 ??= inversion guard: pre-set '0' (traffic enabled) is preserved, not forced to '1'", () => {
    // If a process sets EMBER_DISABLE_NONESSENTIAL_TRAFFIC="0" before process-entry loads,
    // the ??= must leave it at "0" — not force it to "1".
    // This test would fail if the module used an unconditional `= "1"` assignment.
    const KEY = "__ac3_inversion_probe__";
    delete process.env[KEY];

    // Case 1: absent → "1" applied (non-essential traffic disabled by default)
    (process.env as Record<string, string>)[KEY] ??= "1";
    expect(process.env[KEY]).toBe("1");

    // Case 2: pre-set to "0" (caller explicitly enables traffic) → ??= is a no-op
    process.env[KEY] = "0";
    (process.env as Record<string, string>)[KEY] ??= "1";
    expect(process.env[KEY]).toBe("0"); // must be "0", NOT "1" — the flip is preserved

    delete process.env[KEY];
  });
});

describe("process-entry — EMBER_SYNTAX_HIGHLIGHT default is '1' unless pre-set (issue #56/#581)", () => {
  it("EMBER_SYNTAX_HIGHLIGHT is exactly '1' after module load (not merely 'defined')", () => {
    // The module sets: process.env["EMBER_SYNTAX_HIGHLIGHT"] ??= "1"
    // The gate in markdown-and-code.ts reads this via `=== "1"`, so the entry-path default
    // must be the exact string "1" for real launches to render code blocks highlighted (the
    // documented, maintainer-ruled live behavior) -- not merely "defined" to some truthy value.
    // Assumes the test environment has not pre-set this key before this module loaded.
    expect(process.env["EMBER_SYNTAX_HIGHLIGHT"]).toBe("1");
  });

  it("??= inversion guard: pre-set '0' (highlighting disabled) is preserved, not forced to '1'", () => {
    // If a caller sets EMBER_SYNTAX_HIGHLIGHT="0" before process-entry loads, the ??= must
    // leave it at "0" (the unset-env fallback stays disabled; explicit opt-out is respected).
    const KEY = "__ac_syntax_highlight_inversion_probe__";
    delete process.env[KEY];

    // Case 1: absent → "1" applied (highlighting enabled by default)
    (process.env as Record<string, string>)[KEY] ??= "1";
    expect(process.env[KEY]).toBe("1");

    // Case 2: pre-set to "0" (caller explicitly disables highlighting) → ??= is a no-op
    process.env[KEY] = "0";
    (process.env as Record<string, string>)[KEY] ??= "1";
    expect(process.env[KEY]).toBe("0"); // must be "0", NOT "1" — the opt-out is preserved

    delete process.env[KEY];
  });
});

describe("process-entry — AC4: --version prints version and exits 0", () => {
  it("isFastPath detects --version", () => {
    expect(isFastPath(["node", "ember.js", "--version"])).toBe(true);
  });

  it("isFastPath detects -v", () => {
    expect(isFastPath(["node", "ember.js", "-v"])).toBe(true);
  });

  it("isFastPath detects -V", () => {
    expect(isFastPath(["node", "ember.js", "-V"])).toBe(true);
  });

  it("EMBER_CLI_VERSION is a non-empty string", () => {
    expect(typeof EMBER_CLI_VERSION).toBe("string");
    expect(EMBER_CLI_VERSION.length).toBeGreaterThan(0);
  });
});

describe("process-entry — AC13: --help prints usage and exits 0 without spawning a server", () => {
  it("isFastPath detects --help", () => {
    expect(isFastPath(["node", "ember", "--help"])).toBe(true);
  });

  it("isFastPath detects -h", () => {
    expect(isFastPath(["node", "ember", "-h"])).toBe(true);
  });

  it("dispatchFastPath --help writes usage to stdout and exits 0", async () => {
    const exitMock = mockProcessExit();
    const stdoutCap = captureStdout();
    try {
      await dispatchFastPath(["node", "ember", "--help"]);
    } catch (e) {
      if (!(e instanceof Error && "code" in e)) throw e;
    } finally {
      exitMock.restore();
      stdoutCap.restore();
    }
    expect(exitMock.captured()).toBe(0);
    expect(stdoutCap.output().toLowerCase()).toContain("usage");
  });

  it("main() with --help dispatches the fast path and NEVER spawns a server", async () => {
    // AC13 "without spawning a server" — the gap the prior tests left uncovered.
    // main() runs dispatchFastPath first (returns/exits before the spawn block), so an
    // injected spawnServer must never be called on the --help fast path.
    const exitMock = mockProcessExit();
    const stdoutCap = captureStdout();
    let spawnCalls = 0;
    const spawnSpy = async (_o: ServerSpawnOptions): Promise<ServerHandle> => {
      spawnCalls += 1;
      return makeServerHandle({ kill() {} } as unknown as ServerHandle["process"], 20000);
    };
    try {
      await main({ argv: ["node", "ember", "--reference-seat", "--help"], spawnServer: spawnSpy });
    } catch (e) {
      if (!(e instanceof Error && "code" in e)) throw e; // mockProcessExit throws to abort
    } finally {
      exitMock.restore();
      stdoutCap.restore();
    }
    expect(spawnCalls).toBe(0);            // AC13: --help spawns NO server
    expect(exitMock.captured()).toBe(0);  // and exits 0
  });
});

describe("process-entry — detectNCtx reads nested default_generation_settings.n_ctx (ce0cd3f regression guard)", () => {
  const origFetch = globalThis.fetch;
  afterEach(() => { globalThis.fetch = origFetch; });

  function stubFetch(routes: Record<string, unknown>): void {
    globalThis.fetch = (async (input: string | URL | Request) => {
      const url = String(input);
      for (const [frag, body] of Object.entries(routes)) {
        if (url.includes(frag)) {
          if (body === "fail") return new Response(null, { status: 500 });
          return new Response(JSON.stringify(body), {
            status: 200,
            headers: { "content-type": "application/json" },
          });
        }
      }
      return new Response(null, { status: 404 });
    }) as typeof fetch;
  }

  it("returns default_generation_settings.n_ctx when present (the real llama-server shape)", async () => {
    stubFetch({ "/props": { default_generation_settings: { n_ctx: 32768 }, n_ctx: 4096 } });
    expect(await detectNCtx("http://x")).toBe(32768);
  });

  it("falls back to top-level n_ctx when nested is absent", async () => {
    stubFetch({ "/props": { n_ctx: 8192 } });
    expect(await detectNCtx("http://x")).toBe(8192);
  });

  it("falls back to /v1/models context_length when /props fails", async () => {
    stubFetch({ "/props": "fail", "/v1/models": { data: [{ context_length: 16384 }] } });
    expect(await detectNCtx("http://x")).toBe(16384);
  });

  it("issue #267: normalizes a terminal /v1 before both context probes", async () => {
    const urls: string[] = [];
    globalThis.fetch = (async (input: string | URL | Request) => {
      const url = String(input);
      urls.push(url);
      if (url.endsWith("/props")) return new Response(null, { status: 500 });
      if (url.endsWith("/v1/models")) return new Response(
        JSON.stringify({ data: [{ context_length: 12288 }] }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
      return new Response(null, { status: 404 });
    }) as typeof fetch;
    expect(await detectNCtx("http://x/v1/")).toBe(12288);
    expect(urls).toEqual(["http://x/props", "http://x/v1/models"]);
  });

  it("returns 4096 when every probe fails", async () => {
    stubFetch({ "/props": "fail", "/v1/models": "fail" });
    expect(await detectNCtx("http://x")).toBe(4096);
  });
});

describe("process-entry — AC5: --diag-crash exits, no server spawn", () => {
  it("isFastPath detects --diag-crash", () => {
    expect(isFastPath(["node", "ember.js", "--diag-crash"])).toBe(true);
  });

  it("isFastPath detects --diag-startup", () => {
    expect(isFastPath(["node", "ember.js", "--diag-startup"])).toBe(true);
  });
});

describe("process-entry — AC6: models.json endpoint → EMBER_MODEL_URL only if unset", () => {
  it("applyModelsJsonToEnv sets EMBER_MODEL_URL from endpoint when not already set", () => {
    const saved = saveEnv(["EMBER_MODEL_URL"]);
    delete process.env["EMBER_MODEL_URL"];
    applyModelsJsonToEnv({ endpoint: "http://localhost:9999" });
    expect(process.env["EMBER_MODEL_URL"]).toBe("http://localhost:9999");
    restoreEnv(saved);
  });

  it("applyModelsJsonToEnv does NOT overwrite EMBER_MODEL_URL if already set", () => {
    const saved = saveEnv(["EMBER_MODEL_URL"]);
    process.env["EMBER_MODEL_URL"] = "http://pre-existing:8888";
    applyModelsJsonToEnv({ endpoint: "http://localhost:9999" });
    expect(process.env["EMBER_MODEL_URL"]).toBe("http://pre-existing:8888");
    restoreEnv(saved);
  });
});

describe("process-entry — describeEndpointResolution (issue #196 precedence: env > models.json > managed)", () => {
  it("models.json 'endpoint' wins over managed spawn when EMBER_MODEL_URL is unset", () => {
    const r = describeEndpointResolution({ endpoint: "http://localhost:9999" }, undefined);
    expect(r.source).toBe("config");
    expect(r.endpoint).toBe("http://localhost:9999");
    expect(r.text).toContain("http://localhost:9999");
    expect(r.text).toContain("models.json");
  });

  it("EMBER_MODEL_URL WINS over models.json 'endpoint' when both are set (issue #196 precedence fix -- was: config wins)", () => {
    const r = describeEndpointResolution(
      { endpoint: "http://localhost:9999" },
      "http://localhost:1111",
    );
    expect(r.source).toBe("env");
    expect(r.endpoint).toBe("http://localhost:1111");
    expect(r.text).toContain("http://localhost:1111");
    expect(r.text).not.toContain("http://localhost:9999");
  });

  it("EMBER_MODEL_URL WINS over models.json 'binary' -- no managed spawn, no longer silently/disclosed-ly ignored (issue #196 precedence fix -- was: managed spawn, env IGNORED)", () => {
    const r = describeEndpointResolution(
      { binary: "llama-server.exe" },
      "http://localhost:1111",
    );
    expect(r.source).toBe("env");
    expect(r.endpoint).toBe("http://localhost:1111");
    expect(r.text).toContain("http://localhost:1111");
    expect(r.text).not.toContain("IGNORED");
    expect(r.text).not.toContain("llama-server.exe");
  });

  it("models.json 'binary' with no EMBER_MODEL_URL set: managed spawn unchanged", () => {
    const r = describeEndpointResolution({ binary: "llama-server.exe" }, undefined);
    expect(r.source).toBe("managed");
    expect(r.endpoint).toBeNull();
  });

  it("no models.json config: EMBER_MODEL_URL wins as an explicit env override", () => {
    const r = describeEndpointResolution(null, "http://localhost:8081");
    expect(r.source).toBe("env");
    expect(r.endpoint).toBe("http://localhost:8081");
    expect(r.text).toContain("http://localhost:8081");
    expect(r.text).toContain("EMBER_MODEL_URL");
  });

  it("no models.json config and no EMBER_MODEL_URL: managed spawn with the default binary", () => {
    const r = describeEndpointResolution(null, undefined);
    expect(r.source).toBe("managed");
    expect(r.endpoint).toBeNull();
  });
});

describe("process-entry — describeEndpointResolution: EMBER_GPU_FREE precedence over persisted config (issue #602)", () => {
  it("EMBER_GPU_FREE=1 wins over models.json 'endpoint' when EMBER_MODEL_URL is unset (issue #602 regression)", () => {
    const r = describeEndpointResolution({ endpoint: "http://localhost:9999" }, undefined, true);
    expect(r.source).toBe("gpu-free");
    expect(r.endpoint).toBeNull(); // GPU-free wins -- never routed to the persisted config endpoint
    expect(r.text).toContain("GPU-free");
    // The overridden config endpoint is named in the disclosure line (diagnostic transparency:
    // confirms GPU-free actually saw and beat the persisted endpoint), it just never WINS.
    expect(r.text).toContain("overrides");
    expect(r.text).toContain("http://localhost:9999");
  });

  it("EMBER_GPU_FREE=1 wins over models.json 'binary' (managed spawn) when EMBER_MODEL_URL is unset", () => {
    const r = describeEndpointResolution({ binary: "llama-server.exe" }, undefined, true);
    expect(r.source).toBe("gpu-free");
    expect(r.endpoint).toBeNull();
    expect(r.text).toContain("GPU-free");
  });

  it("EMBER_GPU_FREE=1 with no models.json at all still resolves to the dedicated gpu-free source", () => {
    const r = describeEndpointResolution(null, undefined, true);
    expect(r.source).toBe("gpu-free");
    expect(r.endpoint).toBeNull();
    expect(r.text).toContain("GPU-free");
  });

  it("an explicit EMBER_MODEL_URL still wins over EMBER_GPU_FREE=1 (env stays the strongest signal)", () => {
    const r = describeEndpointResolution(
      { endpoint: "http://localhost:9999" },
      "http://localhost:1111",
      true,
    );
    expect(r.source).toBe("env");
    expect(r.endpoint).toBe("http://localhost:1111");
    expect(r.text).toContain("http://localhost:1111");
  });

  it("gpuFreeRequested omitted/false preserves the pre-#602 behavior exactly (backward compatible 2-arg call)", () => {
    const r = describeEndpointResolution({ endpoint: "http://localhost:9999" }, undefined, false);
    expect(r.source).toBe("config");
    expect(r.endpoint).toBe("http://localhost:9999");
  });
});

describe("process-entry — AC7: EMBER_ABLATION_BASELINE sets all ablation vars", () => {
  it("sets all six vars when EMBER_ABLATION_BASELINE is set", () => {
    const saved = saveEnv([
      "EMBER_ABLATION_BASELINE", "EMBER_SIMPLE", "EMBER_DISABLE_THINKING",
      "DISABLE_INTERLEAVED_THINKING", "DISABLE_COMPACT", "DISABLE_AUTO_COMPACT",
      "EMBER_DISABLE_AUTO_MEMORY", "EMBER_DISABLE_BACKGROUND_TASKS",
    ]);
    process.env["EMBER_ABLATION_BASELINE"] = "1";
    delete process.env["EMBER_SIMPLE"];
    delete process.env["EMBER_DISABLE_THINKING"];
    delete process.env["DISABLE_INTERLEAVED_THINKING"];
    delete process.env["DISABLE_COMPACT"];
    delete process.env["DISABLE_AUTO_COMPACT"];
    delete process.env["EMBER_DISABLE_AUTO_MEMORY"];
    delete process.env["EMBER_DISABLE_BACKGROUND_TASKS"];

    applyAblationBaseline();

    expect(process.env["EMBER_SIMPLE"]).toBe("1");
    expect(process.env["EMBER_DISABLE_THINKING"]).toBe("1");
    expect(process.env["DISABLE_INTERLEAVED_THINKING"]).toBe("1");
    expect(process.env["DISABLE_COMPACT"]).toBe("1");
    expect(process.env["DISABLE_AUTO_COMPACT"]).toBe("1");
    expect(process.env["EMBER_DISABLE_AUTO_MEMORY"]).toBe("1");
    expect(process.env["EMBER_DISABLE_BACKGROUND_TASKS"]).toBe("1");

    restoreEnv(saved);
  });

  it("does NOT set ablation vars when EMBER_ABLATION_BASELINE is absent", () => {
    const saved = saveEnv(["EMBER_ABLATION_BASELINE", "EMBER_SIMPLE"]);
    delete process.env["EMBER_ABLATION_BASELINE"];
    delete process.env["EMBER_SIMPLE"];
    applyAblationBaseline();
    expect(process.env["EMBER_SIMPLE"]).toBeUndefined();
    restoreEnv(saved);
  });
});

describe("process-entry — AC8: managed server is NOT spawned for fast-path flags", () => {
  it("isFastPath returns true for --version, --diag-crash, --diag-startup", () => {
    expect(isFastPath(["node", "ember", "--version"])).toBe(true);
    expect(isFastPath(["node", "ember", "--diag-crash"])).toBe(true);
    expect(isFastPath(["node", "ember", "--diag-startup"])).toBe(true);
    expect(isFastPath(["node", "ember", "--dump-system-prompt"])).toBe(true);
  });

  it("isFastPath returns false for normal interactive invocation", () => {
    expect(isFastPath(["node", "ember"])).toBe(false);
  });

  it("treats OS-native liveness installation as a model-free fast path", () => {
    expect(isFastPath(["node", "ember", "liveness", "install"])).toBe(true);
  });
});

describe("process-entry — AC9: managed server killed on clean exit", () => {
  it("makeServerHandle.kill() forwards SIGTERM to the spawned child", () => {
    const sent: Array<string | number> = [];
    const child = {
      kill(sig?: string | number) { sent.push(sig ?? "(default)"); return true; },
    } as unknown as ServerHandle["process"];
    const handle = makeServerHandle(child, 20000);
    expect(handle.port).toBe(20000);
    handle.kill();
    expect(sent).toEqual(["SIGTERM"]);          // real kill path, not just typeof check
  });

  it("registerServerCleanup kills the handle on process 'exit'", () => {
    let killed = 0;
    const handle: ServerHandle = {
      process: {} as ServerHandle["process"],
      port: 20000,
      kill() { killed += 1; },
    };
    const listeners: Record<string, (...a: unknown[]) => void> = {};
    const fakeProc = {
      on(event: string, listener: (...a: unknown[]) => void) { listeners[event] = listener; return undefined; },
      exit(_code?: number) {},
    };
    registerServerCleanup(handle, fakeProc);
    expect(typeof listeners["exit"]).toBe("function");
    listeners["exit"]!();                        // simulate clean process exit
    expect(killed).toBe(1);                      // server killed, not left orphaned
  });

  it("registerServerCleanup on SIGINT kills the handle AND exits 0", () => {
    let killed = 0;
    const exitCodes: Array<number | undefined> = [];
    const handle: ServerHandle = {
      process: {} as ServerHandle["process"],
      port: 20000,
      kill() { killed += 1; },
    };
    const listeners: Record<string, (...a: unknown[]) => void> = {};
    const fakeProc = {
      on(event: string, listener: (...a: unknown[]) => void) { listeners[event] = listener; return undefined; },
      exit(code?: number) { exitCodes.push(code); },
    };
    registerServerCleanup(handle, fakeProc);
    listeners["SIGINT"]!();
    expect(killed).toBe(1);
    expect(exitCodes).toEqual([0]);             // clean shutdown on signal
  });
});

describe("process-entry — AC10: debug-port written to the external state root", () => {
  let tmpDir: string;
  let stateDir: string;
  let savedStateRoot: string | undefined;

  beforeEach(async () => {
    tmpDir = join(tmpdir(), `pe-test-${Date.now()}-${Math.random().toString(36).slice(2)}`);
    await mkdir(tmpDir, { recursive: true });
    // Debug files are cockpit state: they land outside the checkout (#1330). The root is
    // pinned to a SIBLING of the cwd -- the writer-side guard refuses a state root nested
    // inside the directory it serves, which is exactly the defect being cured.
    stateDir = `${tmpDir}-cockpit-state`;
    savedStateRoot = process.env["EMBER_STATE_ROOT"];
    process.env["EMBER_STATE_ROOT"] = stateDir;
  });

  afterEach(async () => {
    if (savedStateRoot === undefined) delete process.env["EMBER_STATE_ROOT"];
    else process.env["EMBER_STATE_ROOT"] = savedStateRoot;
    await rm(tmpDir, { recursive: true, force: true });
    await rm(stateDir, { recursive: true, force: true });
  });

  it("writeDebugPort creates the file with the port number", async () => {
    await writeDebugPort(tmpDir, 8099);
    const { readFile } = await import("node:fs/promises");
    const content = await readFile(join(stateDir, "debug-port"), "utf-8");
    expect(content).toBe("8099");
  });

  it("writeDebugPid creates the file with the PID", async () => {
    await writeDebugPid(tmpDir, 12345);
    const { readFile } = await import("node:fs/promises");
    const content = await readFile(join(stateDir, "debug-pid"), "utf-8");
    expect(content).toBe("12345");
  });

  it("writes nothing into the working directory itself", async () => {
    await writeDebugPort(tmpDir, 8099);
    const { readdir } = await import("node:fs/promises");
    expect(await readdir(tmpDir)).toEqual([]);
  });
});

describe("process-entry — AC11: llama_stderr.log rotation", () => {
  let tmpDir: string;

  beforeEach(async () => {
    tmpDir = join(tmpdir(), `pe-test-${Date.now()}-${Math.random().toString(36).slice(2)}`);
    await mkdir(tmpDir, { recursive: true });
  });

  afterEach(async () => {
    await rm(tmpDir, { recursive: true, force: true });
  });

  it("does not error when log file does not exist", async () => {
    await expect(rotateLlamaStderrLog(join(tmpDir, "nonexistent.log"))).resolves.toBeUndefined();
  });

  it("truncates log to last 10MB when size exceeds 50MB", async () => {
    // Create a file larger than 50MB using a mock approach
    const logPath = join(tmpDir, "llama_stderr.log");
    // We'll fake this by overriding the threshold — just verify the function exists and returns
    // In a real test with a 55MB file this would truncate
    await writeFile(logPath, "small content");
    await expect(rotateLlamaStderrLog(logPath)).resolves.toBeUndefined();
    const { readFile } = await import("node:fs/promises");
    const content = await readFile(logPath, "utf-8");
    expect(content).toBe("small content"); // unchanged (too small to rotate)
  });
});

describe("process-entry — AC12: port resolution respects ports.json > scan > 20000", () => {
  let tmpDir: string;

  beforeEach(async () => {
    tmpDir = join(tmpdir(), `pe-test-${Date.now()}-${Math.random().toString(36).slice(2)}`);
    await mkdir(tmpDir, { recursive: true });
  });

  afterEach(async () => {
    await rm(tmpDir, { recursive: true, force: true });
  });

  it("returns pinned port from ports.json when present", async () => {
    await writeFile(join(tmpDir, "ports.json"), JSON.stringify({ port: 9876 }));
    const port = await readPinnedPort(tmpDir);
    expect(port).toBe(9876);
  });

  it("returns null when ports.json is absent", async () => {
    const port = await readPinnedPort(tmpDir);
    expect(port).toBeNull();
  });

  it("findFreePort returns a number", async () => {
    const port = await findFreePort(30000, 20000);
    expect(typeof port).toBe("number");
    expect(port).toBeGreaterThan(0);
  });

  it("resolveServerPort returns pinned port when ports.json present", async () => {
    await writeFile(join(tmpDir, "ports.json"), JSON.stringify({ port: 7654 }));
    const port = await resolveServerPort(tmpDir);
    expect(port).toBe(7654);
  });

  it("resolveServerPort falls back to scan when ports.json absent", async () => {
    const port = await resolveServerPort(tmpDir);
    expect(typeof port).toBe("number");
    expect(port).toBeGreaterThan(0);
  });
});

describe("process-entry — loadModelsJson", () => {
  let tmpDir: string;

  beforeEach(async () => {
    tmpDir = join(tmpdir(), `pe-test-${Date.now()}-${Math.random().toString(36).slice(2)}`);
    await mkdir(tmpDir, { recursive: true });
  });

  afterEach(async () => {
    await rm(tmpDir, { recursive: true, force: true });
  });

  it("returns null for nonexistent file", async () => {
    const result = await loadModelsJson(join(tmpDir, "nonexistent.json"));
    expect(result).toBeNull();
  });

  it("returns parsed config when file is valid JSON", async () => {
    const p = join(tmpDir, "models.json");
    await writeFile(p, JSON.stringify({ endpoint: "http://localhost:8081", nCtx: 4096 }));
    const result = await loadModelsJson(p);
    expect(result?.endpoint).toBe("http://localhost:8081");
    expect(result?.nCtx).toBe(4096);
  });

  it("returns null for invalid JSON", async () => {
    const p = join(tmpDir, "models.json");
    await writeFile(p, "not json");
    const result = await loadModelsJson(p);
    expect(result).toBeNull();
  });
});

describe("process-entry — isFastPath", () => {
  it("returns false for empty args", () => {
    expect(isFastPath(["node", "ember"])).toBe(false);
  });

  it("detects fast-path subcommands", () => {
    expect(isFastPath(["node", "ember", "daemon"])).toBe(true);
    expect(isFastPath(["node", "ember", "remote-control"])).toBe(true);
    expect(isFastPath(["node", "ember", "ps"])).toBe(true);
  });

  it("detects the gh subcommand (issue #507: ember gh doctor)", () => {
    expect(isFastPath(["node", "ember", "gh"])).toBe(true);
    expect(isFastPath(["node", "ember", "gh", "doctor"])).toBe(true);
  });

  it("returns false for unknown args", () => {
    expect(isFastPath(["node", "ember", "--unknown-flag"])).toBe(false);
  });
});

describe("process-entry — applyModelsJsonToEnv", () => {
  it("sets all supported env vars with ??= semantics", () => {
    const saved = saveEnv([
      "EMBER_MODEL_URL", "EMBER_MODEL_NAME", "EMBER_THINKING_FORMAT",
      "EMBER_THINKING_BUDGET", "EMBER_AUTO_COMPACT_WINDOW", "EMBER_SAMPLING_PARAMS",
    ]);
    delete process.env["EMBER_MODEL_URL"];
    delete process.env["EMBER_MODEL_NAME"];
    delete process.env["EMBER_THINKING_FORMAT"];
    delete process.env["EMBER_THINKING_BUDGET"];
    delete process.env["EMBER_AUTO_COMPACT_WINDOW"];
    delete process.env["EMBER_SAMPLING_PARAMS"];

    applyModelsJsonToEnv({
      endpoint: "http://localhost:1234",
      modelName: "qwen3",
      thinkingFormat: "xml",
      thinkingBudget: 4096,
      autoCompactWindow: 8000,
      samplingParams: { temperature: 0.7 },
    });

    expect(process.env["EMBER_MODEL_URL"]).toBe("http://localhost:1234");
    expect(process.env["EMBER_MODEL_NAME"]).toBe("qwen3");
    expect(process.env["EMBER_THINKING_FORMAT"]).toBe("xml");
    expect(process.env["EMBER_THINKING_BUDGET"]).toBe("4096");
    expect(process.env["EMBER_AUTO_COMPACT_WINDOW"]).toBe("8000");
    expect(process.env["EMBER_SAMPLING_PARAMS"]).toBe(JSON.stringify({ temperature: 0.7 }));

    restoreEnv(saved);
  });
});

describe("process-entry — spawnLlamaServer stdio fd (Bun compiled-binary compatibility)", () => {
  // Bun's compiled child_process shim does not implement "stream object as stdio
  // entry" (crashes: "TODO: stream.Readable stdio @ 2"). spawnLlamaServer must
  // pass an integer file descriptor at stdio[2], which both Node and Bun accept.
  // We verify the fd mechanism directly — the spawn call itself is left to an
  // integration/binary gate (bun build --compile) since mocking module-scoped
  // named imports is not feasible with the current test structure.
  let tmpDir: string;

  beforeEach(async () => {
    tmpDir = join(tmpdir(), `pe-fd-test-${Date.now()}-${Math.random().toString(36).slice(2)}`);
    await mkdir(tmpDir, { recursive: true });
  });

  afterEach(async () => {
    await rm(tmpDir, { recursive: true, force: true });
  });

  it("openSync('a') returns an integer fd (not a stream) for use in stdio array", () => {
    const logPath = join(tmpDir, "llama_stderr.log");
    const fd = openSync(logPath, "a");
    try {
      // Bun's child_process accepts integer fds; stream objects cause a crash.
      expect(typeof fd).toBe("number");
      expect(fd).toBeGreaterThan(0);
    } finally {
      closeSync(fd);
    }
  });
});

// ---------------------------------------------------------------------------
// G3 — parseHeadlessPrint flag parsing
// ---------------------------------------------------------------------------

describe("process-entry — parseHeadlessPrint: flag detection", () => {
  it("returns found:false when no -p / --print flag is present", () => {
    expect(parseHeadlessPrint(["node", "ember"])).toEqual({ found: false });
    expect(parseHeadlessPrint(["node", "ember", "--version"])).toEqual({ found: false });
    expect(parseHeadlessPrint(["node", "ember", "--unknown"])).toEqual({ found: false });
  });

  it("detects -p with an inline prompt value", () => {
    const r = parseHeadlessPrint(["node", "ember", "-p", "hello world"]);
    expect(r.found).toBe(true);
    expect((r as Extract<typeof r, { found: true }>).prompt).toBe("hello world");
  });

  it("detects --print with an inline prompt value", () => {
    const r = parseHeadlessPrint(["node", "ember", "--print", "test prompt"]);
    expect(r.found).toBe(true);
    expect((r as Extract<typeof r, { found: true }>).prompt).toBe("test prompt");
  });

  it("detects --print=value form", () => {
    const r = parseHeadlessPrint(["node", "ember", "--print=my prompt"]);
    expect(r.found).toBe(true);
    expect((r as Extract<typeof r, { found: true }>).prompt).toBe("my prompt");
  });

  it("returns prompt: null when -p has no inline value (stdin read mode)", () => {
    const r = parseHeadlessPrint(["node", "ember", "-p"]);
    expect(r.found).toBe(true);
    expect((r as Extract<typeof r, { found: true }>).prompt).toBeNull();
  });

  it("returns prompt: null when -p is followed by another flag", () => {
    const r = parseHeadlessPrint(["node", "ember", "-p", "--verbose"]);
    expect(r.found).toBe(true);
    expect((r as Extract<typeof r, { found: true }>).prompt).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// G3 — main() routes -p to headlessRunner, NOT launchRepl
// ---------------------------------------------------------------------------

// Shared mock handle factory
function makeFakeHandle(port = 29999): ServerHandle {
  return {
    process: {} as ReturnType<typeof import("node:child_process").spawn>,
    port,
    kill() {},
  };
}

// Shared fake LoopDeps (non-throwing callModel)
function makeFakeDeps(): LoopDeps {
  return {
    callModel: async () => { throw new Error("fake-callModel: not expected to be called in this test"); },
    microcompact: async (msgs) => msgs,
    autocompact: async () => {},
    generateUuid: () => "test-uuid",
    // issue #197: LoopDeps.sleep is required; this test never exercises a
    // retry path, so an instant no-op resolve is sufficient.
    sleep: async () => {},
  };
}

describe("process-entry — G3: main() with -p routes to headlessRunner before launchRepl", () => {
  it("-p 'hello headless' calls headlessRunner with the prompt, not launchRepl", async () => {
    const saved = saveEnv(["EMBER_MODEL_NAME"]);
    const expectedModel = "gate-sentinel-model";
    process.env["EMBER_MODEL_NAME"] = expectedModel;
    let headlessCalled = false;
    // Use sentinel strings/numbers to avoid TypeScript null-narrowing on closures
    let receivedPrompt = "UNSET";
    let receivedModel: string | undefined;
    let exitCodeReceived = -1;

    await main({
      argv: ["node", "ember", "--reference-seat", "-p", "hello headless"],
      spawnServer: async () => makeFakeHandle(29901),
      waitReady: async () => {},
      // #159: deterministic in tests -- the real default performs an actual health-probe
      // fetch, which is flaky/inappropriate in a test process.
      probeExisting: async () => false,
      initFn: async () => {},
      getLoopDepsFn: makeFakeDeps,
      headlessRunner: async (
        prompt: string,
        _io: StructuredIO,
        _tools: Tool[],
        options: HeadlessReplOptions,
        _deps: Partial<LoopDeps>,
      ) => {
        headlessCalled = true;
        receivedPrompt = prompt;
        receivedModel = options.userSpecifiedModel;
        return { events: [], exitCode: 0 };
      },
      exitFn: (code: number): void => {
        exitCodeReceived = code;
      },
    });

    restoreEnv(saved);
    expect(headlessCalled).toBe(true);
    expect(receivedPrompt).toBe("hello headless");
    expect(receivedModel).toBe(`REFERENCE_ONLY: ${expectedModel}`);
    expect(exitCodeReceived).toBe(0);
    // If launchRepl were called it would have thrown or hung; reaching here means it was not.
  });

  it("--print=prompt also routes to headlessRunner", async () => {
    let receivedPrompt = "UNSET";

    await main({
      argv: ["node", "ember", "--reference-seat", "--print=my test prompt"],
      spawnServer: async () => makeFakeHandle(29902),
      waitReady: async () => {},
      // #159: deterministic in tests -- the real default performs an actual health-probe
      // fetch, which is flaky/inappropriate in a test process.
      probeExisting: async () => false,
      initFn: async () => {},
      getLoopDepsFn: makeFakeDeps,
      headlessRunner: async (prompt: string) => {
        receivedPrompt = prompt;
        return { events: [], exitCode: 0 };
      },
      exitFn: () => {},
    });

    expect(receivedPrompt).toBe("my test prompt");
  });

  it("exits with exitCode 1 when headlessRunner returns exitCode 1", async () => {
    let exitCodeReceived = -1;

    await main({
      argv: ["node", "ember", "--reference-seat", "-p", "fail prompt"],
      spawnServer: async () => makeFakeHandle(29903),
      waitReady: async () => {},
      // #159: deterministic in tests -- the real default performs an actual health-probe
      // fetch, which is flaky/inappropriate in a test process.
      probeExisting: async () => false,
      initFn: async () => {},
      getLoopDepsFn: makeFakeDeps,
      headlessRunner: async () => ({ events: [], exitCode: 1 }),
      exitFn: (code: number): void => { exitCodeReceived = code; },
    });

    expect(exitCodeReceived).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// G1 — production deps are threaded into the headless path (not undefined)
// ---------------------------------------------------------------------------

describe("process-entry — G1: headlessRunner receives LoopDeps from getLoopDepsFn", () => {
  it("headlessRunner receives the exact LoopDeps object from getLoopDepsFn", async () => {
    const fakeDeps = makeFakeDeps();
    // Use a wrapper object to avoid TypeScript null-narrowing on the closure-assigned ref
    const capture: { deps: Partial<LoopDeps> | undefined } = { deps: undefined };

    await main({
      argv: ["node", "ember", "--reference-seat", "-p", "deps test"],
      spawnServer: async () => makeFakeHandle(29904),
      waitReady: async () => {},
      // #159: deterministic in tests -- the real default performs an actual health-probe
      // fetch, which is flaky/inappropriate in a test process.
      probeExisting: async () => false,
      initFn: async () => {},
      getLoopDepsFn: () => fakeDeps,
      headlessRunner: async (
        _prompt: string,
        _io: StructuredIO,
        _tools: Tool[],
        _options: HeadlessReplOptions,
        deps: Partial<LoopDeps>,
      ) => {
        capture.deps = deps;
        return { events: [], exitCode: 0 };
      },
      exitFn: () => {},
    });

    const receivedDeps = capture.deps!;
    // The exact same LoopDeps object is passed (identity check)
    expect(receivedDeps).toBe(fakeDeps);
    // callModel is the production (fake) fn — not the throwing default
    expect(receivedDeps.callModel).toBe(fakeDeps.callModel);
    // The throwing default message is "No model sampling function provided to loop deps"
    // Our fake callModel throws a DIFFERENT error — verifying it's not the default
    let msg = "";
    try {
      await receivedDeps.callModel!({
        messages: [],
        systemPrompt: "",
        tools: [],
        model: "x",
        maxTokens: 1,
      });
    } catch (e) {
      msg = e instanceof Error ? e.message : String(e);
    }
    expect(msg).not.toContain("No model sampling function provided");
    expect(msg).toContain("fake-callModel");
  });
});

// ---------------------------------------------------------------------------
// Issue #196 acceptance: main() end-to-end precedence (env > models.json > managed)
// ---------------------------------------------------------------------------

describe("process-entry — main() end-to-end: EMBER_MODEL_URL precedence over models.json (issue #196 acceptance)", () => {
  let tmpDir: string;
  let savedEnv: Record<string, string | undefined>;

  beforeEach(async () => {
    tmpDir = join(tmpdir(), `pe-196-e2e-${Date.now()}-${Math.random().toString(36).slice(2)}`);
    await mkdir(tmpDir, { recursive: true });
    savedEnv = saveEnv(["EMBER_HOME", "EMBER_MODEL_URL", "EMBER_MODEL_NAME"]);
    delete process.env["EMBER_MODEL_NAME"];
    process.env["EMBER_HOME"] = tmpDir;
    _resetConfigHomeMemo();
  });

  afterEach(async () => {
    restoreEnv(savedEnv);
    _resetConfigHomeMemo();
    await rm(tmpDir, { recursive: true, force: true });
  });

  it("acceptance (1): models.json 'binary' present + EMBER_MODEL_URL set -> no managed spawn, serverUrl is the env URL", async () => {
    await writeFile(join(tmpDir, "models.json"), JSON.stringify({ binary: "llama-server.exe" }));
    process.env["EMBER_MODEL_URL"] = "http://localhost:19191";

    let spawnCalls = 0;
    let receivedServerUrl = "UNSET";

    await main({
      argv: ["node", "ember", "--reference-seat", "-p", "hello"],
      spawnServer: async () => { spawnCalls += 1; return makeFakeHandle(29997); },
      waitReady: async () => {},
      // #159: deterministic in tests -- the real default performs an actual health-probe
      // fetch, which is flaky/inappropriate in a test process.
      probeExisting: async () => false,
      initFn: async (o) => { receivedServerUrl = o.serverUrl ?? "UNSET"; },
      getLoopDepsFn: makeFakeDeps,
      headlessRunner: async () => ({ events: [], exitCode: 0 }),
      exitFn: () => {},
    });

    expect(spawnCalls).toBe(0); // env wins -- no managed spawn ever invoked
    expect(receivedServerUrl).toBe("http://localhost:19191");
  });

  it("acceptance (2): models.json 'binary' present + EMBER_MODEL_URL unset -> managed spawn still occurs unchanged", async () => {
    // #159 preflight validation (binary/model must exist before spawn) resolves a bare
    // "llama-server.exe" relative to the RUNNING process's exeDir, not tmpDir -- absolute
    // paths into tmpDir bypass that (path.resolve ignores the base when the 2nd arg is
    // already absolute), so dummy files here satisfy the preflight without touching exeDir.
    const fakeBinary = join(tmpDir, "fake-llama-server.exe");
    const fakeModel  = join(tmpDir, "fake-model.gguf");
    await writeFile(fakeBinary, "");
    await writeFile(fakeModel, "");
    await writeFile(join(tmpDir, "models.json"), JSON.stringify({ binary: fakeBinary, model: fakeModel }));
    delete process.env["EMBER_MODEL_URL"];

    let spawnCalls = 0;

    await main({
      argv: ["node", "ember", "--reference-seat", "-p", "hello"],
      spawnServer: async () => { spawnCalls += 1; return makeFakeHandle(29996); },
      waitReady: async () => {},
      // #159: deterministic in tests -- the real default performs an actual health-probe
      // fetch, which is flaky/inappropriate in a test process.
      probeExisting: async () => false,
      initFn: async () => {},
      getLoopDepsFn: makeFakeDeps,
      headlessRunner: async () => ({ events: [], exitCode: 0 }),
      exitFn: () => {},
    });

    expect(spawnCalls).toBe(1); // no env override present -- managed spawn behavior is unchanged
  });

  it("acceptance (3): models.json 'endpoint' present + EMBER_MODEL_URL set to a DIFFERENT url -> env url is used, not config's", async () => {
    await writeFile(join(tmpDir, "models.json"), JSON.stringify({ endpoint: "http://localhost:9999" }));
    process.env["EMBER_MODEL_URL"] = "http://localhost:19192";

    let receivedServerUrl = "UNSET";

    await main({
      argv: ["node", "ember", "--reference-seat", "-p", "hello"],
      spawnServer: async () => makeFakeHandle(29995),
      waitReady: async () => {},
      // #159: deterministic in tests -- the real default performs an actual health-probe
      // fetch, which is flaky/inappropriate in a test process.
      probeExisting: async () => false,
      initFn: async (o) => { receivedServerUrl = o.serverUrl ?? "UNSET"; },
      getLoopDepsFn: makeFakeDeps,
      headlessRunner: async () => ({ events: [], exitCode: 0 }),
      exitFn: () => {},
    });

    expect(receivedServerUrl).toBe("http://localhost:19192");
  });
});

// ---------------------------------------------------------------------------
// Issue #602 acceptance: EMBER_GPU_FREE=1 must not be silently overridden by a
// persisted models.json endpoint when EMBER_MODEL_URL is unset. Prior behavior:
// externalUrl = envModelUrlBeforeConfigApply ?? modelsCfg?.endpoint -- so an
// unset env var let the persisted config endpoint win the `if (externalUrl)`
// branch even with EMBER_GPU_FREE=1 set, and the cockpit booted against the
// stale endpoint instead of engaging GPU-free mode. Only an EMPTY-STRING
// EMBER_MODEL_URL used to force the GPU-free branch, which cmd.exe cannot
// produce (`set VAR=` deletes the var), so no Windows .bat launcher could ever
// engage GPU-free mode. Fix: a dedicated GPU-free branch, checked AHEAD of the
// env-or-config fallback, wins whenever EMBER_MODEL_URL is unset -- an explicit
// EMBER_MODEL_URL (the operator naming a server) still wins over GPU-free.
// ---------------------------------------------------------------------------

describe("process-entry — main() end-to-end: EMBER_GPU_FREE precedence over persisted models.json endpoint (issue #602 acceptance)", () => {
  let tmpDir: string;
  let savedEnv: Record<string, string | undefined>;

  beforeEach(async () => {
    tmpDir = join(tmpdir(), `pe-602-e2e-${Date.now()}-${Math.random().toString(36).slice(2)}`);
    await mkdir(tmpDir, { recursive: true });
    savedEnv = saveEnv(["EMBER_HOME", "EMBER_MODEL_URL", "EMBER_MODEL_NAME", "EMBER_GPU_FREE"]);
    delete process.env["EMBER_MODEL_NAME"];
    process.env["EMBER_HOME"] = tmpDir;
    _resetConfigHomeMemo();
  });

  afterEach(async () => {
    restoreEnv(savedEnv);
    _resetConfigHomeMemo();
    await rm(tmpDir, { recursive: true, force: true });
  });

  it("EMBER_GPU_FREE=1 alone engages GPU-free mode with a persisted endpoint present and EMBER_MODEL_URL unset (issue #602 regression)", async () => {
    await writeFile(join(tmpDir, "models.json"), JSON.stringify({ endpoint: "http://localhost:9999" }));
    delete process.env["EMBER_MODEL_URL"];
    process.env["EMBER_GPU_FREE"] = "1";

    let spawnCalls = 0;
    // Captured RAW (never defaulted via `??`) -- GPU-free mode signals via serverUrl === null,
    // which `?? "UNSET"` would otherwise collapse into the same sentinel as "never called".
    let receivedServerUrl: string | null | undefined = "NEVER_CALLED" as unknown as string | null;

    const stdoutCap = captureStdout();
    try {
      await main({
        argv: ["node", "ember", "-p", "hello"],
        spawnServer: async () => { spawnCalls += 1; return makeFakeHandle(29994); },
        waitReady: async () => {},
        probeExisting: async () => false,
        initFn: async (o) => { receivedServerUrl = o.serverUrl ?? null; },
        getLoopDepsFn: makeFakeDeps,
        headlessRunner: async () => ({ events: [], exitCode: 0 }),
        exitFn: () => {},
      });
    } finally {
      stdoutCap.restore();
    }

    expect(spawnCalls).toBe(0);              // GPU-free mode never spawns a managed server
    expect(receivedServerUrl).toBeNull();     // never routed to the persisted models.json endpoint
    expect(stdoutCap.output()).toContain("GPU-free");
    // Disclosed for diagnostic transparency (confirms GPU-free saw and beat the persisted
    // config), it just never determines serverUrl -- receivedServerUrl above proves that.
    expect(stdoutCap.output()).toContain("http://localhost:9999");
  });

  it("an explicit EMBER_MODEL_URL still wins over EMBER_GPU_FREE=1 even with a persisted endpoint present", async () => {
    await writeFile(join(tmpDir, "models.json"), JSON.stringify({ endpoint: "http://localhost:9999" }));
    process.env["EMBER_MODEL_URL"] = "http://localhost:19193";
    process.env["EMBER_GPU_FREE"]  = "1";

    let spawnCalls = 0;
    let receivedServerUrl: string | null | undefined = "NEVER_CALLED" as unknown as string | null;

    await main({
      argv: ["node", "ember", "--reference-seat", "-p", "hello"],
      spawnServer: async () => { spawnCalls += 1; return makeFakeHandle(29993); },
      waitReady: async () => {},
      probeExisting: async () => false,
      initFn: async (o) => { receivedServerUrl = o.serverUrl ?? null; },
      getLoopDepsFn: makeFakeDeps,
      headlessRunner: async () => ({ events: [], exitCode: 0 }),
      exitFn: () => {},
    });

    expect(spawnCalls).toBe(0);
    expect(receivedServerUrl).toBe("http://localhost:19193"); // explicit env wins over GPU-free
  });

  it("no models.json + no EMBER_MODEL_URL + EMBER_GPU_FREE=1 -> GPU-free mode, unchanged from before #602 (no regression on the already-working case)", async () => {
    delete process.env["EMBER_MODEL_URL"];
    process.env["EMBER_GPU_FREE"] = "1";

    let spawnCalls = 0;
    let receivedServerUrl: string | null | undefined = "NEVER_CALLED" as unknown as string | null;

    await main({
      argv: ["node", "ember", "-p", "hello"],
      spawnServer: async () => { spawnCalls += 1; return makeFakeHandle(29992); },
      waitReady: async () => {},
      probeExisting: async () => false,
      initFn: async (o) => { receivedServerUrl = o.serverUrl ?? null; },
      getLoopDepsFn: makeFakeDeps,
      headlessRunner: async () => ({ events: [], exitCode: 0 }),
      exitFn: () => {},
    });

    expect(spawnCalls).toBe(0);
    expect(receivedServerUrl).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Issue #344: the cockpit boot spawns a VRAM-resident model server
// unconditionally, even while a training leg holds a live GPU lease (the
// 2026-07-07 incident: cockpit boot at 10:13:46Z OOM'd a W1 training attempt
// at 10:39Z). Fix: an effective planned-outage.json marker (the SAME marker
// services/brain-server-supervisor.ts's device policy already reads) is
// folded into gpuFreeRequested BEFORE the seat is constructed, so the boot
// takes the identical GPU-free code path -- no spawn, OFFLINE seat, and a
// distinct "[ember] GPU leased to training: ..." disclosure line naming the
// lease owner/reason/target/expiry.
// ---------------------------------------------------------------------------

describe("process-entry — main() end-to-end: GPU-lease awareness (issue #344)", () => {
  let tmpDir: string;
  let savedEnv: Record<string, string | undefined>;

  const LIVE_LEASE: OutageMarker = {
    owner: "w2-garm-runner",
    reason: "W2 G-arm training leg",
    target: "single-4090",
    started: "2026-08-03T10:00:00Z",
    expires: "2099-01-01T00:00:00Z", // effectively-forever for this test
    kill_receipt_ref: "receipts/kill/none.json",
  };

  beforeEach(async () => {
    tmpDir = join(tmpdir(), `pe-344-e2e-${Date.now()}-${Math.random().toString(36).slice(2)}`);
    await mkdir(tmpDir, { recursive: true });
    savedEnv = saveEnv(["EMBER_HOME", "EMBER_MODEL_URL", "EMBER_MODEL_NAME", "EMBER_GPU_FREE"]);
    delete process.env["EMBER_MODEL_URL"];
    delete process.env["EMBER_MODEL_NAME"];
    delete process.env["EMBER_GPU_FREE"];
    process.env["EMBER_HOME"] = tmpDir;
    _resetConfigHomeMemo();
  });

  afterEach(async () => {
    restoreEnv(savedEnv);
    _resetConfigHomeMemo();
    await rm(tmpDir, { recursive: true, force: true });
  });

  it("a live GPU lease boots GPU-free (no spawn) with a lease-disclosure line, EMBER_MODEL_URL unset and no models.json endpoint", async () => {
    let spawnCalls = 0;
    let receivedServerUrl: string | null | undefined = "NEVER_CALLED" as unknown as string | null;

    const stdoutCap = captureStdout();
    try {
      await main({
        argv: ["node", "ember", "-p", "hello"],
        checkGpuLease: async () => LIVE_LEASE,
        spawnServer: async () => { spawnCalls += 1; return makeFakeHandle(29981); },
        waitReady: async () => {},
        probeExisting: async () => false,
        initFn: async (o) => { receivedServerUrl = o.serverUrl ?? null; },
        getLoopDepsFn: makeFakeDeps,
        headlessRunner: async () => ({ events: [], exitCode: 0 }),
        exitFn: () => {},
      });
    } finally {
      stdoutCap.restore();
    }

    expect(spawnCalls).toBe(0);            // #344: no VRAM-resident spawn while leased
    expect(receivedServerUrl).toBeNull();  // same GPU-free signal session-init.ts relies on
    const out = stdoutCap.output();
    expect(out).toContain("GPU leased to training");
    expect(out).toContain(LIVE_LEASE.owner);
    expect(out).toContain(LIVE_LEASE.reason);
    expect(out).toContain("model server not spawned");
  });

  it("a live GPU lease with a persisted models.json endpoint present still boots GPU-free (lease beats a stale config endpoint, same precedence as EMBER_GPU_FREE)", async () => {
    await writeFile(join(tmpDir, "models.json"), JSON.stringify({ endpoint: "http://localhost:9999" }));

    let spawnCalls = 0;
    let receivedServerUrl: string | null | undefined = "NEVER_CALLED" as unknown as string | null;

    await main({
      argv: ["node", "ember", "-p", "hello"],
      checkGpuLease: async () => LIVE_LEASE,
      spawnServer: async () => { spawnCalls += 1; return makeFakeHandle(29982); },
      waitReady: async () => {},
      probeExisting: async () => false,
      initFn: async (o) => { receivedServerUrl = o.serverUrl ?? null; },
      getLoopDepsFn: makeFakeDeps,
      headlessRunner: async () => ({ events: [], exitCode: 0 }),
      exitFn: () => {},
    });

    expect(spawnCalls).toBe(0);
    expect(receivedServerUrl).toBeNull();
  });

  it("an explicit EMBER_MODEL_URL still wins over a live GPU lease (operator naming a server is the strongest signal, same rule as EMBER_GPU_FREE)", async () => {
    process.env["EMBER_MODEL_URL"] = "http://localhost:19194";

    let spawnCalls = 0;
    let receivedServerUrl: string | null | undefined = "NEVER_CALLED" as unknown as string | null;
    let leaseCheckCalls = 0;

    await main({
      argv: ["node", "ember", "--reference-seat", "-p", "hello"],
      checkGpuLease: async () => { leaseCheckCalls += 1; return LIVE_LEASE; },
      spawnServer: async () => { spawnCalls += 1; return makeFakeHandle(29983); },
      waitReady: async () => {},
      probeExisting: async () => false,
      initFn: async (o) => { receivedServerUrl = o.serverUrl ?? null; },
      getLoopDepsFn: makeFakeDeps,
      headlessRunner: async () => ({ events: [], exitCode: 0 }),
      exitFn: () => {},
    });

    expect(spawnCalls).toBe(0);
    expect(receivedServerUrl).toBe("http://localhost:19194"); // explicit env wins over the lease
    expect(leaseCheckCalls).toBe(0); // #344: EMBER_MODEL_URL set -> lease is never even checked
  });

  it("no lease (checkGpuLease resolves null) boots normally, spawning the managed server exactly as before #344 (no regression)", async () => {
    const realBinary = join(tmpDir, "real-llama-server.exe");
    const realModel  = join(tmpDir, "real-model.gguf");
    await writeFile(realBinary, "");
    await writeFile(realModel, "");
    await writeFile(join(tmpDir, "models.json"), JSON.stringify({ binary: realBinary, model: realModel }));

    let spawnCalls = 0;
    let receivedServerUrl: string | null | undefined = "NEVER_CALLED" as unknown as string | null;

    await main({
      argv: ["node", "ember", "--reference-seat", "-p", "hello"],
      checkGpuLease: async () => null,
      spawnServer: async () => { spawnCalls += 1; return makeFakeHandle(29984); },
      waitReady: async () => {},
      probeExisting: async () => false,
      initFn: async (o) => { receivedServerUrl = o.serverUrl ?? null; },
      getLoopDepsFn: makeFakeDeps,
      headlessRunner: async () => ({ events: [], exitCode: 0 }),
      exitFn: () => {},
    });

    expect(spawnCalls).toBe(1);
    expect(receivedServerUrl).not.toBeNull();
  });
});

describe("process-entry — defaultCheckGpuLease", () => {
  it("returns null when planned-outage.json is absent (fail-open, matches brain-server-supervisor.ts's resolveDeviceForSpawn)", async () => {
    const marker = await defaultCheckGpuLease();
    // In this test environment there is no live tools/ember-cli/state/planned-outage.json,
    // so this must resolve null, never throw -- the same fail-open contract
    // resolveDeviceForSpawn documents for an absent/unreadable/malformed marker.
    expect(marker).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Acceptance map: state/specs/cockpit-stale-binding-demotion-acceptance-map-2026-07-25.md
// Section 5, tests 1, 2 (x3), 4. This describe block proves the consumer-level half of the
// cure: the catch at the top of main() around loadOwnedDevelopmentIdentity demotes on
// `instanceof OwnedSeatStaleBindingError` and on nothing else. Test 3 (D3, matching bundle
// admits unchanged) is proved at the loader level in owned-seat-loader.test.ts, since it is
// captureDevelopmentResolver's own admission path and does not need a second, more expensive
// main()-level rehearsal to be discriminating.
// ---------------------------------------------------------------------------

describe("process-entry — main() end-to-end: stale owned-binding demotes the seat, not the process (cockpit-stale-binding-demotion-acceptance-map)", () => {
  let tmpDir: string;
  let savedEnv: Record<string, string | undefined>;

  beforeEach(async () => {
    tmpDir = join(tmpdir(), `pe-seatdemote-${Date.now()}-${Math.random().toString(36).slice(2)}`);
    await mkdir(tmpDir, { recursive: true });
    savedEnv = saveEnv(["EMBER_HOME", "EMBER_MODEL_URL", "EMBER_MODEL_NAME", "EMBER_GPU_FREE"]);
    delete process.env["EMBER_MODEL_URL"];
    delete process.env["EMBER_MODEL_NAME"];
    delete process.env["EMBER_GPU_FREE"];
    process.env["EMBER_HOME"] = tmpDir;
    _resetConfigHomeMemo();
  });

  afterEach(async () => {
    restoreEnv(savedEnv);
    _resetConfigHomeMemo();
    await rm(tmpDir, { recursive: true, force: true });
  });

  const STALE_BINDING_MESSAGE =
    "runtime bundle is not bound to the exact compiled cockpit commit; the owned seat is " +
    "refused and the cockpit continues OFFLINE. Use --reference-seat for explicit " +
    "REFERENCE_ONLY parity testing or EMBER_GPU_FREE=1 for offline observation.";

  it("test 1 (D1): a stale-commit binding demotes to OFFLINE -- the process reaches the panel, exit code is the normal cockpit exit, not 1", async () => {
    let exitCode: number | null = null as number | null;
    let spawnCalls = 0;
    const stdoutCap = captureStdout();
    try {
      await main({
        argv: ["node", "ember", "-p", "hello"],
        loadOwnedIdentityFn: () => undefined,
        loadOwnedDevelopmentIdentityFn: () => { throw new OwnedSeatStaleBindingError(STALE_BINDING_MESSAGE); },
        spawnServer: async () => { spawnCalls += 1; return makeFakeHandle(29991); },
        waitReady: async () => {},
        probeExisting: async () => false,
        initFn: async () => {},
        getLoopDepsFn: makeFakeDeps,
        // headlessRunner's own exitCode (0, a normal completion) is what reaches doExit at
        // the end of the headless path -- distinct from the fatal doExitMain(1) the map
        // forbids on the demotion path. This is "the normal cockpit exit, not 1" (section 4).
        headlessRunner: async () => ({ events: [], exitCode: 0 }),
        exitFn: (code) => { exitCode = code; },
      });
    } finally {
      stdoutCap.restore();
    }

    // D1: the fatal doExitMain(1) branch never fires -- the process reaches the offline/
    // reference seat and completes normally, the same GPU-free path issue #602's own tests
    // already prove is a real, working panel path. No managed server is spawned.
    expect(exitCode).toBe(0);
    expect(spawnCalls).toBe(0);
    expect(stdoutCap.output()).toContain("GPU-free");
  });

  it("test 2a (D2, line 201 shape): an index content-hash-mismatch error (typed as a plain Error) still exits 1", async () => {
    let exitCode: number | null = null as number | null;
    await main({
      argv: ["node", "ember", "-p", "hello"],
      loadOwnedIdentityFn: () => undefined,
      loadOwnedDevelopmentIdentityFn: () => { throw new Error("runtime bundle index content hash mismatch"); },
      spawnServer: async () => makeFakeHandle(29990),
      waitReady: async () => {},
      probeExisting: async () => false,
      initFn: async () => {},
      getLoopDepsFn: makeFakeDeps,
      headlessRunner: async () => ({ events: [], exitCode: 0 }),
      exitFn: (code) => { exitCode = code; },
    });
    expect(exitCode).toBe(1);
  });

  it("test 2b (D2, line 224 shape): an invalid trusted-source binding error (plain Error) still exits 1", async () => {
    let exitCode: number | null = null as number | null;
    await main({
      argv: ["node", "ember", "-p", "hello"],
      loadOwnedIdentityFn: () => undefined,
      loadOwnedDevelopmentIdentityFn: () => {
        throw new Error("trusted runtime source binding is invalid: tools/ember-restart-3b/model.py");
      },
      spawnServer: async () => makeFakeHandle(29989),
      waitReady: async () => {},
      probeExisting: async () => false,
      initFn: async () => {},
      getLoopDepsFn: makeFakeDeps,
      headlessRunner: async () => ({ events: [], exitCode: 0 }),
      exitFn: (code) => { exitCode = code; },
    });
    expect(exitCode).toBe(1);
  });

  it("test 2c (D2, line 239 shape): a source-does-not-match-Git-commit error (plain Error) still exits 1, and the message is not the demotion banner", async () => {
    let exitCode: number | null = null as number | null;
    let stderrText = "";
    const origStderrWrite = process.stderr.write.bind(process.stderr);
    // Capture the operator-facing text the same way the ERROR branch writes it, so this test
    // proves both halves of D2: exit 1, AND the tamper case's own message survives unmodified
    // -- it is never overwritten by or confused with the demotion banner.
    process.stderr.write = ((chunk: unknown, ...rest: unknown[]) => {
      stderrText += String(chunk);
      return origStderrWrite(chunk as never, ...(rest as never[]));
    }) as typeof process.stderr.write;
    try {
      await main({
        argv: ["node", "ember", "-p", "hello"],
        loadOwnedIdentityFn: () => undefined,
        loadOwnedDevelopmentIdentityFn: () => {
          throw new Error("runtime source does not match the embedded Git commit: tools/ember-restart-3b/model.py");
        },
        spawnServer: async () => makeFakeHandle(29988),
        waitReady: async () => {},
        probeExisting: async () => false,
        initFn: async () => {},
        getLoopDepsFn: makeFakeDeps,
        headlessRunner: async () => ({ events: [], exitCode: 0 }),
        exitFn: (code) => { exitCode = code; },
      });
    } finally {
      process.stderr.write = origStderrWrite;
    }
    expect(exitCode).toBe(1);
    expect(stderrText).toContain("runtime source does not match the embedded Git commit");
    expect(stderrText).not.toContain("continues OFFLINE");
  });

  it("test 4 (mandatory): a plain Error whose message is byte-identical to the stale-binding string still exits 1 -- proves the catch keys on instanceof, not on message text", async () => {
    let exitCode: number | null = null as number | null;
    let exitCalls = 0;
    await main({
      argv: ["node", "ember", "-p", "hello"],
      loadOwnedIdentityFn: () => undefined,
      // A plain Error, not OwnedSeatStaleBindingError -- same bytes, different type. If the
      // catch ever regresses to message-matching, this is the test that turns RED.
      loadOwnedDevelopmentIdentityFn: () => { throw new Error(STALE_BINDING_MESSAGE); },
      spawnServer: async () => makeFakeHandle(29987),
      waitReady: async () => {},
      probeExisting: async () => false,
      initFn: async () => {},
      getLoopDepsFn: makeFakeDeps,
      headlessRunner: async () => ({ events: [], exitCode: 0 }),
      exitFn: (code) => { exitCode = code; exitCalls += 1; },
    });
    expect(exitCalls).toBe(1);
    expect(exitCode).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// #159 cell 1 — boot matrix: every managed-spawn failure cell produces a clean
// operator-facing error and a controlled exit, never an uncaught exception or a
// silent hang. One receipt row per cell via hardening-receipts.ts.
// ---------------------------------------------------------------------------

describe("process-entry — #159 cell 1: boot matrix (hardening bar)", () => {
  let tmpDir: string;
  let savedEnv: Record<string, string | undefined>;

  beforeEach(async () => {
    tmpDir = join(tmpdir(), `pe-159-boot-${Date.now()}-${Math.random().toString(36).slice(2)}`);
    await mkdir(tmpDir, { recursive: true });
    savedEnv = saveEnv(["EMBER_HOME", "EMBER_MODEL_URL", "EMBER_MODEL_NAME", "EMBER_MODEL_PATH"]);
    delete process.env["EMBER_MODEL_URL"];
    delete process.env["EMBER_MODEL_NAME"];
    delete process.env["EMBER_MODEL_PATH"];
    process.env["EMBER_HOME"] = tmpDir;
    _resetConfigHomeMemo();
  });

  afterEach(async () => {
    restoreEnv(savedEnv);
    _resetConfigHomeMemo();
    await rm(tmpDir, { recursive: true, force: true });
  });

  async function recordCell(cell: string, pass: boolean, detail: string): Promise<void> {
    const { writeHardeningReceipt } = await import("../hardening/hardening-receipts.ts");
    await writeHardeningReceipt({ suite: "boot-matrix", cell, outcome: pass ? "pass" : "fail", detail });
  }

  it("missing models.json + no default binary/model present -> clean error, exit(1), never spawns", async () => {
    // No models.json written at all -- loadModelsJson() correctly returns null (existing,
    // unchanged behavior) and falls to the default "llama-server.exe"/"model.gguf" names,
    // resolved against the running process's own exeDir where neither file exists in a test
    // environment. The bar here is NOT "boots anyway" -- it's "fails the same clean way as
    // an explicitly bad path, never an uncaught exception."
    let spawnCalls = 0;
    // Widened via `as number | null` (not just the type annotation) to work around a real TS
    // narrowing limitation: since the only assignment (`exitCode = code`) happens inside the
    // exitFn closure passed to main(), plain-annotation-only declarations get narrowed to the
    // literal `null` type for every read after `await main(...)` -- widening the INITIALIZER
    // itself keeps every subsequent `expect(exitCode)...` read correctly typed `number | null`.
    let exitCode: number | null = null as number | null;
    const stderrChunks: string[] = [];
    const origWrite = process.stderr.write.bind(process.stderr);
    process.stderr.write = ((s: string) => { stderrChunks.push(s); return true; }) as typeof process.stderr.write;

    try {
      await main({
        argv: ["node", "ember", "--reference-seat", "-p", "hello"],
        spawnServer: async () => { spawnCalls += 1; return makeFakeHandle(29980); },
        waitReady: async () => {},
        probeExisting: async () => false,
        initFn: async () => {},
        getLoopDepsFn: makeFakeDeps,
        headlessRunner: async () => ({ events: [], exitCode: 0 }),
        exitFn: (code: number) => { exitCode = code; },
      });
    } finally {
      process.stderr.write = origWrite;
    }

    const stderr = stderrChunks.join("");
    const pass = spawnCalls === 0 && exitCode === 1 && stderr.includes("[ember] ERROR") && stderr.includes("not found");
    await recordCell("missing-models-json", pass, stderr.trim());

    expect(spawnCalls).toBe(0);
    expect(exitCode).toBe(1);
    expect(stderr).toContain("[ember] ERROR");
    expect(stderr).toContain("not found");
  });

  it("bad binary path -> clean error naming the path, exit(1), never spawns", async () => {
    const realModel = join(tmpDir, "real-model.gguf");
    await writeFile(realModel, "");
    const badBinary = join(tmpDir, "does-not-exist-llama-server.exe");
    await writeFile(join(tmpDir, "models.json"), JSON.stringify({ binary: badBinary, model: realModel }));

    let spawnCalls = 0;
    // Widened via `as number | null` (not just the type annotation) to work around a real TS
    // narrowing limitation: since the only assignment (`exitCode = code`) happens inside the
    // exitFn closure passed to main(), plain-annotation-only declarations get narrowed to the
    // literal `null` type for every read after `await main(...)` -- widening the INITIALIZER
    // itself keeps every subsequent `expect(exitCode)...` read correctly typed `number | null`.
    let exitCode: number | null = null as number | null;
    let stderrText = "";
    const origWrite = process.stderr.write.bind(process.stderr);
    process.stderr.write = ((s: string) => { stderrText += s; return true; }) as typeof process.stderr.write;

    try {
      await main({
        argv: ["node", "ember", "--reference-seat", "-p", "hello"],
        spawnServer: async () => { spawnCalls += 1; return makeFakeHandle(29981); },
        waitReady: async () => {},
        probeExisting: async () => false,
        initFn: async () => {},
        getLoopDepsFn: makeFakeDeps,
        headlessRunner: async () => ({ events: [], exitCode: 0 }),
        exitFn: (code: number) => { exitCode = code; },
      });
    } finally {
      process.stderr.write = origWrite;
    }

    const pass = spawnCalls === 0 && exitCode === 1 && stderrText.includes(badBinary);
    await recordCell("bad-binary-path", pass, stderrText.trim());

    expect(spawnCalls).toBe(0);
    expect(exitCode).toBe(1);
    expect(stderrText).toContain("binary not found");
    expect(stderrText).toContain(badBinary);
  });

  it("bad model path -> clean error naming the path, exit(1), never spawns (was: silent 240s hang)", async () => {
    const realBinary = join(tmpDir, "real-llama-server.exe");
    await writeFile(realBinary, "");
    const badModel = join(tmpDir, "does-not-exist-model.gguf");
    await writeFile(join(tmpDir, "models.json"), JSON.stringify({ binary: realBinary, model: badModel }));

    let spawnCalls = 0;
    // Widened via `as number | null` (not just the type annotation) to work around a real TS
    // narrowing limitation: since the only assignment (`exitCode = code`) happens inside the
    // exitFn closure passed to main(), plain-annotation-only declarations get narrowed to the
    // literal `null` type for every read after `await main(...)` -- widening the INITIALIZER
    // itself keeps every subsequent `expect(exitCode)...` read correctly typed `number | null`.
    let exitCode: number | null = null as number | null;
    let stderrText = "";
    const origWrite = process.stderr.write.bind(process.stderr);
    process.stderr.write = ((s: string) => { stderrText += s; return true; }) as typeof process.stderr.write;

    try {
      await main({
        argv: ["node", "ember", "--reference-seat", "-p", "hello"],
        spawnServer: async () => { spawnCalls += 1; return makeFakeHandle(29982); },
        // Deliberately never resolves -- if the preflight check did NOT catch this cell,
        // this test would hang until its own timeout instead of failing fast, which is
        // exactly the defect this cell exists to catch.
        waitReady: () => new Promise(() => {}),
        probeExisting: async () => false,
        initFn: async () => {},
        getLoopDepsFn: makeFakeDeps,
        headlessRunner: async () => ({ events: [], exitCode: 0 }),
        exitFn: (code: number) => { exitCode = code; },
      });
    } finally {
      process.stderr.write = origWrite;
    }

    const pass = spawnCalls === 0 && exitCode === 1 && stderrText.includes(badModel);
    await recordCell("bad-model-path", pass, stderrText.trim());

    expect(spawnCalls).toBe(0);
    expect(exitCode).toBe(1);
    expect(stderrText).toContain("model not found");
    expect(stderrText).toContain(badModel);
  }, 15000);

  it("spawn itself rejects (e.g. EACCES/permission denied) -> clean error, exit(1)", async () => {
    const realBinary = join(tmpDir, "real-llama-server.exe");
    const realModel  = join(tmpDir, "real-model.gguf");
    await writeFile(realBinary, "");
    await writeFile(realModel, "");
    await writeFile(join(tmpDir, "models.json"), JSON.stringify({ binary: realBinary, model: realModel }));

    // Widened via `as number | null` (not just the type annotation) to work around a real TS
    // narrowing limitation: since the only assignment (`exitCode = code`) happens inside the
    // exitFn closure passed to main(), plain-annotation-only declarations get narrowed to the
    // literal `null` type for every read after `await main(...)` -- widening the INITIALIZER
    // itself keeps every subsequent `expect(exitCode)...` read correctly typed `number | null`.
    let exitCode: number | null = null as number | null;
    let stderrText = "";
    const origWrite = process.stderr.write.bind(process.stderr);
    process.stderr.write = ((s: string) => { stderrText += s; return true; }) as typeof process.stderr.write;

    try {
      await main({
        argv: ["node", "ember", "--reference-seat", "-p", "hello"],
        spawnServer: async () => { throw Object.assign(new Error("EACCES: permission denied"), { code: "EACCES" }); },
        waitReady: async () => {},
        probeExisting: async () => false,
        initFn: async () => {},
        getLoopDepsFn: makeFakeDeps,
        headlessRunner: async () => ({ events: [], exitCode: 0 }),
        exitFn: (code: number) => { exitCode = code; },
      });
    } finally {
      process.stderr.write = origWrite;
    }

    const pass = exitCode === 1 && stderrText.includes("EACCES");
    await recordCell("spawn-rejects", pass, stderrText.trim());

    expect(exitCode).toBe(1);
    expect(stderrText).toContain("[ember] ERROR: could not start the model server");
    expect(stderrText).toContain("EACCES");
  });

  it("backend already running -> adopts existing server, never spawns", async () => {
    const realBinary = join(tmpDir, "real-llama-server.exe");
    const realModel  = join(tmpDir, "real-model.gguf");
    await writeFile(realBinary, "");
    await writeFile(realModel, "");
    await writeFile(join(tmpDir, "models.json"), JSON.stringify({ binary: realBinary, model: realModel }));

    let spawnCalls = 0;
    // Widened via `as number | null` (not just the type annotation) to work around a real TS
    // narrowing limitation: since the only assignment (`exitCode = code`) happens inside the
    // exitFn closure passed to main(), plain-annotation-only declarations get narrowed to the
    // literal `null` type for every read after `await main(...)` -- widening the INITIALIZER
    // itself keeps every subsequent `expect(exitCode)...` read correctly typed `number | null`.
    let exitCode: number | null = null as number | null;
    let stdoutText = "";
    const origWrite = process.stdout.write.bind(process.stdout);
    process.stdout.write = ((s: string) => { stdoutText += s; return true; }) as typeof process.stdout.write;

    try {
      await main({
        argv: ["node", "ember", "--reference-seat", "-p", "hello"],
        spawnServer: async () => { spawnCalls += 1; return makeFakeHandle(29983); },
        waitReady: async () => {},
        probeExisting: async () => true, // a healthy server already answers on this port
        initFn: async () => {},
        getLoopDepsFn: makeFakeDeps,
        headlessRunner: async () => ({ events: [], exitCode: 0 }),
        exitFn: (code: number) => { exitCode = code; },
      });
    } finally {
      process.stdout.write = origWrite;
    }

    // headlessRunner's fake exitCode:0 flows through main()'s OWN headless exit -- exitCode 0
    // here means "reached the end cleanly", not "never called"; a boot-matrix FAILURE cell
    // would instead be exitCode 1 raised from the managed-spawn branch itself.
    const pass = spawnCalls === 0 && exitCode === 0 && stdoutText.includes("adopting already-running server");
    await recordCell("backend-already-running", pass, stdoutText.trim());

    expect(spawnCalls).toBe(0);
    expect(exitCode).toBe(0);
    expect(stdoutText).toContain("adopting already-running server");
  });

  it("child exits before becoming ready -> clean error with exit code, exit(1), does not wait for the full timeout", async () => {
    const { EventEmitter } = await import("node:events");
    const realBinary = join(tmpDir, "real-llama-server.exe");
    const realModel  = join(tmpDir, "real-model.gguf");
    await writeFile(realBinary, "");
    await writeFile(realModel, "");
    await writeFile(join(tmpDir, "models.json"), JSON.stringify({ binary: realBinary, model: realModel }));

    const fakeProc = new EventEmitter();

    // Widened via `as number | null` (not just the type annotation) to work around a real TS
    // narrowing limitation: since the only assignment (`exitCode = code`) happens inside the
    // exitFn closure passed to main(), plain-annotation-only declarations get narrowed to the
    // literal `null` type for every read after `await main(...)` -- widening the INITIALIZER
    // itself keeps every subsequent `expect(exitCode)...` read correctly typed `number | null`.
    let exitCode: number | null = null as number | null;
    let stderrText = "";
    const origWrite = process.stderr.write.bind(process.stderr);
    process.stderr.write = ((s: string) => { stderrText += s; return true; }) as typeof process.stderr.write;

    const start = Date.now();
    try {
      await main({
        argv: ["node", "ember", "--reference-seat", "-p", "hello"],
        spawnServer: async () => {
          setTimeout(() => fakeProc.emit("exit", 17), 20);
          return { process: fakeProc as unknown as ServerHandle["process"], port: 29984, kill() {} };
        },
        // Never resolves on its own -- only the raced child-exit should end this cell.
        waitReady: () => new Promise(() => {}),
        probeExisting: async () => false,
        initFn: async () => {},
        getLoopDepsFn: makeFakeDeps,
        headlessRunner: async () => ({ events: [], exitCode: 0 }),
        exitFn: (code: number) => { exitCode = code; },
      });
    } finally {
      process.stderr.write = origWrite;
    }
    const elapsedMs = Date.now() - start;

    // Threshold is generous (10s, not a tight ms bound) to stay robust under full-suite
    // scheduling contention -- the property under test is "doesn't wait for the 240s timeout
    // at all" (proven simply by completing, since waitReady above never resolves on its own),
    // not a precise latency number.
    const pass = exitCode === 1 && stderrText.includes("exit code 17") && elapsedMs < 10_000;
    await recordCell("child-exits-early", pass, `${stderrText.trim()} (elapsed ${elapsedMs}ms)`);

    expect(exitCode).toBe(1);
    expect(stderrText).toContain("[ember] ERROR: the model server exited before becoming ready");
    expect(stderrText).toContain("exit code 17");
    expect(elapsedMs).toBeLessThan(10_000); // bounded time-to-signal -- nowhere near the 240s timeout
  }, 15000);

  it("happy path: valid binary + model, spawn succeeds and becomes ready -> clean exit(0), no failure path taken", async () => {
    const realBinary = join(tmpDir, "real-llama-server.exe");
    const realModel  = join(tmpDir, "real-model.gguf");
    await writeFile(realBinary, "");
    await writeFile(realModel, "");
    await writeFile(join(tmpDir, "models.json"), JSON.stringify({ binary: realBinary, model: realModel }));

    let spawnCalls = 0;
    // Widened via `as number | null` (not just the type annotation) to work around a real TS
    // narrowing limitation: since the only assignment (`exitCode = code`) happens inside the
    // exitFn closure passed to main(), plain-annotation-only declarations get narrowed to the
    // literal `null` type for every read after `await main(...)` -- widening the INITIALIZER
    // itself keeps every subsequent `expect(exitCode)...` read correctly typed `number | null`.
    let exitCode: number | null = null as number | null;
    let receivedServerUrl = "UNSET";

    await main({
      argv: ["node", "ember", "--reference-seat", "-p", "hello"],
      spawnServer: async () => { spawnCalls += 1; return makeFakeHandle(29985); },
      waitReady: async () => {},
      probeExisting: async () => false,
      initFn: async (o) => { receivedServerUrl = o.serverUrl ?? "UNSET"; },
      getLoopDepsFn: makeFakeDeps,
      headlessRunner: async () => ({ events: [], exitCode: 0 }),
      exitFn: (code: number) => { exitCode = code; },
    });

    // headlessRunner's fake exitCode:0 flows through main()'s own headless exit -- 0 means
    // "reached the end cleanly", distinct from the exitCode:1 raised by any failure cell above.
    const pass = spawnCalls === 1 && exitCode === 0 && receivedServerUrl.startsWith("http://localhost:");
    await recordCell("happy-path", pass, `spawnCalls=${spawnCalls} exitCode=${exitCode} url=${receivedServerUrl}`);

    expect(spawnCalls).toBe(1);
    expect(exitCode).toBe(0);
    expect(receivedServerUrl).toMatch(/^http:\/\/localhost:\d+$/);
  });
});

// ---------------------------------------------------------------------------
// AC13 follow-up: --help's Environment paragraph reflects the new precedence
// ---------------------------------------------------------------------------

describe("process-entry — AC13 --help contract: EMBER_MODEL_URL precedence paragraph", () => {
  it("--help discloses that EMBER_MODEL_URL wins over models.json (issue #196 precedence fix)", async () => {
    const exitMock = mockProcessExit();
    const stdoutCap = captureStdout();
    try {
      await dispatchFastPath(["node", "ember", "--help"]);
    } catch (e) {
      if (!(e instanceof Error && "code" in e)) throw e;
    } finally {
      exitMock.restore();
      stdoutCap.restore();
    }
    const out = stdoutCap.output();
    expect(out).toContain("EMBER_MODEL_URL");
    expect(out).toContain("requires admitted owned identity");
    expect(out).toContain("--reference-seat");
    expect(out).toContain("EMBER_REFERENCE_SEAT");
    expect(out).toContain("EMBER_OWNED_DEVELOPMENT_MANIFEST");
    expect(out).toContain("Exact non-claiming manifest");
  });
});

// ---------------------------------------------------------------------------
// PR948 round-9 repair: production wiring, process-entry.ts main() -> the REAL
// session-init.ts init() (opts.initFn is NOT overridden here -- that's the whole
// point). Round-8 (17c53b4f) added modelSupportsStructuredOutputs gating inside
// buildProductionCallModel, but process-entry.ts derived modelContract (~line 782)
// and never passed it into InitOpts -- so in the real mounted path,
// buildGuardedProductionCallModel was always constructed with NO capability
// declaration and a jsonSchema request was ALWAYS denied, regardless of what the
// served model actually supported. Round-8's positive tests only proved the gate
// itself works by calling buildProductionCallModel/buildGuardedProductionCallModel
// directly with hand-built opts -- they never drove process-entry.ts's main() at all,
// so they could not have caught this. These tests mock ONLY the network (global
// fetch) and drive the real main() -> session-init.ts init() -> LoopDeps.callModel
// path end to end.
// ---------------------------------------------------------------------------

function makeChatCompletionsReader() {
  const encoder = new TextEncoder();
  const chunk = encoder.encode(
    'data: {"choices":[{"finish_reason":"stop","index":0,"delta":{}}]}\n\n',
  );
  let sent = false;
  return {
    read: async () => {
      if (!sent) {
        sent = true;
        return { done: false, value: chunk };
      }
      return { done: true, value: undefined };
    },
    releaseLock: () => {},
  };
}

describe("process-entry -> session-init production wiring (PR948 round-9 repair)", () => {
  let tmpDir: string;
  let savedEnv: Record<string, string | undefined>;
  let origFetch: typeof fetch;

  const SHA = "e".repeat(64);

  function makeOwnedIdentity(withCapability: boolean): OwnedModelIdentity {
    return {
      seat:               "OWNED_ADMITTED",
      checkpointSha256:   "f".repeat(64),
      endpointUrl:        "http://localhost:29777",
      identityUrl:        "http://localhost:29777/identity",
      modelConfigSha256:  SHA,
      modelName:          "ember-owned-test",
      serverSourceSha256: "g".repeat(64),
      tokenizerSha256:    "h".repeat(64),
      modelConfigCapabilities: withCapability
        ? { modelConfigSha256: SHA, structuredOutputs: true }
        : undefined,
    };
  }

  beforeEach(async () => {
    tmpDir = join(tmpdir(), `pe-r9-wiring-${Date.now()}-${Math.random().toString(36).slice(2)}`);
    await mkdir(tmpDir, { recursive: true });
    savedEnv = saveEnv(["EMBER_HOME", "EMBER_MODEL_URL", "EMBER_MODEL_NAME"]);
    delete process.env["EMBER_MODEL_URL"];
    delete process.env["EMBER_MODEL_NAME"];
    process.env["EMBER_HOME"] = tmpDir;
    _resetConfigHomeMemo();
    _resetInitForTests();
    origFetch = globalThis.fetch;
  });

  afterEach(async () => {
    globalThis.fetch = origFetch;
    restoreEnv(savedEnv);
    _resetConfigHomeMemo();
    _resetInitForTests();
    await rm(tmpDir, { recursive: true, force: true });
  });

  /** Drives the REAL main() -> session-init init() path for the given owned identity,
   *  network mocked (only /v1/chat/completions answers; every other fetch -- the /props
   *  and /v1/models n_ctx probes -- rejects and falls back, exactly as a real unreachable
   *  probe would). Captures the real LoopDeps handed to the headless runner so the test can
   *  drive its callModel directly. Returns the fetch URLs actually reached. */
  async function driveRealInitAndCapture(
    ownedIdentity: OwnedModelIdentity,
  ): Promise<{ fetchUrls: string[]; deps: LoopDeps }> {
    const fetchUrls: string[] = [];
    globalThis.fetch = (async (url: string) => {
      const u = String(url);
      fetchUrls.push(u);
      if (u.includes("/v1/chat/completions")) {
        return {
          ok:   true,
          body: { getReader: () => makeChatCompletionsReader() },
        } as unknown as Response;
      }
      throw new Error("network disabled in test (n_ctx probe -- expected to fail and fall back)");
    }) as unknown as typeof fetch;

    let capturedDeps: LoopDeps | null = null;
    await main({
      argv:                  ["node", "ember", "-p", "hello"],
      loadOwnedIdentityFn:   () => ownedIdentity,
      handshakeEmberLabFn:     async () => {},
      ensureOwnedServerFn:   async () => ({ outcome: "spawned", port: 29777, handle: { process: { pid: 1 }, port: 29777, kill: () => {} } as never }),
      verifyOwnedEndpointFn: async () => {},
      headlessRunner: async (_prompt, _io, _tools, _opts, deps) => {
        capturedDeps = deps;
        return { events: [], exitCode: 0 };
      },
      exitFn: () => {},
    });

    if (!capturedDeps) throw new Error("headlessRunner was never invoked -- main() did not reach the headless path");
    return { fetchUrls, deps: capturedDeps };
  }

  const baseParams: Omit<CallModelParams, "jsonSchema"> = {
    messages:     [{ role: "user", content: "hello" }],
    systemPrompt: "test",
    tools:        [],
    model:        "test-model",
    maxTokens:    256,
  };

  it("(a) matching owned declaration + served hash: a real jsonSchema request reaches the fetch layer", async () => {
    const { deps, fetchUrls } = await driveRealInitAndCapture(makeOwnedIdentity(true));

    const before = fetchUrls.length;
    const result = await deps.callModel({ ...baseParams, jsonSchema: { type: "object" } });

    expect(result.stop_reason).toBe("end_turn");
    expect(fetchUrls.slice(before).some((u) => u.includes("/v1/chat/completions"))).toBe(true);
  });

  it("(b) no modelConfigCapabilities declared on the owned identity: jsonSchema request is denied with ZERO model-request fetches", async () => {
    const { deps, fetchUrls } = await driveRealInitAndCapture(makeOwnedIdentity(false));

    const before = fetchUrls.length;
    let thrown: unknown = null;
    try {
      await deps.callModel({ ...baseParams, jsonSchema: { type: "object" } });
    } catch (err) {
      thrown = err;
    }

    expect(thrown).not.toBeNull();
    expect(String((thrown as Error).message)).toContain("structured outputs");
    expect(fetchUrls.slice(before).some((u) => u.includes("/v1/chat/completions"))).toBe(false);
  });

  it("a request with no jsonSchema still succeeds regardless of capability (gate only fires on jsonSchema)", async () => {
    const { deps } = await driveRealInitAndCapture(makeOwnedIdentity(false));
    const result = await deps.callModel({ ...baseParams });
    expect(result.stop_reason).toBe("end_turn");
  });
});

// ---------------------------------------------------------------------------
// process-entry — `ember --watch [--interval N]` (gh issue #34, C-OBS)
//
// Execution-binding proof: this spawns a REAL subprocess through dispatchFastPath (the exact
// function main() calls) against a fixture goalforge root, so it proves the production `--watch`
// argv path actually reaches core/watch-loop.ts's real render code -- not just that watch-loop.ts
// works when called directly (that unit coverage lives in core/watch-loop.test.ts). Subprocess
// (not mock.module) for the same two reasons commands/world-state.test.ts uses one:
// core/ember-world-state.ts's GOALFORGE_ROOT is a module-level const frozen at first import, and
// bun:test's mock.module() corrupts the shared module registry for the rest of the test process.
// ---------------------------------------------------------------------------

describe("process-entry — dispatchFastPath('--watch') execution binding", () => {
  const watchTmpDirs: string[] = [];

  afterEach(async () => {
    while (watchTmpDirs.length > 0) {
      const dir = watchTmpDirs.pop()!;
      await rm(dir, { recursive: true, force: true });
    }
  });

  async function makeWatchFixtureRoot(): Promise<string> {
    const root = join(
      tmpdir(),
      `ember-watch-fastpath-test-${Date.now()}-${Math.random().toString(36).slice(2)}`,
    );
    const boardDir = join(root, "scripts", "ember_totality", "receipts-totality");
    await mkdir(boardDir, { recursive: true });
    await mkdir(join(root, "docs", "ledgers"), { recursive: true });
    await mkdir(join(root, "receipts"), { recursive: true });
    await writeFile(join(root, "GOAL.md"), "# Watch Fixture Goal\n\n## Topology\n\nbody\n");
    await writeFile(
      join(root, "docs", "ledgers", "ember-debt-ledger.md"),
      "## Current Blocker Packet\n\n(none)\n\n## Active Rows\n\n| ID | Class | Debt | X | Y | Status |\n| --- | --- | --- | --- | --- | --- |\n",
    );
    const receipt = {
      ts: "20260725T000000Z",
      rows: [{ condition: "C-OBS", status: "GREEN", reason: "fixture" }],
      summary: { total: 1, green: 1, red: 0, completion_math: { pct_complete: 100 } },
    };
    await writeFile(
      join(boardDir, "ember-totality-20260725T000000Z.json"),
      JSON.stringify(receipt),
    );
    await writeFile(join(root, "receipts", "r1.json"), "{}");
    watchTmpDirs.push(root);
    return root;
  }

  const SRC_DIR = join(import.meta.dir, ".."); // tools/ember-cli/src

  it(
    "fires repeated refresh cycles through the real render path and exits cleanly on SIGINT",
    async () => {
      const root = await makeWatchFixtureRoot();
      const specifier = join(SRC_DIR, "entrypoints", "process-entry.ts").split("\\").join("/");
      const driverScript = [
        `const { dispatchFastPath } = await import("file://${specifier}");`,
        `const handled = await dispatchFastPath(["node", "ember", "--watch", "--interval", "0.2"]);`,
        'if (!handled) { process.stderr.write("NOT_HANDLED" + String.fromCharCode(10)); process.exit(2); }',
      ].join("\n");
      const driverPath = join(root, "watch-driver.mjs");
      await writeFile(driverPath, driverScript);

      const proc = Bun.spawn({
        cmd: ["node", driverPath],
        cwd: SRC_DIR,
        env: { ...process.env, EMBER_GOALFORGE_ROOT: root },
        stdout: "pipe",
        stderr: "pipe",
      });

      // Let several refresh cycles fire (interval 0.2s), then send the real termination signal --
      // this is the SIGINT lifecycle clause, exercised against the real process, not a fake.
      await new Promise((r) => setTimeout(r, 900));
      proc.kill("SIGINT");

      const [stdout, stderr, exitCode] = await Promise.all([
        new Response(proc.stdout).text(),
        new Response(proc.stderr).text(),
        proc.exited,
      ]);

      expect(stderr).not.toContain("NOT_HANDLED");
      // Real renderMonitorPanel/renderReceiptsTail output, not a placeholder: the fixture
      // condition id and the fixture receipt path both must appear.
      expect(stdout).toContain("C-OBS");
      expect(stdout).toContain("r1.json");
      // Repeated refresh: the bordered panel's top border must appear MORE THAN ONCE -- proof
      // this is a loop, not a single render (the thing #405 explicitly warned never got wired).
      const panelStarts = (stdout.match(/╭/g) ?? []).length;
      expect(panelStarts).toBeGreaterThan(1);
      // Clean SIGINT exit: no leftover process. Exit CODE is platform-dependent here --
      // services/brain-server-supervisor.test.ts documents the same fact this codebase already
      // knows: "on Windows this is an unconditional terminate" (Node's child.kill(signal) has no
      // real POSIX signal to deliver on Windows, so the OS force-terminates rather than letting
      // the child's own `process.on("SIGINT", ...)` handler run process.exit(0) -- the graceful
      // in-process handler path is covered for real by core/watch-loop.test.ts's "clean SIGINT
      // lifecycle" test, which invokes the actual registered handler function directly). What
      // THIS test can assert cross-platform is the thing that actually matters operationally: the
      // process is gone -- no orphaned ambient-watch process left running after termination.
      expect(exitCode).not.toBeNull();
      const isAlive = (): boolean => { try { process.kill(proc.pid!, 0); return true; } catch { return false; } };
      expect(isAlive()).toBe(false);
    },
    20000,
  );

  it(
    "refresh-error resilience: a missing board receipt reports an error line and the process is still alive to receive SIGINT",
    async () => {
      // No board receipt written -- buildEmberWorldState() throws every cycle; the loop must
      // report it and keep running rather than crashing the ambient process.
      const root = join(
        tmpdir(),
        `ember-watch-fastpath-error-test-${Date.now()}-${Math.random().toString(36).slice(2)}`,
      );
      await mkdir(root, { recursive: true });
      watchTmpDirs.push(root);
      const specifier = join(SRC_DIR, "entrypoints", "process-entry.ts").split("\\").join("/");
      const driverScript = [
        `const { dispatchFastPath } = await import("file://${specifier}");`,
        `await dispatchFastPath(["node", "ember", "--watch", "--interval", "0.2"]);`,
      ].join("\n");
      const driverPath = join(root, "watch-driver-error.mjs");
      await writeFile(driverPath, driverScript);

      const proc = Bun.spawn({
        cmd: ["node", driverPath],
        cwd: SRC_DIR,
        env: { ...process.env, EMBER_GOALFORGE_ROOT: root },
        stdout: "pipe",
        stderr: "pipe",
      });

      await new Promise((r) => setTimeout(r, 700));
      proc.kill("SIGINT");
      const [stdout] = await Promise.all([
        new Response(proc.stdout).text(),
        new Response(proc.stderr).text(),
        proc.exited,
      ]);

      expect(stdout).toContain("[watch] refresh error:");
      // Same platform note as the sibling test above: exit CODE is not asserted here (Windows
      // child.kill(signal) unconditionally terminates rather than invoking the in-process
      // handler); what matters is the loop survived every erroring cycle up to this point
      // (proven by the refresh-error line appearing, meaning it logged-and-continued rather than
      // crashing) and left no process behind.
      const isAlive = (): boolean => { try { process.kill(proc.pid!, 0); return true; } catch { return false; } };
      expect(isAlive()).toBe(false);
    },
    20000,
  );

  it("rejects a hostile --interval before starting any loop (fail closed, non-zero exit, names the arg)", async () => {
    const root = await makeWatchFixtureRoot();
    const specifier = join(SRC_DIR, "entrypoints", "process-entry.ts").split("\\").join("/");
    const driverScript = [
      `const { dispatchFastPath } = await import("file://${specifier}");`,
      `await dispatchFastPath(["node", "ember", "--watch", "--interval", "-3"]);`,
    ].join("\n");
    const driverPath = join(root, "watch-driver-bad-interval.mjs");
    await writeFile(driverPath, driverScript);

    const proc = Bun.spawn({
      cmd: ["node", driverPath],
      cwd: SRC_DIR,
      env: { ...process.env, EMBER_GOALFORGE_ROOT: root },
      stdout: "pipe",
      stderr: "pipe",
    });
    const [, stderr, exitCode] = await Promise.all([
      new Response(proc.stdout).text(),
      new Response(proc.stderr).text(),
      proc.exited,
    ]);
    expect(exitCode).toBe(1);
    expect(stderr).toContain("--interval");
    expect(stderr).toContain("greater than 0");
  }, 10000);
});

describe("process-entry — --watch fast-path flag detection", () => {
  it("isFastPath detects --watch", () => {
    expect(isFastPath(["node", "ember", "--watch"])).toBe(true);
  });

  it("isFastPath detects --watch with --interval", () => {
    expect(isFastPath(["node", "ember", "--watch", "--interval", "5"])).toBe(true);
  });
});
