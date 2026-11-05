// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// extensions/mcp-client.ts — a small MCP (Model Context Protocol) client with a stdio
// transport (newline-delimited JSON-RPC over a child process) and a streamable-HTTP
// transport (JSON-RPC over POST, JSON or SSE replies). It implements the existing
// McpClientInterface (mcp-tools.ts) so buildMCPTool can call through it.
//
// Nothing here throws into the session: connect() rejects with a plain Error that the
// manager turns into a notice, and a dead server turns its calls into tool errors.

import { spawn } from "node:child_process";
import type { ChildProcess } from "node:child_process";
import type {
  McpClientInterface,
  McpResourceContent,
  McpResourceDescriptor,
} from "../mcp-tools.ts";
import type { McpServerConfig } from "../mcp-config.ts";

export const MCP_PROTOCOL_VERSION = "2025-03-26";
export const DEFAULT_CONNECT_TIMEOUT_MS = 30_000;
export const DEFAULT_CALL_TIMEOUT_MS = 120_000;

export interface McpToolInfo {
  name: string;
  description?: string;
  inputSchema?: Record<string, unknown>;
}

export interface McpPromptInfo {
  name: string;
  description?: string;
  arguments?: Array<{ name: string; description?: string; required?: boolean }>;
}

export type McpClientStatus = "pending" | "connected" | "failed" | "closed";

type Json = Record<string, unknown>;

function envNumber(name: string, fallback: number): number {
  const raw = process.env[name];
  const n = raw === undefined ? NaN : Number(raw);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

export function connectTimeoutMs(): number {
  return envNumber("EMBER_MCP_CONNECT_TIMEOUT_MS", DEFAULT_CONNECT_TIMEOUT_MS);
}

function callTimeoutMs(): number {
  return envNumber("EMBER_MCP_TOOL_TIMEOUT_MS", DEFAULT_CALL_TIMEOUT_MS);
}

function withTimeout<T>(p: Promise<T>, ms: number, what: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`${what} timed out after ${ms} ms`)), ms);
    p.then(
      (v) => { clearTimeout(timer); resolve(v); },
      (e) => { clearTimeout(timer); reject(e); },
    );
  });
}

/** Flattens an MCP tools/call result into the text the model reads. */
export function mcpResultToText(result: Json): string {
  const parts: string[] = [];
  const content = Array.isArray(result["content"]) ? (result["content"] as Json[]) : [];
  for (const block of content) {
    const type = block["type"];
    if (type === "text" && typeof block["text"] === "string") {
      parts.push(block["text"] as string);
    } else if (type === "image") {
      parts.push(`[image: ${String(block["mimeType"] ?? "unknown type")}]`);
    } else if (type === "resource" && block["resource"] && typeof block["resource"] === "object") {
      const res = block["resource"] as Json;
      parts.push(typeof res["text"] === "string" ? (res["text"] as string) : `[resource: ${String(res["uri"] ?? "")}]`);
    } else {
      parts.push(JSON.stringify(block));
    }
  }
  if (parts.length === 0 && result["structuredContent"] !== undefined) {
    parts.push(JSON.stringify(result["structuredContent"]));
  }
  return parts.join("\n");
}

// ---------------------------------------------------------------------------
// Base: the protocol layer shared by both transports
// ---------------------------------------------------------------------------

export abstract class McpClientBase implements McpClientInterface {
  status: McpClientStatus = "pending";
  capabilities: Record<string, unknown> = {};
  serverInfo: { name?: string; version?: string } = {};
  transportType: string;
  transportUrl?: string;

  constructor(public readonly serverName: string, transportType: string) {
    this.transportType = transportType;
  }

  protected abstract open(): Promise<void>;
  protected abstract rpc(method: string, params: Json | undefined, timeoutMs: number): Promise<Json>;
  protected abstract notify(method: string, params?: Json): Promise<void>;
  abstract close(): Promise<void>;

  /** Opens the transport and runs the initialize handshake. Rejects on any failure. */
  async connect(timeoutMs: number = connectTimeoutMs()): Promise<void> {
    try {
      await withTimeout(this.handshake(), timeoutMs, `MCP server "${this.serverName}" startup`);
      this.status = "connected";
    } catch (err) {
      this.status = "failed";
      await this.close().catch(() => {});
      throw err instanceof Error ? err : new Error(String(err));
    }
  }

  private async handshake(): Promise<void> {
    await this.open();
    const init = await this.rpc(
      "initialize",
      {
        protocolVersion: MCP_PROTOCOL_VERSION,
        capabilities: {},
        clientInfo: { name: "ember-cli", version: "0.0.0" },
      },
      connectTimeoutMs(),
    );
    this.capabilities = (init["capabilities"] as Json | undefined) ?? {};
    this.serverInfo = (init["serverInfo"] as { name?: string; version?: string } | undefined) ?? {};
    await this.notify("notifications/initialized");
  }

  hasCapability(cap: string): boolean {
    return this.capabilities[cap] !== undefined && this.capabilities[cap] !== null;
  }

  private async paged(method: string, key: string): Promise<Json[]> {
    const out: Json[] = [];
    let cursor: string | undefined;
    for (let page = 0; page < 50; page++) {
      const res = await this.rpc(method, cursor ? { cursor } : {}, callTimeoutMs());
      const items = res[key];
      if (Array.isArray(items)) out.push(...(items as Json[]));
      const next = res["nextCursor"];
      if (typeof next !== "string" || next === "") break;
      cursor = next;
    }
    return out;
  }

  async listTools(): Promise<McpToolInfo[]> {
    if (!this.hasCapability("tools")) return [];
    return (await this.paged("tools/list", "tools")) as unknown as McpToolInfo[];
  }

  async listPrompts(): Promise<McpPromptInfo[]> {
    if (!this.hasCapability("prompts")) return [];
    return (await this.paged("prompts/list", "prompts")) as unknown as McpPromptInfo[];
  }

  async getPrompt(name: string, args: Record<string, string>): Promise<string> {
    const res = await this.rpc("prompts/get", { name, arguments: args }, callTimeoutMs());
    const messages = Array.isArray(res["messages"]) ? (res["messages"] as Json[]) : [];
    return messages
      .map((m) => {
        const c = m["content"] as Json | undefined;
        return c && typeof c["text"] === "string" ? (c["text"] as string) : "";
      })
      .filter(Boolean)
      .join("\n\n");
  }

  async callTool(name: string, input: unknown): Promise<string> {
    const res = await this.rpc(
      "tools/call",
      { name, arguments: (input ?? {}) as Json },
      callTimeoutMs(),
    );
    const text = mcpResultToText(res);
    if (res["isError"] === true) throw new Error(text || `MCP tool ${name} reported an error`);
    return text;
  }

  async listResources(): Promise<McpResourceDescriptor[]> {
    if (!this.hasCapability("resources")) return [];
    return (await this.paged("resources/list", "resources")) as unknown as McpResourceDescriptor[];
  }

  async readResource(uri: string): Promise<McpResourceContent[]> {
    const res = await this.rpc("resources/read", { uri }, callTimeoutMs());
    return (Array.isArray(res["contents"]) ? res["contents"] : []) as McpResourceContent[];
  }
}

// ---------------------------------------------------------------------------
// stdio transport
// ---------------------------------------------------------------------------

interface Pending {
  resolve: (v: Json) => void;
  reject: (e: Error) => void;
  timer: ReturnType<typeof setTimeout>;
}

const STDERR_TAIL_CHARS = 2000;

/** Resolves a bare command through PATH (so Windows .cmd shims such as npx are found). */
function resolveCommand(command: string, env: Record<string, string | undefined>): { file: string; shell: boolean } {
  let file = command;
  try {
    const found = Bun.which(command, { PATH: env["PATH"] ?? env["Path"] ?? process.env["PATH"] ?? "" });
    if (found) file = found;
  } catch {
    // keep the bare command
  }
  return { file, shell: process.platform === "win32" && /\.(cmd|bat)$/i.test(file) };
}

/** Quotes one word for cmd.exe when it holds whitespace or a shell metacharacter. */
export function quoteForCmd(word: string): string {
  return /[\s"&|<>^()]/.test(word) ? `"${word.replace(/"/g, '""')}"` : word;
}

export class StdioMcpClient extends McpClientBase {
  private child: ChildProcess | null = null;
  private nextId = 1;
  private readonly pending = new Map<number, Pending>();
  private buffer = "";
  private stderrTail = "";
  private exited = false;

  constructor(serverName: string, private readonly config: McpServerConfig, private readonly cwd: string) {
    super(serverName, "stdio");
  }

  /** Last output the server wrote to stderr (diagnosis for a startup failure). */
  get stderr(): string {
    return this.stderrTail.trim();
  }

  protected async open(): Promise<void> {
    const command = this.config.command;
    if (typeof command !== "string" || command === "") {
      throw new Error(`MCP server "${this.serverName}" has no "command"`);
    }
    const env = { ...process.env, ...(this.config.env ?? {}) } as Record<string, string | undefined>;
    const { file, shell } = resolveCommand(command, env);
    const args = Array.isArray(this.config.args) ? (this.config.args as string[]).map(String) : [];
    // A .cmd/.bat shim runs through cmd.exe, and node joins file and args with plain spaces, so a
    // path such as "C:\Program Files\nodejs\npx.cmd" or an argument with a space must be quoted here.
    const child = spawn(shell ? quoteForCmd(file) : file, shell ? args.map(quoteForCmd) : args, {
      cwd: this.cwd,
      env: env as NodeJS.ProcessEnv,
      stdio: ["pipe", "pipe", "pipe"],
      shell,
      windowsHide: true,
    });
    this.child = child;
    await new Promise<void>((resolve, reject) => {
      child.once("spawn", () => resolve());
      child.once("error", (e) => reject(new Error(`could not start "${command}": ${e.message}`)));
    });
    child.stdout!.setEncoding("utf8");
    child.stdout!.on("data", (chunk: string) => this.onData(chunk));
    child.stderr!.setEncoding("utf8");
    child.stderr!.on("data", (chunk: string) => {
      this.stderrTail = (this.stderrTail + chunk).slice(-STDERR_TAIL_CHARS);
    });
    child.stdin!.on("error", () => {});
    child.on("error", (e) => this.failAll(new Error(`MCP server "${this.serverName}": ${e.message}`)));
    child.on("exit", (code, signal) => {
      this.exited = true;
      if (this.status === "connected") this.status = "closed";
      const tail = this.stderr ? `: ${this.stderr.split("\n").pop()}` : "";
      this.failAll(new Error(`MCP server "${this.serverName}" exited (${signal ?? `code ${code}`})${tail}`));
    });
  }

  private onData(chunk: string): void {
    this.buffer += chunk;
    let nl: number;
    while ((nl = this.buffer.indexOf("\n")) >= 0) {
      const line = this.buffer.slice(0, nl).trim();
      this.buffer = this.buffer.slice(nl + 1);
      if (line === "") continue;
      let msg: Json;
      try {
        msg = JSON.parse(line) as Json;
      } catch {
        continue; // not JSON-RPC (a server that logs to stdout): ignore the line
      }
      this.onMessage(msg);
    }
  }

  private onMessage(msg: Json): void {
    const id = msg["id"];
    if (typeof msg["method"] === "string") {
      // A request from the server: answer ping, refuse everything else.
      if (id !== undefined) {
        const reply: Json =
          msg["method"] === "ping"
            ? { jsonrpc: "2.0", id, result: {} }
            : { jsonrpc: "2.0", id, error: { code: -32601, message: "Method not supported by ember-cli" } };
        this.write(reply);
      }
      return;
    }
    if (typeof id !== "number") return;
    const p = this.pending.get(id);
    if (!p) return;
    this.pending.delete(id);
    clearTimeout(p.timer);
    const err = msg["error"] as { message?: string } | undefined;
    if (err) p.reject(new Error(err.message ?? "MCP error"));
    else p.resolve((msg["result"] as Json | undefined) ?? {});
  }

  private write(msg: Json): void {
    if (!this.child || this.exited || !this.child.stdin || this.child.stdin.destroyed) return;
    this.child.stdin.write(JSON.stringify(msg) + "\n");
  }

  private failAll(err: Error): void {
    for (const [id, p] of this.pending) {
      clearTimeout(p.timer);
      p.reject(err);
      this.pending.delete(id);
    }
  }

  protected rpc(method: string, params: Json | undefined, timeoutMs: number): Promise<Json> {
    if (this.exited) {
      return Promise.reject(new Error(`MCP server "${this.serverName}" is not running`));
    }
    const id = this.nextId++;
    return new Promise<Json>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`MCP server "${this.serverName}" did not answer ${method} within ${timeoutMs} ms`));
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      this.write({ jsonrpc: "2.0", id, method, ...(params !== undefined ? { params } : {}) });
    });
  }

  protected async notify(method: string, params?: Json): Promise<void> {
    this.write({ jsonrpc: "2.0", method, ...(params !== undefined ? { params } : {}) });
  }

  async close(): Promise<void> {
    if (this.status === "connected") this.status = "closed";
    this.failAll(new Error(`MCP server "${this.serverName}" closed`));
    const child = this.child;
    if (!child || this.exited) return;
    try {
      child.stdin?.end();
    } catch {
      // already closed
    }
    // This is the child THIS client spawned (pid held in `child`), never a name-pattern kill.
    const killer = setTimeout(() => {
      try { child.kill(); } catch { /* gone */ }
    }, 500);
    killer.unref?.();
    child.once("exit", () => clearTimeout(killer));
  }

  /** Synchronous best-effort kill for process exit handlers. */
  killNow(): void {
    try { this.child?.kill(); } catch { /* gone */ }
  }
}

// ---------------------------------------------------------------------------
// streamable-HTTP transport
// ---------------------------------------------------------------------------

/** Pulls the JSON-RPC response with `id` out of an SSE body. */
async function readSseResponse(res: Response, id: number): Promise<Json> {
  const reader = res.body?.getReader();
  if (!reader) throw new Error("empty SSE response");
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (value) buf += decoder.decode(value, { stream: true });
    let sep: number;
    while ((sep = buf.search(/\r?\n\r?\n/)) >= 0) {
      const rawEvent = buf.slice(0, sep);
      buf = buf.slice(sep).replace(/^\r?\n\r?\n/, "");
      const data = rawEvent
        .split(/\r?\n/)
        .filter((l) => l.startsWith("data:"))
        .map((l) => l.slice(5).replace(/^ /, ""))
        .join("\n");
      if (!data) continue;
      try {
        const msg = JSON.parse(data) as Json;
        if (msg["id"] === id) {
          await reader.cancel().catch(() => {});
          return msg;
        }
      } catch {
        // ignore a malformed event
      }
    }
    if (done) break;
  }
  throw new Error("SSE stream ended without a response");
}

export class HttpMcpClient extends McpClientBase {
  private nextId = 1;
  private sessionId: string | undefined;

  constructor(serverName: string, private readonly config: McpServerConfig) {
    super(serverName, "http");
    this.transportUrl = typeof config.url === "string" ? config.url : undefined;
  }

  protected async open(): Promise<void> {
    if (!this.transportUrl) throw new Error(`MCP server "${this.serverName}" has no "url"`);
  }

  private headers(): Record<string, string> {
    return {
      "content-type": "application/json",
      accept: "application/json, text/event-stream",
      ...(this.config.headers ?? {}),
      ...(this.sessionId ? { "mcp-session-id": this.sessionId } : {}),
    };
  }

  protected async rpc(method: string, params: Json | undefined, timeoutMs: number): Promise<Json> {
    const id = this.nextId++;
    const body = { jsonrpc: "2.0", id, method, ...(params !== undefined ? { params } : {}) };
    const run = async (): Promise<Json> => {
      const res = await fetch(this.transportUrl!, {
        method: "POST",
        headers: this.headers(),
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(timeoutMs),
      });
      const sid = res.headers.get("mcp-session-id");
      if (sid) this.sessionId = sid;
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(`MCP server "${this.serverName}" answered HTTP ${res.status}${text ? `: ${text.slice(0, 200)}` : ""}`);
      }
      const type = res.headers.get("content-type") ?? "";
      const msg = type.includes("text/event-stream")
        ? await readSseResponse(res, id)
        : ((await res.json()) as Json);
      const err = msg["error"] as { message?: string } | undefined;
      if (err) throw new Error(err.message ?? "MCP error");
      return (msg["result"] as Json | undefined) ?? {};
    };
    try {
      return await run();
    } catch (e) {
      if (e instanceof Error && (e.name === "TimeoutError" || e.name === "AbortError")) {
        throw new Error(`MCP server "${this.serverName}" did not answer ${method} within ${timeoutMs} ms`);
      }
      throw e;
    }
  }

  protected async notify(method: string, params?: Json): Promise<void> {
    const res = await fetch(this.transportUrl!, {
      method: "POST",
      headers: this.headers(),
      body: JSON.stringify({ jsonrpc: "2.0", method, ...(params !== undefined ? { params } : {}) }),
      signal: AbortSignal.timeout(10_000),
    });
    await res.arrayBuffer().catch(() => {});
  }

  async close(): Promise<void> {
    if (this.status === "connected") this.status = "closed";
    if (this.sessionId && this.transportUrl) {
      try {
        await fetch(this.transportUrl, {
          method: "DELETE",
          headers: this.headers(),
          signal: AbortSignal.timeout(2000),
        });
      } catch {
        // best effort
      }
      this.sessionId = undefined;
    }
  }
}

/** Picks the transport from the server config: `url` means HTTP, `command` means stdio. */
export function createMcpClient(name: string, config: McpServerConfig, cwd: string): McpClientBase {
  const type = typeof config.type === "string" ? config.type.toLowerCase() : undefined;
  if (type === "http" || type === "sse" || type === "streamable-http" || (type === undefined && config.url)) {
    return new HttpMcpClient(name, config);
  }
  return new StdioMcpClient(name, config, cwd);
}
