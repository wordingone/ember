// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// commands/memory.ts -- /memory: what the session loaded into its system prompt (#2374).

import type { CommandContext, CommandResult, RegistryCommand } from "../types/command-types.ts";
import { describeLoadedContext, loadProjectContext } from "../services/project-context.ts";

export const MEMORY_COMMAND_NAME = "memory";

export interface MemoryCommandDeps {
  /** EMBER_HOME override; tests pass a temp directory. */
  home?: () => string | undefined;
}

export function createMemoryCommand(deps: MemoryCommandDeps = {}): RegistryCommand {
  return {
    name: MEMORY_COMMAND_NAME,
    description: "Show the instruction files and memory index loaded into the system prompt",
    isEnabled: () => true,
    async execute(_args: string, ctx: CommandContext): Promise<CommandResult> {
      const home = deps.home?.();
      const loaded = loadProjectContext({ cwd: ctx.cwd, ...(home !== undefined ? { home } : {}) });
      return { type: "message", message: describeLoadedContext(loaded) };
    },
  };
}
