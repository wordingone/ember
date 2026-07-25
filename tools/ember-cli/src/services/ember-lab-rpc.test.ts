// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// ember-lab-rpc.test.ts — strict Ember CLI client for the resident ember-lab pipe.

import { afterEach, describe, expect, test } from "bun:test";
import net from "node:net";

import {
  callEmberLab,
  configuredEmberLabPipe,
  pingEmberLab,
} from "./ember-lab-rpc.ts";
import { operatorPipeName } from "./operator-pipe.ts";

const servers: net.Server[] = [];

afterEach(() => {
  for (const server of servers.splice(0)) server.close();
});

describe("configuredEmberLabPipe", () => {
  test("requires the explicit ember-lab pipe and rejects the per-PID operator pipe", () => {
    expect(() => configuredEmberLabPipe({})).toThrow("EMBER_LAB_PIPE");
    expect(() => configuredEmberLabPipe({ EMBER_LAB_PIPE: operatorPipeName(1234) })).toThrow("operator");
    expect(configuredEmberLabPipe({ EMBER_LAB_PIPE: "\\\\.\\pipe\\ember-lab-test-1234" }))
      .toBe("\\\\.\\pipe\\ember-lab-test-1234");
  });
});

const winTest = process.platform === "win32" ? test : test.skip;

winTest("callEmberLab uses one request per connection and reconnects for each call", async () => {
  const pipe = `\\\\.\\pipe\\ember-lab-p2c-reconnect-${process.pid}-${Math.random().toString(16).slice(2)}`;
  let connections = 0;
  const requests: Array<{ id: string; method: string; params: unknown }> = [];
  const server = net.createServer((socket) => {
    connections += 1;
    socket.setEncoding("utf8");
    socket.once("data", (line: string) => {
      const request = JSON.parse(line) as { id: string; method: string; params: unknown };
      requests.push(request);
      socket.end(JSON.stringify({ jsonrpc: "2.0", id: request.id, result: { status: "ok" } }) + "\n");
    });
  });
  servers.push(server);
  await new Promise<void>((resolve, reject) => server.listen(pipe, () => resolve()).once("error", reject));

  await expect(callEmberLab({ pipeName: pipe, requestId: "first", method: "ping", params: {} })).resolves.toEqual({ status: "ok" });
  await expect(callEmberLab({ pipeName: pipe, requestId: "second", method: "ping", params: {} })).resolves.toEqual({ status: "ok" });
  expect(connections).toBe(2);
  expect(requests).toEqual([
    { jsonrpc: "2.0", id: "first", method: "ping", params: {} },
    { jsonrpc: "2.0", id: "second", method: "ping", params: {} },
  ]);
});

winTest("callEmberLab writes the first request inside the daemon 500ms idle boundary", async () => {
  const pipe = `\\\\.\\pipe\\ember-lab-p2c-idle-boundary-${process.pid}-${Math.random().toString(16).slice(2)}`;
  let firstRequestDelayMs = Number.POSITIVE_INFINITY;
  const server = net.createServer((socket) => {
    const connectedAt = performance.now();
    socket.setEncoding("utf8");
    socket.once("data", (line: string) => {
      firstRequestDelayMs = performance.now() - connectedAt;
      const request = JSON.parse(line) as { id: string };
      socket.end(JSON.stringify({ jsonrpc: "2.0", id: request.id, result: { status: "ok" } }) + "\n");
    });
  });
  servers.push(server);
  await new Promise<void>((resolve, reject) => server.listen(pipe, () => resolve()).once("error", reject));

  await expect(pingEmberLab({ pipeName: pipe, requestId: "idle-boundary", timeoutMs: 500 })).resolves.toBeUndefined();
  expect(firstRequestDelayMs).toBeLessThan(500);
});

winTest("callEmberLab retries a transient pipe-open failure within the bounded window", async () => {
  const pipe = `\\\\.\\pipe\\ember-lab-p2c-retry-${process.pid}-${Math.random().toString(16).slice(2)}`;
  const pending = callEmberLab({ pipeName: pipe, requestId: "retry", method: "ping", params: {} });
  await new Promise((resolve) => setTimeout(resolve, 60));
  const server = net.createServer((socket) => {
    socket.setEncoding("utf8");
    socket.once("data", (line: string) => {
      const request = JSON.parse(line) as { id: string };
      socket.end(JSON.stringify({ jsonrpc: "2.0", id: request.id, result: { status: "ok" } }) + "\n");
    });
  });
  servers.push(server);
  await new Promise<void>((resolve, reject) => server.listen(pipe, () => resolve()).once("error", reject));
  await expect(pending).resolves.toEqual({ status: "ok" });
}, 15_000);

test("callEmberLab rejects a request above the daemon 65536-byte ceiling before connecting", async () => {
  await expect(callEmberLab({
    pipeName: "\\\\.\\pipe\\ember-lab-p2c-too-large",
    requestId: "too-large",
    method: "ping",
    params: { padding: "x".repeat(70_000) },
  })).rejects.toThrow("request exceeds 65536 bytes");
});
winTest("pingEmberLab sends one exact JSON-RPC ping and accepts only its matching response id", async () => {
  const pipe = `\\\\.\\pipe\\ember-lab-p2c-${process.pid}-${Math.random().toString(16).slice(2)}`;
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

  await expect(pingEmberLab({ pipeName: pipe, requestId: "p2c-ping", timeoutMs: 500 })).resolves.toBeUndefined();
  expect(requests).toEqual([{ jsonrpc: "2.0", id: "p2c-ping", method: "ping", params: {} }]);
});

winTest("pingEmberLab rejects an idle response at the bounded deadline", async () => {
  const pipe = `\\\\.\\pipe\\ember-lab-p2c-idle-${process.pid}-${Math.random().toString(16).slice(2)}`;
  const server = net.createServer(() => {});
  servers.push(server);
  await new Promise<void>((resolve, reject) => server.listen(pipe, () => resolve()).once("error", reject));

  await expect(pingEmberLab({ pipeName: pipe, requestId: "idle", timeoutMs: 25 }))
    .rejects.toThrow("timeout");
});

winTest("pingEmberLab rejects a response frame above the fixed 65536-byte bound", async () => {
  const pipe = `\\\\.\\pipe\\ember-lab-p2c-large-${process.pid}-${Math.random().toString(16).slice(2)}`;
  const server = net.createServer((socket) => {
    socket.once("data", () => socket.end("x".repeat(65_537)));
  });
  servers.push(server);
  await new Promise<void>((resolve, reject) => server.listen(pipe, () => resolve()).once("error", reject));

  await expect(pingEmberLab({ pipeName: pipe, requestId: "large", timeoutMs: 500 }))
    .rejects.toThrow("65536");
});
winTest("pingEmberLab rejects malformed JSON, malformed results, and multiple response frames", async () => {
  const pipe = `\\\\.\\pipe\\ember-lab-p2c-malformed-${process.pid}-${Math.random().toString(16).slice(2)}`;
  const responses = [
    "not-json\n",
    "[]\n",
    '{"jsonrpc":"2.0","id":"bad-result","result":"not-an-object"}\n',
    '{"jsonrpc":"2.0","id":"multi","result":{"status":"ok"}}\n{"jsonrpc":"2.0","id":"multi","result":{"status":"ok"}}\n',
  ];
  const server = net.createServer((socket) => {
    socket.once("data", () => socket.end(responses.shift()!));
  });
  servers.push(server);
  await new Promise<void>((resolve, reject) => server.listen(pipe, () => resolve()).once("error", reject));

  await expect(pingEmberLab({ pipeName: pipe, requestId: "bad-json", timeoutMs: 500 })).rejects.toThrow("not JSON");
  await expect(pingEmberLab({ pipeName: pipe, requestId: "non-object", timeoutMs: 500 })).rejects.toThrow("not an object");
  await expect(pingEmberLab({ pipeName: pipe, requestId: "bad-result", timeoutMs: 500 })).rejects.toThrow("malformed");
  await expect(pingEmberLab({ pipeName: pipe, requestId: "multi", timeoutMs: 500 })).rejects.toThrow("multiple frames");
});
winTest("pingEmberLab closes after one valid frame; delayed second frames are outside the one-request connection", async () => {
  const pipe = `\\\\.\\pipe\\ember-lab-p2c-delayed-${process.pid}-${Math.random().toString(16).slice(2)}`;
  let closedBeforeDelayedWrite = false;
  const server = net.createServer((socket) => {
    socket.once("data", () => {
      socket.write('{"jsonrpc":"2.0","id":"delayed","result":{"status":"ok"}}\n');
      socket.once("close", () => { closedBeforeDelayedWrite = true; });
      setTimeout(() => socket.write('{"jsonrpc":"2.0","id":"delayed","result":{"status":"ok"}}\n'), 25);
    });
  });
  servers.push(server);
  await new Promise<void>((resolve, reject) => server.listen(pipe, () => resolve()).once("error", reject));

  await expect(pingEmberLab({ pipeName: pipe, requestId: "delayed", timeoutMs: 500 })).resolves.toBeUndefined();
  await new Promise((resolve) => setTimeout(resolve, 50));
  expect(closedBeforeDelayedWrite).toBe(true);
});
winTest("pingEmberLab rejects mismatched IDs and JSON-RPC errors", async () => {
  const pipe = `\\\\.\\pipe\\ember-lab-p2c-bad-${process.pid}-${Math.random().toString(16).slice(2)}`;
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

  await expect(pingEmberLab({ pipeName: pipe, requestId: "expected", timeoutMs: 500 }))
    .rejects.toThrow("response id");
  await expect(pingEmberLab({ pipeName: pipe, requestId: "error", timeoutMs: 500 }))
    .rejects.toThrow("JSON-RPC error");
});
function oneUtf8ResponseServer(pipe: string, response: Buffer, splitAt?: number): Promise<net.Server> {
  const server = net.createServer((socket) => {
    socket.once("data", () => {
      if (splitAt === undefined) socket.end(response);
      else {
        socket.write(response.subarray(0, splitAt));
        setTimeout(() => socket.end(response.subarray(splitAt)), 5);
      }
    });
  });
  servers.push(server);
  return new Promise<void>((resolve, reject) => server.listen(pipe, () => resolve()).once("error", reject)).then(() => server);
}

winTest("callEmberLab preserves one valid UTF-8 code point split across raw pipe chunks", async () => {
  const pipe = `\\\\.\\pipe\\ember-lab-p2c-utf8-valid-${process.pid}-${Math.random().toString(16).slice(2)}`;
  const explosion = String.fromCodePoint(0x1f4a5);
  const explosionBytes = Buffer.from([0xf0, 0x9f, 0x92, 0xa5]);
  const response = Buffer.from(JSON.stringify({ jsonrpc: "2.0", id: "emoji", result: { note: explosion } }) + "\n", "utf8");
  const emoji = response.indexOf(explosionBytes);
  await oneUtf8ResponseServer(pipe, response, emoji + 2);
  await expect(callEmberLab({ pipeName: pipe, requestId: "emoji", method: "ping", params: {} }))
    .resolves.toMatchObject({ note: explosion });
});

winTest("callEmberLab rejects one malformed raw UTF-8 byte", async () => {
  const pipe = `\\\\.\\pipe\\ember-lab-p2c-utf8-malformed-${process.pid}-${Math.random().toString(16).slice(2)}`;
  const response = Buffer.concat([Buffer.from('{"jsonrpc":"2.0","id":"malformed","result":{"note":"'), Buffer.from([0xff]), Buffer.from('"}}\n')]);
  await oneUtf8ResponseServer(pipe, response);
  await expect(callEmberLab({ pipeName: pipe, requestId: "malformed", method: "ping", params: {} }))
    .rejects.toThrow("valid UTF-8");
});

winTest("callEmberLab rejects one incomplete raw UTF-8 sequence", async () => {
  const pipe = `\\\\.\\pipe\\ember-lab-p2c-utf8-incomplete-${process.pid}-${Math.random().toString(16).slice(2)}`;
  const response = Buffer.concat([Buffer.from('{"jsonrpc":"2.0","id":"incomplete","result":{"note":"'), Buffer.from([0xf0, 0x9f, 0x92]), Buffer.from('"}}\n')]);
  await oneUtf8ResponseServer(pipe, response);
  await expect(callEmberLab({ pipeName: pipe, requestId: "incomplete", method: "ping", params: {} }))
    .rejects.toThrow("valid UTF-8");
});