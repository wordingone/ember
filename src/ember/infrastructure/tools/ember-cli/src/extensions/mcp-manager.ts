// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// extensions/mcp-manager.ts — loads MCP server configs, starts the servers in parallel,
// and turns each connected server's tools and prompts into model tools and slash commands.
//
// Config files (both optional, project wins on a name clash):
//   $EMBER_HOME/mcp.json            user scope
//   <project>/.ember/mcp.json       project scope
// shape: { "mcpServers": { "<name>": { "command", "args", "env" } | { "type": "http", "url", "headers" } } }
//
// A server that fails to start never blocks the session: it is recorded as failed and a
// notice is emitted. Tools appear as mcp__<server>__<tool>.

import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import {
  McpConfigService,
  expandEnvVarsInConfig,
  normalizeMcpServerName,
} from "../mcp-config.ts";
import type { ConfigScope, McpServerConfig, McpServerEntry } from "../mcp-config.ts";
import {
  buildListMcpResourcesTool,
  buildMCPTool,
  buildReadMcpResourceTool,
} from "../mcp-tools.ts";
import type { McpClientInterface, McpResourceDescriptor, McpToolsContext } from "../mcp-tools.ts";
import type { Tool } from "../core/tool-interface.ts";
import type { RegistryCommand } from "../types/command-types.ts";
import { StdioMcpClient, createMcpClient, connectTimeoutMs } from "./mcp-client.ts";
import type { McpClientBase, McpPromptInfo } from "./mcp-client.ts";

export type McpServerStatus = "connecting" | "connected" | "failed";

export interface McpServerState {
  name: string;
  scope: ConfigScope;
  /** "stdio" or "http". */
  transport: string;
  status: McpServerStatus;
  error?: string;
  toolNames: string[];
  promptNames: string[];
  resourceCount: number;
}

// ---------------------------------------------------------------------------
// Config loading
// ---------------------------------------------------------------------------

export interface LoadedMcpConfigs {
  entries: McpServerEntry[];
  notices: string[];
}

async function readServersFile(path: string, notices: string[]): Promise<Record<string, McpServerConfig>> {
  let raw: string;
  try {
    raw = await readFile(path, "utf-8");
  } catch {
    return {}; // no file is the normal case
  }
  try {
    const parsed = JSON.parse(raw.replace(/^﻿/, "")) as { mcpServers?: unknown };
    const servers = parsed?.mcpServers;
    if (servers && typeof servers === "object" && !Array.isArray(servers)) {
      return servers as Record<string, McpServerConfig>;
    }
    notices.push(`${path}: no "mcpServers" object, nothing started from it`);
  } catch (e) {
    notices.push(`${path}: not valid JSON (${e instanceof Error ? e.message : String(e)}), nothing started from it`);
  }
  return {};
}

export async function loadMcpConfigs(
  cwd: string,
  home: string,
  pluginServers: Record<string, McpServerConfig> = {},
): Promise<LoadedMcpConfigs> {
  const notices: string[] = [];
  const svc = new McpConfigService(cwd);
  for (const [name, cfg] of Object.entries(await readServersFile(join(home, "mcp.json"), notices))) {
    svc.addMcpConfig(name, cfg, "user");
  }
  for (const [name, cfg] of Object.entries(await readServersFile(join(cwd, ".ember", "mcp.json"), notices))) {
    svc.addMcpConfig(name, cfg, "project");
  }
  for (const [name, cfg] of Object.entries(pluginServers)) {
    svc.addMcpConfig(name, cfg, "dynamic");
  }
  const entries: McpServerEntry[] = [];
  for (const entry of await svc.getEmberMcpConfigs()) {
    const cfg = entry.config;
    if (!cfg || typeof cfg !== "object" || cfg["disabled"] === true) continue;
    if (typeof cfg.command !== "string" && typeof cfg.url !== "string") {
      notices.push(`MCP server "${entry.name}" has neither "command" nor "url", skipped`);
      continue;
    }
    entries.push({ ...entry, config: expandEnvVarsInConfig(cfg) });
  }
  return { entries, notices };
}

// ---------------------------------------------------------------------------
// Manager
// ---------------------------------------------------------------------------

export interface McpManagerOptions {
  cwd: string;
  home: string;
  /** Called once per problem; the REPL shows it as a transcript notice. */
  notice?: (message: string) => void;
  /** Test seam. */
  createClient?: (name: string, config: McpServerConfig, cwd: string) => McpClientBase;
  connectTimeoutMs?: number;
}

const MAX_DESCRIPTION_CHARS = 2048;

export class McpManager {
  private readonly states = new Map<string, McpServerState>();
  private readonly clients = new Map<string, McpClientBase>();
  private readonly tools: Tool[] = [];
  private readonly promptCommands: RegistryCommand[] = [];
  private readonly resourceCache = new Map<string, McpResourceDescriptor[]>();
  private readonly toolListeners = new Set<(tool: Tool) => void>();
  private readonly changeListeners = new Set<() => void>();
  private resourceToolsAdded = false;
  private started: Promise<void> | null = null;
  private exitHookInstalled = false;

  constructor(private readonly opts: McpManagerOptions) {}

  private readonly mcpContext: McpToolsContext = {
    getClients: () => [...this.clients.values()].filter((c) => c.status === "connected"),
    getClient: (name: string) => this.clients.get(name),
    startOAuthFlow: () => null,
    replaceAuthToolWithRealTools: () => {},
    persistBlob: async (data: Buffer, ext: string, id: string) => {
      const dir = join(tmpdir(), "ember-mcp-blobs");
      await mkdir(dir, { recursive: true });
      const file = join(dir, `${id.replace(/[^A-Za-z0-9_.-]/g, "_")}${ext}`);
      await writeFile(file, data);
      return file;
    },
    resourceCache: this.resourceCache,
  };

  /** Starts every configured server in parallel. Resolves when all have settled; never rejects. */
  start(pluginServers: Record<string, McpServerConfig> = {}): Promise<void> {
    if (!this.started) this.started = this.doStart(pluginServers).catch((e) => {
      this.emitNotice(`MCP startup error: ${e instanceof Error ? e.message : String(e)}`);
    });
    return this.started;
  }

  private emitNotice(message: string): void {
    try {
      this.opts.notice?.(message);
    } catch {
      // a broken notice sink must not break startup
    }
  }

  private async doStart(pluginServers: Record<string, McpServerConfig>): Promise<void> {
    const { entries, notices } = await loadMcpConfigs(this.opts.cwd, this.opts.home, pluginServers);
    for (const n of notices) this.emitNotice(n);
    for (const entry of entries) {
      this.states.set(entry.name, {
        name: entry.name,
        scope: entry.scope,
        transport: entry.config.url && !entry.config.command ? "http" : "stdio",
        status: "connecting",
        toolNames: [],
        promptNames: [],
        resourceCount: 0,
      });
    }
    this.changed();
    // Two servers whose names normalise to the same identifier would collide in tool names.
    const byNormalised = new Map<string, string>();
    const runnable = entries.filter((entry) => {
      const norm = normalizeMcpServerName(entry.name);
      const prior = byNormalised.get(norm);
      if (prior !== undefined) {
        this.fail(entry.name, `name collides with MCP server "${prior}" after normalisation (mcp__${norm}__...)`);
        return false;
      }
      byNormalised.set(norm, entry.name);
      return true;
    });
    await Promise.all(runnable.map((entry) => this.connectOne(entry)));
  }

  private fail(name: string, error: string): void {
    const st = this.states.get(name);
    if (st) {
      st.status = "failed";
      st.error = error;
    }
    this.emitNotice(`MCP server "${name}" failed to start: ${error}`);
    this.changed();
  }

  private async connectOne(entry: McpServerEntry): Promise<void> {
    const make = this.opts.createClient ?? createMcpClient;
    let client: McpClientBase;
    try {
      client = make(entry.name, entry.config, this.opts.cwd);
    } catch (e) {
      this.fail(entry.name, e instanceof Error ? e.message : String(e));
      return;
    }
    this.installExitHook();
    this.clients.set(entry.name, client);
    try {
      await client.connect(this.opts.connectTimeoutMs ?? connectTimeoutMs());
      const toolInfos = await client.listTools();
      const prompts: McpPromptInfo[] = await client.listPrompts().catch(() => []);
      const resources = client.hasCapability("resources")
        ? await client.listResources().catch(() => [] as McpResourceDescriptor[])
        : [];
      const st = this.states.get(entry.name)!;
      for (const info of toolInfos) {
        if (typeof info?.name !== "string") continue;
        const tool = buildMCPTool({
          serverName: entry.name,
          toolName: info.name,
          toolSchema: info.inputSchema ?? { type: "object", properties: {} },
          description: (info.description ?? `Call ${info.name} on MCP server ${entry.name}`).slice(0, MAX_DESCRIPTION_CHARS),
          mcpContext: this.mcpContext,
        });
        const readOnlyHint = (info as { annotations?: { readOnlyHint?: boolean } }).annotations?.readOnlyHint === true;
        if (readOnlyHint) Object.assign(tool, { isReadOnly: () => true, isConcurrencySafe: () => true });
        this.tools.push(tool as unknown as Tool);
        st.toolNames.push(tool.name);
        this.toolListeners.forEach((l) => l(tool as unknown as Tool));
      }
      for (const p of prompts) {
        if (typeof p?.name !== "string") continue;
        const cmd = this.promptCommand(entry.name, client, p);
        this.promptCommands.push(cmd);
        st.promptNames.push(cmd.name);
      }
      st.resourceCount = resources.length;
      if (resources.length > 0) this.addResourceTools();
      st.status = "connected";
      delete st.error;
      this.changed();
    } catch (e) {
      const stderr = client instanceof StdioMcpClient && client.stderr ? ` (stderr: ${client.stderr.split("\n").pop()})` : "";
      this.fail(entry.name, (e instanceof Error ? e.message : String(e)) + stderr);
    }
  }

  private addResourceTools(): void {
    if (this.resourceToolsAdded) return;
    this.resourceToolsAdded = true;
    for (const t of [buildListMcpResourcesTool(this.mcpContext), buildReadMcpResourceTool(this.mcpContext)]) {
      this.tools.push(t as unknown as Tool);
      this.toolListeners.forEach((l) => l(t as unknown as Tool));
    }
  }

  private promptCommand(server: string, client: McpClientBase, info: McpPromptInfo): RegistryCommand {
    const name = `mcp__${normalizeMcpServerName(server)}__${info.name}`;
    const argNames = (info.arguments ?? []).map((a) => a.name);
    return {
      name,
      description: `${info.description ?? `Prompt ${info.name}`} (MCP ${server})`,
      type: "prompt",
      isMcpSkill: true,
      isEnabled: () => client.status === "connected",
      async execute(args) {
        // Positional arguments map onto the prompt's declared arguments, in order.
        const values = args.trim() === "" ? [] : args.trim().split(/\s+/);
        const map: Record<string, string> = {};
        argNames.forEach((n, i) => {
          if (values[i] !== undefined) map[n] = i === argNames.length - 1 ? values.slice(i).join(" ") : values[i]!;
        });
        const text = await client.getPrompt(info.name, map);
        return { type: "message", message: "", prompt: text };
      },
    };
  }

  private installExitHook(): void {
    if (this.exitHookInstalled) return;
    this.exitHookInstalled = true;
    // Stop only the server processes THIS manager spawned, when the CLI itself exits.
    process.once("exit", () => this.killAllNow());
  }

  private changed(): void {
    this.changeListeners.forEach((l) => {
      try { l(); } catch { /* listener errors are not the manager's business */ }
    });
  }

  // ---- queries ----

  getServers(): McpServerState[] {
    return [...this.states.values()];
  }

  getTools(): Tool[] {
    return [...this.tools];
  }

  getPromptCommands(): RegistryCommand[] {
    return [...this.promptCommands];
  }

  getClient(name: string): McpClientInterface | undefined {
    return this.clients.get(name);
  }

  isStarted(): boolean {
    return this.started !== null;
  }

  /** Resolves when startup has settled or `ms` elapsed, whichever is first. */
  async whenSettled(ms: number): Promise<void> {
    if (!this.started) return;
    await Promise.race([this.started, new Promise<void>((r) => { const t = setTimeout(r, ms); t.unref?.(); })]);
  }

  /** Appends current and future MCP tools to `target` (the engine's live tool list). */
  bindToolList(target: Tool[]): void {
    for (const t of this.tools) if (!target.includes(t)) target.push(t);
    this.toolListeners.add((t) => { if (!target.includes(t)) target.push(t); });
  }

  onChange(listener: () => void): () => void {
    this.changeListeners.add(listener);
    return () => this.changeListeners.delete(listener);
  }

  async closeAll(): Promise<void> {
    await Promise.all([...this.clients.values()].map((c) => c.close().catch(() => {})));
  }

  killAllNow(): void {
    for (const c of this.clients.values()) {
      if (c instanceof StdioMcpClient) c.killNow();
    }
  }
}
