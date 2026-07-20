// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// emberd-rpc.ts — strict Ember CLI client for the resident emberd named-pipe RPC.

import net from "node:net";

const PIPE_PREFIX = "\\\\.\\pipe\\emberd-";
const OPERATOR_PIPE_PREFIX = "\\\\.\\pipe\\ember-operator-";
const MAX_FRAME_BYTES = 64 * 1024;
const DEFAULT_RESPONSE_TIMEOUT_MS = 5_000;
const OPEN_RETRY_INTERVAL_MS = 20;
const OPEN_RETRY_WINDOW_MS = 10_000;

export interface EmberdPingOptions {
  pipeName: string;
  requestId?: string;
  timeoutMs?: number;
}

export interface EmberdRequestOptions {
  pipeName: string;
  method: string;
  params: Record<string, unknown>;
  requestId?: string;
  timeoutMs?: number;
}

export function configuredEmberdPipe(
  environment: Record<string, string | undefined> = process.env,
): string {
  const pipeName = environment["EMBERD_PIPE"];
  if (!pipeName) throw new Error("EMBERD_PIPE is required for a connected owned Ember seat");
  if (pipeName.startsWith(OPERATOR_PIPE_PREFIX)) {
    throw new Error("EMBERD_PIPE must not use the per-PID operator input pipe namespace");
  }
  if (
    !pipeName.startsWith(PIPE_PREFIX)
    || pipeName.length > 240
    || /[\r\n\0]/.test(pipeName)
  ) {
    throw new Error("EMBERD_PIPE must be one exact local emberd named-pipe identity");
  }
  return pipeName;
}

function responseError(message: string): Error {
  return new Error("emberd RPC rejected: " + message);
}

function isAccessDenied(error: unknown): boolean {
  const code = typeof error === "object" && error !== null
    ? (error as NodeJS.ErrnoException).code
    : undefined;
  return code === "EACCES" || code === "EPERM";
}

async function openEmberdPipe(pipeName: string): Promise<net.Socket> {
  return new Promise<net.Socket>((resolve, reject) => {
    let settled = false;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    let currentSocket: net.Socket | undefined;
    const deadlineTimer = setTimeout(() => {
      finish(responseError("named-pipe open retry window elapsed"));
    }, OPEN_RETRY_WINDOW_MS);
    const finish = (error?: Error, socket?: net.Socket): void => {
      if (settled) return;
      settled = true;
      clearTimeout(deadlineTimer);
      if (retryTimer) clearTimeout(retryTimer);
      if (currentSocket && currentSocket !== socket) currentSocket.destroy();
      if (error) reject(error);
      else if (socket) resolve(socket);
      else reject(responseError("named-pipe open failed without a socket"));
    };
    const attempt = (): void => {
      if (settled) return;
      const socket = net.createConnection(pipeName);
      currentSocket = socket;
      const onError = (error: NodeJS.ErrnoException): void => {
        socket.destroy();
        if (settled) return;
        if (isAccessDenied(error)) {
          finish(responseError("same-user named-pipe access denied"));
          return;
        }
        retryTimer = setTimeout(attempt, OPEN_RETRY_INTERVAL_MS);
      };
      socket.once("error", onError);
      socket.once("connect", () => {
        socket.removeListener("error", onError);
        if (settled) {
          socket.destroy();
          return;
        }
        finish(undefined, socket);
      });
    };
    attempt();
  });
}

export async function callEmberd(options: EmberdRequestOptions): Promise<Record<string, unknown>> {
  const pipeName = configuredEmberdPipe({ EMBERD_PIPE: options.pipeName });
  if (!options.method || /[\r\n\0]/.test(options.method)) {
    throw new Error("emberd RPC method must be one nonempty framed token");
  }
  const requestId = options.requestId ?? crypto.randomUUID();
  const timeoutMs = options.timeoutMs ?? DEFAULT_RESPONSE_TIMEOUT_MS;
  if (!Number.isInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > DEFAULT_RESPONSE_TIMEOUT_MS) {
    throw new Error("emberd RPC response timeout must be a positive bounded integer");
  }
  const request = JSON.stringify({ jsonrpc: "2.0", id: requestId, method: options.method, params: options.params }) + "\n";
  if (Buffer.byteLength(request, "utf8") > MAX_FRAME_BYTES) {
    throw responseError("request exceeds 65536 bytes");
  }
  const socket = await openEmberdPipe(pipeName);
  return new Promise<Record<string, unknown>>((resolve, reject) => {
    let settled = false;
    const finish = (error?: Error, result?: Record<string, unknown>): void => {
      if (settled) return;
      settled = true;
      clearTimeout(deadline);
      socket.destroy();
      if (error) reject(error);
      else if (result) resolve(result);
      else reject(responseError("response completed without a result"));
    };
    const deadline = setTimeout(() => finish(responseError("named-pipe response timeout")), timeoutMs);
    let rawBuffer = Buffer.alloc(0);
    const decodeUtf8 = (bytes: Buffer): string => {
      try {
        return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
      } catch {
        throw responseError("response is not valid UTF-8");
      }
    };
    const processFrame = (): void => {
      const newline = rawBuffer.indexOf(0x0a);
      if (newline < 0) return;
      let line: string;
      let trailing: string;
      try {
        line = decodeUtf8(rawBuffer.subarray(0, newline));
        trailing = decodeUtf8(rawBuffer.subarray(newline + 1));
      } catch (error) {
        finish(error instanceof Error ? error : responseError("response is not valid UTF-8"));
        return;
      }
      if (trailing.trim() !== "") {
        finish(responseError("response contains multiple frames"));
        return;
      }
      let response: unknown;
      try {
        response = JSON.parse(line);
      } catch {
        finish(responseError("response is not JSON"));
        return;
      }
      if (!response || typeof response !== "object" || Array.isArray(response)) {
        finish(responseError("response is not an object"));
        return;
      }
      const record = response as Record<string, unknown>;
      if (record["jsonrpc"] !== "2.0" || record["id"] !== requestId) {
        finish(responseError("response id or JSON-RPC version does not match request"));
        return;
      }
      if ("error" in record) {
        finish(responseError("response contains JSON-RPC error"));
        return;
      }
      const result = record["result"];
      if (!result || typeof result !== "object" || Array.isArray(result)) {
        finish(responseError("response result is malformed"));
        return;
      }
      // A valid frame completes this one-request connection; delayed bytes are outside the closed connection contract.
      finish(undefined, result as Record<string, unknown>);
    };
    socket.on("data", (chunk: Buffer | string) => {
      const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk, "utf8");
      rawBuffer = Buffer.concat([rawBuffer, bytes]);
      if (rawBuffer.length > MAX_FRAME_BYTES) {
        finish(responseError("response exceeds 65536 bytes"));
        return;
      }
      processFrame();
    });
    socket.once("end", () => {
      if (settled) return;
      try {
        decodeUtf8(rawBuffer);
      } catch (error) {
        finish(error instanceof Error ? error : responseError("response is not valid UTF-8"));
        return;
      }
      finish(responseError("response ended before one complete frame"));
    });
    socket.once("error", (error: Error) => finish(error));
    socket.write(request);
  });
}

export async function pingEmberd(options: EmberdPingOptions): Promise<void> {
  const result = await callEmberd({
    pipeName: options.pipeName,
    requestId: options.requestId,
    timeoutMs: options.timeoutMs,
    method: "ping",
    params: {},
  });
  if (result["status"] !== "ok") {
    throw responseError("ping result is malformed");
  }
}

export async function handshakeConfiguredEmberd(): Promise<void> {
  await pingEmberd({ pipeName: configuredEmberdPipe() });
}