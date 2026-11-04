// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// commands/compact.ts -- /compact [instructions]: summarize the conversation now.

import type { CommandResult, RegistryCommand } from "../types/command-types.ts";
import { describeCompactionOutcome } from "../services/compaction.ts";
import { getSessionControl } from "../services/session-control.ts";

export const COMPACT_COMMAND_NAME = "compact";

export function createCompactCommand(): RegistryCommand {
  return {
    name: COMPACT_COMMAND_NAME,
    description: "Summarize the conversation now to free context; optional instructions shape the summary",
    isEnabled: () => true,
    async execute(args: string): Promise<CommandResult> {
      const control = getSessionControl();
      if (control === null) return { type: "message", message: "No active conversation to compact." };
      const outcome = await control.compact(args.trim());
      return { type: "message", message: describeCompactionOutcome(outcome) };
    },
  };
}
