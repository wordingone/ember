// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// ember-lab-hour.test.ts — typed client for the ember-lab hour job class, against a fake named-pipe daemon.

import { afterEach, describe, expect, test } from "bun:test";
import net from "node:net";
import { isAbsolute, resolve } from "node:path";

import { hourJobExitCode, hourJobState, jobEvents, startHour, stopHourJob } from "./ember-lab-hour.ts";
import { callEmberLab, EmberLabRpcError } from "./ember-lab-rpc.ts";

const servers: net.Server[] = [];

afterEach(() => {
  for (const server of servers.splice(0)) server.close();
});

const winTest = process.platform === "win32" ? test : test.skip;

type Request = { id: string; jsonrpc: string; method: string; params: Record<string, unknown> };

function fakeDaemon(reply: (request: Request) => Record<string, unknown>): { pipe: string; requests: Request[] } {
  const pipe = `\\\\.\\pipe\\ember-lab-hour-ts-${process.pid}-${Math.random().toString(16).slice(2)}`;
  const requests: Request[] = [];
  const server = net.createServer((socket) => {
    socket.setEncoding("utf8");
    socket.once("data", (line: string) => {
      const request = JSON.parse(line) as Request;
      requests.push(request);
      socket.end(JSON.stringify({ jsonrpc: "2.0", id: request.id, ...reply(request) }) + "\n");
    });
  });
  server.listen(pipe);
  servers.push(server);
  return { pipe, requests };
}

const SHA = "a".repeat(64);

describe("startHour", () => {
  winTest("sends absolute paths and the environment minus every EMBER_* key, and parses the start receipt", async () => {
    const daemon = fakeDaemon(() => ({
      result: {
        job_id: "hour-aaaaaaaaaaaa-bbbbbbbb",
        pid: 4321,
        script: "B:/s/h49_dispatch_v2.sh",
        sha256: SHA,
        log: "B:/l/hour.log",
        receipt_path: "B:/l/hour.log.lab-start.json",
        bash: "C:/Program Files/Git/bin/bash.exe",
        cwd: null,
      },
    }));
    const result = await startHour({
      pipeName: daemon.pipe,
      script: "h49_dispatch_v2.sh",
      sha256: SHA,
      log: "hour.log",
      baseDir: "B:/work",
      env: { PATH: "p", EMBER_API_KEY: "k", ember_model_seat: "s", HOME: "h" },
    });
    expect(result).toEqual({
      ok: true,
      jobId: "hour-aaaaaaaaaaaa-bbbbbbbb",
      pid: 4321,
      script: "B:/s/h49_dispatch_v2.sh",
      sha256: SHA,
      log: "B:/l/hour.log",
      receiptPath: "B:/l/hour.log.lab-start.json",
      bash: "C:/Program Files/Git/bin/bash.exe",
      cwd: null,
      receiptComplete: true,
    });
    expect(daemon.requests.length).toBe(1);
    const sent = daemon.requests[0]!;
    expect(sent.method).toBe("start_hour");
    expect(sent.params["env"]).toEqual({ PATH: "p", HOME: "h" });
    expect(sent.params["script"]).toBe(resolve("B:/work", "h49_dispatch_v2.sh"));
    expect(isAbsolute(String(sent.params["log"]))).toBe(true);
    expect(sent.params["cwd"]).toBe(null);
    expect(sent.params["bash"]).toBe(null);
    expect(Object.keys(sent.params).sort()).toEqual(["bash", "cwd", "env", "log", "script", "sha256"]);
  });

  winTest("a running hour whose start receipt could not be completed is a SUCCESS carrying jobId, pid and the receipt error", async () => {
    const daemon = fakeDaemon(() => ({
      result: {
        job_id: "hour-aaaaaaaaaaaa-bbbbbbbb",
        pid: 4321,
        script: "B:/s/h49_dispatch_v2.sh",
        sha256: SHA,
        log: "B:/l/hour.log",
        receipt_path: "B:/l/hour.log.lab-start.json",
        bash: "C:/Program Files/Git/bin/bash.exe",
        cwd: null,
        receipt_complete: false,
        receipt_error: "hour_receipt_write: hour hour-aaaaaaaaaaaa-bbbbbbbb is RUNNING (pid 4321); completing the receipt failed: disk full",
      },
    }));
    const result = await startHour({ pipeName: daemon.pipe, script: "B:/s/h49_dispatch_v2.sh", sha256: SHA, log: "B:/l/hour.log", env: {} });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.jobId).toBe("hour-aaaaaaaaaaaa-bbbbbbbb");
    expect(result.pid).toBe(4321);
    expect(result.receiptComplete).toBe(false);
    expect(result.receiptError).toContain("disk full");
  });

  winTest("a running hour whose start tail failed is a SUCCESS carrying startTailError (the lab kept the lease)", async () => {
    const daemon = fakeDaemon(() => ({
      result: {
        job_id: "hour-aaaaaaaaaaaa-bbbbbbbb",
        pid: 4321,
        script: "B:/s/h49_dispatch_v2.sh",
        sha256: SHA,
        log: "B:/l/hour.log",
        receipt_path: "B:/l/hour.log.lab-start.json",
        bash: "C:/Program Files/Git/bin/bash.exe",
        cwd: null,
        receipt_complete: true,
        start_tail_error: "hour_start_tail: hour hour-aaaaaaaaaaaa-bbbbbbbb is RUNNING (pid 4321) and keeps its lease; start_job returned an error after the child was resumed: Poisoned",
      },
    }));
    const result = await startHour({ pipeName: daemon.pipe, script: "B:/s/h49_dispatch_v2.sh", sha256: SHA, log: "B:/l/hour.log", env: {} });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.pid).toBe(4321);
    expect(result.receiptComplete).toBe(true);
    expect(result.startTailError).toContain("keeps its lease");
    expect(result.receiptError).toBeUndefined();
  });

  winTest("returns a contract refusal as a value with its own code and rc, never a throw", async () => {
    const daemon = fakeDaemon(() => ({
      error: { code: -32001, message: "hour_refused", data: { refusal_code: "hour_sha_mismatch", rc: 24, detail: "sha differs" } },
    }));
    const result = await startHour({ pipeName: daemon.pipe, script: "B:/s/h49_dispatch_v2.sh", sha256: SHA, log: "B:/l/x.log", env: {} });
    expect(result).toEqual({ ok: false, refusalCode: "hour_sha_mismatch", rc: 24, detail: "sha differs" });
  });

  winTest("throws on a non-refusal RPC error and on a malformed receipt", async () => {
    const failing = fakeDaemon(() => ({ error: { code: -32000, message: "ember-lab operation failed", data: "boom" } }));
    await expect(startHour({ pipeName: failing.pipe, script: "B:/s/h1_dispatch_v1.sh", sha256: SHA, log: "B:/l/y.log", env: {} }))
      .rejects.toThrow("JSON-RPC error");
    const malformed = fakeDaemon(() => ({ result: { job_id: "j", pid: 0 } }));
    await expect(startHour({ pipeName: malformed.pipe, script: "B:/s/h1_dispatch_v1.sh", sha256: SHA, log: "B:/l/z.log", env: {} }))
      .rejects.toThrow("pid is malformed");
  });

  winTest("callEmberLab keeps the server's error object on EmberLabRpcError", async () => {
    const daemon = fakeDaemon(() => ({ error: { code: -32001, message: "hour_refused", data: { refusal_code: "x", rc: 9, detail: "d" } } }));
    const error = await callEmberLab({ pipeName: daemon.pipe, method: "start_hour", params: {} }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(EmberLabRpcError);
    expect((error as EmberLabRpcError).rpcError["message"]).toBe("hour_refused");
  });
});

describe("job RPC wrappers", () => {
  winTest("jobEvents parses events and sends the cursor", async () => {
    const daemon = fakeDaemon(() => ({
      result: { events: [{ seq: 5, ts_ms: 100, kind: "job_started", payload: { pid: 1 } }, { seq: 6, ts_ms: 200, kind: "job_exited", payload: {} }] },
    }));
    const events = await jobEvents(daemon.pipe, "hour-1", 4, 50);
    expect(events.map((event) => [event.seq, event.kind])).toEqual([[5, "job_started"], [6, "job_exited"]]);
    expect(daemon.requests[0]!.params).toEqual({ job_id: "hour-1", after_seq: 4, limit: 50 });
  });

  winTest("state, exit code and stop use the existing job RPCs", async () => {
    const state = fakeDaemon(() => ({ result: { state: "running" } }));
    expect(await hourJobState(state.pipe, "hour-1")).toBe("running");
    const exitNull = fakeDaemon(() => ({ result: { exit_code: null } }));
    expect(await hourJobExitCode(exitNull.pipe, "hour-1")).toBe(null);
    const exitZero = fakeDaemon(() => ({ result: { exit_code: 0 } }));
    expect(await hourJobExitCode(exitZero.pipe, "hour-1")).toBe(0);
    const stop = fakeDaemon(() => ({ result: { stopped: true } }));
    await stopHourJob(stop.pipe, "hour-1");
    expect(stop.requests[0]!.method).toBe("stop_job");
    const refusedStop = fakeDaemon(() => ({ result: { stopped: false } }));
    await expect(stopHourJob(refusedStop.pipe, "hour-1")).rejects.toThrow("stop_job result is malformed");
  });
});
