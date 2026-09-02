// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// mcp-server-entry.ts — MCP stdio server entry point.
//
// Spec: specs/entrypoints/mcp-server-entry.md — AC1–AC7.
//
// When invoked via --mcp, this module presents all available tools over the
// MCP stdio transport (newline-delimited JSON-RPC). No TUI, no managed model
// server.

import { EMBER_CLI_VERSION } from "../../../../../../../tools/ember-cli/src/entrypoints/process-entry.ts";
import { init as sessionInit } from "../../../../../../../tools/ember-cli/src/entrypoints/session-init.ts";

// ---------------------------------------------------------------------------
// MCP server identity (AC7: server name for the MCP transport)
// ---------------------------------------------------------------------------

export const MCP_SERVER_NAME = "ember/repl" as const;
export const MCP_SERVER_VERSION: string = EMBER_CLI_VERSION;

// ---------------------------------------------------------------------------
// File state LRU cache (AC5: reused across CallToolRequest calls)
// ---------------------------------------------------------------------------

export interface FileStateCacheEntry {
  content: string;
  sizeBytes: number;
  timestamp: number;
}

export class FileStateCache {
  private _maxFiles: number;
  private _maxBytes: number;
  private _totalBytes: number = 0;
  private _entries: Map<string, FileStateCacheEntry> = new Map();

  constructor(maxFiles = 100, maxMb = 25) {
    this._maxFiles = maxFiles;
    this._maxBytes = maxMb * 1024 * 1024;
  }

  get(path: string): FileStateCacheEntry | undefined {
    const entry = this._entries.get(path);
    if (entry) {
      // LRU: re-insert to maintain insertion-order for eviction
      this._entries.delete(path);
      this._entries.set(path, entry);
    }
    return entry;
  }

  set(path: string, content: string): void {
    const sizeBytes = Buffer.byteLength(content, "utf-8");

    // Evict existing entry for this path
    const existing = this._entries.get(path);
    if (existing) {
      this._totalBytes -= existing.sizeBytes;
      this._entries.delete(path);
    }

    // Evict LRU entries until there is room
    while (
      this._entries.size >= this._maxFiles ||
      this._totalBytes + sizeBytes > this._maxBytes
    ) {
      const firstKey = this._entries.keys().next().value;
      if (firstKey === undefined) break;
      const first = this._entries.get(firstKey)!;
      this._totalBytes -= first.sizeBytes;
      this._entries.delete(firstKey);
    }

    this._entries.set(path, { content, sizeBytes, timestamp: Date.now() });
    this._totalBytes += sizeBytes;
  }

  has(path: string): boolean {
    return this._entries.has(path);
  }

  get size(): number {
    return this._entries.size;
  }

  get totalBytes(): number {
    return this._totalBytes;
  }
}

// ---------------------------------------------------------------------------
// Tool abstraction (structural shape — derived from spec behavior)
// ---------------------------------------------------------------------------

export interface McpTool {
  name: string;
  description(permCtx: Record<string, unknown>): string;
  inputSchema(): Record<string, unknown>;   // JSON Schema (after conversion)
  outputSchema?(): Record<string, unknown>; // Optional — may have anyOf/oneOf
  isEnabled(): boolean;
  validateInput?(args: Record<string, unknown>): string | null; // null = valid
  call(
    args: Record<string, unknown>,
    ctx: McpToolContext,
  ): Promise<McpCallToolResult>;
}

export interface McpToolContext {
  abortController: AbortController;
  messages: unknown[];
  getAppState(): Record<string, unknown>;
  setAppState(_state: Record<string, unknown>): void;
  isNonInteractiveSession: boolean;
  fileStateCache: FileStateCache;
  // no-op stubs below
  setResponseLength(_len: number): void;
  setFileHistory(_h: unknown): void;
  setAttribution(_a: unknown): void;
}

export type McpCallToolResult =
  | { type: "text"; text: string }
  | { type: "error"; error: string };

// ---------------------------------------------------------------------------
// JSON Schema helpers (AC2 / AC4: strip anyOf/oneOf from output schemas)
// ---------------------------------------------------------------------------

function hasRootUnion(schema: Record<string, unknown>): boolean {
  return "anyOf" in schema || "oneOf" in schema;
}

// ---------------------------------------------------------------------------
// Tool registry (injected / module-level for production)
// ---------------------------------------------------------------------------

let _toolRegistry: McpTool[] | null = null;

export function registerToolRegistry(tools: McpTool[]): void {
  _toolRegistry = tools;
}

export function getToolRegistry(): McpTool[] {
  return _toolRegistry ?? [];
}

// ---------------------------------------------------------------------------
// MCP protocol types (interop shapes)
// ---------------------------------------------------------------------------

interface McpListToolsRequest {
  jsonrpc: "2.0";
  id: number | string;
  method: "tools/list";
}

interface McpCallToolRequest {
  jsonrpc: "2.0";
  id: number | string;
  method: "tools/call";
  params: {
    name: string;
    arguments?: Record<string, unknown>;
  };
}

interface McpInitializeRequest {
  jsonrpc: "2.0";
  id: number | string;
  method: "initialize";
  params?: {
    protocolVersion?: string;
    clientInfo?: { name: string; version: string };
    capabilities?: Record<string, unknown>;
  };
}

type McpRequest = McpListToolsRequest | McpCallToolRequest | McpInitializeRequest | { jsonrpc: "2.0"; id: number | string; method: string; params?: unknown };

// ---------------------------------------------------------------------------
// Handle requests
// ---------------------------------------------------------------------------

/**
 * AC1: ListToolsRequest returns at least the same tools as the interactive session.
 * AC2: Disabled tools are absent from the listing.
 * AC4: anyOf/oneOf schemas in output are excluded.
 */
export function handleListTools(): {
  tools: Array<{ name: string; description: string; inputSchema: Record<string, unknown> }>;
} {
  const tools = getToolRegistry()
    .filter((t) => t.isEnabled())
    .filter((t) => {
      // AC4: exclude tools whose output schema has anyOf/oneOf at root
      const out = t.outputSchema?.();
      return !out || !hasRootUnion(out);
    })
    .map((t) => ({
      name: t.name,
      description: t.description({}),
      inputSchema: t.inputSchema(),
    }));
  return { tools };
}

/**
 * AC3: CallToolRequest for a disabled tool returns an error result.
 * AC4: Failed input validation returns an error result.
 */
export async function handleCallTool(
  name: string,
  args: Record<string, unknown>,
  ctx: McpToolContext,
): Promise<McpCallToolResult> {
  const registry = getToolRegistry();
  const tool = registry.find((t) => t.name === name);

  if (!tool) {
    return { type: "error", error: `Tool not found: ${name}` };
  }

  // AC3: disabled tool → error, not crash
  if (!tool.isEnabled()) {
    return { type: "error", error: `Tool is disabled: ${name}` };
  }

  // AC4: input validation
  if (tool.validateInput) {
    const err = tool.validateInput(args);
    if (err !== null) {
      return { type: "error", error: `Validation failed for ${name}: ${err}` };
    }
  }

  try {
    return await tool.call(args, ctx);
  } catch (e: unknown) {
    return { type: "error", error: e instanceof Error ? e.message : String(e) };
  }
}

// ---------------------------------------------------------------------------
// MCP stdio transport
// ---------------------------------------------------------------------------

function makeOkResponse(id: number | string, result: unknown): string {
  return JSON.stringify({ jsonrpc: "2.0", id, result }) + "\n";
}

function makeErrResponse(id: number | string, code: number, message: string): string {
  return JSON.stringify({ jsonrpc: "2.0", id, error: { code, message } }) + "\n";
}

/**
 * Dispatches a single parsed MCP request.
 */
export async function dispatchMcpRequest(
  req: McpRequest,
  fileStateCache: FileStateCache,
  abortController: AbortController,
): Promise<string> {
  const { id } = req;

  try {
    if (req.method === "initialize") {
      // AC7: server name in handshake is exactly MCP_SERVER_NAME
      return makeOkResponse(id, {
        protocolVersion: "2024-11-05",
        capabilities: { tools: {} },
        serverInfo: { name: MCP_SERVER_NAME, version: MCP_SERVER_VERSION },
      });
    }

    if (req.method === "tools/list") {
      return makeOkResponse(id, handleListTools());
    }

    if (req.method === "tools/call") {
      const callReq = req as McpCallToolRequest;
      const { name, arguments: args = {} } = callReq.params;
      const ctx: McpToolContext = {
        abortController,
        messages: [],         // AC5: empty, no history in MCP mode
        getAppState: () => ({}),
        setAppState: () => {},
        isNonInteractiveSession: true, // AC6
        fileStateCache,               // AC5: shared across calls
        setResponseLength: () => {},
        setFileHistory: () => {},
        setAttribution: () => {},
      };
      const result = await handleCallTool(name, args, ctx);
      if (result.type === "error") {
        return makeOkResponse(id, {
          isError: true,
          content: [{ type: "text", text: result.error }],
        });
      }
      return makeOkResponse(id, {
        content: [{ type: "text", text: result.text }],
      });
    }

    return makeErrResponse(id, -32601, `Method not found: ${req.method}`);
  } catch (e: unknown) {
    return makeErrResponse(id, -32603, e instanceof Error ? e.message : String(e));
  }
}

// ---------------------------------------------------------------------------
// Server run loop
// ---------------------------------------------------------------------------

export interface McpServerOptions {
  /** Current working directory (used by tools). */
  cwd?: string;
  /** Enable debug logging to stderr. */
  debug?: boolean;
  /** Enable verbose logging. */
  verbose?: boolean;
}

/**
 * AC6: Runs the MCP server loop. Does NOT start a TUI or managed model server.
 * Reads JSON-RPC from stdin, writes responses to stdout.
 */
export async function runMcpServer(opts: McpServerOptions = {}): Promise<void> {
  const { debug = false } = opts;

  // AC6: do not start managed model server or TUI.
  // init() wires the production callModel; it does not spawn a new server.
  // The server URL must already be set in EMBER_MODEL_URL by the caller.
  await sessionInit();

  const fileStateCache = new FileStateCache(100, 25); // AC5
  const abortController = new AbortController();

  if (debug) {
    process.stderr.write(`[mcp] Server started: ${MCP_SERVER_NAME}@${MCP_SERVER_VERSION}\n`);
  }

  let buffer = "";

  process.stdin.setEncoding("utf-8");
  process.stdin.on("data", async (chunk: string) => {
    buffer += chunk;
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;

      try {
        const req = JSON.parse(trimmed) as McpRequest;
        const response = await dispatchMcpRequest(req, fileStateCache, abortController);
        process.stdout.write(response);
      } catch (e: unknown) {
        const errStr = e instanceof Error ? e.message : String(e);
        process.stdout.write(
          JSON.stringify({ jsonrpc: "2.0", id: null, error: { code: -32700, message: errStr } }) + "\n",
        );
      }
    }
  });

  process.stdin.on("end", () => {
    abortController.abort();
    if (debug) process.stderr.write("[mcp] stdin closed, shutting down\n");
  });

  // Wait for stdin to end
  await new Promise<void>((resolve) => {
    process.stdin.on("end", resolve);
    process.stdin.on("close", resolve);
  });
}
