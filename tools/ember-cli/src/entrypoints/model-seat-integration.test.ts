// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { afterEach, beforeEach, describe, expect, it } from "bun:test";
import { mkdir, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";

import { main } from "./process-entry.ts";
import { _resetConfigHomeMemo } from "../utils/env-detection.ts";
import type { LoopDeps } from "../query/query-loop-support.ts";

function fakeDeps(): LoopDeps {
  return {
    callModel: async () => {
      throw new Error("model call is not exercised");
    },
    microcompact: async (messages) => messages,
    autocompact: async () => {},
    generateUuid: () => "model-seat-test",
    sleep: async () => {},
  };
}

describe("process entry model-seat enforcement", () => {
  let tmpDir: string;
  let savedEnv: Record<string, string | undefined>;

  beforeEach(async () => {
    tmpDir = join(
      tmpdir(),
      "ember-model-seat-" + Date.now() + "-" + Math.random().toString(36).slice(2),
    );
    await mkdir(tmpDir, { recursive: true });
    savedEnv = {};
    for (const key of [
      "EMBER_HOME",
      "EMBER_GPU_FREE",
      "EMBER_MODEL_NAME",
      "EMBER_MODEL_SEAT",
      "EMBER_MODEL_URL",
      "EMBER_REFERENCE_SEAT",
      "EMBER_OWNED_RUNG_MANIFEST",
      "EMBER_TRUSTED_VERIFIER_REGISTRY",
      "EMBER_PYTHON",
    ]) {
      savedEnv[key] = process.env[key];
      delete process.env[key];
    }
    process.env["EMBER_HOME"] = tmpDir;
    _resetConfigHomeMemo();
  });

  afterEach(async () => {
    for (const [key, value] of Object.entries(savedEnv)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    _resetConfigHomeMemo();
    await rm(tmpDir, { recursive: true, force: true });
  });

  async function runMcpInitialize(
    args: string[],
    envOverrides: Record<string, string>,
  ): Promise<{ stdout: string; stderr: string; exitCode: number }> {
    const env: Record<string, string | undefined> = { ...process.env };
    delete env["EMBER_MODEL_URL"];
    delete env["EMBER_REFERENCE_SEAT"];
    Object.assign(env, envOverrides);
    const child = Bun.spawn(
      [process.execPath, join(import.meta.dir, "main.ts"), ...args],
      {
        cwd: tmpDir,
        env,
        stdin: "pipe",
        stdout: "pipe",
        stderr: "pipe",
      },
    );
    child.stdin.write(
      JSON.stringify({
        jsonrpc: "2.0",
        id: 1,
        method: "initialize",
        params: {},
      }) + "\n",
    );
    child.stdin.end();
    const [stdout, stderr, exitCode] = await Promise.all([
      new Response(child.stdout).text(),
      new Response(child.stderr).text(),
      child.exited,
    ]);
    return { stdout, stderr, exitCode };
  }

  function expectJsonOnlyInitialize(stdout: string): void {
    const lines = stdout.split(/\r?\n/).filter((line) => line.length > 0);
    expect(lines).toHaveLength(1);
    const response = JSON.parse(lines[0]!) as {
      jsonrpc: string;
      id: number;
      result: { serverInfo: { name: string } };
    };
    expect(response.jsonrpc).toBe("2.0");
    expect(response.id).toBe(1);
    expect(response.result.serverInfo.name).toBe("ember/repl");
  }

  it("keeps GPU-free MCP stdout JSON-only and puts the OFFLINE seat on stderr", async () => {
    const result = await runMcpInitialize(
      ["--mcp"],
      { EMBER_GPU_FREE: "1" },
    );

    expect(result.exitCode).toBe(0);
    expectJsonOnlyInitialize(result.stdout);
    expect(result.stderr).toContain("model seat: OFFLINE");
  });

  it("keeps reference MCP stdout JSON-only and puts REFERENCE_ONLY on stderr", async () => {
    const server = Bun.serve({
      hostname: "127.0.0.1",
      port: 0,
      fetch(request) {
        const pathname = new URL(request.url).pathname;
        if (pathname === "/props") {
          return Response.json({ n_ctx: 4096 });
        }
        return new Response("not found", { status: 404 });
      },
    });

    try {
      const result = await runMcpInitialize(
        ["--reference-seat", "--mcp"],
        { EMBER_MODEL_URL: "http://127.0.0.1:" + server.port },
      );

      expect(result.exitCode).toBe(0);
      expectJsonOnlyInitialize(result.stdout);
      expect(result.stderr).toContain("model seat: REFERENCE_ONLY");
    } finally {
      server.stop(true);
    }
  });

  it("rejects MCP startup before dispatch when no model seat is authorized", async () => {
    let exitCode = -1;
    let stderr = "";
    const originalStderr = process.stderr.write.bind(process.stderr);
    process.stderr.write = ((chunk: string) => {
      stderr += chunk;
      return true;
    }) as typeof process.stderr.write;

    try {
      await main({
        argv: ["node", "ember", "--mcp"],
        exitFn: (code: number) => {
          exitCode = code;
        },
      });
    } finally {
      process.stderr.write = originalStderr;
    }

    expect(exitCode).toBe(1);
    expect(stderr).toContain("no admitted owned Ember identity");
    expect(process.env["EMBER_MODEL_SEAT"]).toBeUndefined();
  });

  it("rejects a persisted Qwen endpoint before init or model traffic", async () => {
    await writeFile(
      join(tmpDir, "models.json"),
      JSON.stringify({
        endpoint: "http://127.0.0.1:9",
        modelName: "qwen3.6-27b",
      }),
    );

    let exitCode = -1;
    let initCalls = 0;
    let stderr = "";
    const originalStderr = process.stderr.write.bind(process.stderr);
    process.stderr.write = ((chunk: string) => {
      stderr += chunk;
      return true;
    }) as typeof process.stderr.write;

    try {
      await main({
        argv: ["node", "ember", "-p", "hello"],
        initFn: async () => {
          initCalls += 1;
        },
        getLoopDepsFn: fakeDeps,
        headlessRunner: async () => ({ events: [], exitCode: 0 }),
        exitFn: (code: number) => {
          exitCode = code;
        },
      });
    } finally {
      process.stderr.write = originalStderr;
    }

    expect(exitCode).toBe(1);
    expect(initCalls).toBe(0);
    expect(stderr).toContain("no admitted owned Ember identity");
    expect(process.env["EMBER_MODEL_NAME"]).toBeUndefined();
  });

  it("selects the admitted owned endpoint and ignores persisted Qwen configuration", async () => {
    await writeFile(
      join(tmpDir, "models.json"),
      JSON.stringify({
        endpoint: "http://127.0.0.1:9999",
        modelName: "qwen3.6-27b",
      }),
    );

    let exitCode = -1;
    let initCalls = 0;
    let verifyCalls = 0;
    let ensureCalls = 0;
    const startupOrder: string[] = [];
    let stdout = "";
    const originalStdout = process.stdout.write.bind(process.stdout);
    process.stdout.write = ((chunk: string) => {
      stdout += chunk;
      return true;
    }) as typeof process.stdout.write;

    try {
      await main({
        argv: ["node", "ember", "-p", "hello"],
        loadOwnedIdentityFn: () => ({
          checkpointSha256: "e".repeat(64),
          endpointUrl: "http://127.0.0.1:9",
          identityUrl: "http://127.0.0.1:9/v1/models",
          modelConfigSha256: "b".repeat(64),
          modelName: "ember-owned:" + "e".repeat(12),
          serverSourceSha256: "a".repeat(64),
          tokenizerSha256: "c".repeat(64),
          launch: {
            authorityKind: "ADMISSION",
            checkpointDir: "C:\\owned\\checkpoint",
            mode: "INTERACTIVE",
      modelConfigPath: "C:\\owned\\model-config.json",
            pythonExecutable: "python-owned",
            runManifestPath: "C:\\owned\\run.json",
            serverPath: "C:\\repo\\serve_owned_openai.py",
            tokenizerPath: "C:\\owned\\tokenizer.json",
            trustedVerifierRegistryPath: "C:\\owned\\trusted.json",
          },
        }),
        handshakeEmberLabFn: async () => { startupOrder.push("handshake"); },
        ensureOwnedServerFn: async (ownedIdentity) => {
          expect(ownedIdentity.launch?.mode).toBe("INTERACTIVE");
          startupOrder.push("supervise");
          ensureCalls += 1;
          return {
            outcome: "spawned",
            port: 9,
            handle: { process: { pid: 77 }, port: 9, kill: () => {} } as never,
          };
        },
        verifyOwnedEndpointFn: async () => {
          verifyCalls += 1;
        },
        initFn: async () => {
          initCalls += 1;
        },
        getLoopDepsFn: fakeDeps,
        builtinToolsFn: async () => [{ name: "clean-checkout-tool" }] as never[],
        headlessRunner: async (_prompt, _io, tools) => {
          expect(tools).toEqual([{ name: "clean-checkout-tool" }]);
          return { events: [], exitCode: 0 };
        },
        exitFn: (code: number) => {
          exitCode = code;
        },
      });
    } finally {
      process.stdout.write = originalStdout;
    }

    expect(exitCode).toBe(0);
    expect(initCalls).toBe(1);
    expect(ensureCalls).toBe(1);
    expect(verifyCalls).toBe(1);
    expect(startupOrder).toEqual(["handshake", "supervise"]);
    expect(process.env["EMBER_MODEL_SEAT"]).toBe("OWNED_ADMITTED");
    expect(process.env["EMBER_MODEL_URL"]).toBe("http://127.0.0.1:9");
    expect(process.env["EMBER_MODEL_NAME"]).toBe(
      "ember-owned:" + "e".repeat(12),
    );
    expect(stdout).toContain("model seat: OWNED_ADMITTED");
    expect(stdout).toContain("bound by admitted checkpoint manifest");
    expect(stdout).toContain("supervised server started");
    expect(stdout).not.toContain("adopted");
    expect(stdout).not.toContain("qwen3.6-27b");
    expect(stdout).not.toContain("http://127.0.0.1:9999");
  });

  it("defaults to the exact owned development checkpoint without borrowing Qwen credit", async () => {
    await writeFile(
      join(tmpDir, "models.json"),
      JSON.stringify({ endpoint: "http://127.0.0.1:9999", modelName: "qwen3.6-27b" }),
    );
    let exitCode = -1;
    let ensureCalls = 0;
    const injectedTools = [{ name: "test-tool" }] as never[];
    let injectedToolCount = -1;
    let verifyCalls = 0;
    let stdout = "";
    const originalStdout = process.stdout.write.bind(process.stdout);
    process.stdout.write = ((chunk: string) => { stdout += chunk; return true; }) as typeof process.stdout.write;
    try {
      await main({
        argv: ["node", "ember", "-p", "hello"],
        loadOwnedIdentityFn: () => undefined,
        loadOwnedDevelopmentIdentityFn: () => ({
          seat: "OWNED_DEVELOPMENT",
          claimStatus: "NON_ADMISSIBLE",
          tokensSeen: 2048,
          allocatedParameters: 3_839_161_856,
          activeParameters: 1_020_589_568,
          checkpointSha256: "f".repeat(64),
          endpointUrl: "http://127.0.0.1:9",
          identityUrl: "http://127.0.0.1:9/v1/models",
          modelConfigSha256: "b".repeat(64),
          modelName: "ember-owned-development:" + "f".repeat(12),
          serverSourceSha256: "a".repeat(64),
          tokenizerSha256: "c".repeat(64),
          launch: {
            authorityKind: "DEVELOPMENT",
            cleanupRuntimeSnapshot: () => {},
            developmentManifestSha256: "e".repeat(64),
            runtimeIndexPath: "C:\\owned\\runtime-bundle-index.json",
            runtimeIndexSha256: "f".repeat(64),
            checkpointDir: "C:\\owned\\checkpoint",
            developmentManifestPath: "C:\\owned\\development.json",
            mode: "INTERACTIVE",
            modelConfigPath: "C:\\owned\\model-config.json",
            pythonExecutable: "python-owned",
            serverPath: "C:\\repo\\serve_owned_openai.py",
            tokenizerPath: "C:\\owned\\tokenizer.json",
          },
        }),
        handshakeEmberLabFn: async () => {},
        ensureOwnedServerFn: async () => {
          ensureCalls += 1;
          return { outcome: "spawned", port: 9, handle: { process: { pid: 77 }, port: 9, kill: () => {} } as never };
        },
        verifyOwnedEndpointFn: async () => { verifyCalls += 1; },
        initFn: async () => {},
        getLoopDepsFn: fakeDeps,
        builtinToolsFn: async () => injectedTools,
        headlessRunner: async (_prompt, _io, tools) => { expect(tools).toBe(injectedTools); injectedToolCount = tools.length; return { events: [], exitCode: 0 }; },
        exitFn: (code: number) => { exitCode = code; },
      });
    } finally {
      process.stdout.write = originalStdout;
    }

    expect(exitCode).toBe(0);
    expect(ensureCalls).toBe(1);
    expect(injectedToolCount).toBeGreaterThan(0);
    expect(verifyCalls).toBe(1);
    expect(process.env["EMBER_MODEL_SEAT"]).toBe("OWNED_DEVELOPMENT");
    expect(process.env["EMBER_MODEL_NAME"]).toBe("ember-owned-development:" + "f".repeat(12));
    expect(stdout).toContain("model seat: OWNED_DEVELOPMENT");
    expect(stdout).toContain("2,048 training tokens");
    expect(stdout).toContain("NON_ADMISSIBLE");
    expect(stdout).not.toContain("qwen3.6-27b");
    expect(stdout).not.toContain("http://127.0.0.1:9999");
  });
  it("allows the same endpoint only in an explicit visible reference seat", async () => {
    await writeFile(
      join(tmpDir, "models.json"),
      JSON.stringify({
        endpoint: "http://127.0.0.1:9",
        modelName: "qwen3.6-27b",
      }),
    );

    let exitCode = -1;
    let initCalls = 0;
    let stdout = "";
    const originalStdout = process.stdout.write.bind(process.stdout);
    process.stdout.write = ((chunk: string) => {
      stdout += chunk;
      return true;
    }) as typeof process.stdout.write;

    try {
      await main({
        argv: ["node", "ember", "--reference-seat", "-p", "hello"],
        initFn: async () => {
          initCalls += 1;
        },
        getLoopDepsFn: fakeDeps,
        builtinToolsFn: async () => [{ name: "clean-checkout-tool" }] as never[],
        headlessRunner: async (_prompt, _io, tools) => {
          expect(tools).toEqual([{ name: "clean-checkout-tool" }]);
          return { events: [], exitCode: 0 };
        },
        exitFn: (code: number) => {
          exitCode = code;
        },
      });
    } finally {
      process.stdout.write = originalStdout;
    }

    expect(exitCode).toBe(0);
    expect(initCalls).toBe(1);
    expect(stdout).toContain("model seat: REFERENCE_ONLY");
    expect(process.env["EMBER_MODEL_NAME"]).toBe(
      "REFERENCE_ONLY: qwen3.6-27b",
    );
    expect(process.env["EMBER_MODEL_SEAT"]).toBe("REFERENCE_ONLY");
  });

  it("requires ember-lab handshake before owned server supervision", async () => {
    let exitCode = -1;
    let ensureCalls = 0;
    let initCalls = 0;
    let stderr = "";
    const originalStderr = process.stderr.write.bind(process.stderr);
    process.stderr.write = ((chunk: string) => { stderr += chunk; return true; }) as typeof process.stderr.write;
    try {
      await main({
        argv: ["node", "ember", "-p", "hello"],
        loadOwnedIdentityFn: () => ({
          checkpointSha256: "d".repeat(64), endpointUrl: "http://127.0.0.1:9", identityUrl: "http://127.0.0.1:9/v1/models",
          modelConfigSha256: "b".repeat(64), modelName: "ember-owned:" + "d".repeat(12), serverSourceSha256: "a".repeat(64), tokenizerSha256: "c".repeat(64),
          launch: { authorityKind: "ADMISSION", checkpointDir: "C:\\owned\\checkpoint", mode: "INTERACTIVE", modelConfigPath: "C:\\owned\\model-config.json", pythonExecutable: "python-owned", runManifestPath: "C:\\owned\\run.json", serverPath: "C:\\repo\\serve_owned_openai.py", tokenizerPath: "C:\\owned\\tokenizer.json", trustedVerifierRegistryPath: "C:\\owned\\trusted.json" },
        }),
        handshakeEmberLabFn: async () => { throw new Error("ping unavailable"); },
        ensureOwnedServerFn: async () => { ensureCalls += 1; return { outcome: "spawned", port: 9, handle: { process: { pid: 77 }, port: 9, kill: () => {} } as never }; },
        initFn: async () => { initCalls += 1; },
        getLoopDepsFn: fakeDeps,
        headlessRunner: async () => ({ events: [], exitCode: 0 }),
        exitFn: (code: number) => { exitCode = code; },
      });
    } finally {
      process.stderr.write = originalStderr;
    }
    expect(exitCode).toBe(1);
    expect(ensureCalls).toBe(0);
    expect(initCalls).toBe(0);
    expect(stderr).toContain("ember-lab handshake");
  });
});
