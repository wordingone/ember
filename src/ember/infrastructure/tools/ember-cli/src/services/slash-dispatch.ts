// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/slash-dispatch.ts — routes "/name args" REPL input to the command registry.
//
// Without this seam the slash-command subsystem (command-registry.ts + commands/*.ts)
// is built and unit-tested but never reached from the running REPL: typing "/help"
// would be sent to the model as an ordinary message. This module is the production
// dispatch path. It is pure — registry access is injected — and returns the command's
// CommandResult to render, or null when the input is NOT a slash command (in which case
// the caller proceeds with a normal model turn).

import {
  getCommands as realGetCommands,
  findCommand as realFindCommand,
} from "../../../../../../../tools/ember-cli/src/command-registry.ts";
import type {
  CommandContext,
  CommandResult,
  RegistryCommand,
} from "../types/command-types.ts";

export interface SlashDispatchDeps {
  getCommands: (cwd: string) => Promise<RegistryCommand[]>;
  findCommand: (name: string, cmds: RegistryCommand[]) => RegistryCommand | undefined;
}

const defaultDeps: SlashDispatchDeps = {
  getCommands: realGetCommands,
  findCommand: realFindCommand,
};

/**
 * Splits "/name rest of args" into { name, args }. Returns null when `text` is not a
 * slash command (no leading slash, or a bare "/" with no command name).
 */
export function parseSlashInput(text: string): { name: string; args: string } | null {
  const trimmed = text.trim();
  if (!trimmed.startsWith("/")) return null;
  const body = trimmed.slice(1);
  const m = body.match(/^(\S+)\s*([\s\S]*)$/);
  if (!m) return null; // bare "/" — treat as ordinary input, not a command
  return { name: m[1], args: m[2].trim() };
}

/**
 * Attempts to dispatch `text` as a slash command against the command registry.
 * - Returns null when `text` is not a slash command (caller runs a normal model turn).
 * - Returns a CommandResult to render otherwise: the command's own result, an
 *   "unknown command" message (with the available list), or a "not available" message
 *   when the matched command is disabled.
 */
export async function tryDispatchSlashCommand(
  text: string,
  ctx: CommandContext,
  deps: SlashDispatchDeps = defaultDeps,
): Promise<CommandResult | null> {
  const parsed = parseSlashInput(text);
  if (parsed === null) return null;
  const { name, args } = parsed;

  const commands = await deps.getCommands(ctx.cwd);
  const cmd = deps.findCommand(name, commands);

  if (!cmd) {
    const available = commands
      .filter((c) => c.isEnabled())
      .map((c) => `/${c.name}`)
      .sort()
      .join(", ");
    return {
      type: "message",
      message: `Unknown command: /${name}` + (available ? `\nAvailable: ${available}` : ""),
    };
  }

  if (!cmd.isEnabled()) {
    return { type: "message", message: `/${name} is not available right now.` };
  }

  const result = await cmd.execute(args, ctx);
  return result ?? { type: "message", message: `/${name} ran.` };
}

/**
 * Interactive boundary for slash dispatch: convert registry and command failures
 * into a renderable message so one bad command cannot reject the REPL turn.
 */
export async function tryDispatchSlashCommandSafely(
  text: string,
  ctx: CommandContext,
  deps: SlashDispatchDeps = defaultDeps,
): Promise<CommandResult | null> {
  try {
    return await tryDispatchSlashCommand(text, ctx, deps);
  } catch (error) {
    const parsed = parseSlashInput(text);
    const command = parsed ? `/${parsed.name}` : "slash command";
    const detail = error instanceof Error ? error.message : String(error);
    return { type: "message", message: `${command} failed: ${detail}` };
  }
}
