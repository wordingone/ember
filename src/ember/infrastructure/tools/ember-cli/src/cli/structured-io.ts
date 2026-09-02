// cli/structured-io.ts — structured NDJSON IO surface for headless and interactive sessions.
// Parses NDJSON from an async input stream, buffers prepended messages, and dispatches
// control request/response round-trips over the same wire.
// Bundle: cli/structured-io.ts (byte offsets ~54346000–54352000)

import type { QueryEvent } from "../core/query-engine.ts";

// ---------------------------------------------------------------------------
// Wire-protocol shapes (private to this module)
// ---------------------------------------------------------------------------

interface ControlRequest {
  type?:       string;
  request_id?: string;
  subtype?:    string;
  [key: string]: unknown;
}

interface ControlResponse {
  request_id:  string;
  tool_use_id?: string;
  [key: string]: unknown;
}

interface PendingEntry {
  request: { type: "control_request"; request_id: string } & ControlRequest;
  resolve: (value: ControlResponse) => void;
  reject:  (reason: Error) => void;
  schema:  unknown;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const LS_CHAR          = " ";
const PS_CHAR          = " ";
const LS_ESC           = "\\u2028";
const PS_ESC           = "\\u2029";
const MAX_RESOLVED_IDS = 1000;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function toNdjsonLine(value: unknown): string {
  let json = JSON.stringify(value);
  if (json.includes(LS_CHAR)) json = json.split(LS_CHAR).join(LS_ESC);
  if (json.includes(PS_CHAR)) json = json.split(PS_CHAR).join(PS_ESC);
  return json + "\n";
}

export function cliError(msg?: string): never {
  if (msg !== undefined) process.stderr.write(msg + "\n");
  process.exit(1);
}

export function cliOk(msg?: string): never {
  if (msg !== undefined) process.stdout.write(msg + "\n");
  process.exit(0);
}

// ---------------------------------------------------------------------------
// StructuredIO — NDJSON IO surface for interactive and headless sessions
// ---------------------------------------------------------------------------

export class StructuredIO {
  private readonly _input: AsyncIterable<unknown>;
  private readonly _out:   { write(s: string): unknown };
  private _prepended:   unknown[]                 = [];
  private _pending:     Map<string, PendingEntry> = new Map();
  private _resolvedIds: string[]                  = [];
  private _closed                                 = false;

  constructor(
    _input: AsyncIterable<unknown>,
    _out:   { write(s: string): unknown } = process.stdout,
  ) {
    this._input = _input;
    this._out   = _out;
  }

  write(message: QueryEvent): void {
    this._out.write(toNdjsonLine(message));
  }

  prependUserMessage(content: string | unknown[]): void {
    const c = typeof content === "string"
      ? [{ type: "text", text: content }]
      : content;
    const msg = {
      role:      "user",
      content:   c,
      uuid:      crypto.randomUUID(),
      timestamp: new Date().toISOString(),
    };
    this._prepended.push({ type: "user", ...msg });
  }

  sendRequest(
    request:    ControlRequest,
    schema:     unknown,
    signal?:    AbortSignal | null,
    requestId?: string,
  ): Promise<ControlResponse> {
    if (this._closed) {
      return Promise.reject(new Error("stream closed"));
    }
    const id   = requestId ?? request.request_id ?? crypto.randomUUID();
    const full = { ...request, type: "control_request" as const, request_id: id };
    return new Promise<ControlResponse>((resolve, reject) => {
      this._pending.set(id, { request: full, resolve, reject, schema });
      this.write(full as unknown as QueryEvent);
      if (signal) {
        signal.addEventListener(
          "abort",
          () => {
            if (this._pending.has(id)) {
              this._pending.delete(id);
              reject(new Error("Request aborted"));
            }
          },
          { once: true },
        );
      }
    });
  }

  injectControlResponse(response: ControlResponse): void {
    const entry = this._pending.get(response.request_id);
    if (!entry) return;
    this._pending.delete(response.request_id);
    if (response.tool_use_id) this._markResolved(response.tool_use_id);
    entry.resolve(response);
    this.write(
      { type: "control_cancel_request", request_id: response.request_id } as unknown as QueryEvent,
    );
  }

  getPendingPermissionRequests(): Array<{ type: "control_request"; request_id: string } & ControlRequest> {
    const result: Array<{ type: "control_request"; request_id: string } & ControlRequest> = [];
    for (const entry of this._pending.values()) {
      if (entry.request.subtype === "can_use_tool") {
        result.push(entry.request);
      }
    }
    return result;
  }

  private _markResolved(id: string): void {
    if (this._resolvedIds.length >= MAX_RESOLVED_IDS) {
      this._resolvedIds.shift();
    }
    this._resolvedIds.push(id);
  }

  private _isResolved(id: string): boolean {
    return this._resolvedIds.includes(id);
  }

  private _rejectAll(err: Error): void {
    for (const entry of this._pending.values()) {
      entry.reject(err);
    }
    this._pending.clear();
  }

  private _handleControlResponse(response: ControlResponse): void {
    if (response.tool_use_id && this._isResolved(response.tool_use_id)) {
      return;
    }
    const entry = this._pending.get(response.request_id);
    if (!entry) return;
    this._pending.delete(response.request_id);
    if (response.tool_use_id) this._markResolved(response.tool_use_id);
    entry.resolve(response);
  }

  async *[Symbol.asyncIterator](): AsyncGenerator<unknown> {
    yield* this._drainPrepended();
    let buffer = "";
    try {
      for await (const chunk of this._input) {
        buffer += String(chunk);
        let nl: number;
        while ((nl = buffer.indexOf("\n")) !== -1) {
          const line = buffer.slice(0, nl).trim();
          buffer     = buffer.slice(nl + 1);
          if (!line) continue;
          yield* this._drainPrepended();
          let parsed: Record<string, unknown>;
          try {
            parsed = JSON.parse(line) as Record<string, unknown>;
          } catch {
            continue;
          }
          const type = parsed["type"];
          switch (type) {
            case "keep_alive":
              break;
            case "update_environment_variables": {
              const vars = parsed["variables"];
              if (vars && typeof vars === "object") {
                for (const [k, v] of Object.entries(vars as Record<string, string>)) {
                  process.env[k] = String(v);
                }
              }
              break;
            }
            case "control_response":
              this._handleControlResponse(parsed as unknown as ControlResponse);
              break;
            case "user":
            case "assistant":
            case "system":
              yield parsed;
              break;
            default:
              break;
          }
        }
      }
    } finally {
      this._closed = true;
      this._rejectAll(new Error("stream closed"));
    }
  }

  private *_drainPrepended(): Generator<unknown> {
    while (this._prepended.length > 0) {
      yield this._prepended.shift();
    }
  }
}

// ---------------------------------------------------------------------------
// HeadlessIO — headless variant; elicitation always resolves to null
// ---------------------------------------------------------------------------

export class HeadlessIO extends StructuredIO {
  async handleElicitation(): Promise<null> {
    return null;
  }
}
