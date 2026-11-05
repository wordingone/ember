// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// extensions/runtime.ts — the session-wide extension runtime: plugins, MCP servers, hooks.
//
// startExtensions() is called once at session start. It returns immediately: plugins and
// hook settings load synchronously/quickly and MCP servers connect in the background, so a
// slow or broken server never delays the prompt. Problems are collected as notices that the
// REPL renders; none of them throws.

import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { getEmberConfigHomeDir } from "../utils/env-detection.ts";
import { getSettingsFilePathForSource } from "../settings.ts";
import { setExtraSkillDirs } from "../tools/skill-registration.ts";
import type { Tool } from "../core/tool-interface.ts";
import type { McpServerConfig } from "../mcp-config.ts";
import { McpManager } from "./mcp-manager.ts";
import type { McpManagerOptions } from "./mcp-manager.ts";
import { loadPlugins } from "./plugin-loader.ts";
import type { LoadedPlugin } from "./plugin-loader.ts";
import { HookRunner, parseHooksConfig, setActiveHookRunner, HOOK_EVENTS } from "./hooks.ts";
import type { HooksConfig, HookMatcherEntry } from "./hooks.ts";

export interface ExtensionRuntime {
  cwd: string;
  home: string;
  mcp: McpManager;
  plugins: LoadedPlugin[];
  hooks: HookRunner;
  /** Resolves when hook settings are loaded and every MCP server has settled. */
  ready: Promise<void>;
}

export interface StartExtensionsOptions {
  cwd?: string;
  home?: string;
  createClient?: McpManagerOptions["createClient"];
  connectTimeoutMs?: number;
  sessionId?: string;
}

let current: ExtensionRuntime | null = null;
const noticeHistory: string[] = [];
const noticeListeners = new Set<(message: string) => void>();

export function pushExtensionNotice(message: string): void {
  noticeHistory.push(message);
  for (const l of noticeListeners) {
    try { l(message); } catch { /* a broken listener must not stop the others */ }
  }
}

/** Subscribes to notices; past ones are replayed first. Returns an unsubscribe function. */
export function onExtensionNotice(listener: (message: string) => void): () => void {
  for (const m of noticeHistory) listener(m);
  noticeListeners.add(listener);
  return () => noticeListeners.delete(listener);
}

export function getExtensions(): ExtensionRuntime | null {
  return current;
}

/** Merges hook entries from every settings source: arrays concatenate, nothing is replaced. */
export async function loadHooksConfig(cwd: string, home: string, warn: (m: string) => void): Promise<HooksConfig> {
  const paths: string[] = [join(home, "settings.json")];
  for (const source of ["project", "local"] as const) {
    try {
      paths.push(getSettingsFilePathForSource(source, cwd));
    } catch {
      // an unusable state root just means no settings from that source
    }
  }
  paths.push(join(cwd, ".ember", "settings.json"), join(cwd, ".ember", "settings.local.json"));

  const merged: HooksConfig = {};
  for (const path of new Set(paths)) {
    let raw: string;
    try {
      raw = await readFile(path, "utf-8");
    } catch {
      continue;
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw.replace(/^﻿/, ""));
    } catch (e) {
      warn(`${path}: not valid JSON (${e instanceof Error ? e.message : String(e)}), its hooks were ignored`);
      continue;
    }
    const hooks = (parsed as { hooks?: unknown } | null)?.hooks;
    const cfg = parseHooksConfig(hooks, (m) => warn(`${path}: ${m}`));
    for (const event of HOOK_EVENTS) {
      const add = cfg[event];
      if (add) merged[event] = [...(merged[event] ?? []), ...add] as HookMatcherEntry[];
    }
  }
  return merged;
}

export function startExtensions(opts: StartExtensionsOptions = {}): ExtensionRuntime {
  const cwd = opts.cwd ?? process.cwd();
  if (current && current.cwd === cwd) return current;

  const home = opts.home ?? getEmberConfigHomeDir();
  const plugins = loadPlugins(home);
  setExtraSkillDirs(plugins.flatMap((p) => (p.skillsDir ? [p.skillsDir] : [])));
  for (const p of plugins) {
    if (p.error) pushExtensionNotice(`plugin "${p.name}": ${p.error}`);
  }

  const pluginServers: Record<string, McpServerConfig> = {};
  for (const p of plugins) {
    for (const [name, cfg] of Object.entries(p.mcpServers)) {
      pluginServers[`plugin_${p.name}_${name}`] = cfg;
    }
  }

  const mcp = new McpManager({
    cwd,
    home,
    notice: pushExtensionNotice,
    createClient: opts.createClient,
    connectTimeoutMs: opts.connectTimeoutMs,
  });
  // A late-connecting server adds slash commands (MCP prompts): drop the cached command list.
  // (dynamic import: command-registry imports this module's commands, so a static import cycles)
  mcp.onChange(() => { void import("../command-registry.ts").then((m) => m.clearCommandsCache()).catch(() => {}); });

  const hooks = new HookRunner({}, { cwd, sessionId: opts.sessionId });
  setActiveHookRunner(hooks);
  const hooksLoaded = loadHooksConfig(cwd, home, pushExtensionNotice)
    .then((cfg) => hooks.setConfig(cfg))
    .catch((e) => pushExtensionNotice(`hooks: ${e instanceof Error ? e.message : String(e)}`));

  const ready = Promise.all([hooksLoaded, mcp.start(pluginServers)]).then(() => {});
  current = { cwd, home, mcp, plugins, hooks, ready };
  return current;
}

/**
 * Production entry: starts the runtime unless disabled (EMBER_EXTENSIONS=0) and never inside a
 * unit-test process (NODE_ENV=test, unless EMBER_EXTENSIONS=1), so tests that drive the real
 * entry points do not read or start the developer's own MCP servers.
 */
export function startExtensionsForSession(opts: StartExtensionsOptions = {}): ExtensionRuntime | null {
  const flag = process.env["EMBER_EXTENSIONS"];
  if (flag === "0") return null;
  if (process.env["NODE_ENV"] === "test" && flag !== "1") return null;
  try {
    return startExtensions(opts);
  } catch (e) {
    pushExtensionNotice(`extensions could not start: ${e instanceof Error ? e.message : String(e)}`);
    return null;
  }
}

/** Waits (bounded) for hooks and MCP servers to settle; never rejects. */
export async function awaitExtensionsReady(ms: number): Promise<void> {
  const rt = current;
  if (!rt) return;
  await Promise.race([rt.ready, new Promise<void>((r) => { const t = setTimeout(r, ms); t.unref?.(); })]);
}

/**
 * The tool list handed to the QueryEngine: `base` plus every MCP tool, now and later. The
 * engine reads the array on each model call, so a server that connects after the first
 * prompt contributes its tools from the next call on.
 */
export function bindExtensionTools(base: Tool[]): Tool[] {
  const live = [...base];
  current?.mcp.bindToolList(live);
  return live;
}

export async function stopExtensions(): Promise<void> {
  const rt = current;
  current = null;
  setActiveHookRunner(null);
  setExtraSkillDirs([]);
  if (rt) await rt.mcp.closeAll();
}

export function _resetExtensionsForTests(): void {
  current = null;
  noticeHistory.length = 0;
  noticeListeners.clear();
  setActiveHookRunner(null);
  setExtraSkillDirs([]);
}
