// goal_id: EMBER-01
// workstream_id: EMBER-01A
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
        headlessRunner: async () => ({ events: [], exitCode: 0 }),
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
});
