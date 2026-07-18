// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// emberd-rpc.ts — strict Ember CLI client for the resident emberd named-pipe RPC.

import net from "node:net";

const PIPE_PREFIX = "\\\\.\\pipe\\emberd-";
const OPERATOR_PIPE_PREFIX = "\\\\.\\pipe\\ember-operator-";
const MAX_RESPONSE_BYTES = 64 * 1024;
const DEFAULT_TIMEOUT_MS = 5_000;

export interface EmberdPingOptions {
  pipeName: string;
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
  return new Error("emberd ping rejected: " + message);
}

export async function pingEmberd(options: EmberdPingOptions): Promise<void> {
  const pipeName = configuredEmberdPipe({ EMBERD_PIPE: options.pipeName });
  const requestId = options.requestId ?? crypto.randomUUID();
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  if (!Number.isInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > DEFAULT_TIMEOUT_MS) {
    throw new Error("emberd ping timeout must be a positive bounded integer");
  }
  const request = JSON.stringify({ jsonrpc: "2.0", id: requestId, method: "ping", params: {} }) + "\n";

  await new Promise<void>((resolve, reject) => {
    let settled = false;
    let buffer = "";
    const socket = net.createConnection(pipeName);
    const finish = (error?: Error): void => {
      if (settled) return;
      settled = true;
      clearTimeout(deadline);
      socket.destroy();
      if (error) reject(error);
      else resolve();
    };
    const deadline = setTimeout(() => finish(responseError("named-pipe connect/read timeout")), timeoutMs);

    socket.once("connect", () => socket.write(request));
    socket.once("error", (error) => finish(responseError(error.message)));
    socket.on("data", (chunk: Buffer | string) => {
      buffer += chunk.toString();
      if (Buffer.byteLength(buffer, "utf8") > MAX_RESPONSE_BYTES) {
        finish(responseError("response exceeds 65536 bytes"));
        return;
      }
      const newline = buffer.indexOf("\n");
      if (newline < 0) return;
      const line = buffer.slice(0, newline);
      if (buffer.slice(newline + 1).trim() !== "") {
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
      if (
        !result || typeof result !== "object" || Array.isArray(result)
        || (result as Record<string, unknown>)["status"] !== "ok"
      ) {
        finish(responseError("ping result is malformed"));
        return;
      }
      finish();
    });
  });
}

export async function handshakeConfiguredEmberd(): Promise<void> {
  await pingEmberd({ pipeName: configuredEmberdPipe() });
}