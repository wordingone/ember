// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// commands/session-basics.ts -- /help and /clear, the two commands every chat surface
// needs. The registry otherwise holds only Ember governance commands, so a blind
// tester typing /help got "Unknown command". /clear's state change (dropping the
// transcript and the engine's history) is done by the REPL, which owns that state;
// this command only reports it.

import type { CommandContext, RegistryCommand } from "../types/command-types.ts";

export const KEY_BINDINGS_HELP = [
  "Keys:",
  "  Enter submit · Esc or Ctrl+C interrupt a reply · Ctrl+C clears a draft, and exits on an empty prompt",
  "  Left/Right/Home/End move the cursor · Ctrl+A/Ctrl+E line start/end · Ctrl+U clear the line",
  "  Up/Down recall earlier prompts · PageUp/PageDown scroll the transcript · Ctrl+O unfold very long replies",
  "  Shift+Tab cycle permission mode · Tab accept a suggestion",
  "  When a tool asks for approval: y yes · a always for this tool · n or Esc no",
].join("\n");

export function createHelpCommand(listCommands: (cwd: string) => Promise<RegistryCommand[]>): RegistryCommand {
  return {
    name: "help",
    description: "List commands and key bindings",
    isEnabled: () => true,
    async execute(_args: string, ctx: CommandContext) {
      const cmds = (await listCommands(ctx.cwd)).filter((c) => c.isEnabled());
      const width = Math.max(...cmds.map((c) => c.name.length), 4) + 2;
      const lines = cmds
        .slice()
        .sort((a, b) => a.name.localeCompare(b.name))
        .map((c) => `  /${c.name.padEnd(width)}${c.description}`);
      return { type: "message" as const, message: ["Commands:", ...lines, "", KEY_BINDINGS_HELP].join("\n") };
    },
  };
}

export const CLEAR_COMMAND_NAME = "clear";

export function createClearCommand(): RegistryCommand {
  return {
    name: CLEAR_COMMAND_NAME,
    description: "Clear the conversation and start fresh",
    isEnabled: () => true,
    async execute() {
      return { type: "message" as const, message: "Conversation cleared." };
    },
  };
}
