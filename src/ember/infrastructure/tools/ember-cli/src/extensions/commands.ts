// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// extensions/commands.ts — the slash commands this layer contributes to the registry:
//   /mcp /skills /plugins /loop          builtins (createExtensionCommands)
//   /<skill>                             one prompt command per discovered skill
//   /<plugin>:<command>                  plugin commands
//   /mcp__<server>__<prompt>             MCP prompts
// Prompt-type commands return { prompt } so the REPL runs a model turn with that text.

import { join } from "node:path";
import { discoverSkills } from "../tools/skill-registration.ts";
import type { RegistryCommand, CommandContext, CommandResult } from "../types/command-types.ts";
import { getExtensions } from "./runtime.ts";
import {
  cancelAllLoops,
  formatInterval,
  listLoops,
  MIN_LOOP_INTERVAL_MS,
  parseInterval,
  startLoop,
} from "./scheduler.ts";
import { getEmberConfigHomeDir } from "../utils/env-detection.ts";

const msg = (message: string): CommandResult => ({ type: "message", message });

// ---------------------------------------------------------------------------
// Skills as slash commands
// ---------------------------------------------------------------------------

function skillSourceLabel(source: string, cwd: string): string {
  const norm = (p: string): string => p.replace(/\\/g, "/").toLowerCase();
  if (norm(source).startsWith(norm(join(cwd, ".ember")))) return "project";
  if (norm(source).startsWith(norm(join(getEmberConfigHomeDir(), "skills")))) return "user";
  return "plugin";
}

/** One prompt command per user-invocable skill under .ember/skills, $EMBER_HOME/skills and plugins. */
export function buildSkillCommands(cwd: string): RegistryCommand[] {
  const out: RegistryCommand[] = [];
  for (const skill of discoverSkills(cwd)) {
    if (skill.userInvocable === false) continue;
    const content = skill.content ?? "";
    out.push({
      name: skill.name,
      description: skill.description ?? `Skill ${skill.name}`,
      type: "prompt",
      settingsSource: skillSourceLabel(skill.source, cwd),
      isEnabled: () => true,
      ...(skill.disableModelInvocation ? { disableModelInvocation: true } : {}),
      ...(skill.argumentHint ? { whenToUse: skill.argumentHint } : {}),
      async execute(args) {
        const prompt = content.includes("$ARGUMENTS")
          ? content.replace(/\$ARGUMENTS/g, args)
          : args
            ? `${content.trimEnd()}\n\nARGUMENTS: ${args}`
            : content;
        return { type: "message", message: skill.warning ?? "", prompt: `Run the "${skill.name}" skill:\n\n${prompt.trim()}` };
      },
    });
  }
  return out;
}

export function getPluginCommandList(): RegistryCommand[] {
  return (getExtensions()?.plugins ?? []).flatMap((p) => p.commands);
}

export function getMcpPromptCommandList(): RegistryCommand[] {
  return getExtensions()?.mcp.getPromptCommands() ?? [];
}

export function mcpPromptCommandsAvailable(): boolean {
  return getMcpPromptCommandList().length > 0;
}

// ---------------------------------------------------------------------------
// /mcp
// ---------------------------------------------------------------------------

function mcpCommand(): RegistryCommand {
  return {
    name: "mcp",
    description: "List MCP servers and their status; /mcp <server> shows its tools",
    isEnabled: () => true,
    async execute(args): Promise<CommandResult> {
      const rt = getExtensions();
      if (!rt) return msg("Extensions are not running in this session.");
      const servers = rt.mcp.getServers();
      const want = args.trim();
      if (want) {
        const s = servers.find((x) => x.name === want);
        if (!s) return msg(`No MCP server named "${want}". Configured: ${servers.map((x) => x.name).join(", ") || "none"}`);
        const lines = [`${s.name}  ${s.status}  (${s.transport}, ${s.scope} scope)`];
        if (s.error) lines.push(`  error: ${s.error}`);
        for (const t of s.toolNames) lines.push(`  tool    ${t}`);
        for (const p of s.promptNames) lines.push(`  prompt  /${p}`);
        if (s.resourceCount > 0) lines.push(`  ${s.resourceCount} resource(s), readable with mcp__read_resource`);
        return msg(lines.join("\n"));
      }
      if (servers.length === 0) {
        return msg(
          "No MCP servers configured.\nAdd them to " +
            `${join(rt.home, "mcp.json")} or ${join(rt.cwd, ".ember", "mcp.json")}:\n` +
            '  { "mcpServers": { "name": { "command": "...", "args": [] } } }  (or { "type": "http", "url": "..." })',
        );
      }
      const mark = { connected: "ok     ", failed: "FAILED ", connecting: "wait   " } as const;
      const lines = [`MCP servers (${servers.length}):`];
      for (const s of servers) {
        const detail =
          s.status === "connected"
            ? `${s.toolNames.length} tool(s)${s.promptNames.length ? `, ${s.promptNames.length} prompt(s)` : ""}`
            : s.status === "failed"
              ? (s.error ?? "failed")
              : "starting";
        lines.push(`  ${mark[s.status]}${s.name}  ${s.transport}/${s.scope}  ${detail}`);
      }
      return msg(lines.join("\n"));
    },
  };
}

// ---------------------------------------------------------------------------
// /skills and /plugins
// ---------------------------------------------------------------------------

function skillsCommand(): RegistryCommand {
  return {
    name: "skills",
    description: "List the available skills (run one as /<skill>)",
    isEnabled: () => true,
    async execute(_args, ctx: CommandContext): Promise<CommandResult> {
      const skills = discoverSkills(ctx.cwd);
      if (skills.length === 0) {
        return msg(
          `No skills found.\nAdd one as ${join(ctx.cwd, ".ember", "skills", "<name>", "SKILL.md")} ` +
            `or ${join(getEmberConfigHomeDir(), "skills", "<name>", "SKILL.md")}.`,
        );
      }
      const lines = [`Skills (${skills.length}):`];
      for (const s of skills) {
        const hint = s.argumentHint ? ` ${s.argumentHint}` : "";
        lines.push(`  /${s.name}${hint}  [${skillSourceLabel(s.source, ctx.cwd)}]  ${s.description ?? ""}`.trimEnd());
        if (s.warning) lines.push(`    ! ${s.warning}`);
      }
      return msg(lines.join("\n"));
    },
  };
}

function pluginsCommand(): RegistryCommand {
  return {
    name: "plugins",
    description: "List the installed plugins and what they contribute",
    isEnabled: () => true,
    async execute(): Promise<CommandResult> {
      const rt = getExtensions();
      const plugins = rt?.plugins ?? [];
      if (plugins.length === 0) {
        return msg(`No plugins installed. Put a plugin directory under ${join(rt?.home ?? getEmberConfigHomeDir(), "plugins")}.`);
      }
      const lines = [`Plugins (${plugins.length}):`];
      for (const p of plugins) {
        const parts = [
          `${p.commands.length} command(s)`,
          p.skillsDir ? "skills" : "",
          Object.keys(p.mcpServers).length ? `${Object.keys(p.mcpServers).length} MCP server(s)` : "",
        ].filter(Boolean);
        lines.push(`  ${p.name}${p.version ? ` ${p.version}` : ""}  ${parts.join(", ")}${p.error ? `  (problem: ${p.error})` : ""}`);
        for (const c of p.commands) lines.push(`    /${c.name}  ${c.description}`);
      }
      return msg(lines.join("\n"));
    },
  };
}

// ---------------------------------------------------------------------------
// /loop
// ---------------------------------------------------------------------------

export const LOOP_USAGE = "Usage: /loop <interval> <prompt>   e.g. /loop 5m check the build\n       /loop stop   (or press Esc) stops every loop";

function loopCommand(): RegistryCommand {
  return {
    name: "loop",
    description: "Repeat a prompt every interval while idle (Esc stops)",
    argumentHint: "<interval> <prompt>",
    isEnabled: () => true,
    async execute(args): Promise<CommandResult> {
      const text = args.trim();
      if (text === "" || text === "status") {
        const loops = listLoops();
        if (loops.length === 0) return msg(LOOP_USAGE);
        return msg(
          [`Loops running (${loops.length}):`, ...loops.map((l) => `  every ${formatInterval(l.intervalMs)}, ${l.runs} run(s): ${l.prompt}`), "Press Esc or /loop stop to stop."].join("\n"),
        );
      }
      if (text === "stop" || text === "cancel") {
        const n = cancelAllLoops();
        return msg(n === 0 ? "No loop is running." : `Stopped ${n} loop(s).`);
      }
      const m = /^(\S+)\s+([\s\S]+)$/.exec(text);
      const interval = m ? parseInterval(m[1]!) : null;
      if (!m || interval === null) return msg(`Could not read an interval and a prompt from "${text}".\n${LOOP_USAGE}`);
      if (interval < MIN_LOOP_INTERVAL_MS) {
        return msg(`The shortest loop interval is ${formatInterval(MIN_LOOP_INTERVAL_MS)}.\n${LOOP_USAGE}`);
      }
      const prompt = m[2]!.trim();
      const job = startLoop(interval, prompt);
      return {
        type: "message",
        message: `Loop started: every ${formatInterval(job.intervalMs)}, only while idle. Press Esc to stop.`,
        prompt,
      };
    },
  };
}

/** Builtin slash commands of this layer. */
export function createExtensionCommands(): RegistryCommand[] {
  return [mcpCommand(), skillsCommand(), pluginsCommand(), loopCommand()];
}
