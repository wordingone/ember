// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// extensions/plugin-loader.ts — discovers plugins under $EMBER_HOME/plugins/<name>/.
//
// A plugin directory may hold:
//   plugin.json | .ember-plugin/plugin.json | .claude-plugin/plugin.json   manifest (optional)
//   commands/<cmd>.md        slash commands: /<plugin>:<cmd>, body is the prompt ($ARGUMENTS)
//   skills/<skill>/SKILL.md  skills, merged into the Skill tool and the /<skill> commands
//   mcp.json | .mcp.json     MCP servers ({ "mcpServers": { ... } }), also manifest.mcpServers
//
// Loading is synchronous and never throws: a broken plugin becomes an `error` on its entry.

import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { basename, join } from "node:path";
import type { RegistryCommand } from "../types/command-types.ts";
import type { McpServerConfig } from "../mcp-config.ts";
import { parseSkillMd } from "../skill-framework.ts";

export interface LoadedPlugin {
  name: string;
  dir: string;
  description?: string;
  version?: string;
  commands: RegistryCommand[];
  skillsDir?: string;
  mcpServers: Record<string, McpServerConfig>;
  /** Set when the plugin could not be (fully) loaded. */
  error?: string;
}

const MANIFEST_PATHS = ["plugin.json", join(".ember-plugin", "plugin.json"), join(".claude-plugin", "plugin.json")];
const MCP_PATHS = ["mcp.json", ".mcp.json"];

function readJson(path: string): Record<string, unknown> | undefined {
  const parsed: unknown = JSON.parse(readFileSync(path, "utf-8").replace(/^﻿/, ""));
  if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed as Record<string, unknown>;
  throw new Error(`${basename(path)} must hold a JSON object`);
}

function str(v: unknown): string | undefined {
  return typeof v === "string" && v.trim() !== "" ? v : undefined;
}

/** Slash-command names stay simple: letters, digits, `-` and `_`. */
function safeName(raw: string): string {
  return raw.trim().replace(/[^A-Za-z0-9_-]/g, "-");
}

function commandFromMarkdown(plugin: string, file: string, raw: string, dirName: string): RegistryCommand {
  const { frontmatter, body } = parseSkillMd(raw.replace(/\r\n/g, "\n"));
  const cmdName = `${plugin}:${safeName(basename(file, ".md"))}`;
  const description = str(frontmatter["description"]) ?? `Command from plugin ${plugin}`;
  const argumentHint = str(frontmatter["argument-hint"]);
  const template = body.replace(/\$\{EMBER_PLUGIN_DIR\}/g, dirName.replace(/\\/g, "/"));
  return {
    name: cmdName,
    description,
    type: "prompt",
    pluginName: plugin,
    isEnabled: () => true,
    ...(frontmatter["disable-model-invocation"] === true ? { disableModelInvocation: true } : {}),
    async execute(args) {
      const prompt = template.includes("$ARGUMENTS")
        ? template.replace(/\$ARGUMENTS/g, args)
        : args
          ? `${template.trimEnd()}\n\nARGUMENTS: ${args}`
          : template;
      return { type: "message", message: "", prompt: prompt.trim() };
    },
    // `argumentHint` is advisory only; a bare invocation of a plugin command is valid.
    ...(argumentHint ? { whenToUse: argumentHint } : {}),
  };
}

export function loadPlugin(dir: string): LoadedPlugin {
  const plugin: LoadedPlugin = { name: basename(dir), dir, commands: [], mcpServers: {} };
  const errors: string[] = [];
  try {
    for (const rel of MANIFEST_PATHS) {
      const path = join(dir, rel);
      if (!existsSync(path)) continue;
      const manifest = readJson(path)!;
      plugin.name = safeName(str(manifest["name"]) ?? plugin.name);
      plugin.description = str(manifest["description"]);
      plugin.version = str(manifest["version"]);
      const inline = manifest["mcpServers"];
      if (inline && typeof inline === "object" && !Array.isArray(inline)) {
        Object.assign(plugin.mcpServers, inline as Record<string, McpServerConfig>);
      }
      break;
    }
  } catch (e) {
    errors.push(`manifest: ${e instanceof Error ? e.message : String(e)}`);
  }

  const commandsDir = join(dir, "commands");
  try {
    if (existsSync(commandsDir)) {
      for (const file of readdirSync(commandsDir).sort()) {
        if (!file.toLowerCase().endsWith(".md")) continue;
        try {
          plugin.commands.push(commandFromMarkdown(plugin.name, file, readFileSync(join(commandsDir, file), "utf-8"), dir));
        } catch (e) {
          errors.push(`commands/${file}: ${e instanceof Error ? e.message : String(e)}`);
        }
      }
    }
  } catch (e) {
    errors.push(`commands: ${e instanceof Error ? e.message : String(e)}`);
  }

  const skillsDir = join(dir, "skills");
  if (existsSync(skillsDir)) plugin.skillsDir = skillsDir;

  for (const rel of MCP_PATHS) {
    const path = join(dir, rel);
    if (!existsSync(path)) continue;
    try {
      const servers = readJson(path)!["mcpServers"];
      if (servers && typeof servers === "object" && !Array.isArray(servers)) {
        Object.assign(plugin.mcpServers, servers as Record<string, McpServerConfig>);
      }
    } catch (e) {
      errors.push(`${rel}: ${e instanceof Error ? e.message : String(e)}`);
    }
    break;
  }

  if (errors.length > 0) plugin.error = errors.join("; ");
  return plugin;
}

/** Loads every plugin directory under `<home>/plugins`. Never throws. */
export function loadPlugins(home: string): LoadedPlugin[] {
  const root = join(home, "plugins");
  let entries: string[];
  try {
    entries = readdirSync(root).sort();
  } catch {
    return [];
  }
  const out: LoadedPlugin[] = [];
  const seen = new Set<string>();
  for (const entry of entries) {
    const dir = join(root, entry);
    try {
      if (!statSync(dir).isDirectory()) continue;
    } catch {
      continue;
    }
    const plugin = loadPlugin(dir);
    if (seen.has(plugin.name)) {
      plugin.error = `${plugin.error ? plugin.error + "; " : ""}duplicate plugin name "${plugin.name}" ignored`;
      plugin.commands = [];
      plugin.mcpServers = {};
      delete plugin.skillsDir;
    }
    seen.add(plugin.name);
    out.push(plugin);
  }
  return out;
}
