// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// emberd-rpc.test.ts — strict Ember CLI client for the resident emberd pipe.

import { afterEach, describe, expect, test } from "bun:test";
import net from "node:net";

import {
  configuredEmberdPipe,
  pingEmberd,
} from "./emberd-rpc.ts";
import { operatorPipeName } from "./operator-pipe.ts";

const servers: net.Server[] = [];

afterEach(() => {
  for (const server of servers.splice(0)) server.close();
});

describe("configuredEmberdPipe", () => {
  test("requires the explicit emberd pipe and rejects the per-PID operator pipe", () => {
    expect(() => configuredEmberdPipe({})).toThrow("EMBERD_PIPE");
    expect(() => configuredEmberdPipe({ EMBERD_PIPE: operatorPipeName(1234) })).toThrow("operator");
    expect(configuredEmberdPipe({ EMBERD_PIPE: "\\\\.\\pipe\\emberd-test-1234" }))
      .toBe("\\\\.\\pipe\\emberd-test-1234");
  });
});

const winTest = process.platform === "win32" ? test : test.skip;

winTest("pingEmberd sends one exact JSON-RPC ping and accepts only its matching response id", async () => {
  const pipe = `\\\\.\\pipe\\emberd-p2c-${process.pid}-${Math.random().toString(16).slice(2)}`;
  const requests: unknown[] = [];
  const server = net.createServer((socket) => {
    socket.setEncoding("utf8");
    socket.once("data", (line: string) => {
      const request = JSON.parse(line) as { id: string; jsonrpc: string; method: string; params: unknown };
      requests.push(request);
      socket.end(JSON.stringify({ jsonrpc: "2.0", id: request.id, result: { status: "ok" } }) + "\n");
    });
  });
  servers.push(server);
  await new Promise<void>((resolve, reject) => server.listen(pipe, () => resolve()).once("error", reject));

  await expect(pingEmberd({ pipeName: pipe, requestId: "p2c-ping", timeoutMs: 500 })).resolves.toBeUndefined();
  expect(requests).toEqual([{ jsonrpc: "2.0", id: "p2c-ping", method: "ping", params: {} }]);
});

winTest("pingEmberd rejects an idle response at the bounded deadline", async () => {
  const pipe = `\\\\.\\pipe\\emberd-p2c-idle-${process.pid}-${Math.random().toString(16).slice(2)}`;
  const server = net.createServer(() => {});
  servers.push(server);
  await new Promise<void>((resolve, reject) => server.listen(pipe, () => resolve()).once("error", reject));

  await expect(pingEmberd({ pipeName: pipe, requestId: "idle", timeoutMs: 25 }))
    .rejects.toThrow("timeout");
});

winTest("pingEmberd rejects a response frame above the fixed 65536-byte bound", async () => {
  const pipe = `\\\\.\\pipe\\emberd-p2c-large-${process.pid}-${Math.random().toString(16).slice(2)}`;
  const server = net.createServer((socket) => {
    socket.once("data", () => socket.end("x".repeat(65_537)));
  });
  servers.push(server);
  await new Promise<void>((resolve, reject) => server.listen(pipe, () => resolve()).once("error", reject));

  await expect(pingEmberd({ pipeName: pipe, requestId: "large", timeoutMs: 500 }))
    .rejects.toThrow("65536");
});
winTest("pingEmberd rejects mismatched IDs and JSON-RPC errors", async () => {
  const pipe = `\\\\.\\pipe\\emberd-p2c-bad-${process.pid}-${Math.random().toString(16).slice(2)}`;
  let connection = 0;
  const server = net.createServer((socket) => {
    socket.setEncoding("utf8");
    socket.once("data", () => {
      connection += 1;
      const response = connection === 1
        ? '{"jsonrpc":"2.0","id":"wrong","result":{"status":"ok"}}\n'
        : '{"jsonrpc":"2.0","id":"error","error":{"code":-32000,"message":"unavailable"}}\n';
      socket.end(response);
    });
  });
  servers.push(server);
  await new Promise<void>((resolve, reject) => server.listen(pipe, () => resolve()).once("error", reject));

  await expect(pingEmberd({ pipeName: pipe, requestId: "expected", timeoutMs: 500 }))
    .rejects.toThrow("response id");
  await expect(pingEmberd({ pipeName: pipe, requestId: "error", timeoutMs: 500 }))
    .rejects.toThrow("JSON-RPC error");
});