// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// ember-lab-rpc.ts — strict Ember CLI client for the resident ember-lab named-pipe RPC.

import net from "node:net";

const PIPE_PREFIX = "\\\\.\\pipe\\ember-lab-";
const OPERATOR_PIPE_PREFIX = "\\\\.\\pipe\\ember-operator-";
const MAX_FRAME_BYTES = 64 * 1024;
const DEFAULT_RESPONSE_TIMEOUT_MS = 5_000;
const OPEN_RETRY_INTERVAL_MS = 20;
const OPEN_RETRY_WINDOW_MS = 10_000;

export interface EmberLabPingOptions {
  pipeName: string;
  requestId?: string;
  timeoutMs?: number;
}

export interface EmberLabRequestOptions {
  pipeName: string;
  method: string;
  params: Record<string, unknown>;
  requestId?: string;
  timeoutMs?: number;
}

export interface EmberLabRuntimeIdentity {
  schema_version: "ember-lab-runtime-identity-v1";
  pid: number;
}

export interface EmberLabWallObservationSnapshot {
  schema_version: "ember-lab-wall-observation-snapshot-v1";
  captured_at_ms: number;
  after_vram_seq: number;
  after_disk_seq: number;
  next_vram_seq: number;
  next_disk_seq: number;
  daemon_identity: {
    schema_version: "ember-lab-runtime-identity-v1";
    pid: number;
    binary_sha256: string;
    source_sha256: string;
  };
  vram_observations: Array<{
    seq: number;
    job_id: string;
    observed_at_ms: number;
    outcome: string;
    payload: Record<string, unknown>;
  }>;
  disk_observations: Array<{
    seq: number;
    job_id: string;
    write_root: string;
    observed_at_ms: number;
    outcome: string;
    payload: Record<string, unknown>;
  }>;
}

export function configuredEmberLabPipe(
  environment: Record<string, string | undefined> = process.env,
): string {
  const pipeName = environment["EMBER_LAB_PIPE"];
  if (!pipeName) throw new Error("EMBER_LAB_PIPE is required for a connected owned Ember seat");
  if (pipeName.startsWith(OPERATOR_PIPE_PREFIX)) {
    throw new Error("EMBER_LAB_PIPE must not use the per-PID operator input pipe namespace");
  }
  if (
    !pipeName.startsWith(PIPE_PREFIX)
    || pipeName.length > 240
    || /[\r\n\0]/.test(pipeName)
  ) {
    throw new Error("EMBER_LAB_PIPE must be one exact local ember-lab named-pipe identity");
  }
  return pipeName;
}

function responseError(message: string): Error {
  return new Error("ember-lab RPC rejected: " + message);
}

function isAccessDenied(error: unknown): boolean {
  const code = typeof error === "object" && error !== null
    ? (error as NodeJS.ErrnoException).code
    : undefined;
  return code === "EACCES" || code === "EPERM";
}

async function openEmberLabPipe(pipeName: string): Promise<net.Socket> {
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

export async function callEmberLab(options: EmberLabRequestOptions): Promise<Record<string, unknown>> {
  const pipeName = configuredEmberLabPipe({ EMBER_LAB_PIPE: options.pipeName });
  if (!options.method || /[\r\n\0]/.test(options.method)) {
    throw new Error("ember-lab RPC method must be one nonempty framed token");
  }
  const requestId = options.requestId ?? crypto.randomUUID();
  const timeoutMs = options.timeoutMs ?? DEFAULT_RESPONSE_TIMEOUT_MS;
  if (!Number.isInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > DEFAULT_RESPONSE_TIMEOUT_MS) {
    throw new Error("ember-lab RPC response timeout must be a positive bounded integer");
  }
  const request = JSON.stringify({ jsonrpc: "2.0", id: requestId, method: options.method, params: options.params }) + "\n";
  if (Buffer.byteLength(request, "utf8") > MAX_FRAME_BYTES) {
    throw responseError("request exceeds 65536 bytes");
  }
  const socket = await openEmberLabPipe(pipeName);
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

export async function pingEmberLab(options: EmberLabPingOptions): Promise<void> {
  const result = await callEmberLab({
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

export async function identifyEmberLabRuntime(
  options: EmberLabPingOptions,
): Promise<EmberLabRuntimeIdentity> {
  const result = await callEmberLab({
    pipeName: options.pipeName,
    requestId: options.requestId,
    timeoutMs: options.timeoutMs,
    method: "runtime_identity",
    params: {},
  });
  if (
    Object.keys(result).sort().join(",") !== "pid,schema_version"
    || result["schema_version"] !== "ember-lab-runtime-identity-v1"
    || !Number.isSafeInteger(result["pid"])
    || (result["pid"] as number) <= 0
  ) {
    throw responseError("runtime identity result is malformed");
  }
  return result as unknown as EmberLabRuntimeIdentity;
}

function exactObject(value: unknown, keys: readonly string[]): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value)
    && Object.keys(value).sort().join(",") === [...keys].sort().join(",");
}

function nonnegativeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && (value as number) >= 0;
}

export function parseEmberLabWallObservationSnapshot(
  result: unknown,
): EmberLabWallObservationSnapshot {
  const topKeys = ["schema_version", "captured_at_ms", "after_vram_seq", "after_disk_seq", "next_vram_seq", "next_disk_seq", "daemon_identity", "vram_observations", "disk_observations"];
  if (!exactObject(result, topKeys)) {
    throw responseError("wall observation snapshot result is malformed");
  }
  const row = result;
  const identity = row["daemon_identity"];
  const sha256 = /^[0-9a-f]{64}$/;
  const validRow = (row: unknown, disk: boolean): boolean => {
    const keys = disk
      ? ["seq", "job_id", "write_root", "observed_at_ms", "outcome", "payload"]
      : ["seq", "job_id", "observed_at_ms", "outcome", "payload"];
    if (!exactObject(row, keys) || !nonnegativeInteger(row["seq"]) || !nonnegativeInteger(row["observed_at_ms"])) return false;
    if (typeof row["job_id"] !== "string" || !row["job_id"] || typeof row["outcome"] !== "string" || !row["outcome"]) return false;
    if (disk && (typeof row["write_root"] !== "string" || !row["write_root"])) return false;
    return !!row["payload"] && typeof row["payload"] === "object" && !Array.isArray(row["payload"]);
  };
  if (
    row["schema_version"] !== "ember-lab-wall-observation-snapshot-v1"
    || !nonnegativeInteger(row["captured_at_ms"])
    || !nonnegativeInteger(row["after_vram_seq"])
    || !nonnegativeInteger(row["after_disk_seq"])
    || !nonnegativeInteger(row["next_vram_seq"])
    || !nonnegativeInteger(row["next_disk_seq"])
    || (row["next_vram_seq"] as number) < (row["after_vram_seq"] as number)
    || (row["next_disk_seq"] as number) < (row["after_disk_seq"] as number)
    || !exactObject(identity, ["schema_version", "pid", "binary_sha256", "source_sha256"])
    || identity["schema_version"] !== "ember-lab-runtime-identity-v1"
    || !Number.isSafeInteger(identity["pid"])
    || (identity["pid"] as number) <= 0
    || typeof identity["binary_sha256"] !== "string"
    || !sha256.test(identity["binary_sha256"])
    || typeof identity["source_sha256"] !== "string"
    || !sha256.test(identity["source_sha256"])
    || !Array.isArray(row["vram_observations"])
    || !row["vram_observations"].every((observation) => validRow(observation, false))
    || !Array.isArray(row["disk_observations"])
    || !row["disk_observations"].every((observation) => validRow(observation, true))
  ) {
    throw responseError("wall observation snapshot result is malformed");
  }
  const monotoneRows = (rows: Array<{ seq: number }>, after: number, next: number): boolean => {
    let prior = after;
    for (const row of rows) {
      if (row.seq <= prior || row.seq > next) return false;
      prior = row.seq;
    }
    return rows.length === 0 ? next === after : prior === next;
  };
  if (
    !monotoneRows(row["vram_observations"] as Array<{ seq: number }>, row["after_vram_seq"] as number, row["next_vram_seq"] as number)
    || !monotoneRows(row["disk_observations"] as Array<{ seq: number }>, row["after_disk_seq"] as number, row["next_disk_seq"] as number)
  ) {
    throw responseError("wall observation snapshot cursors are malformed");
  }
  return row as unknown as EmberLabWallObservationSnapshot;
}

export async function readEmberLabWallObservationSnapshot(
  options: EmberLabPingOptions & { afterVramSeq: number; afterDiskSeq: number },
): Promise<EmberLabWallObservationSnapshot> {
  if (!nonnegativeInteger(options.afterVramSeq) || !nonnegativeInteger(options.afterDiskSeq)) {
    throw new Error("ember-lab wall observation cursors must be nonnegative integers");
  }
  return parseEmberLabWallObservationSnapshot(await callEmberLab({
    pipeName: options.pipeName,
    requestId: options.requestId,
    timeoutMs: options.timeoutMs,
    method: "wall_observation_snapshot",
    params: { after_vram_seq: options.afterVramSeq, after_disk_seq: options.afterDiskSeq },
  }));
}

export async function handshakeConfiguredEmberLab(): Promise<void> {
  await pingEmberLab({ pipeName: configuredEmberLabPipe() });
}
